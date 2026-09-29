"""Unit tests for central company preparation (mocked providers, no keys).

Covers: INFY search/select/prepare, quote+history storage, timestamp
propagation to API responses, stale-date protection, Firm/Industry/
Sentiment/Portfolio data flow, industry peer fallback + relevance,
dynamic-universe stocks, duplicate-free re-preparation, honest missing-data
handling, no fabricated values, yfinance independence, and Upstox provider
selection via LIVE_MARKET_PROVIDER.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ProviderUnavailableError
from app.data.providers.market.upstox_client import UpstoxHttpClient
from app.data.providers.market.upstox_provider import UpstoxMarketProvider
from app.data.providers.market.yfinance_provider import YFinanceMarketProvider
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import clear_dynamic_registry
from app.domain.contracts.providers import FundamentalDataProvider, NewsProvider
from app.domain.models.news import NewsArticle
from app.repositories.agent_output_repository import AgentOutputRepository
from app.repositories.financial_repository import FinancialRepository
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.macro_repository import MacroRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.news_repository import NewsRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.universe_repository import UniverseRepository
from app.services.agent_service import AgentService
from app.services.company_preparation_service import CompanyPreparationService
from app.services.fundamentals_service import FundamentalsService
from app.services.market_service import MarketService
from app.services.news_service import NewsService


FAKE_TS = "2026-09-28T15:30:00+05:30"


def _search_row(symbol, name, isin, token):
    return {
        "name": name,
        "segment": "NSE_EQ",
        "exchange": "NSE",
        "isin": isin,
        "instrument_key": f"NSE_EQ|{isin}",
        "exchange_token": token,
        "trading_symbol": symbol,
        "instrument_type": "EQ",
    }


_SEARCH = {
    "INFY": [("INFY", "INFOSYS LTD", "INE009A01021", "1594")],
    "TCS": [("TCS", "TATA CONSULTANCY SERVICES LTD", "INE467B01029", "2955")],
    "RELIANCE": [("RELIANCE", "RELIANCE INDUSTRIES LTD", "INE002A01018", "2885")],
    "WIPRO": [("WIPRO", "WIPRO LTD", "INE075A01022", "3787")],
    "ONGC": [("ONGC", "OIL & NATURAL GAS CORP LTD", "INE213A01029", "2475")],
    "ADANIENT": [("ADANIENT", "ADANI ENTERPRISES LTD", "INE423A01024", "25")],
    "ADANIPOWER": [("ADANIPOWER", "ADANI POWER LTD", "INE814H01011", "3291")],
    "BBL": [("BBL", "BHARAT BIJLEE LTD", "INE464A01028", "1036")],
    "TATAPOWER": [("TATAPOWER", "TATA POWER CO LTD", "INE245A01021", "400")],
    "NTPC": [("NTPC", "NTPC LTD", "INE733E01010", "2882")],
}

_QUOTE_PRICE = {
    "INFY": (1750.0, 1740.0),
    "TCS": (3142.75, 3105.50),
    "RELIANCE": (1420.5, 1400.0),
    "WIPRO": (520.0, 515.0),
    "ONGC": (310.0, 305.0),
    "ADANIENT": (2500.0, 2480.0),
    "ADANIPOWER": (620.0, 610.0),
    "BBL": (3800.0, 3750.0),
    "TATAPOWER": (430.0, 425.0),
    "NTPC": (390.0, 385.0),
}


def _gen_candles(start: date, end: date, base: float = 100.0):
    out, d, i = [], start, 0
    while d <= end:
        if d.weekday() < 5:
            o = base + i * 0.5
            out.append([d.isoformat() + "T00:00:00+05:30", o, o * 1.02, o * 0.98, o * 1.01, 1000 + i * 10, 0])
            i += 1
        d += timedelta(days=1)
    return out


class FakePrepUpstoxClient(UpstoxHttpClient):
    """Canned Upstox search/quotes/candles; no network, no real token."""

    def __init__(self, *, auth_fail=False):
        super().__init__("fake-token-for-tests-only")
        self.auth_fail = auth_fail
        self.calls: list = []

    def _boom(self):
        raise ProviderUnavailableError(
            "Upstox authentication failed — check UPSTOX_ACCESS_TOKEN.",
            details={"provider": "upstox"},
        )

    def search_instruments(self, query, **kwargs):
        self.calls.append(("search", query))
        if self.auth_fail:
            self._boom()
        q = (query or "").strip().upper().replace(".NS", "")
        rows = _SEARCH.get(q, [])
        return {
            "status": "success",
            "data": [_search_row(*r) for r in rows],
            "meta_data": {},
        }

    def fetch_full_quotes(self, instrument_keys):
        self.calls.append(("quotes", tuple(instrument_keys)))
        if self.auth_fail:
            self._boom()
        data = {}
        for key in instrument_keys:
            symbol = "X"
            for sym, rows in _SEARCH.items():
                if any(f"NSE_EQ|{r[2]}" == key for r in rows):
                    symbol = sym
            last, prev = _QUOTE_PRICE.get(symbol, (100.0, 99.0))
            data[f"NSE_EQ:{symbol}"] = {
                "ohlc": {"open": prev, "high": last + 5, "low": prev - 5,
                         "close": last, "volume": 123456, "ts": 1757000100000},
                "timestamp": FAKE_TS,
                "instrument_token": key,
                "symbol": symbol,
                "last_price": last,
                "volume": 123456,
                "average_price": (last + prev) / 2,
                "prev_close_price": prev,
                "year_high": last + 200,
                "year_low": prev - 200,
            }
        return data

    def fetch_daily_candles(self, instrument_key, start, end):
        self.calls.append(("candles", instrument_key))
        if self.auth_fail:
            self._boom()
        return _gen_candles(start, end)


def _bundle(symbol):
    annual = []
    for i, (rev, ni) in enumerate([(1000.0, 150.0), (900.0, 120.0)]):
        annual.append({
            "period_end": date(2025 - i, 3, 31),
            "total_revenue": rev,
            "net_income": ni,
            "total_assets": 2000.0,
            "total_equity": 800.0,
            "total_debt": 200.0,
        })
    return {
        "symbol": symbol,
        "ticker": f"{symbol}.NS",
        "currency": "INR",
        "annual": annual,
        "snapshot": {"pe_ratio": 22.5, "roe": 0.19, "as_of": date.today().isoformat()},
        "warnings": [],
    }


class FakeFundamentalsProvider(FundamentalDataProvider):
    name = "fake_fundamentals"

    def fetch_fundamentals(self, ticker: str) -> dict:
        return _bundle(ticker)


class FakeNewsProvider(NewsProvider):
    """First call per query returns nothing (to exercise the fallback
    variant); the fallback query returns relevant articles."""

    name = "fake_news"

    def __init__(self):
        self.is_configured = True
        self.queries: list[str] = []

    def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
        self.queries.append(query)
        base = datetime(2026, 9, 27, tzinfo=timezone.utc)
        if "stock OR" in query or "shares" in query:
            titles = [
                ("https://n.test/infy1", "Infosys beats quarterly estimates"),
                ("https://n.test/infy2", "Infosys surges to record profit"),
                ("https://n.test/infy3", "Infosys wins large deal, strong outlook"),
            ]
            return [
                NewsArticle(
                    article_id=hashlib.sha256(url.encode()).hexdigest(),
                    title=title,
                    description="Infosys reports quarterly revenue growth",
                    content=None,
                    source="Fake Wire",
                    source_url=url,
                    published_at=base - timedelta(days=i),
                    language="en",
                    content_hash=hashlib.sha256(title.encode()).hexdigest(),
                )
                for i, (url, title) in enumerate(titles)
            ]
        return []


class FakeSentimentModel:
    model_id = "fake-finbert"

    def analyze(self, texts):
        return [
            {"label": "positive", "positive": 0.9, "neutral": 0.07,
             "negative": 0.03, "confidence": 0.9}
            for _ in texts
        ]


@pytest.fixture(autouse=True)
def _clean_dynamic():
    clear_dynamic_registry()
    yield
    clear_dynamic_registry()


def _make_prep_stack(tmp_path, db_name, *, research_service=None, news_provider=None,
                     industry_classifier=None):
    from app.repositories.research_repository import ResearchRepository

    storage = DuckDBStorage(tmp_path / db_name)
    storage.connect()
    market_repo = MarketRepository(storage)
    financial_repo = FinancialRepository(storage)
    news_repo = NewsRepository(storage)
    output_repo = AgentOutputRepository(storage)
    provenance_repo = ProvenanceRepository(storage)
    instrument_repo = InstrumentRepository(storage)
    universe_repo = UniverseRepository(storage)
    macro_repo = MacroRepository(storage)
    portfolio_repo = PortfolioRepository(storage)
    research_repo = ResearchRepository(storage)

    from app.data.universe.universe_config import get_static_universe

    yf = YFinanceMarketProvider({e.symbol: e.ticker for e in get_static_universe()})
    client = FakePrepUpstoxClient()
    provider = UpstoxMarketProvider("fake-token", client=client, fallback=yf)
    market_service = MarketService(
        provider, market_repo, provenance_repo,
        instrument_repo=instrument_repo, universe_repo=universe_repo,
    )
    fund_service = FundamentalsService(FakeFundamentalsProvider(), financial_repo, provenance_repo)
    news_provider = news_provider or FakeNewsProvider()
    news_service = NewsService(news_provider, news_repo, provenance_repo)
    prep = CompanyPreparationService(
        market_service=market_service,
        fundamentals_service=fund_service,
        news_service=news_service,
        market_repo=market_repo,
        financial_repo=financial_repo,
        news_repo=news_repo,
        instrument_repo=instrument_repo,
        universe_repo=universe_repo,
        research_service=research_service,
        industry_classifier=industry_classifier,
    )
    agents = AgentService(
        financial_repo, market_repo, output_repo,
        news_repo=news_repo,
        sentiment_model=FakeSentimentModel(),
        market_service=market_service,
        macro_repo=macro_repo,
        portfolio_repo=portfolio_repo,
    )
    return {
        "storage": storage, "prep": prep, "agents": agents,
        "market_service": market_service, "market_repo": market_repo,
        "financial_repo": financial_repo, "news_repo": news_repo,
        "instrument_repo": instrument_repo, "client": client,
        "news_provider": news_provider, "research_repo": research_repo,
        "research_service": research_service, "provenance_repo": provenance_repo,
    }


@pytest.fixture()
def stack(tmp_path):
    s = _make_prep_stack(tmp_path, "prep.duckdb")
    yield s
    s["storage"].close()


# 1. Search INFY ---------------------------------------------------------------


def test_search_infy(stack):
    res = stack["market_service"].search_symbols("INFY")
    assert res["count"] == 1
    row = res["results"][0]
    assert row["symbol"] == "INFY"
    assert row["instrument_key"] == "NSE_EQ|INE009A01021"
    assert row["exchange"] == "NSE"
    assert row["segment"] == "EQ"


# 2. Select INFY -----------------------------------------------------------------


def test_select_infy(stack):
    resolved = stack["market_service"].resolve_symbol("INFY")
    assert resolved["symbol"] == "INFY"
    assert resolved["name"] == "Infosys"
    assert resolved["dynamic"] is False


# 3. Preparation succeeds -----------------------------------------------------------


def test_preparation_succeeds(stack):
    prep = stack["prep"].prepare_company("INFY")
    assert prep["symbol"] == "INFY"
    assert prep["readiness"] in ("ready", "partial")
    assert set(prep["areas"]) == {
        "resolve", "company_metadata", "quote", "history",
        "fundamentals", "news", "peers", "web_research",
    }
    assert prep["areas"]["quote"]["status"] in ("LIVE", "CACHED")
    assert prep["areas"]["history"]["status"] in ("LIVE", "CACHED")


# 4. Quote stored / available ------------------------------------------------------------


def test_quote_stored_and_available(stack):
    stack["prep"].prepare_company("INFY")
    stored = stack["market_repo"].get_stored_quote("INFY")
    assert stored is not None
    assert stored["last_price"] == 1750.0
    assert stored["timestamp"] == FAKE_TS
    assert stored["source"] == "upstox"
    quote = stack["market_service"].get_quote("INFY")
    assert quote["last_price"] == 1750.0
    assert quote["timestamp"] == FAKE_TS


# 5. History stored / available --------------------------------------------------------------


def test_history_stored_and_available(stack):
    stack["prep"].prepare_company("INFY")
    count = stack["market_repo"].count("INFY")
    assert count >= 10
    latest = stack["market_repo"].latest_trade_date("INFY")
    assert latest is not None
    assert (date.today() - latest).days <= 7


# 6. Timestamp reaches the frontend (API shape) -------------------------------------------------


def test_timestamp_reaches_api_response(stack, tmp_path, monkeypatch):
    import app.api.routes.market as market_routes
    from app.main import create_app

    stack["prep"].prepare_company("INFY")

    class TestContainer:
        def __init__(self):
            self.market_service = stack["market_service"]
            self.market_repo = stack["market_repo"]
            self.company_preparation_service = stack["prep"]

    monkeypatch.setattr(market_routes, "get_container", lambda: TestContainer())
    client = TestClient(create_app())

    q = client.get("/api/market/quote/INFY")
    assert q.status_code == 200
    body = q.json()
    assert body["timestamp"] == FAKE_TS
    assert body["source"] == "upstox"
    assert body["last_price"] == 1750.0

    p = client.get("/api/market/prices/INFY")
    assert p.status_code == 200
    series = p.json()
    assert series["quote_timestamp"] == FAKE_TS
    assert series["quote_source"] == "upstox"
    assert series["count"] >= 10

    r = client.get("/api/market/prepared/INFY")
    assert r.status_code == 200
    assert r.json()["areas"]["quote"]["timestamp"] == FAKE_TS


# 7. Newer Upstox data wins over older cached dates --------------------------------------------------


def test_newer_upstox_quote_beats_stale_series_date(stack):
    from app.domain.models.market import MarketPrice

    stack["market_repo"].upsert_bars([
        MarketPrice(
            symbol="INFY", provider_ticker="INFY.NS", trade_date=date(2024, 1, 2),
            open=100.0, high=110.0, low=95.0, close=105.0, volume=1000,
        )
    ])
    stack["prep"].prepare_company("INFY")
    series = stack["market_service"].get_price_series("INFY")
    assert series["quote_timestamp"] == FAKE_TS
    # The Upstox quote timestamp survives alongside history (which refreshes
    # through today) — freshness comes from the quote, not the bar dates.
    assert series["quote_timestamp"] is not None
    # An older yfinance snapshot must never overwrite the Upstox one,
    # regardless of wall-clock date (no fixed-date ordering assumptions).
    assert stack["market_repo"].upsert_quote({
        "symbol": "INFY", "timestamp": "2024-01-03",
        "source": "yfinance", "last_price": 1.0,
    }) is False
    assert stack["market_repo"].get_stored_quote("INFY")["timestamp"] == FAKE_TS


# 8. Firm receives data -------------------------------------------------------------------


def test_firm_receives_data(stack):
    stack["prep"].prepare_company("INFY")
    out = stack["agents"].run_agent("firm_analyst", "INFY")
    assert out.score is not None
    assert out.status in ("OK", "DEGRADED")


# 9. Industry receives data -----------------------------------------------------------------


def test_industry_receives_data(stack):
    stack["prep"].prepare_company("INFY")
    out = stack["agents"].run_agent("industry_analyst", "INFY")
    assert out.score is not None
    assert "TCS" in (out.provenance.get("peers_with_prices") or [])


# 10. Industry fallback peers when configured peers missing ---------------------------------------


def test_industry_finds_fallback_peers(stack):
    prep = stack["prep"].prepare_company("RELIANCE")
    discovered = prep["areas"]["peers"]["discovered_peers"]
    assert len(discovered) >= 1
    out = stack["agents"].run_agent("industry_analyst", "RELIANCE")
    assert out.score is not None


# 11. Fallback peers are relevant ----------------------------------------------------------------------


def test_fuzzy_upstox_match_never_becomes_peer(stack, monkeypatch):
    """Upstox search is fuzzy: 'LTIM' can return BSE Ltd as the top row.
    Discovery must only accept exact listings, never a lookalike."""
    real_search = FakePrepUpstoxClient.search_instruments

    def fuzzy_search(self, query, **kwargs):
        if (query or "").strip().upper() == "LTIM":
            return {
                "status": "success",
                "data": [{
                    "name": "BSE LTD",
                    "segment": "NSE_EQ",
                    "exchange": "NSE",
                    "isin": "INE118H01025",
                    "instrument_key": "NSE_EQ|INE118H01025",
                    "exchange_token": "9999",
                    "trading_symbol": "BSE",
                    "instrument_type": "EQ",
                }],
                "meta_data": {},
            }
        return real_search(self, query, **kwargs)

    monkeypatch.setattr(FakePrepUpstoxClient, "search_instruments", fuzzy_search)
    prep = stack["prep"].prepare_company("INFY")
    discovered = prep["areas"]["peers"]["discovered_peers"]
    assert "BSE" not in discovered
    # BSE (Financial Services) must not leak into the IT peer set either.
    peers = stack["prep"].company_peers("INFY")
    assert "BSE" not in {p["symbol"] for p in peers["peers"]}


def test_fallback_peers_relevant(stack):
    prep = stack["prep"].prepare_company("RELIANCE")
    discovered = prep["areas"]["peers"]["discovered_peers"]
    assert discovered
    from app.data.universe.universe_config import SECTOR_PEER_CANDIDATES

    energy_candidates = {c[0] for c in SECTOR_PEER_CANDIDATES["Energy"]}
    assert set(discovered) <= energy_candidates
    peers = stack["prep"].company_peers("RELIANCE")
    by_symbol = {p["symbol"]: p for p in peers["peers"]}
    for sym in discovered:
        assert by_symbol[sym]["sector"] == "Energy"


# 12. Sentiment preparation runs ------------------------------------------------------------------------


def test_sentiment_preparation_runs(stack):
    prep = stack["prep"].prepare_company("INFY")
    news_area = prep["areas"]["news"]
    assert news_area["stored_total"] >= 3
    # The fallback variant query ran (first attempt stored nothing).
    assert any("shares" in q for q in stack["news_provider"].queries)
    out = stack["agents"].run_agent("sentiment_analyst", "INFY")
    assert out.score is not None
    assert out.status in ("OK", "DEGRADED")


# 13. Portfolio receives analyst outputs ---------------------------------------------------------------------


def test_portfolio_receives_outputs(stack):
    stack["prep"].prepare_company("INFY")
    # Analysts run from their own runs first; synthesis only reads storage.
    for agent_id in ("firm_analyst", "industry_analyst", "sentiment_analyst", "macro_analyst"):
        stack["agents"].run_agent(agent_id, "INFY")
    view = stack["agents"].run_portfolio("INFY")
    assert len(view.perspectives) == 4
    assert view.agreement.available_count >= 1


# 14. Stock outside the static universe -----------------------------------------------------------------------------


def test_dynamic_universe_stock(stack):
    prep = stack["prep"].prepare_company("ADANIENT")
    assert prep["readiness"] in ("ready", "partial")
    assert prep["areas"]["history"]["rows"] >= 10
    quote = stack["market_service"].get_quote("ADANIENT")
    assert quote["last_price"] == 2500.0


# 15. No duplicate rows on repeat ------------------------------------------------------------------------------


def test_repeat_preparation_no_duplicates(stack):
    stack["prep"].prepare_company("INFY")
    first_market = stack["market_repo"].count("INFY")
    first_fund = len(stack["financial_repo"].get_observations("INFY"))
    first_news = len(stack["news_repo"].get_articles("INFY", limit=1000))
    stack["prep"].prepare_company("INFY")
    assert stack["market_repo"].count("INFY") == first_market
    assert len(stack["financial_repo"].get_observations("INFY")) == first_fund
    assert len(stack["news_repo"].get_articles("INFY", limit=1000)) == first_news
    assert stack["market_repo"].get_stored_quote("INFY")["timestamp"] == FAKE_TS
    rows = stack["storage"].fetch_all(
        "SELECT COUNT(*) AS n FROM upstox_instruments WHERE symbol = ?", ["INFY"]
    )
    assert int(rows[0]["n"]) == 1


# 16-17. Missing data honest, nothing fabricated --------------------------------------------------------------------------


def test_missing_provider_data_honest(tmp_path):
    from app.data.universe.universe_config import get_static_universe

    storage = DuckDBStorage(tmp_path / "prep_fail.duckdb")
    storage.connect()
    try:
        market_repo = MarketRepository(storage)
        client = FakePrepUpstoxClient(auth_fail=True)
        provider = UpstoxMarketProvider("fake", client=client)
        market_service = MarketService(
            provider, market_repo, ProvenanceRepository(storage),
            instrument_repo=InstrumentRepository(storage),
            universe_repo=UniverseRepository(storage),
        )
        prep = CompanyPreparationService(
            market_service=market_service,
            fundamentals_service=FundamentalsService(
                FakeFundamentalsProvider(), FinancialRepository(storage),
                ProvenanceRepository(storage),
            ),
            news_service=NewsService(
                FakeNewsProvider(), NewsRepository(storage),
                ProvenanceRepository(storage),
            ),
            market_repo=market_repo,
            financial_repo=FinancialRepository(storage),
            news_repo=NewsRepository(storage),
        )
        result = prep.prepare_company("INFY")
        assert result["readiness"] in ("partial", "unavailable")
        assert result["areas"]["quote"]["status"] in ("UNAVAILABLE", "ERROR")
        assert result["areas"]["history"]["status"] in ("UNAVAILABLE", "ERROR")
        # Nothing fabricated anywhere.
        assert market_repo.count("INFY") == 0
        assert market_repo.get_stored_quote("INFY") is None
        rows = storage.fetch_all(
            "SELECT DISTINCT source_type AS s FROM market_prices"
        )
        assert all(r["s"] != "sample" for r in rows)
    finally:
        storage.close()


# 18. yfinance independent -------------------------------------------------------------------------------------------


def test_yfinance_provider_still_works(tmp_path):
    import pandas as pd

    provider = YFinanceMarketProvider({"TCS": "TCS.NS"})
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    df = pd.DataFrame(
        {"Open": [100.0, 101.0], "High": [110.0, 111.0], "Low": [95.0, 96.0],
         "Close": [105.0, 106.0], "Volume": [1000, 1100]},
        index=idx,
    )
    bars = provider.normalize_frame(df, symbol="TCS", provider_ticker="TCS.NS")
    assert len(bars) == 2
    assert bars[0].source_name == "yfinance"

    storage = DuckDBStorage(tmp_path / "yf.duckdb")
    storage.connect()
    try:
        market_repo = MarketRepository(storage)
        svc = MarketService(provider, market_repo, ProvenanceRepository(storage))
        # yfinance-only search degrades to the static universe filter.
        res = svc.search_symbols("INFY")
        assert res["count"] >= 1
        assert res["results"][0]["symbol"] == "INFY"
        # yfinance-only quote derives honestly from stored bars.
        market_repo.upsert_bars(bars)
        quote = svc.get_quote("TCS")
        assert quote["last_price"] == 106.0
        assert quote["source"] == "yfinance"
    finally:
        storage.close()


# 19. Upstox active via LIVE_MARKET_PROVIDER -------------------------------------------------------------------------------


def test_upstox_active_provider_selection(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("LIVE_MARKET_PROVIDER", "upstox")
    assert get_settings().live_market_provider == "upstox"
    assert UpstoxMarketProvider("x", client=FakePrepUpstoxClient()).name == "upstox"

# --- Research-backed scenarios (ADANIPOWER / BBL) ---------------------------------


class FakeResearchProvider:
    """Canned Gemini-style research; no network, no keys."""

    name = "fake_research"

    def __init__(self, *, configured=True, enrich=None, peers=None, digest=None):
        self.is_configured = configured
        self.model_name = "fake-gemini"
        # symbol -> (sector, industry, confidence)
        self.enrich = enrich or {}
        # symbol -> list[(symbol, name, reason)]
        self.peers = peers or {}
        # symbol -> list[digest items]
        self.digest = digest or {}
        self.calls: list = []

    def research_company(self, symbol, company_name):
        from app.core.exceptions import ProviderUnavailableError

        self.calls.append(("company", symbol))
        if not self.is_configured:
            raise ProviderUnavailableError("not configured", details={"provider": self.name})
        sector, industry, conf = self.enrich.get(symbol.upper(), (None, None, 0.0))
        return {
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "business_description": f"{company_name} business (fake research).",
            "confidence": conf,
            "peers": [],
            "sources": [{"title": "Fake source", "url": "https://fake.test/x",
                         "domain": "fake.test", "retrieved_at": "2026-09-28T00:00:00+00:00"}],
            "model": self.model_name,
            "retrieved_at": "2026-09-28T00:00:00+00:00",
        }

    def suggest_peers(self, symbol, company_name, sector, industry, *, max_peers=8):
        self.calls.append(("peers", symbol))
        rows = self.peers.get(symbol.upper(), [])
        return {
            "peers": [
                {"symbol": s, "name": n, "reason": r} for s, n, r in rows
            ][:max_peers],
            "sources": [],
            "model": self.model_name,
            "retrieved_at": "2026-09-28T00:00:00+00:00",
        }

    def research_news(self, symbol, company_name):
        self.calls.append(("news", symbol))
        return {
            "items": list(self.digest.get(symbol.upper(), [])),
            "sources": [],
            "model": self.model_name,
            "retrieved_at": "2026-09-28T00:00:00+00:00",
        }


@pytest.fixture()
def rst_stack(tmp_path):
    """Preparation stack with fake Gemini research wired in.

    The classifier uses the real committed CSV but a stubbed yfinance
    fetcher (no network): CSV misses fall through to the fake research,
    which is exactly the BBL path under test.
    """
    from app.data.universe.industry_classifier import IndustryClassifier
    from app.services.research_service import ResearchService

    def _no_yfinance(symbol):
        raise RuntimeError("network disabled in tests")

    s = _make_prep_stack(
        tmp_path, "prep_research.duckdb",
        industry_classifier=IndustryClassifier(yfinance_fetcher=_no_yfinance),
    )
    provider = FakeResearchProvider(
        enrich={
            "ADANIPOWER": ("Utilities", "Power Generation", 0.9),
            "BBL": ("Industrials", "Electrical Equipment", 0.82),
        },
        peers={
            "ADANIPOWER": [
                ("TATAPOWER", "Tata Power", "thermal peer"),
                ("NTPC", "NTPC", "power peer"),
                ("FAKECO", "Fake Co", "must be skipped: not a real listing"),
            ],
            "BBL": [
                ("TATAPOWER", "Tata Power", "equipment-adjacent peer"),
                ("FAKECO", "Fake Co", "must be skipped: not a real listing"),
            ],
        },
        digest={
            "ADANIPOWER": [
                {"title": "Adani Power commissions new unit",
                 "summary": "800 MW added (fake research).",
                 "url": "https://fake.test/adani-unit",
                 "source": "Fake Wire", "published_at": "2026-09-20"},
            ],
        },
    )
    research_service = ResearchService(
        provider, s["research_repo"], s["provenance_repo"],
    )
    s["prep"].research_service = research_service
    s["research_provider"] = provider
    s["research_service"] = research_service
    # Hermetic classifier: real committed CSV, stubbed yfinance (no network).
    # CSV misses (BBL) fall through to the fake research above.
    from app.data.universe.industry_classifier import IndustryClassifier

    def _no_yfinance(symbol):
        raise RuntimeError("network disabled in tests")

    s["prep"].industry_classifier = IndustryClassifier(yfinance_fetcher=_no_yfinance)
    yield s
    s["storage"].close()

# 20. ADANIPOWER classified via NSE CSV (structured beats research) -----------


def test_adanipower_classified_not_unknown(rst_stack):
    from app.data.universe.universe_config import get_universe_entry

    prep = rst_stack["prep"].prepare_company("ADANIPOWER")
    assert prep["readiness"] in ("ready", "partial")
    meta = prep["areas"]["company_metadata"]
    assert meta["status"] == "LIVE"
    # NSE's official list wins over the fake research below (Utilities).
    assert meta["sector"] == "Power"
    assert meta["industry"] == "Power"
    assert meta["source"] == "nse_nifty500_csv"
    entry = get_universe_entry("ADANIPOWER")
    assert entry.sector == "Power"
    assert entry.industry == "Power"
    assert prep["components"]["company_metadata"] == "READY"


# 21. CSV peers validated through Upstox --------------------------------------------


def test_adanipower_csv_peers_validated(rst_stack):
    prep = rst_stack["prep"].prepare_company("ADANIPOWER")
    peers = prep["areas"]["peers"]
    assert peers["status"] in ("LIVE", "CACHED")
    assert {"TATAPOWER", "NTPC"} <= set(peers["usable_peers"])
    # CSV peers were insufficient alone (not Upstox-resolvable in order), so
    # the fake research filled the gap — both sources validated live.
    assert "FAKECO" not in peers["usable_peers"]
    assert prep["components"]["peers"] == "READY"
    assert prep["components"]["industry"] == "READY"


# 22. Industry Analyst scores for ADANIPOWER ----------------------------------------------


def test_adanipower_industry_scores(rst_stack):
    rst_stack["prep"].prepare_company("ADANIPOWER")
    out = rst_stack["agents"].run_agent("industry_analyst", "ADANIPOWER")
    assert out.score is not None
    assert out.status in ("OK", "DEGRADED")
    # Full trace: Gemini-suggested, Upstox-validated peers actually reach the
    # Industry Analyst's peer set — not just stored, but consumed.
    with_prices = set(out.provenance.get("peers_with_prices") or [])
    assert {"TATAPOWER", "NTPC"} <= with_prices
    assert "FAKECO" not in with_prices


# 23. News variants tried for ADANIPOWER ----------------------------------------------------


def test_adanipower_news_variants_tried(rst_stack):
    rst_stack["prep"].prepare_company("ADANIPOWER")
    queries = rst_stack["news_provider"].queries
    # Short company-name variant ("ADANI POWER") must be attempted, not only
    # the exact quoted legal name.
    assert any("ADANI POWER" in q.upper() for q in queries)
    assert len(queries) >= 2  # default + at least one variant


# 24. Research digest fallback is labeled, sentiment stays honest -------------------------------


def test_adanipower_digest_labeled_and_sentiment_honest(rst_stack):
    # Empty-news provider: NewsAPI yields nothing, digest must fill the gap.
    from app.services.news_service import NewsService

    class _EmptyNews:
        name = "empty_news"
        is_configured = True

        def fetch_articles(self, *a, **k):
            return []

    s = rst_stack
    s["prep"].news_service = NewsService(
        _EmptyNews(), s["news_repo"], s["provenance_repo"],
    )
    prep = s["prep"].prepare_company("ADANIPOWER")
    research = prep["areas"]["news"].get("research")
    assert research is not None
    assert len(research["items"]) == 1
    assert "not" in research["label"] and "FinBERT" in research["label"]
    # Digest items are research evidence: nothing stored as articles, so the
    # Sentiment Analyst honestly reports UNAVAILABLE (nothing scored).
    assert s["news_repo"].count("ADANIPOWER") == 0
    out = s["agents"].run_agent("sentiment_analyst", "ADANIPOWER")
    assert out.score is None
    assert out.status == "UNAVAILABLE"


# 25-26. BBL: news works, industry gets peers ----------------------------------------------


def test_bbl_news_and_industry(rst_stack):
    prep = rst_stack["prep"].prepare_company("BBL")
    assert prep["areas"]["company_metadata"]["sector"] == "Industrials"
    peers = prep["areas"]["peers"]
    assert "TATAPOWER" in peers["usable_peers"]
    # FAKECO suggested by research but not a real listing: skipped, never used.
    assert "FAKECO" not in peers["usable_peers"]
    out = rst_stack["agents"].run_agent("industry_analyst", "BBL")
    assert out.score is not None
    assert "TATAPOWER" in (out.provenance.get("peers_with_prices") or [])


# 27. Research reports are deduplicated -------------------------------------------------------


def test_research_reports_no_duplicates(rst_stack):
    rst_stack["prep"].prepare_company("ADANIPOWER")
    first = rst_stack["research_repo"].count("ADANIPOWER")
    assert first >= 2  # company_profile + peer_discovery (+ digest)
    rst_stack["prep"].prepare_company("ADANIPOWER")
    assert rst_stack["research_repo"].count("ADANIPOWER") == first


# 28. Low-confidence research is not applied ------------------------------------------------------


def test_low_confidence_research_not_applied(tmp_path):
    from app.services.research_service import ResearchService

    s = _make_prep_stack(tmp_path, "prep_lowconf.duckdb")
    try:
        provider = FakeResearchProvider(
            enrich={"ADANIPOWER": ("Utilities", "Power Generation", 0.1)}
        )
        service = ResearchService(provider, s["research_repo"], s["provenance_repo"])
        out = service.enrich_company("ADANIPOWER", "ADANI POWER LTD")
        assert out["usable"] is False
        assert out["status"] == "UNAVAILABLE"
        from app.data.universe.universe_config import get_universe_entry

        # Register via market resolution, then confirm preparation applies
        # nothing: sector stays unknown.
        s["market_service"].resolve_symbol("ADANIPOWER")
        assert get_universe_entry("ADANIPOWER").sector == "Unknown"
    finally:
        s["storage"].close()


# 29. Unconfigured research degrades honestly -------------------------------------------------------


def test_unconfigured_research_degrades(stack):
    from app.data.universe.industry_classifier import IndustryClassifier
    from app.services.research_service import ResearchService

    # Hermetic classifier whose structured sources know nothing: forces the
    # honest Unknown path without touching the network.
    def _no_yfinance(symbol):
        raise RuntimeError("network disabled in tests")

    stack["prep"].industry_classifier = IndustryClassifier(
        csv_path="/nonexistent.csv", yfinance_fetcher=_no_yfinance
    )

    class _Unconfigured:
        name = "unconfigured"
        is_configured = False
        model_name = "none"

    # ResearchService requires repos; build directly against stack storage.
    from app.repositories.provenance_repository import ProvenanceRepository
    from app.repositories.research_repository import ResearchRepository

    service = ResearchService(
        _Unconfigured(),
        ResearchRepository(stack["storage"]),
        ProvenanceRepository(stack["storage"]),
    )
    out = service.enrich_company("ADANIPOWER", "ADANI POWER LTD")
    assert out["status"] == "UNAVAILABLE"
    assert out["usable"] is False
    # Preparation without research keeps Unknown sector honestly.
    prep = stack["prep"].prepare_company("ADANIPOWER")
    assert prep["areas"]["company_metadata"]["status"] == "UNAVAILABLE"
    assert prep["areas"]["peers"]["status"] == "UNAVAILABLE"
    assert prep["components"]["company_metadata"] == "UNAVAILABLE"


# 26. End-to-end outside the original 10: NSE-CSV classification + RSS-style
# news -> industry + sentiment score (no Gemini, no curated aliases) ---------


class _NhpcNewsProvider(FakeNewsProvider):
    """NHPC-titled articles for any query (RSS-shaped retrieval)."""

    def fetch_articles(self, query, from_date=None, to_date=None, page_size=50):
        self.queries.append(query)
        base = datetime(2026, 9, 27, tzinfo=timezone.utc)
        titles = [
            ("https://n.test/nhpc1", "NHPC shares jump on strong quarterly results"),
            ("https://n.test/nhpc2", "NHPC commissions solar unit, outlook raised"),
            ("https://n.test/nhpc3", "NHPC declares dividend, shares gain"),
        ]
        return [
            NewsArticle(
                article_id=hashlib.sha256(url.encode()).hexdigest(),
                title=title,
                description="NHPC reports power generation growth",
                content=None,
                source="Fake Wire",
                source_url=url,
                published_at=base - timedelta(days=i),
                language="en",
                content_hash=hashlib.sha256(title.encode()).hexdigest(),
            )
            for i, (url, title) in enumerate(titles)
        ]


def test_e2e_non_universe_symbol_csv_classified_scores(tmp_path, monkeypatch):
    """NHPC is outside the static 10 and the curated Energy map: the NSE CSV
    classifies it (Power), CSV peers validate live, news scores."""
    from app.data.universe.industry_classifier import IndustryClassifier

    monkeypatch.setitem(
        _SEARCH, "NHPC", [("NHPC", "NHPC LTD", "INE031A01036", "6480")]
    )
    monkeypatch.setitem(_QUOTE_PRICE, "NHPC", (95.0, 92.0))
    # Make the first two committed-CSV Power peers resolvable so the CSV
    # peer path (not Gemini) is what the end-to-end flow exercises.
    csv_peers = IndustryClassifier().peers_for_industry("Power", exclude={"NHPC"}, limit=2)
    assert len(csv_peers) == 2
    for i, (sym, _name) in enumerate(csv_peers):
        monkeypatch.setitem(
            _SEARCH, sym, [(sym, f"{sym} LTD", f"INE000A0102{i}", f"900{i}")]
        )
        monkeypatch.setitem(_QUOTE_PRICE, sym, (100.0 + i, 99.0 + i))
    s = _make_prep_stack(tmp_path, "prep_e2e.duckdb", news_provider=_NhpcNewsProvider())
    try:
        # Research service with an UNCONFIGURED provider: classification must
        # still apply from structured sources, with evidence persisted.
        from app.services.research_service import ResearchService
        from types import SimpleNamespace

        s["prep"].research_service = ResearchService(
            SimpleNamespace(name="unconfigured_research", is_configured=False),
            s["research_repo"],
            s["provenance_repo"],
        )
        prep = s["prep"].prepare_company("NHPC")
        assert prep["readiness"] in ("ready", "partial")
        meta = prep["areas"]["company_metadata"]
        assert meta["status"] == "LIVE"
        assert meta["source"] == "nse_nifty500_csv"
        assert meta["industry"] == "Power"
        assert prep["components"]["company_metadata"] == "READY"

        peers = prep["areas"]["peers"]
        assert peers["status"] in ("LIVE", "CACHED")
        assert "nifty500_csv" in peers["discovered_sources"]
        assert prep["components"]["peers"] in ("READY", "PARTIAL")

        industry = s["agents"].run_agent("industry_analyst", "NHPC")
        assert industry.score is not None
        assert industry.status in ("OK", "DEGRADED")

        sentiment = s["agents"].run_agent("sentiment_analyst", "NHPC")
        assert sentiment.score is not None
        assert sentiment.status in ("OK", "DEGRADED")

        # Classification evidence persisted with source + confidence.
        reports = s["research_repo"].list_reports("NHPC")
        assert any(
            r["report_type"] == "industry_classification"
            and (r.get("source_name") or "") == "nse_nifty500_csv"
            for r in reports
        )
    finally:
        s["storage"].close()


# 27. Agent runs resolve renamed symbols canonically ---------------------------


def test_agent_run_resolves_renamed_symbol(tmp_path):
    """ZOMATO-style renames: the agent runs under the canonical symbol
    (ETERNAL) that preparation registered, instead of 404ing."""
    from datetime import timedelta

    from app.core.exceptions import NotFoundError
    from app.domain.models.market import MarketPrice

    s = _make_prep_stack(tmp_path, "prep_rename.duckdb")
    try:
        class _RenamingMarketService:
            def resolve_symbol(self, symbol, instrument_key=None):
                if symbol.upper() == "ZOMATO":
                    return {"symbol": "ETERNAL"}
                raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe")

            def ensure_history(self, symbols, **kwargs):
                return [
                    {"symbol": sym, "action": "cached", "status": "CACHED"}
                    for sym in symbols
                ]

        agents = AgentService(
            s["financial_repo"],
            s["market_repo"],
            AgentOutputRepository(s["storage"]),
            market_service=_RenamingMarketService(),
        )
        base = date.today() - timedelta(days=60)
        bars = []
        d = base
        while d <= date.today():
            if d.weekday() < 5:
                bars.append(
                    MarketPrice(
                        symbol="ETERNAL",
                        provider_ticker="ETERNAL.NS",
                        trade_date=d,
                        open=100.0, high=101.0, low=99.0, close=100.0, volume=1000,
                    )
                )
            d += timedelta(days=1)
        s["market_repo"].upsert_bars(bars)
        out = agents.run_agent("industry_analyst", "ZOMATO")
        assert out.entity_id == "ETERNAL"
        # Unknown symbols still 404 honestly.
        with pytest.raises(NotFoundError):
            agents.run_agent("industry_analyst", "NOPEXYZ")
    finally:
        s["storage"].close()
