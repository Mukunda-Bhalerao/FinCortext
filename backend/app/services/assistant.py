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
from types import SimpleNamespace

from app.db import Database
from app.errors import AppError, ProviderUnavailable, RateLimited
from app.providers.ollama import OllamaClient
from app.schemas.insights import AIStatus, AskAnswer, AskRequest, Brief, Fact, Narrative, Scenario
from app.schemas.plan import GoalRequest
from app.services import analyst, insights
from app.services.instruments import InstrumentService
from app.services.llm_budget import LLMBudget
from app.services.monitor import SourceMonitor
from app.services.portfolio import PortfolioService
from app.services.research import ResearchService
from app.services.signal_lab import SignalLab

log = logging.getLogger(__name__)

ASK_PER_MINUTE = 10
RETRY_REJECTED = 15 * 60  # seconds before a rejected brief is written again
_NUMBER = re.compile(r"(?<![A-Za-z])-?\d+(?:,\d{2,3})*(?:\.\d+)?")
_FACT_ID = re.compile(r"\[(F\d+)\]")
_FACT_REF = re.compile(r"\s*[\[(](?:F\d+(?:,\s*)?)+[\])]")
_INSTRUCTION = re.compile(
    r"\b(you should (buy|sell|invest|exit)|i recommend (buying|selling)|guarantee[sd]?|"
    r"sure to (rise|gain)|will (definitely|certainly) (rise|fall)|very high chance|"
    r"^yes\b)\b",
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
    "You are the FinCortext portfolio analyst for an Indian retail investor. Answer using ONLY "
    "the numbered facts. Put the fact id in square brackets after each claim, like [F3]. When "
    "the engine computed a result for this question, lead with that result and its numbers. If "
    "the facts do not answer the question, say so and name the missing data. Never invent "
    "numbers, prices, targets or forecasts; copy numbers exactly as written in the facts. "
    "Backtest and goal figures are past frequencies with stocks picked today: state them as "
    "such and never say yes, guaranteed, certain or very likely. Research scores have not been "
    "shown to predict returns, so never present them as the cause or a predictor of a price "
    "move. Do not tell the user to buy or sell; explain options and trade-offs, the user "
    "decides. At most 130 words, plain language, explain any term you use. When the user asks "
    "to try or compare a change (add or drop stocks, change the objective or a stock's weight), "
    "also return a scenario using NSE symbols. Objectives: lower_risk, balanced, growth, income. "
    'Return JSON: {"answer": string, "cited": [fact ids], "scenario": null or {"objective": '
    'string or null, "include": [symbols], "exclude": [symbols], "max_weight": number or null, '
    '"label": string}}.'
)
CHAT_SYSTEM = (
    "You are the assistant inside FinCortext, a stock-market practice app for beginners in "
    "India. Rewrite the engine's answer in a warm, plain voice using ONLY the numbered facts. "
    "Copy every number exactly as written; add no numbers, forecasts or promises. Never tell "
    "the user to buy or sell; describe what is true and what they could look at. Explain any "
    "market term in a few words. At most 110 words, no lists. "
    'Return JSON: {"answer": string, "cited": [fact ids]}.'
)
CONCEPT_SYSTEM = (
    "You explain stock-market concepts to a beginner in India, inside a practice app. Answer "
    "in at most 90 words of plain language. Use no numbers, figures, prices or percentages at "
    "all. Do not predict anything and do not tell the user to buy or sell. If the question "
    "needs live data or is not about investing, say what the app can calculate instead. "
    'Return JSON: {"answer": string}.'
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
        budget: LLMBudget | None = None,
        lab: SignalLab | None = None,
    ):
        self._budget = budget
        self._lab = lab
        self._db = db
        self._portfolio = portfolio
        self._research = research
        self._instruments = instruments
        self._llm = llm
        self._monitor = monitor
        self._calls: deque[float] = deque()
        self._symbols: set[str] | None = None
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
        used = self._budget.used_today()["calls"] if self._budget else 0
        return AIStatus(
            enabled=True,
            model=self._llm.model,
            detail=detail,
            calls_today=used,
            daily_limit=self._budget.daily_calls if self._budget else 0,
        )

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()

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

    async def _call(self, system: str, messages: list[dict], purpose: str = "chat") -> dict:
        assert self._llm is not None
        try:
            try:
                out = await self._llm.chat_json(system, messages, purpose)
            except ProviderUnavailable as exc:
                if "malformed" not in exc.message:
                    raise
                out = await self._llm.chat_json(system, messages, purpose)  # one retry
        except AppError as exc:
            self._monitor.failed("llm", exc.message)
            raise
        self._monitor.ok("llm")
        return out

    @staticmethod
    def _facts_text(facts: list[Fact]) -> str:
        return "\n".join(f"[{f.id}] ({f.basis}) {f.text}" for f in facts)

    async def narrate(
        self, headline: str, points: list[str], facts: list[Fact]
    ) -> Narrative | None:
        """A short written summary of ``facts``; None when the model is off, over budget or its
        text fails the checks. Cached by the facts it used."""
        if self._llm is None or not facts:
            return None
        return await self._narrative(headline, [SimpleNamespace(title=p) for p in points], facts)

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
            out = await self._call(BRIEF_SYSTEM, [{"role": "user", "content": prompt}], "brief")
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

    # --- helpers for the app-wide assistant ---------------------------------------------

    @property
    def model_name(self) -> str | None:
        return self._llm.model if self._llm is not None else None

    async def phrase(
        self, question: str, draft: str, facts: list[Fact], history: list[dict]
    ) -> tuple[str, list[str]] | None:
        """The engine's answer in a warmer voice, or None when the model is off, fails, adds a
        number that is not in the facts, or drifts into advice. The engine's own answer is
        then shown unchanged."""
        if self._llm is None or not facts:
            return None
        facts_text = self._facts_text(facts)
        messages = [
            *history[-4:],
            {
                "role": "user",
                "content": f"Question: {question}\n\nEngine answer: {draft}\n\n"
                f"Facts:\n{facts_text}",
            },
        ]
        try:
            out = await self._call(CHAT_SYSTEM, messages, "chat")
        except AppError:
            return None
        text = str(out.get("answer") or "").strip()
        allowed = f"{facts_text}\n{question}\n{draft}"
        if not 30 <= len(text) <= 1000 or ungrounded(text, allowed) or _INSTRUCTION.search(text):
            log.info("chat phrasing rejected by checks")
            return None
        valid = {f.id for f in facts}
        cited = [c for c in out.get("cited") or [] if isinstance(c, str) and c in valid]
        return _FACT_REF.sub("", text).strip(), cited

    async def pick_tool(self, question: str, tools: dict[str, str]) -> dict | None:
        """When the rules cannot place a question, let the model choose among the tools. It
        only chooses; the tool still computes the answer."""
        if self._llm is None:
            return None
        system = (
            "Choose the tool that answers the user's question in an Indian stock-market "
            "practice app. Tools:\n"
            + "\n".join(f"- {k}: {v}" for k, v in tools.items())
            + '\nReturn JSON: {"tool": a tool name or "none", "symbol": an NSE symbol or null, '
            '"term": a market term or null}.'
        )
        try:
            out = await self._call(system, [{"role": "user", "content": question}], "route")
        except AppError:
            return None
        return out if isinstance(out, dict) else None

    async def concept(self, question: str) -> str | None:
        """A short conceptual explanation with no figures, for questions no tool covers.
        Rejected if it contains any number or reads as advice."""
        if self._llm is None:
            return None
        try:
            out = await self._call(
                CONCEPT_SYSTEM, [{"role": "user", "content": question}], "concept"
            )
        except AppError:
            return None
        text = str(out.get("answer") or "").strip()
        if not 40 <= len(text) <= 800 or ungrounded(text, question) or _INSTRUCTION.search(text):
            return None
        return text

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

    # --- analyst tools ------------------------------------------------------------

    def _known_symbols(self) -> set[str]:
        if self._symbols is None:
            rows = self._db.fetchall(
                "SELECT trading_symbol FROM instruments WHERE segment = 'NSE_EQ'"
            )
            self._symbols = {r[0].upper() for r in rows}
        return self._symbols

    async def _tool(self, r: analyst.Route, prefs, plan, analysis) -> analyst.ToolOutcome | None:
        if r.tool == "scenario" and plan is not None:
            include = [s for s in r.add if s not in prefs.include]
            exclude = [s for s in r.remove if s not in prefs.exclude]
            if not (
                include or exclude or r.weights or (r.objective and r.objective != prefs.objective)
            ):
                return None
            label_parts = []
            if exclude:
                label_parts.append("without " + ", ".join(exclude))
            if include:
                label_parts.append("adding " + ", ".join(include))
            if r.weights:
                label_parts.append(", ".join(f"{k} at {v:.0%}" for k, v in r.weights.items()))
            if r.objective and r.objective != prefs.objective:
                label_parts.append(r.objective.replace("_", " "))
            scenario = Scenario(
                objective=r.objective if r.objective != prefs.objective else None,
                include=include,
                exclude=exclude,
                custom_weights=r.weights or None,
                label=("Try " + "; ".join(label_parts))[:80],
            )
            after_prefs = prefs.model_copy(
                update={
                    "objective": scenario.objective or prefs.objective,
                    "include": list(dict.fromkeys(prefs.include + include))[-8:],
                    "exclude": list(dict.fromkeys(prefs.exclude + exclude)),
                    "custom_weights": r.weights or prefs.custom_weights,
                }
            )
            after = await self._portfolio.plan(after_prefs)
            return analyst.scenario_outcome(plan, after, scenario)
        if r.tool == "compare" and analysis is not None and analysis.objectives:
            return analyst.compare_outcome(analysis.objectives, prefs.objective)
        if r.tool == "investigate" and r.symbols:
            return await self._investigate(r.symbols[0], plan)
        if r.tool == "goal":
            if not r.target or not r.years:
                return analyst.ToolOutcome(
                    "goal",
                    "Goal check",
                    'Tell me a target amount and a time frame, for example: "Can I reach 50 '
                    'lakh in 10 years adding 10k a month?"',
                    [],
                )
            req = GoalRequest(
                preferences=prefs,
                target=r.target,
                years=min(30, max(1, r.years)),
                initial=prefs.capital,
                monthly=r.monthly or 0.0,
            )
            proj = await self._portfolio.goal(req)
            needed = await self._portfolio.required_monthly(req, (0.5, 0.75))
            return analyst.goal_outcome(proj, {"even": needed[0], "three-in-four": needed[1]}, r)
        return None

    async def _investigate(self, sym: str, plan) -> analyst.ToolOutcome | None:
        try:
            inst = self._instruments.by_symbol(sym)
        except AppError:
            return None
        data = await self._portfolio.performance(inst)
        if data is None:
            return None
        summary = await self._portfolio.summary()
        holding = next((h for h in summary.holdings if h.symbol == sym), None)
        asset = next((a for a in plan.assets if a.symbol == sym), None) if plan else None
        research = self._research.latest(inst.instrument_key)
        changes = self._research.changes(inst.instrument_key, research) if research else None
        return analyst.investigate_outcome(sym, data, holding, asset, research, changes)

    async def ask(self, req: AskRequest) -> AskAnswer:
        """Route the question to a deterministic tool, then let the model explain the result
        from the computed facts. Without the model (off, offline, over budget or invalid
        output) the tool's own summary is the answer."""
        self._limit()
        analysis, plan, research = await self._context()
        prefs = self._portfolio.preferences()
        held = {a.symbol for a in plan.assets} if plan else set()
        familiar = {c.symbol for c in analysis.candidates} if analysis else set()
        question = req.question.strip()
        r = analyst.route(question, self._known_symbols(), held, datetime.now(UTC).date(), familiar)
        try:
            outcome = await self._tool(r, prefs, plan, analysis)
        except AppError as exc:
            outcome = analyst.ToolOutcome(r.tool, "Could not compute", exc.message, [])

        _, _, facts = insights.build(analysis, plan, research)
        book = insights.FactBook()
        tool_ids: list[str] = []
        if outcome:
            for f in outcome.facts:
                tool_ids.append(book.add(f.text, f.source, f.basis, f.as_of))
        for f in facts:
            book.add(f.text, f.source, f.basis, f.as_of)
        if plan:
            insights.plan_facts(book, plan)
        validation = self._lab.latest() if self._lab else None
        if validation:
            book.add(validation.headline, "FinCortext research validation", "measured")
            for t in validation.tests:
                if t.kind != "factor" and t.mean_ic is not None:
                    book.add(
                        f"{t.label}: average rank correlation with the next month's returns "
                        f"{t.mean_ic:+.3f} over {t.months} months ({t.verdict}). {t.verdict_text}",
                        "FinCortext research validation",
                        "measured",
                    )
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
        valid = {f.id: f for f in facts}

        def engine_answer(notice: str | None) -> AskAnswer:
            if outcome is not None:
                text = outcome.summary
                cited = tool_ids
            else:
                headline, items, _ = insights.build(analysis, plan, research)
                text = headline + (
                    " " + " ".join(i.title + "." for i in items[:3]) if items else ""
                )
                text += (
                    " Ask about a specific stock, a what-if change, a comparison of objectives "
                    "or a goal for a calculated answer."
                )
                cited = []
            return AskAnswer(
                answer=text,
                cited=[valid[c] for c in cited if c in valid][:10],
                scenario=outcome.scenario if outcome else None,
                grounded=True,
                model=None,
                generated_at=datetime.now(UTC),
                tool=outcome.tool if outcome else None,
                title=outcome.title if outcome else None,
                data=outcome.data if outcome else None,
                answered_by="engine",
                notice=notice,
            )

        if self._llm is None:
            return engine_answer(
                "The language model is off, so this answer comes from the calculation engine."
            )
        facts_text = self._facts_text(facts)
        history = [{"role": t.role, "content": t.content} for t in req.history[-4:]]
        lead = (
            f"The engine computed this for the question ({outcome.tool}): {outcome.summary}\n"
            f"The facts {', '.join(tool_ids)} hold its numbers; build the answer on them.\n\n"
            if outcome and tool_ids
            else ""
        )
        messages = [
            *history,
            {"role": "user", "content": f"{lead}Facts:\n{facts_text}\n\nQuestion: {question}"},
        ]
        answer = ""
        cited: list[str] = []
        raw_scenario = None
        grounded = False
        try:
            for attempt in range(2):
                out = await self._call(ASK_SYSTEM, messages, "ask")
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
                        "These numbers are not in the facts: "
                        f"{', '.join(f'{x:g}' for x in bad[:5])}."
                        if bad
                        else "Do not instruct the user to buy or sell or promise outcomes."
                    )
                    messages = [
                        *messages,
                        {"role": "assistant", "content": json.dumps(out)},
                        {
                            "role": "user",
                            "content": f"{problem} Answer again using only the facts.",
                        },
                    ]
        except RateLimited as exc:
            return engine_answer(exc.message)
        except AppError as exc:
            return engine_answer(f"{exc.message} This answer comes from the calculation engine.")
        if not grounded:
            return engine_answer(
                "The model's answer contained numbers that are not in the data, so the engine's "
                "own answer is shown instead."
            )
        scenario = (
            outcome.scenario
            if outcome and outcome.scenario
            else self._scenario(raw_scenario, analysis, plan)
        )
        cited = list(dict.fromkeys(tool_ids + cited)) if outcome else cited
        return AskAnswer(
            answer=_FACT_REF.sub("", answer).strip(),
            cited=[valid[c] for c in cited if c in valid][:10],
            scenario=scenario,
            grounded=True,
            model=self._llm.model,
            generated_at=datetime.now(UTC),
            tool=outcome.tool if outcome else None,
            title=outcome.title if outcome else None,
            data=outcome.data if outcome else None,
        )
