from datetime import UTC, date, datetime, timedelta

from app.agents import firm, industry, macro, sentiment
from app.agents.base import Peer, PriceSeries, ResearchContext
from app.providers.fred import parse_series
from app.providers.yahoo import Fundamentals, parse_summary
from app.schemas.market import Instrument, NewsItem
from app.services.research import composite, grounded
from app.services.research_data import MACRO_SERIES, macro_indicator
from app.tools import technicals as ta
from app.tools.headlines import is_relevant, name_terms, score_headline
from app.tools.scoring import percentile_rank, scale, signal_for, weighted

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
INST = Instrument(
    instrument_key="NSE_EQ|INE009A01021",
    symbol="INFY",
    name="Infosys",
    exchange="NSE",
    segment="NSE_EQ",
    instrument_type="EQ",
    isin="INE009A01021",
)


def _series(closes: list[float], label: str = "X") -> PriceSeries:
    start = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp())
    return PriceSeries(label, [start + i * 86400 for i in range(len(closes))], closes, "test", NOW)


def _trend(n: int, start: float, step: float) -> list[float]:
    return [start * (1 + step) ** i for i in range(n)]


# --- tools ----------------------------------------------------------------------


def test_scale_clamps_and_inverts():
    assert scale(0, -1, 1) == 0
    assert scale(5, -1, 1) == 1
    assert scale(-5, -1, 1) == -1
    assert scale(1.5, 1.5, 0.0) == -1  # inverted: high debt scores low


def test_weighted_reports_coverage():
    score, cov = weighted([(1.0, 0.5), (None, 0.5)])
    assert score == 1.0 and cov == 0.5
    assert weighted([(None, 1.0)]) == (None, 0.0)


def test_signal_requires_coverage():
    assert signal_for(0.9, 0.3) == "insufficient_data"
    assert signal_for(0.25, 1.0) == "positive"
    assert signal_for(-0.25, 1.0) == "negative"
    assert signal_for(0.1, 1.0) == "neutral"


def test_technicals():
    rising = _trend(260, 100, 0.001)
    assert ta.sma([1, 2, 3, 4], 2) == 3.5
    assert ta.period_return([100, 110], 1) == 0.10000000000000009
    assert ta.rsi(rising) == 100.0
    assert ta.max_drawdown([100, 120, 90, 130]) == -0.25
    market, asset = [100.0], [100.0]
    for i in range(120):
        r = 0.01 if i % 2 else -0.008
        market.append(market[-1] * (1 + r))
        asset.append(asset[-1] * (1 + 2 * r))
    assert abs(ta.beta(asset, market) - 2.0) < 1e-9
    assert percentile_rank(5, [1, 2, 3, 4]) == 1.0


def test_headline_scoring_traces_terms_and_negation():
    s = score_headline("Infosys shares surge after strong Q2 results")
    assert s.score == 1.0 and set(s.positive) == {"surge", "strong"}
    assert "Results" in s.events
    assert score_headline("Company faces probe, shares fall").score == -1.0
    assert score_headline("No loss seen this year").score == 1.0  # negated negative
    assert score_headline("Board meets on Monday").score == 0.0


def test_relevance_filter():
    terms = name_terms("Reliance Industries Ltd", "RELIANCE")
    assert "reliance industries" in terms
    assert is_relevant("Reliance shares rise", terms)
    assert not is_relevant("Nifty ends flat", terms)


# --- providers (parsing only) ---------------------------------------------------------


def test_fred_parse_skips_missing():
    rows = parse_series("observation_date,X\n2026-01-01,7.1\n2026-01-02,.\n2026-01-05,7.2\n")
    assert rows == [(date(2026, 1, 1), 7.1), (date(2026, 1, 5), 7.2)]


def test_yahoo_parse_derives_roe_and_converts_debt_ratio():
    result = {
        "financialData": {"debtToEquity": {"raw": 46.0}, "numberOfAnalystOpinions": {"raw": 5}},
        "defaultKeyStatistics": {
            "netIncomeToCommon": {"raw": 100.0},
            "bookValue": {"raw": 10.0},
            "sharesOutstanding": {"raw": 50.0},
        },
        "summaryDetail": {"trailingPE": {"raw": 21.5}},
        "recommendationTrend": {"trend": [{"period": "0m", "buy": 3, "hold": 2}]},
    }
    f = parse_summary("X.NS", result, NOW)
    assert f.roe == 0.2 and f.roe_derived
    assert f.debt_to_equity == 0.46
    assert f.trailing_pe == 21.5 and f.analyst_count == 5
    assert f.rating_counts == {"buy": 3, "hold": 2}
    assert f.esg_total is None
    assert Fundamentals.from_json(f.to_json()) == f


def test_macro_indicator_change_and_staleness():
    spec = next(s for s in MACRO_SERIES if s[0] == "in10y")
    rows = [(date(2026, 6, 1), 6.8), (date(2026, 9, 1), 7.06)]
    ind = macro_indicator(spec, rows, date(2026, 10, 25))
    assert ind.value == 7.06 and round(ind.change, 2) == 0.26 and not ind.stale
    old = macro_indicator(spec, rows, date(2027, 6, 1))
    assert old.stale and "Sep 2026" in (old.problem or "")
    assert macro_indicator(spec, [], date(2026, 10, 25)).value is None


