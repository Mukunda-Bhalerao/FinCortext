"""Unit tests for the Upstox Analytics integration (mocked, no network/token).

Covers: search TCS / RELIANCE, instrument resolution, quote fetch,
historical candles, normalization, dynamic stocks outside the static
universe, null-preservation into API responses, auth failure, unknown
symbols, and yfinance independence.
"""

from datetime import date

import pytest

from app.core.exceptions import NotFoundError, ProviderUnavailableError
from app.data.providers.market.upstox_client import UpstoxHttpClient
from app.data.providers.market.upstox_provider import (
    normalize_quote,
    normalize_search_item,
    UpstoxMarketProvider,
)
from app.data.providers.market.yfinance_provider import YFinanceMarketProvider
from app.data.storage.duckdb_storage import DuckDBStorage
from app.data.universe.universe_config import clear_dynamic_registry, get_universe_entry
from app.repositories.instrument_repository import InstrumentRepository
from app.repositories.market_repository import MarketRepository
from app.repositories.provenance_repository import ProvenanceRepository
from app.repositories.universe_repository import UniverseRepository
from app.services.market_service import MarketService


FAKE_TOKEN = "fake-token-for-tests-only"


def _tcs_search_payload():
    return {
        "status": "success",
        "data": [
            {
                "name": "TATA CONSULTANCY SERVICES LTD",
                "segment": "NSE_EQ",
                "exchange": "NSE",
                "isin": "INE467B01029",
                "instrument_key": "NSE_EQ|INE467B01029",
                "exchange_token": "2955",
                "trading_symbol": "TCS",
                "short_name": "TCS",
                "tick_size": 5.0,
                "lot_size": 1,
                "instrument_type": "EQ",
                "freeze_quantity": 100000.0,
                "qty_multiplier": 1,
            },
            # BSE row must be filtered out (NSE equity only).
            {
                "name": "TATA CONSULTANCY SERVICES LTD.",
                "segment": "BSE_EQ",
                "exchange": "BSE",
                "isin": "INE467B01029",
                "instrument_key": "BSE_EQ|532540",
                "exchange_token": "532540",
                "trading_symbol": "TCS",
                "instrument_type": "A",
            },
        ],
        "meta_data": {"page": {"page_number": 1, "total_pages": 1, "records": 20, "total_records": 2}},
    }


def _reliance_search_payload():
    return {
        "status": "success",
        "data": [
            {
                "name": "RELIANCE INDUSTRIES LTD",
                "segment": "NSE_EQ",
                "exchange": "NSE",
                "isin": "INE002A01018",
                "instrument_key": "NSE_EQ|INE002A01018",
                "exchange_token": "2885",
                "trading_symbol": "RELIANCE",
                "short_name": "Reliance",
                "tick_size": 10.0,
                "lot_size": 1,
                "instrument_type": "EQ",
                "freeze_quantity": 100000.0,
                "qty_multiplier": 1,
            }
        ],
        "meta_data": {"page": {"page_number": 1, "total_pages": 1, "records": 20, "total_records": 1}},
    }


def _adani_search_payload():
    return {
        "status": "success",
        "data": [
            {
                "name": "ADANI ENTERPRISES LTD",
                "segment": "NSE_EQ",
                "exchange": "NSE",
                "isin": "INE423A01024",
                "instrument_key": "NSE_EQ|INE423A01024",
                "exchange_token": "25",
                "trading_symbol": "ADANIENT",
                "short_name": "Adani Ent",
                "tick_size": 5.0,
                "lot_size": 1,
                "instrument_type": "EQ",
                "freeze_quantity": 100000.0,
                "qty_multiplier": 1,
            }
        ],
        "meta_data": {"page": {"page_number": 1, "total_pages": 1, "records": 20, "total_records": 1}},
    }


def _quote_data(symbol="TCS", key="NSE_EQ|INE467B01029"):
    return {
        f"NSE_EQ:{symbol}": {
            "ohlc": {
                "open": 3100.0,
                "high": 3150.5,
                "low": 3090.25,
                "close": 3140.0,
                "volume": 1234567,
                "ts": 1757000100000,
            },
            "timestamp": "2026-09-04T15:22:31.099+05:30",
            "instrument_token": key,
            "symbol": symbol,
            "last_price": 3142.75,
            "volume": 1234567,
            "average_price": 3120.10,
            "prev_close_price": 3105.50,
            "year_high": 3500.0,
            "year_low": 2800.0,
        }
    }


