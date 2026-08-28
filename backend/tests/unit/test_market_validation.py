"""Unit tests for market data validation and yfinance normalization."""

from datetime import date

import pandas as pd
import pytest

from app.core.exceptions import ProviderError
from app.data.providers.market.yfinance_provider import YFinanceMarketProvider
from app.data.validation.market_validation import validate_market_bars
from app.domain.models.market import MarketPrice


def _bar(symbol="RELIANCE", d=date(2024, 1, 2), close=105.0, **overrides):
    data = dict(
        symbol=symbol,
        provider_ticker=f"{symbol}.NS",
        trade_date=d,
        open=100.0,
        high=110.0,
        low=95.0,
        close=close,
        volume=1000.0,
    )
    data.update(overrides)
    return MarketPrice(**data)


# --- Validation -----------------------------------------------------------


def test_validation_accepts_clean_bars():
    result = validate_market_bars([_bar(), _bar(d=date(2024, 1, 3))])
    assert len(result.valid) == 2
    assert result.rejected == []


def test_validation_rejects_inverted_high_low():
    bad = _bar(high=90.0)  # high < low → close also outside range
    result = validate_market_bars([bad])
    assert result.valid == []
    assert "high < low" in result.rejected[0]["reasons"]
    assert "close outside high/low range" in result.rejected[0]["reasons"]


def test_validation_rejects_duplicates():
    result = validate_market_bars([_bar(), _bar()])
    assert len(result.valid) == 1
    assert "duplicate trade_date for symbol" in result.rejected[0]["reasons"]


def test_validation_rejects_negative_price_via_model():
    with pytest.raises(Exception):
        _bar(open=-5)


# --- yfinance adapter normalization ------------------------------------------


def _fake_yf_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            ("Open", "RELIANCE.NS"): [100.0, 101.0],
            ("High", "RELIANCE.NS"): [110.0, 111.0],
            ("Low", "RELIANCE.NS"): [95.0, 96.0],
            ("Close", "RELIANCE.NS"): [105.0, 106.0],
            ("Volume", "RELIANCE.NS"): [1000, 1100],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )


def test_yfinance_normalizes_multiindex_frame():
    provider = YFinanceMarketProvider({"RELIANCE": "RELIANCE.NS"})
    bars = provider.normalize_frame(
        _fake_yf_frame(), symbol="RELIANCE", provider_ticker="RELIANCE.NS"
    )
    assert len(bars) == 2
    assert bars[0].symbol == "RELIANCE"
    assert bars[0].trade_date == date(2024, 1, 2)
    assert bars[1].close == 106.0


def test_yfinance_normalization_rejects_missing_columns():
    provider = YFinanceMarketProvider()
    df = pd.DataFrame({"Open": [1.0], "Close": [1.0]})
    with pytest.raises(ProviderError):
        provider.normalize_frame(df, symbol="X", provider_ticker="X.NS")


def test_yfinance_fetch_wraps_errors(monkeypatch):
    provider = YFinanceMarketProvider()

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    import yfinance as yf

    monkeypatch.setattr(yf, "download", boom)
    with pytest.raises(ProviderError) as exc_info:
        provider.fetch_ohlcv("RELIANCE.NS", date(2024, 1, 1), date(2024, 1, 31))
    assert "network down" in str(exc_info.value)


def test_yfinance_fetch_empty_returns_no_bars(monkeypatch):
    provider = YFinanceMarketProvider()
    import pandas as pd
    import yfinance as yf

    monkeypatch.setattr(yf, "download", lambda *a, **k: pd.DataFrame())
    bars = provider.fetch_ohlcv("RELIANCE.NS", date(2024, 1, 1), date(2024, 1, 31))
    assert bars == []