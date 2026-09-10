"""Portfolio Agent — Central Orchestrator (synthesis, not scoring).

Consumes the four existing analyst outputs for ONE company and explains how
they fit together. It runs no models, fetches no data, and invents no
numbers: every sentence traces back to an underlying output's signals,
factors, limitations, or coverage gaps.

Deliberately absent from the output: any overall score or overall signal.
Blending a company BUY with a macro NEUTRAL into a single rating would
misrepresent both. Disagreement is shown, not averaged away.
"""

from __future__ import annotations

from app.agents.portfolio import methodology as M
from app.data.universe.universe_config import get_universe_entry
from app.domain.models.agent_output import AgentOutput
from app.domain.models.macro import MacroOutput
from app.domain.models.portfolio import (
    AgreementView,
    PortfolioEvidence,
    PortfolioView,
    PerspectiveView,
    ScenarioView,
)

# What each perspective needs when it is missing — used verbatim in scenarios.
MISSING_INPUTS = {
    "firm_analyst": "fundamental observations and price history",
    "industry_analyst": "peer price history",
    "sentiment_analyst": "relevant financial news",
    "macro_analyst": "macro indicator history",
}


class PortfolioAgent:
    """Deterministic synthesis over the four analyst outputs."""

    agent_id = "portfolio_agent"

    def __init__(self, portfolio_repo=None):
        self._portfolio_repo = portfolio_repo

    # ------------------------------------------------------------------

    def analyze(
        self,
        symbol: str,
        *,
        firm: AgentOutput | None = None,
        industry: AgentOutput | None = None,
        sentiment: AgentOutput | None = None,
        macro: MacroOutput | None = None,
    ) -> PortfolioView:
        entry = get_universe_entry(symbol)
        perspectives = [
            self._perspective("firm_analyst", "Firm Analyst", "analyst", firm),
            self._perspective("industry_analyst", "Industry Analyst", "analyst", industry),
            self._perspective("sentiment_analyst", "Sentiment Analyst", "analyst", sentiment),
            self._perspective("macro_analyst", "Macro Analyst", "macro", macro),
        ]
        available = [p for p in perspectives if p.direction != "missing"]
        directions = [p.direction for p in available]

        verdict, summary = M.agreement_of(directions)
        conflicts = self._conflicts(available)
        agreement = AgreementView(
            available_count=len(available),
            positive_count=sum(1 for d in directions if d == "positive"),
            neutral_count=sum(1 for d in directions if d == "neutral"),
            negative_count=sum(1 for d in directions if d == "negative"),
            verdict=verdict,
            conflicts=conflicts,
            summary=summary,
        )

        scenarios = self._scenarios(perspectives, available)
        thesis = self._thesis(entry.symbol, available, agreement, conflicts)
        evidence = self._evidence(perspectives)
        risks = self._risks(perspectives)

        coverage = len(available) / 4
        confidence = M.combine_confidence(
            [p.confidence for p in available], len(available)
        )
        if not available:
            status = "UNAVAILABLE"
        elif len(available) < M.MIN_PERSPECTIVES_OK:
            status = "DEGRADED"
        else:
            status = "OK"

        limitations = self._limitations(perspectives)
        rationale = self._rationale(entry.symbol, agreement, conflicts, scenarios, coverage)

        return PortfolioView(
            entity_id=entry.symbol,
            perspectives=perspectives,
            agreement=agreement,
            scenarios=scenarios,
            thesis=thesis,
            evidence=evidence,
            risks=risks,
            coverage=round(coverage, 2),
            confidence=confidence,
            status=status,
            rationale=rationale,
            data_limitations=limitations,
            provenance={
                "methodology": "portfolio_agent_v1",
                "analysts_available": len(available),
                "analysts_total": 4,
                "macro_data_through": (
                    macro.data_through if macro is not None else {}
                ),
            },
        )

    def run(
        self,
        symbol: str,
        *,
        persist: bool = True,
        firm: AgentOutput | None = None,
        industry: AgentOutput | None = None,
        sentiment: AgentOutput | None = None,
        macro: MacroOutput | None = None,
    ) -> PortfolioView:
        """Synthesize (optionally persisting the view)."""
        output = self.analyze(
            symbol, firm=firm, industry=industry, sentiment=sentiment, macro=macro
        )
        if persist and self._portfolio_repo is not None:
            self._portfolio_repo.save_output(output)
        return output

    # -- perspective normalization ---------------------------------------------

    @staticmethod
    def _perspective(agent_id: str, label: str, kind: str, output) -> PerspectiveView:
        if output is None:
            entity = "MACRO_INDIA" if kind == "macro" else "unknown"
            return PerspectiveView(
                agent_id=agent_id,
                label=label,
                entity_id=entity,
                direction="missing",
                signal_label="not run",
                score=None,
                confidence=0.0,
                status="UNAVAILABLE",
                takeaway=f"{label}: no result available for this run.",
                limitations=[f"{label} produced no output in this run."],
                generated_at=None,
            )
        if kind == "macro":
            direction = M.direction_of("macro", output.overall_signal.value, output.score)
            signal_label = f"{output.overall_signal.value.upper()}-environment"
            takeaway = (
                f"{label}: {output.overall_signal.value.upper()} environment "
                f"at {output.score:.0f}/100"
                if output.score is not None
                else f"{label}: {output.overall_signal.value.upper()} environment"
            ) + f" ({output.status}, confidence {round(output.confidence * 100):.0f}%)."
            return PerspectiveView(
                agent_id=agent_id,
                label=label,
                entity_id=output.entity_id,
                direction=direction or "missing",
                signal_label=signal_label,
                score=output.score,
                confidence=output.confidence,
                status=output.status,
                takeaway=takeaway,
                limitations=list(output.data_limitations),
                generated_at=output.generated_at.isoformat()
                if output.generated_at is not None
                else None,
            )
        direction = M.direction_of("analyst", output.signal.value, output.score)
        signal_label = output.signal.value.replace("_", " ").upper()
        if direction is None:
            takeaway = f"{label}: no usable score — treated as missing, not neutral."
        else:
            takeaway = (
                f"{label}: {signal_label} at "
                f"{round(output.score):.0f}/100"  # type: ignore[arg-type]
                if output.score is not None
                else f"{label}: {signal_label}"
            ) + f" ({output.status}, confidence {round(output.confidence * 100):.0f}%)."
        return PerspectiveView(
            agent_id=agent_id,
            label=label,
            entity_id=output.entity_id,
            direction=direction or "missing",
            signal_label=signal_label,
            score=output.score,
            confidence=output.confidence,
            status=output.status,
            takeaway=takeaway,
            limitations=list(output.data_limitations),
            generated_at=output.generated_at.isoformat()
            if output.generated_at is not None
            else None,
        )

    # -- agreement / conflicts ----------------------------------------------------

    @staticmethod
    def _conflicts(available: list[PerspectiveView]) -> list[dict]:
        conflicts = []
        for i, first in enumerate(available):
            for second in available[i + 1:]:
                pair = {first.direction, second.direction}
                if pair == {"positive", "negative"}:
                    conflicts.append(
                        {
                            "between": [first.label, second.label],
                            "description": (
                                f"{first.label} leans positive ({first.signal_label}) "
                                f"while {second.label} leans negative "
                                f"({second.signal_label}) — both views are kept; "
                                f"neither is averaged away."
                            ),
                        }
                    )
        return conflicts

    # -- scenarios ------------------------------------------------------------------

    @staticmethod
    def _first_limitation(perspective: PerspectiveView) -> str | None:
        return perspective.limitations[0] if perspective.limitations else None

    def _scenarios(
        self, perspectives: list[PerspectiveView], available: list[PerspectiveView]
    ) -> list[ScenarioView]:
        base_bits = []
        for p in available:
            base_bits.append(f"{p.label}: {p.signal_label}.")
        if not base_bits:
            base_bits.append("No analyst views are available — no base case can be stated.")
        base = ScenarioView(
            label="Base case",
            leaning="as-stated",
            conditions=base_bits,
            note="Takes every available perspective exactly as reported, limitations included.",
        )

        bull_conditions = []
        for p in perspectives:
            if p.direction == "positive":
                continue
            if p.direction == "missing":
                bull_conditions.append(
                    f"{p.label} has no usable result — fresh "
                    f"{MISSING_INPUTS.get(p.agent_id, 'inputs')} would be needed first."
                )
            else:
                first = self._first_limitation(p)
                bull_conditions.append(
                    f"{p.label} reads {p.signal_label}"
                    + (f"; its own caveat: {first}" if first else "")
                    + " — a turn here would strengthen the overall picture."
                )
        if not bull_conditions:
            bull_conditions.append(
                "All available perspectives already lean positive — the bull case "
                "is simply that current evidence holds."
            )
        bull = ScenarioView(
            label="Bull case",
            leaning="conditional-positive",
            conditions=bull_conditions,
            note="What would have to change (or hold) for a stronger picture. "
            "Conditions, not predictions.",
        )

        bear_conditions = []
        for p in available:
            if p.direction != "positive":
                continue
            first = self._first_limitation(p)
            bear_conditions.append(
                f"{p.label} is positive ({p.signal_label})"
                + (f" but flags: {first}" if first else "")
                + " — deterioration here would weaken the overall picture."
            )
        if not bear_conditions:
            bear_conditions.append(
                "No currently-positive perspective to defend — the bear case is "
                "that missing inputs arrive weak."
            )
        bear = ScenarioView(
            label="Bear case",
            leaning="conditional-negative",
            conditions=bear_conditions,
            note="What would have to break for a weaker picture. "
            "Conditions, not predictions.",
        )
        return [base, bull, bear]

    # -- thesis / evidence / risks -----------------------------------------------------

    @staticmethod
    def _thesis(symbol: str, available, agreement, conflicts) -> str:
        if not available:
            return (
                f"No analyst perspectives are available for {symbol}, so no "
                f"investment thesis can be stated. Run the analysts first — "
                f"nothing is inferred from missing data."
            )
        strongest = max(available, key=lambda p: p.confidence)
        weakest = min(available, key=lambda p: p.confidence)
        macro_line = ""
        for p in available:
            if p.agent_id == "macro_analyst":
                macro_line = (
                    f" The macro backdrop reads {p.signal_label}"
                    f"{f' at {round(p.score):.0f}/100' if p.score is not None else ''} "
                    f"and applies equally to every company — it supports context, "
                    f"not a stock call."
                )
        conflict_line = ""
        if conflicts:
            names = "; ".join(
                f"{c['between'][0]} vs {c['between'][1]}" for c in conflicts
            )
            conflict_line = f" Open disagreements ({len(conflicts)}): {names}."
        return (
            f"For {symbol}: {agreement.summary} "
            f"Best-supported view: {strongest.label} ({strongest.signal_label}, "
            f"confidence {round(strongest.confidence * 100):.0f}%). "
            f"Weakest link: {weakest.label} ({weakest.status})."
            f"{macro_line}{conflict_line}"
        )

    @staticmethod
    def _evidence(perspectives: list[PerspectiveView]) -> list[PortfolioEvidence]:
        evidence = []
        for p in perspectives:
            if p.direction == "missing" and p.status == "UNAVAILABLE" and not p.limitations:
                continue
            evidence.append(
                PortfolioEvidence(
                    agent_id=p.agent_id,
                    entity_id=p.entity_id,
                    signal=p.signal_label,
                    score=p.score,
                    status=p.status,
                    generated_at=p.generated_at,
                    note=p.takeaway,
                )
            )
        return evidence

    @staticmethod
    def _risks(perspectives: list[PerspectiveView]) -> list[str]:
        risks = []
        for p in perspectives:
            if p.direction == "missing":
                risks.append(f"{p.label} unavailable — its angle is absent from this view.")
            elif p.status in {"DEGRADED", "ERROR"}:
                risks.append(f"{p.label} is {p.status} — treat its view as partial.")
            risks.extend(f"{p.label}: {lim}" for lim in p.limitations)
        return risks

    @staticmethod
    def _limitations(perspectives: list[PerspectiveView]) -> list[str]:
        missing = [p.label for p in perspectives if p.direction == "missing"]
        limitations = []
        if missing:
            limitations.append(
                "Missing perspectives (shown, not filled in): " + ", ".join(missing) + "."
            )
        limitations.append(
            "Synthesis only — perspectives are compared, never blended into one score."
        )
        return limitations

    @staticmethod
    def _rationale(symbol: str, agreement, conflicts, scenarios, coverage: float) -> str:
        conflict_bit = (
            f" {len(conflicts)} explicit disagreement(s) are listed, not hidden."
            if conflicts
            else " No opposing pairs among available perspectives."
        )
        bull = next(s for s in scenarios if s.label == "Bull case")
        bear = next(s for s in scenarios if s.label == "Bear case")
        return (
            f"Portfolio view for {symbol}: {agreement.summary}{conflict_bit} "
            f"Bull case hinges on: {bull.conditions[0] if bull.conditions else '—'} "
            f"Bear case hinges on: {bear.conditions[0] if bear.conditions else '—'} "
            f"Coverage {round(coverage * 100):.0f}% of perspectives available."
        )