def _candles():
    return [
        ["2024-01-02T00:00:00+05:30", 100.0, 110.0, 95.0, 105.0, 1000, 0],
        ["2024-01-03T00:00:00+05:30", 105.0, 112.0, 100.0, 108.0, 1200, 0],
        ["2024-01-04T00:00:00+05:30", 108.0, 115.0, 107.0, 112.0, 1300, 0],
    ]


class FakeUpstoxClient(UpstoxHttpClient):
    """Canned Upstox responses keyed by query; no network, no real token."""

    def __init__(self, *, auth_fail=False, empty_search=False):
        super().__init__(FAKE_TOKEN)
        self.auth_fail = auth_fail
        self.empty_search = empty_search
        self.calls: list = []

    def search_instruments(self, query, **kwargs):
        self.calls.append(("search", query))
        if self.auth_fail:
            raise ProviderUnavailableError(
                "Upstox authentication failed — check UPSTOX_ACCESS_TOKEN.",
                details={"provider": "upstox"},
            )
        if self.empty_search or (query or "").strip().upper() in {"NOPEXYZ", "UNKNOWN123"}:
            return {"status": "success", "data": [], "meta_data": {}}
        q = (query or "").strip().upper().replace(".NS", "")
        if q in {"TCS", "TATA"}:
            return _tcs_search_payload()
        if "RELIANCE" in q or q == "RIL":
            return _reliance_search_payload()
        if "ADANI" in q or q == "ADANIENT":
            return _adani_search_payload()
        if q == "INFY":
            return {
                "status": "success",
                "data": [
                    {
                        "name": "INFOSYS LTD",
                        "segment": "NSE_EQ",
                        "exchange": "NSE",
                        "isin": "INE009A01021",
                        "instrument_key": "NSE_EQ|INE009A01021",
                        "exchange_token": "1594",
                        "trading_symbol": "INFY",
                        "instrument_type": "EQ",
                    }
                ],
                "meta_data": {},
            }
        return {"status": "success", "data": [], "meta_data": {}}

    def fetch_full_quotes(self, instrument_keys):
        self.calls.append(("quotes", tuple(instrument_keys)))
        if self.auth_fail:
            raise ProviderUnavailableError(
                "Upstox authentication failed — check UPSTOX_ACCESS_TOKEN.",
                details={"provider": "upstox"},
            )
        key = instrument_keys[0]
        if "INE467B01029" in key:
            return _quote_data("TCS", key)
        if "INE002A01018" in key:
            d = _quote_data("RELIANCE", key)
            # Vary numbers so RELIANCE assertions can't pass on TCS fixtures.
            inner = d["NSE_EQ:RELIANCE"]
            inner["last_price"] = 1420.5
            inner["prev_close_price"] = 1400.0
            return d
        if "INE423A01024" in key:
            d = _quote_data("ADANIENT", key)
            inner = d["NSE_EQ:ADANIENT"]
            inner["last_price"] = 2500.0
            inner["prev_close_price"] = 2480.0
            return d
        if "INE009A01021" in key:
            d = _quote_data("INFY", key)
            inner = d["NSE_EQ:INFY"]
            inner["last_price"] = 1750.0
            inner["prev_close_price"] = 1740.0
            return d
        return _quote_data("X", key)

    def fetch_daily_candles(self, instrument_key, start, end):
        self.calls.append(("candles", instrument_key))
        if self.auth_fail:
            raise ProviderUnavailableError(
                "Upstox authentication failed — check UPSTOX_ACCESS_TOKEN.",
                details={"provider": "upstox"},
            )
        return _candles()


@pytest.fixture(autouse=True)
def _clean_dynamic():
    clear_dynamic_registry()
    yield
    clear_dynamic_registry()


def _service(tmp_path, client: FakeUpstoxClient):
    storage = DuckDBStorage(tmp_path / "upstox.duckdb")
    storage.connect()
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=client)
    svc = MarketService(
        provider,
        MarketRepository(storage),
        ProvenanceRepository(storage),
        instrument_repo=InstrumentRepository(storage),
        universe_repo=UniverseRepository(storage),
    )
    return storage, provider, svc


# 1. Search TCS ----------------------------------------------------------------


