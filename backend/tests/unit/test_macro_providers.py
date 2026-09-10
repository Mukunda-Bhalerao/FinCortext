"""Unit tests: macro providers (curated CSVs + yfinance normalization, no network)."""

import pandas as pd
import pytest

from app.core.exceptions import NotFoundError, ProviderError
from app.data.macro.indicators import get_indicator, indicator_ids
from app.data.providers.macro.curated_provider import CuratedMacroProvider
from app.data.providers.macro.yfinance_macro_provider import YFinanceMacroProvider


def test_indicator_catalog_covers_all_seven_areas():
    ids = set(indicator_ids())
    assert {"gdp_real_yoy", "cpi_yoy", "repo_rate", "usd_inr", "brent_crude", "us10y", "india_vix"} <= ids
    for indicator_id in ids:
        meta = get_indicator(indicator_id)
        assert meta["label"] and meta["unit"] and meta["freshness_days"] > 0
        assert meta["source"] in {"curated", "yfinance"}
    with pytest.raises(NotFoundError):
        get_indicator("nope_not_real")


def test_curated_csvs_parse_with_sane_bounds():
    """The committed official datasets load with plausible, sourced rows."""
    provider = CuratedMacroProvider()
    repo = provider.fetch_indicator("repo_rate")
    assert len(repo["points"]) >= 8
    for p in repo["points"]:
        assert 0.0 <= p["value"] <= 20.0, p
        assert p["source_url"], "every curated row carries its source"
    # Known anchors from RBI MPC statements.
    by_date = {p["period_end"]: p["value"] for p in repo["points"]}
    assert by_date["2025-02-07"] == 6.25
    assert by_date["2025-06-06"] == 5.50
    assert by_date["2025-12-05"] == 5.25
    assert by_date["2026-06-05"] == 5.25

    cpi = provider.fetch_indicator("cpi_yoy")
    assert len(cpi["points"]) >= 10
    for p in cpi["points"]:
        assert -5.0 <= p["value"] <= 15.0, p
    cpi_by_date = {p["period_end"]: p["value"] for p in cpi["points"]}
    assert cpi_by_date["2026-07-31"] == 4.45
    assert cpi_by_date["2025-10-31"] == 0.25

    gdp = provider.fetch_indicator("gdp_real_yoy")
    assert len(gdp["points"]) >= 5
    for p in gdp["points"]:
        assert -10.0 <= p["value"] <= 15.0, p
    gdp_by_date = {p["period_end"]: p["value"] for p in gdp["points"]}
    assert gdp_by_date["2026-06-30"] == 7.8
    assert gdp_by_date["2025-09-30"] == 8.4


def test_curated_unknown_indicator_rejected():
    with pytest.raises(NotFoundError):
        CuratedMacroProvider().fetch_indicator("nifty_fairy_dust")


def _fake_yfinance_frame(dates, closes):
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": [1000] * len(closes),
        },
        index=pd.DatetimeIndex(dates),
    )
    return frame


def test_yfinance_macro_normalizes_closes(monkeypatch):
    import sys
    import types

    closes = [90.0 + i * 0.1 for i in range(10)]
    dates = pd.date_range("2026-08-01", periods=10, freq="D")
    fake = types.ModuleType("yfinance")
    fake.download = lambda *a, **k: _fake_yfinance_frame(dates, closes)
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    bundle = YFinanceMacroProvider().fetch_indicator("usd_inr")
    assert bundle["unit"] == "INR per USD"
    assert len(bundle["points"]) == 10
    assert bundle["points"][-1]["value"] == closes[-1]
    assert bundle["points"][-1]["period_end"] == "2026-08-10"


def test_yfinance_macro_empty_frame_reports_no_points(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("yfinance")
    fake.download = lambda *a, **k: pd.DataFrame()
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    bundle = YFinanceMacroProvider().fetch_indicator("brent_crude")
    assert bundle["points"] == []
    assert bundle["warnings"]


def test_yfinance_macro_wrong_kind_rejected():
    with pytest.raises(ProviderError):
        YFinanceMacroProvider().fetch_indicator("repo_rate")
