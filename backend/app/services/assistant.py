"""Portfolio brief and question answering on top of the deterministic engine.

The language model sees only numbered facts the engine computed. Its output is rejected when
it contains numbers that are not in those facts (beyond rounding), cites unknown facts, or
reads as a personal buy or sell instruction. Results are cached by the facts they used, so the
model is called again only when the underlying data changes.
"""

import hashlib
import json
import logging
import re
import time
from collections import deque
from datetime import UTC, datetime

from app.db import Database
from app.errors import AppError, RateLimited
from app.providers.ollama import OllamaClient
from app.schemas.insights import AIStatus, AskAnswer, AskRequest, Brief, Fact, Narrative, Scenario
from app.services import insights
from app.services.instruments import InstrumentService
from app.services.monitor import SourceMonitor
from app.services.portfolio import PortfolioService
from app.services.research import ResearchService

log = logging.getLogger(__name__)

ASK_PER_MINUTE = 10
RETRY_REJECTED = 15 * 60  # seconds before a rejected brief is written again
_NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:,\d{2,3})*(?:\.\d+)?")
_FACT_ID = re.compile(r"\[(F\d+)\]")
_FACT_REF = re.compile(r"\s*[\[(](?:F\d+(?:,\s*)?)+[\])]")
_INSTRUCTION = re.compile(
    r"\b(you should (buy|sell|invest|exit)|i recommend (buying|selling)|guarantee[sd]?|"
    r"sure to (rise|gain)|will (definitely|certainly) (rise|fall))\b",
    re.I,
)

BRIEF_SYSTEM = (
    "You write the opening note of a portfolio app for an Indian retail investor. Use ONLY the "
    "numbered facts provided. Write 3 or 4 short sentences in plain English: what the portfolio "
    "looks like, how it has behaved, the main risk, and the most useful option to consider. "
    "Explain any financial term in everyday words. Copy numbers exactly as written in the facts. "
    "Do not predict prices or returns, do not promise anything, and do not tell the reader to buy "
    'or sell; describe options. Return JSON: {"text": string, "cited": [fact ids]}.'
)
ASK_SYSTEM = (
    "You are the FinCortext portfolio assistant for an Indian retail investor. Answer using ONLY "
    "the numbered facts. Put the fact id in square brackets after each claim, like [F3]. If the "
    "facts do not answer the question, say so and name the missing data. Never invent numbers, "
    "prices, targets or forecasts; copy numbers exactly as written in the facts. Do not promise "
    "returns. Do not tell the user to buy or sell; explain the options and trade-offs, the user "
    "decides. Past results are not forecasts. At most 120 words, plain language, explain any "
    "term you use. When the user asks to try or compare a change (add or drop stocks, change the "
    "objective or the maximum weight per stock), also return a scenario using NSE symbols. "
    'Objectives: lower_risk, balanced, growth, income. Return JSON: {"answer": string, '
    '"cited": [fact ids], "scenario": null or {"objective": string or null, "include": '
    '[symbols], "exclude": [symbols], "max_weight": number or null, "label": string}}.'
)


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUMBER.findall(text):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def ungrounded(text: str, source: str) -> list[float]:
    """Numbers in ``text`` that match no number in ``source`` within rounding."""
    known = _numbers(source)
    bad = []
    for x in _numbers(_FACT_REF.sub("", text)):
        if abs(x) <= 12 and x == int(x):
            continue  # counts and small ordinals ("2 stocks", "3 agents")
        if not any(abs(x - k) <= max(0.051, abs(k) * 0.02) for k in known):
            bad.append(x)
    return bad