def test_search_tcs_returns_nse_equity():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient())
    results = provider.search_equity("TCS")
    assert len(results) == 1  # BSE row filtered
    row = results[0]
    assert row["symbol"] == "TCS"
    assert row["trading_symbol"] == "TCS"
    assert row["instrument_key"] == "NSE_EQ|INE467B01029"
    assert row["exchange"] == "NSE"
    assert row["segment"] == "EQ"
    assert row["isin"] == "INE467B01029"
    assert "TATA" in row["name"]


# 2. Search RELIANCE -------------------------------------------------------------


def test_search_reliance_returns_nse_equity():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient())
    results = provider.search_equity("RELIANCE")
    assert len(results) == 1
    assert results[0]["symbol"] == "RELIANCE"
    assert results[0]["instrument_key"] == "NSE_EQ|INE002A01018"


# 3. Resolve instrument -----------------------------------------------------------


def test_resolve_instrument_prefers_exact_symbol():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient())
    resolved = provider.resolve_equity("RELIANCE")
    assert resolved["instrument_key"] == "NSE_EQ|INE002A01018"
    assert resolved["exchange"] == "NSE"
    assert resolved["segment"] == "EQ"


# 4. Fetch quote -------------------------------------------------------------------


def test_fetch_quote_returns_all_fields():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient())
    quote = provider.fetch_quote_for_symbol("TCS")
    assert quote["symbol"] == "TCS"
    assert quote["instrument_key"] == "NSE_EQ|INE467B01029"
    assert quote["last_price"] == pytest.approx(3142.75)
    assert quote["prev_close"] == pytest.approx(3105.50)
    assert quote["open"] == pytest.approx(3100.0)
    assert quote["high"] == pytest.approx(3150.5)
    assert quote["low"] == pytest.approx(3090.25)
    assert quote["volume"] == pytest.approx(1234567)
    assert quote["year_high"] == pytest.approx(3500.0)
    assert quote["year_low"] == pytest.approx(2800.0)
    assert quote["timestamp"] is not None
    assert quote["day_change"] == pytest.approx(3142.75 - 3105.50)
    assert quote["source"] == "upstox"


# 5. Historical candles --------------------------------------------------------------


def test_fetch_historical_candles_normalize_to_market_price(tmp_path):
    storage, provider, _ = _service(tmp_path, FakeUpstoxClient())
    try:
        bars = provider.fetch_ohlcv("TCS", date(2024, 1, 2), date(2024, 1, 4))
        assert len(bars) == 3
        assert [b.trade_date.isoformat() for b in bars] == ["2024-01-02", "2024-01-03", "2024-01-04"]
        first = bars[0]
        assert first.symbol == "TCS"
        assert first.provider_ticker == "NSE_EQ|INE467B01029"
        assert first.open == pytest.approx(100.0)
        assert first.close == pytest.approx(105.0)
        assert first.source_name == "upstox"
    finally:
        storage.close()


# 6. Normalization ---------------------------------------------------------------------


def test_normalize_preserves_values_and_none_for_missing():
    raw_item = _tcs_search_payload()["data"][0]
    norm = normalize_search_item(raw_item)
    assert norm["symbol"] == "TCS"
    assert norm["instrument_key"] == "NSE_EQ|INE467B01029"

    full = _quote_data()["NSE_EQ:TCS"]
    q = normalize_quote(full, instrument_key="NSE_EQ|INE467B01029", fallback_symbol="TCS")
    assert q["last_price"] == pytest.approx(3142.75)

    partial = dict(full)
    partial.pop("year_high", None)
    partial.pop("prev_close_price", None)
    q2 = normalize_quote(partial, instrument_key="NSE_EQ|INE467B01029", fallback_symbol="TCS")
    # Genuinely missing stays None — never coerced to 0.
    assert q2["year_high"] is None
    assert q2["prev_close"] is None
    assert q2["day_change"] is None
    assert q2["last_price"] == pytest.approx(3142.75)


# 7. Dynamic stock outside the static universe ----------------------------------------------


