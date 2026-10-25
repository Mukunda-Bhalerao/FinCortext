"""Shared input context and output builder for the research agents.

Agents are pure functions of a ``ResearchContext``: the research service gathers every input
first (prices, fundamentals, peers, macro series, headlines), then each agent scores what it
was given. Numbers in the output come from these inputs and the tools package only.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.providers.yahoo import Fundamentals
from app.schemas.market import Instrument, NewsItem
from app.schemas.research import AgentOutput, Evidence, FactorScore, MacroIndicator
from app.tools.scoring import confidence, signal_for, weighted


@dataclass
class PriceSeries:
    label: str
    times: list[int]  # session start, UTC seconds
    closes: list[float]
    source: str
    as_of: datetime

    @property
    def pairs(self) -> list[tuple[int, float]]:
        return list(zip(self.times, self.closes, strict=True))


@dataclass
class Peer:
    instrument: Instrument
    series: PriceSeries | None
    fundamentals: Fundamentals | None


@dataclass
class ResearchContext:
    instrument: Instrument
    now: datetime
    industry: str | None = None
    industry_source: str | None = None
    sector_label: str | None = None
    stock: PriceSeries | None = None
    benchmark: PriceSeries | None = None  # NIFTY 50
    sector: PriceSeries | None = None
    vix: PriceSeries | None = None
    fundamentals: Fundamentals | None = None
    peers: list[Peer] = field(default_factory=list)
    peer_basis: str | None = None
    macro: list[MacroIndicator] = field(default_factory=list)
    headlines: list[NewsItem] = field(default_factory=list)
    headline_terms: list[str] = field(default_factory=list)
    problems: dict[str, str] = field(default_factory=dict)  # input name -> reason it is missing


def pct(x: float | None) -> float | None:
    return round(x * 100.0, 2) + 0.0 if x is not None else None


def r2(x: float | None) -> float | None:
    return round(x, 2) if x is not None else None


def fmt_value(value: float | str | None, unit: str | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return value
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    if unit in ("%", "x"):
        return f"{text}{unit}"
    if unit == "pp":
        return f"{value:+.2f} pp"
    return f"{text} {unit}" if unit and unit != "count" else text


class Factor:
    def __init__(self, name: str, weight: float):
        self.name = name
        self.weight = weight
        self.parts: list[float] = []
        self.note: str | None = None

    def add(self, score: float | None) -> float | None:
        if score is not None:
            self.parts.append(score)
        return score

    @property
    def score(self) -> float | None:
        return sum(self.parts) / len(self.parts) if self.parts else None


class AgentBuilder:
    def __init__(self, agent: str, subject: str, method: str, now: datetime):
        self.agent = agent
        self.subject = subject
        self.method = method
        self.now = now
        self.factors: list[Factor] = []
        self.evidence_rows: list[Evidence] = []
        self.gaps: list[str] = []

    def factor(self, name: str, weight: float) -> Factor:
        f = Factor(name, weight)
        self.factors.append(f)
        return f

    def evidence(
        self,
        factor: str,
        metric: str,
        value: float | str | None,
        *,
        source: str,
        unit: str | None = None,
        detail: str | None = None,
        as_of: datetime | None = None,
        score: float | None = None,
    ) -> None:
        self.evidence_rows.append(
            Evidence(
                factor=factor,
                metric=metric,
                value=value,
                unit=unit,
                detail=detail,
                source=source,
                as_of=as_of,
                score=r2(score),
            )
        )

    def gap(self, text: str) -> None:
        text = text.replace("..", ".")
        if text not in self.gaps:
            self.gaps.append(text)

    def build(self, quality: float = 1.0) -> AgentOutput:
        score, coverage = weighted([(f.score, f.weight) for f in self.factors])
        scored = [f for f in self.factors if f.score is not None]
        signal = signal_for(score, coverage)
        return AgentOutput(
            agent=self.agent,  # type: ignore[arg-type]
            subject=self.subject,
            signal=signal,  # type: ignore[arg-type]
            score=r2(score) if signal != "insufficient_data" else None,
            confidence=confidence(coverage, [f.score for f in scored], quality)  # type: ignore[misc]
            if signal != "insufficient_data"
            else 0.0,
            coverage=round(coverage, 2),
            factors=[
                FactorScore(name=f.name, weight=f.weight, score=r2(f.score), note=f.note)
                for f in self.factors
            ],
            evidence=self.evidence_rows,
            data_gaps=self.gaps,
            rationale=self._rationale(signal),
            method=self.method,
            computed_at=self.now,
        )

    def _lead(self, factor: Factor) -> str:
        rows = [e for e in self.evidence_rows if e.factor == factor.name and e.score is not None]
        if not rows:
            return factor.name
        key = max(rows, key=lambda e: abs(e.score or 0))
        return f"{factor.name} ({key.metric} {fmt_value(key.value, key.unit)})"

    def _rationale(self, signal: str) -> str:
        active = [f for f in self.factors if f.weight > 0]
        scored = [f for f in active if f.score is not None]
        missing = [f.name for f in active if f.score is None]
        if signal == "insufficient_data":
            text = f"Not enough data to score: {len(scored)} of {len(active)} factors."
        else:
            text = f"{len(scored)} of {len(active)} factors scored."
            up = sorted((f for f in scored if f.score >= 0.2), key=lambda f: -f.score)  # type: ignore[operator]
            down = sorted((f for f in scored if f.score <= -0.2), key=lambda f: f.score)  # type: ignore[arg-type]
            if up:
                text += " Supportive: " + "; ".join(self._lead(f) for f in up[:2]) + "."
            if down:
                text += " Weighing: " + "; ".join(self._lead(f) for f in down[:2]) + "."
            if not up and not down:
                text += " No factor is strongly supportive or weighing."
        if missing:
            text += " Not covered: " + ", ".join(missing) + "."
        return text
