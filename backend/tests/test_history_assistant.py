import json
from datetime import UTC, datetime, timedelta

from app.db import Database
from app.schemas.market import Instrument, NewsItem
from app.schemas.research import (
    AgentOutput,
    Classification,
    Composite,
    FactorScore,
    ResearchReport,
)
from app.services.assistant import ungrounded
from app.services.research import ResearchService
from app.tools.research_diff import diff_reports

INST = Instrument(
    instrument_key="NSE_EQ|INE009A01021",
    symbol="INFY",
    name="Infosys",
    exchange="NSE",
    segment="NSE_EQ",
    instrument_type="EQ",
    isin="INE009A01021",
)


def _report(at: datetime, score: float, signal: str, sentiment: float, titles: list[str]):
    def agent(name: str, s: float, sig: str) -> AgentOutput:
        return AgentOutput(
            agent=name,
            subject="INFY",
            signal=sig,
            score=s,
            confidence=0.7,
            coverage=1.0,
            factors=[FactorScore(name="Tone", weight=1.0, score=s)],
            evidence=[],
            data_gaps=[],
            rationale=None,
            method="t",
            computed_at=at,
        )

    sent_sig = "positive" if sentiment > 0.2 else "negative" if sentiment < -0.2 else "neutral"
    return ResearchReport(
        instrument=INST,
        classification=Classification(
            industry=None, industry_source=None, sector_index=None, peers=[], peer_basis=None
        ),
        agents=[agent("firm", 0.1, "neutral"), agent("sentiment", sentiment, sent_sig)],
        composite=Composite(signal=signal, score=score, confidence=0.6, agents_used=2, method="t"),
        headlines=[
            NewsItem(title=t, link=f"https://x/{t}", publisher="p", published_at=at) for t in titles
        ],
        computed_at=at,
        duration_ms=1,
    )


def test_diff_names_signal_changes_and_new_headlines():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    old = _report(t0, 0.25, "positive", 0.4, ["A"])
    new = _report(t0 + timedelta(days=1), 0.05, "neutral", -0.3, ["A", "B"])
    d = diff_reports(old, new)
    texts = [c.text for c in d.items]
    assert d.items[0].kind == "signal" and d.items[0].direction == "worse"
    assert "Overall view changed from positive to neutral." in texts
    assert any("News sentiment view changed" in t for t in texts)
    assert any("1 new headline" in t for t in texts)
    assert diff_reports(old, old).summary == "No material change."


def test_history_keeps_runs_and_compares_with_a_day_ago():
    db = Database(":memory:")
    svc = ResearchService(db, None, None, lambda: [])  # type: ignore[arg-type]
    now = datetime.now(UTC)
    runs = [
        _report(now - timedelta(days=1, hours=2), 0.3, "positive", 0.4, ["A"]),
        _report(now - timedelta(hours=6), 0.28, "positive", 0.35, ["A"]),
        _report(now, 0.0, "neutral", -0.3, ["A", "B"]),
    ]
    for r in runs:
        payload = r.model_dump_json()
        db.execute(
            "INSERT OR REPLACE INTO research_reports VALUES (?, ?, ?, ?)",
            [INST.instrument_key, r.composite.signal, payload, r.computed_at],
        )
        svc._record(INST.instrument_key, r, payload)
    h = svc.history(INST)
    assert len(h.points) == 3 and h.points[-1].score == 0.0
    assert h.changes is not None and h.changes.since == runs[0].computed_at
    assert h.changes.previous_signal == "positive"


def test_history_thins_old_days_to_their_last_run():
    db = Database(":memory:")
    svc = ResearchService(db, None, None, lambda: [])  # type: ignore[arg-type]
    day = datetime.now(UTC) - timedelta(days=10)
    for h in (2, 8, 14):
        r = _report(day.replace(hour=h), 0.1, "neutral", 0.0, [])
        svc._record(INST.instrument_key, r, r.model_dump_json())
    rows = db.fetchall("SELECT computed_at FROM research_history")
    assert len(rows) == 1


def test_backfill_seeds_history_from_stored_reports():
    db = Database(":memory:")
    r = _report(datetime.now(UTC), 0.2, "neutral", 0.0, [])
    db.execute(
        "INSERT INTO research_reports VALUES (?, ?, ?, ?)",
        [INST.instrument_key, "neutral", r.model_dump_json(), r.computed_at],
    )
    ResearchService(db, None, None, lambda: [])  # type: ignore[arg-type]
    row = db.fetchone("SELECT payload FROM research_history")
    assert json.loads(row[0])["composite"]["score"] == 0.2


def test_ungrounded_allows_rounding_and_counts_but_not_new_numbers():
    facts = "[F1] Estimated volatility is 14.8% and the plan returned +19.0% a year from 2018."
    assert ungrounded("Swings of about 15% and +19% a year [F1] across 3 stocks.", facts) == []
    assert ungrounded("It will return 25% next year.", facts) == [25.0]
    assert ungrounded("Since 2018 [F1].", facts) == []
