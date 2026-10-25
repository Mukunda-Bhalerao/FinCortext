"""Research engine: runs the four agents per stock, stores reports, keeps the watchlist covered.

Runs are queued and processed one at a time so provider rate limits hold. Adding a stock to the
watchlist queues it; a scheduler re-queues watchlist reports once they age past the refresh
window.
"""

import asyncio
import contextlib
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from app.agents import firm, industry, macro, sentiment
from app.agents.base import ResearchContext, fmt_value
from app.db import Database, _as_utc
from app.errors import AppError
from app.providers.ollama import OllamaClient
from app.schemas.market import Instrument
from app.schemas.research import (
    AgentOutput,
    Classification,
    Composite,
    ResearchItem,
    ResearchOverview,
    ResearchReport,
)
from app.services.instruments import InstrumentService
from app.services.research_data import ResearchData
from app.tools.scoring import signal_for

log = logging.getLogger(__name__)

AGENTS = (firm, industry, macro, sentiment)
COMPOSITE_METHOD = "composite-v1: confidence-weighted mean of agent scores"
REFRESH_AFTER = timedelta(hours=6)
RETRY_AFTER = timedelta(minutes=30)  # reports that could not be scored
SCHEDULER_INTERVAL = 15 * 60


def composite(outputs: list[AgentOutput]) -> Composite:
    used = [o for o in outputs if o.score is not None and o.confidence > 0]
    coverage = len(used) / len(AGENTS)
    weight = sum(o.confidence for o in used)
    score = sum(o.score * o.confidence for o in used) / weight if weight else None  # type: ignore[operator]
    conf = (weight / len(used)) * coverage if used else 0.0
    signal = signal_for(score, coverage)
    return Composite(
        signal=signal,  # type: ignore[arg-type]
        score=round(score, 2) if score is not None and signal != "insufficient_data" else None,
        confidence=round(conf, 2),
        agents_used=len(used),
        method=COMPOSITE_METHOD,
    )


_NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {round(float(n.replace(",", "")), 2) for n in _NUMBER.findall(text)}


def grounded(text: str, source: str) -> bool:
    """True when every number in ``text`` also appears in ``source``."""
    return _numbers(text) <= _numbers(source)


ADVICE = re.compile(r"\b(buy|sell|accumulate|invest|recommend|should|target price)\b", re.I)


def _prompt(output: AgentOutput) -> str:
    facts = "\n".join(
        f"- {e.factor}: {e.metric} = {fmt_value(e.value, e.unit)}"
        + (f" ({e.detail})" if e.detail else "")
        for e in output.evidence
    )
    gaps = "\n".join(f"- {g}" for g in output.data_gaps)
    return (
        f"You summarise a {output.agent} analysis of {output.subject} for a research tool.\n"
        f"Signal: {output.signal}. Score: {output.score}. Confidence: {output.confidence}.\n"
        f"Evidence:\n{facts}\nData gaps:\n{gaps}\n"
        "Write at most 2 sentences (under 60 words) explaining the signal from the evidence. "
        "Use only numbers that appear above. Do not give advice, do not tell anyone to buy or "
        "sell, and do not predict prices. Plain text only."
    )