def test_dynamic_stock_not_in_static_universe(tmp_path):
    with pytest.raises(NotFoundError):
        get_universe_entry("ADANIENT")
    storage, _, svc = _service(tmp_path, FakeUpstoxClient())
    try:
        resolved = svc.resolve_symbol("ADANIENT")
        assert resolved["symbol"] == "ADANIENT"
        assert resolved["instrument_key"] == "NSE_EQ|INE423A01024"
        assert resolved["dynamic"] is True
        # Company context now exists dynamically.
        assert get_universe_entry("ADANIENT").symbol == "ADANIENT"

        refreshed = svc.refresh_symbol("ADANIENT", start=date(2024, 1, 2), end=date(2024, 1, 4))
        assert refreshed["status"] == "LIVE"
        assert refreshed["rows_stored"] == 3

        series = svc.get_price_series("ADANIENT")
        assert series["count"] == 3
        assert series["prices"][0]["close"] == pytest.approx(105.0)
    finally:
        storage.close()


# 8. Valid values survive to the API response -------------------------------------------------


def test_api_responses_preserve_valid_upstox_values(tmp_path, monkeypatch):
    import app.api.routes.market as market_routes

    storage = DuckDBStorage(tmp_path / "api_upstox.duckdb")
    storage.connect()
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient())
    svc = MarketService(
        provider,
        MarketRepository(storage),
        ProvenanceRepository(storage),
        instrument_repo=InstrumentRepository(storage),
        universe_repo=UniverseRepository(storage),
    )
    svc.refresh_symbol("TCS", start=date(2024, 1, 2), end=date(2024, 1, 4))

    class TestContainer:
        def __init__(self):
            self.market_service = svc
            self.market_repo = svc.market_repo

    # Build the app directly to avoid touching the global container.
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    # Re-patch on the already-imported route module used by this app instance.
    monkeypatch.setattr(market_routes, "get_container", lambda: TestContainer())
    client = TestClient(app)

    r = client.get("/api/market/prices/TCS")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["prices"][0]["close"] is not None
    assert body["prices"][0]["close"] == pytest.approx(105.0)
    assert body["prices"][0]["open"] == pytest.approx(100.0)

    r = client.get("/api/market/quote/TCS")
    assert r.status_code == 200
    quote = r.json()
    # Exact snake_case field names — the null-bug contract.
    for field in ("last_price", "prev_close", "open", "high", "low", "volume", "year_high", "year_low", "timestamp"):
        assert field in quote, f"missing field {field}"
    assert quote["last_price"] == pytest.approx(3142.75)
    assert quote["prev_close"] == pytest.approx(3105.50)
    assert quote["volume"] == pytest.approx(1234567)
    storage.close()


# 9. Authentication failure ----------------------------------------------------------------------


def test_upstox_auth_failure_surfaces_without_token_leak():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient(auth_fail=True))
    with pytest.raises(ProviderUnavailableError) as excinfo:
        provider.search_equity("TCS")
    assert FAKE_TOKEN not in str(excinfo.value.message)
    assert FAKE_TOKEN not in repr(getattr(excinfo.value, "details", {}))
    with pytest.raises(ProviderUnavailableError):
        provider.fetch_quote_for_symbol("TCS")


def test_market_service_search_auth_failure(tmp_path):
    storage, _, svc = _service(tmp_path, FakeUpstoxClient(auth_fail=True))
    try:
        with pytest.raises(ProviderUnavailableError):
            svc.search_symbols("TCS")
    finally:
        storage.close()


# 10. Unknown stock / no results ---------------------------------------------------------------------


def test_unknown_stock_search_has_no_results():
    provider = UpstoxMarketProvider(FAKE_TOKEN, client=FakeUpstoxClient(empty_search=True))
    assert provider.search_equity("NOPEXYZ") == []


def test_unknown_symbol_resolve_is_not_found(tmp_path):
    storage, _, svc = _service(tmp_path, FakeUpstoxClient(empty_search=True))
    try:
        with pytest.raises(NotFoundError):
            svc.resolve_symbol("NOPEXYZ")
    finally:
        storage.close()


# 11. yfinance still works -------------------------------------------------------------------------------


def test_yfinance_provider_still_works_independently():
    import pandas as pd

    provider = YFinanceMarketProvider({"TCS": "TCS.NS"})
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    df = pd.DataFrame(
        {"Open": [100.0, 101.0], "High": [110.0, 111.0], "Low": [95.0, 96.0], "Close": [105.0, 106.0], "Volume": [1000, 1100]},
        index=idx,
    )
    bars = provider.normalize_frame(df, symbol="TCS", provider_ticker="TCS.NS")
    assert len(bars) == 2
    assert bars[0].symbol == "TCS"
    assert bars[0].close == pytest.approx(105.0)