class Assistant:
    def __init__(
        self,
        db: Database,
        portfolio: PortfolioService,
        research: ResearchService,
        instruments: InstrumentService,
        llm: OllamaClient | None,
        monitor: SourceMonitor,
    ):
        self._db = db
        self._portfolio = portfolio
        self._research = research
        self._instruments = instruments
        self._llm = llm
        self._monitor = monitor
        self._calls: deque[float] = deque()
        self._rejected: dict[str, float] = {}  # brief key -> when the model output failed checks

    def status(self) -> AIStatus:
        if self._llm is None:
            return AIStatus(
                enabled=False,
                model=None,
                detail="Set LLM_PROVIDER=ollama and OLLAMA_MODEL in .env to turn on the written "
                "brief and questions.",
            )
        state = next((s for s in self._monitor.states() if s.name == "llm"), None)
        detail = state.last_error if state and state.consecutive_failures else None
        return AIStatus(enabled=True, model=self._llm.model, detail=detail)

    # --- context ------------------------------------------------------------------

    def _research_items(self, symbols: list[str]):
        items = []
        for sym in symbols:
            try:
                items.append(self._research.item(self._instruments.by_symbol(sym)))
            except AppError:
                continue
        return items

    async def _context(self):
        prefs = self._portfolio.preferences()
        analysis = self._portfolio.latest()
        plan = None
        try:
            plan = await self._portfolio.plan(prefs)
        except AppError as exc:
            log.info("plan unavailable for brief: %s", exc.message)
        symbols = [a.symbol for a in plan.assets] if plan else []
        return analysis, plan, self._research_items(symbols)

    async def brief(self) -> Brief:
        analysis, plan, research = await self._context()
        headline, items, facts = insights.build(analysis, plan, research)
        narrative = None
        if self._llm is not None and facts:
            narrative = await self._narrative(headline, items, facts)
        return Brief(
            generated_at=datetime.now(UTC),
            analysis_at=analysis.computed_at if analysis else None,
            headline=headline,
            insights=items,
            facts=facts,
            narrative=narrative,
            ai=self.status(),
        )

    # --- model calls ----------------------------------------------------------------

    def _cached(self, key: str) -> dict | None:
        row = self._db.fetchone("SELECT text FROM text_cache WHERE k = ?", [key])
        return json.loads(row[0]) if row else None

    def _store(self, key: str, value: dict) -> None:
        assert self._llm is not None
        self._db.execute(
            "INSERT OR REPLACE INTO text_cache VALUES (?, ?, ?, ?)",
            [key, self._llm.model, json.dumps(value), datetime.now(UTC)],
        )

    async def _call(self, system: str, messages: list[dict]) -> dict:
        assert self._llm is not None
        try:
            out = await self._llm.chat_json(system, messages)
        except AppError as exc:
            self._monitor.failed("llm", exc.message)
            raise
        self._monitor.ok("llm")
        return out

    @staticmethod
    def _facts_text(facts: list[Fact]) -> str:
        return "\n".join(f"[{f.id}] ({f.basis}) {f.text}" for f in facts)

    async def _narrative(self, headline, items, facts: list[Fact]) -> Narrative | None:
        assert self._llm is not None
        facts_text = self._facts_text(facts)
        key = "brief:" + hashlib.sha1(f"{self._llm.model}\n{facts_text}".encode()).hexdigest()
        hit = self._cached(key)
        if hit and hit.get("text"):
            return Narrative(**hit)
        if time.monotonic() - self._rejected.get(key, -1e9) < RETRY_REJECTED:
            return None
        prompt = (
            f"Facts:\n{facts_text}\n\nMain points, most important first:\n"
            + "\n".join(f"- {i.title}" for i in items[:6])
            + f"\n\nSummary line already shown: {headline}"
        )
        valid = {f.id for f in facts}
        try:
            out = await self._call(BRIEF_SYSTEM, [{"role": "user", "content": prompt}])
        except AppError:
            self._rejected[key] = time.monotonic()
            return None
        text = str(out.get("text") or "").strip()
        cited = [c for c in out.get("cited") or [] if isinstance(c, str) and c in valid]
        ok = (
            40 <= len(text) <= 900
            and not ungrounded(text, facts_text)
            and not _INSTRUCTION.search(text)
        )
        result = (
            {
                "text": _FACT_REF.sub("", text).strip(),
                "cited": cited,
                "model": self._llm.model,
            }
            if ok
            else {}
        )
        if not ok:
            log.info("brief narrative rejected by checks")
            self._rejected[key] = time.monotonic()
            return None
        self._store(key, result)
        return Narrative(**result)

    def _limit(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) >= ASK_PER_MINUTE:
            raise RateLimited("Too many questions in a minute; try again shortly.")
        self._calls.append(now)

    def _scenario(self, raw, analysis, plan) -> Scenario | None:
        if not isinstance(raw, dict):
            return None
        try:
            sc = Scenario.model_validate(raw)
        except ValueError:
            return None
        known_plan = {a.symbol for a in plan.assets} if plan else set()
        include = []
        for sym in sc.include:
            s = str(sym).upper().strip()
            try:
                inst = self._instruments.by_symbol(s)
            except AppError:
                continue
            if inst.segment == "NSE_EQ" and s not in known_plan:
                include.append(s)
        exclude = [str(s).upper() for s in sc.exclude if str(s).upper() in known_plan]
        if not (include or exclude or sc.objective or sc.max_weight):
            return None
        return Scenario(
            objective=sc.objective,
            include=include,
            exclude=exclude,
            max_weight=sc.max_weight,
            label=(sc.label or "Suggested scenario")[:80],
        )

    async def ask(self, req: AskRequest) -> AskAnswer:
        if self._llm is None:
            raise AppError(
                "The assistant is off. Set LLM_PROVIDER=ollama and OLLAMA_MODEL in .env.",
                code="assistant_disabled",
                status_code=503,
            )
        self._limit()
        analysis, plan, research = await self._context()
        _, items, facts = insights.build(analysis, plan, research)
        book = insights.FactBook()
        book.facts = list(facts)
        if plan:
            insights.plan_facts(book, plan)
        for item in research:
            rep = item.report
            if rep is None:
                continue
            for a in rep.agents:
                if a.score is not None:
                    book.add(
                        f"{rep.instrument.symbol} {insights.AGENT_LABEL[a.agent].lower()} agent: "
                        f"{a.signal} ({a.score:+.2f}, confidence {a.confidence:.0%}). "
                        f"{a.rationale or ''}".strip(),
                        insights.RESEARCH,
                        "observed",
                        a.computed_at,
                    )
        if analysis:
            for c in analysis.candidates[:5]:
                book.add(f"Candidate {c.symbol}: {c.explanation}", insights.ENGINE, "estimate")
        facts = book.facts
        facts_text = self._facts_text(facts)
        valid = {f.id: f for f in facts}
        history = [{"role": t.role, "content": t.content} for t in req.history[-4:]]
        question = req.question.strip()
        messages = [
            *history,
            {"role": "user", "content": f"Facts:\n{facts_text}\n\nQuestion: {question}"},
        ]
        assert self._llm is not None
        answer = ""
        cited: list[str] = []
        raw_scenario = None
        grounded = False
        for attempt in range(2):
            out = await self._call(ASK_SYSTEM, messages)
            answer = str(out.get("answer") or "").strip()
            cited = [c for c in out.get("cited") or [] if isinstance(c, str) and c in valid]
            cited += [c for c in re.findall(r"F\d+", answer) if c in valid and c not in cited]
            raw_scenario = out.get("scenario")
            bad = ungrounded(answer, facts_text + "\n" + question)
            if answer and not bad and not _INSTRUCTION.search(answer):
                grounded = True
                break
            if attempt == 0:
                problem = (
                    f"These numbers are not in the facts: {', '.join(f'{x:g}' for x in bad[:5])}."
                    if bad
                    else "Do not instruct the user to buy or sell or promise outcomes."
                )
                messages = [
                    *messages,
                    {"role": "assistant", "content": json.dumps(out)},
                    {"role": "user", "content": f"{problem} Answer again using only the facts."},
                ]
        if not grounded:
            answer = (
                "I could not answer that using only verified data. The facts closest to your "
                "question are listed below."
            )
        return AskAnswer(
            answer=_FACT_REF.sub("", answer).strip(),
            cited=[valid[c] for c in dict.fromkeys(cited)][:8],
            scenario=self._scenario(raw_scenario, analysis, plan) if grounded else None,
            grounded=grounded,
            model=self._llm.model,
            generated_at=datetime.now(UTC),
        )