class ResearchService:
    def __init__(
        self,
        db: Database,
        instruments: InstrumentService,
        data: ResearchData,
        watchlist_keys,
        llm: OllamaClient | None = None,
    ):
        self._db = db
        self._instruments = instruments
        self._data = data
        self._watchlist_keys = watchlist_keys
        self._llm = llm
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._state: dict[str, tuple[str, str | None]] = {}
        self._tasks: list[asyncio.Task] = []

    # --- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._worker()),
            asyncio.create_task(self._scheduler()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._data.aclose()
        if self._llm is not None:
            await self._llm.aclose()

    def enqueue(self, instrument_key: str, force: bool = False) -> None:
        state, _ = self._state.get(instrument_key, ("not_started", None))
        if state in ("queued", "running"):
            return
        if not force and not self._is_stale(self._stored_at(instrument_key)):
            return
        self._state[instrument_key] = ("queued", None)
        self._queue.put_nowait(instrument_key)

    async def _worker(self) -> None:
        while True:
            key = await self._queue.get()
            self._state[key] = ("running", None)
            try:
                await self.run(self._instruments.get(key))
                self._state[key] = ("ready", None)
            except AppError as exc:
                self._state[key] = ("failed", exc.message)
            except Exception:
                log.exception("research run failed for %s", key)
                self._state[key] = ("failed", "The research run failed unexpectedly.")

    async def _scheduler(self) -> None:
        await self._instruments.ready.wait()
        while True:
            for key in self._watchlist_keys():
                self.enqueue(key)
            await asyncio.sleep(SCHEDULER_INTERVAL)

    # --- runs and storage --------------------------------------------------------

    async def run(self, instrument: Instrument) -> ResearchReport:
        started = time.perf_counter()
        ctx = await self._data.context(instrument)
        outputs = [agent.run(ctx) for agent in AGENTS]
        if self._llm is not None:
            outputs = [await self._phrase(o) for o in outputs]
        report = ResearchReport(
            instrument=instrument,
            classification=self._classification(ctx),
            agents=outputs,
            composite=composite(outputs),
            headlines=ctx.headlines[:12],
            computed_at=ctx.now,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        self._db.execute(
            "INSERT OR REPLACE INTO research_reports VALUES (?, ?, ?, ?)",
            [
                instrument.instrument_key,
                report.composite.signal,
                report.model_dump_json(),
                report.computed_at,
            ],
        )
        return report

    async def _phrase(self, output: AgentOutput) -> AgentOutput:
        if output.signal == "insufficient_data" or self._llm is None:
            return output
        prompt = _prompt(output)
        try:
            text = await self._llm.generate(prompt)
        except AppError as exc:
            log.info("rationale model unavailable: %s", exc.message)
            return output
        if text and len(text) < 600 and grounded(text, prompt) and not ADVICE.search(text):
            return output.model_copy(update={"rationale": text, "rationale_source": "model"})
        return output

    @staticmethod
    def _classification(ctx: ResearchContext) -> Classification:
        return Classification(
            industry=ctx.industry,
            industry_source=ctx.industry_source,
            sector_index=ctx.sector_label,
            peers=[p.instrument.symbol for p in ctx.peers],
            peer_basis=ctx.peer_basis,
        )

    def latest(self, instrument_key: str) -> ResearchReport | None:
        row = self._db.fetchone(
            "SELECT payload FROM research_reports WHERE instrument_key = ?", [instrument_key]
        )
        return ResearchReport.model_validate(json.loads(row[0])) if row else None

    def _stored_at(self, instrument_key: str) -> tuple[datetime, str] | None:
        row = self._db.fetchone(
            "SELECT computed_at, signal FROM research_reports WHERE instrument_key = ?",
            [instrument_key],
        )
        return (_as_utc(row[0]), row[1]) if row else None

    @staticmethod
    def _is_stale(stored: tuple[datetime, str] | None) -> bool:
        if stored is None:
            return True
        at, signal = stored
        window = RETRY_AFTER if signal == "insufficient_data" else REFRESH_AFTER
        return datetime.now(UTC) - at > window

    def item(self, instrument: Instrument) -> ResearchItem:
        key = instrument.instrument_key
        report = self.latest(key)
        state, error = self._state.get(key, ("ready" if report else "not_started", None))
        stored = (report.computed_at, report.composite.signal) if report else None
        return ResearchItem(
            instrument=instrument,
            state=state,  # type: ignore[arg-type]
            error=error,
            stale=report is not None and self._is_stale(stored),
            report=report,
        )

    async def overview(self) -> ResearchOverview:
        keys = self._watchlist_keys()
        found = self._instruments.get_many(keys)
        return ResearchOverview(
            items=[self.item(found[k]) for k in keys if k in found],
            macro=await self._data.macro(),
            refresh_after_hours=REFRESH_AFTER.total_seconds() / 3600,
        )
