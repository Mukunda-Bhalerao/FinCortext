"""Unit tests for market data validation."""

from datetime import date

import pytest

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


# --- Canonical defaults (Upstox is the only market provider) ----------------


def test_market_price_defaults_to_upstox_provenance():
    bar = _bar()
    assert bar.source_type.value == "upstox"
    assert bar.source_name == "upstox"