# --- agents ---------------------------------------------------------------------------


def test_agents_report_insufficient_data_without_inputs():
    ctx = ResearchContext(instrument=INST, now=NOW, problems={"prices": "Upstox not connected"})
    for agent in (firm, industry, macro, sentiment):
        out = agent.run(ctx)
        assert out.signal == "insufficient_data"
        assert out.score is None and out.confidence == 0.0
        assert out.data_gaps  # every missing input is explained


def test_firm_agent_scores_with_evidence():
    peers = [
        Peer(INST, None, Fundamentals(symbol=f"P{i}", fetched_at=NOW, trailing_pe=pe))
        for i, pe in enumerate([20.0, 25.0, 30.0])
    ]
    f = Fundamentals(
        symbol="INFY.NS",
        fetched_at=NOW,
        trailing_pe=15.0,
        trailing_eps=60.0,
        roe=0.3,
        revenue_growth=0.10,
        earnings_growth=0.05,
        debt_to_equity=0.1,
    )
    ctx = ResearchContext(
        instrument=INST,
        now=NOW,
        stock=_series(_trend(300, 100, 0.002)),
        fundamentals=f,
        peers=peers,
        industry="Information Technology",
    )
    out = firm.run(ctx)
    assert out.signal == "positive" and out.score is not None and out.coverage == 1.0
    pe = next(e for e in out.evidence if e.metric == "P/E (trailing)")
    assert pe.score == 0.8  # 15x against a 25x peer median
    assert "peer median 25x" in (pe.detail or "")
    assert any("ESG" in g for g in out.data_gaps)
    assert out.rationale and "Not enough data" not in out.rationale


def test_firm_skips_leverage_for_lenders():
    f = Fundamentals(symbol="B.NS", fetched_at=NOW, debt_to_equity=8.0, roe=0.15)
    ctx = ResearchContext(instrument=INST, now=NOW, fundamentals=f, industry="Financial Services")
    out = firm.run(ctx)
    balance = next(x for x in out.factors if x.name == "Balance sheet")
    assert balance.weight == 0 and balance.score is None


def test_sentiment_uses_headlines_and_analysts():
    news = [
        NewsItem(title=t, link="https://x", publisher="P", published_at=NOW - timedelta(days=1))
        for t in ("Infosys wins large deal", "Infosys profit jumps", "Infosys shares rally")
    ]
    f = Fundamentals(
        symbol="INFY.NS", fetched_at=NOW, recommendation_mean=2.0, analyst_count=10, target_mean=110
    )
    ctx = ResearchContext(
        instrument=INST, now=NOW, headlines=news, fundamentals=f, stock=_series([100.0] * 70)
    )
    out = sentiment.run(ctx)
    assert out.signal == "positive"
    gap = next(e for e in out.evidence if e.metric == "Mean target vs last price")
    assert gap.value == 10.0


def test_macro_sector_exposure_follows_rules():
    rising_crude = macro_indicator(
        next(s for s in MACRO_SERIES if s[0] == "brent"),
        [(date(2026, 7, 20), 80.0), (date(2026, 10, 20), 100.0)],
        date(2026, 10, 25),
    )
    ctx = ResearchContext(
        instrument=INST, now=NOW, macro=[rising_crude], industry="Fast Moving Consumer Goods"
    )
    out = macro.run(ctx)
    exposure = next(x for x in out.factors if x.name == "Sector exposure")
    assert exposure.score is not None and exposure.score < 0  # FMCG input costs rise with crude


def test_composite_ignores_unscored_agents():
    ctx = ResearchContext(instrument=INST, now=NOW)
    empty = [a.run(ctx) for a in (firm, industry, macro, sentiment)]
    c = composite(empty)
    assert c.signal == "insufficient_data" and c.score is None and c.agents_used == 0


def test_rationale_grounding():
    src = "P/E = 15.36x (peer median 26.79x); revenue growth 1.4%"
    assert grounded("P/E of 15.36x sits below the 26.79x median.", src)
    assert not grounded("Shares could rise 20%.", src)


# --- API ------------------------------------------------------------------------------


def test_research_endpoints_and_watch_queues_run(make_client):
    client = make_client()
    svc = client.app.state.services
    svc.research._data.macro = _no_macro  # keep the test offline
    assert client.get("/api/research").json()["items"] == []
    item = client.get("/api/research/RELIANCE").json()
    assert item["state"] == "not_started" and item["report"] is None
    assert client.put("/api/watchlist", params={"key": "NSE_EQ|INE002A01018"}).status_code == 204
    body = client.get("/api/research").json()
    assert body["items"][0]["state"] == "queued"
    assert client.get("/api/research/NOPE").status_code == 404


async def _no_macro():
    return []
