"""Unit tests: macro providers (curated CSVs + Upstox gauges, no network)."""

import pytest

from app.core.exceptions import NotFoundError, ProviderError
from app.data.macro.indicators import get_indicator, indicator_ids
from app.data.providers.macro.curated_provider import CuratedMacroProvider
from app.data.providers.macro.upstox_gauges import UpstoxGaugeProvider


class FakeGaugeClient:
    """Stubbed Upstox HTTP client returning canned daily candles."""

    def __init__(self, candles=(), empty=False):
        self.candles = list(candles)
        self.empty = empty

    @property
    def is_configured(self) -> bool:
        return True

    def fetch_daily_candles(self, instrument_key, start, end):
        if self.empty:
            return []
        return self.candles


def test_indicator_catalog_covers_all_seven_areas():
    ids = set(indicator_ids())
    assert {"gdp_real_yoy", "cpi_yoy", "repo_rate", "usd_inr", "brent_crude", "us10y", "india_vix"} <= ids
    for indicator_id in ids:
        meta = get_indicator(indicator_id)
        assert meta["label"] and meta["unit"] and meta["freshness_days"] > 0
        assert meta["source"] in {"curated", "upstox", "unavailable"}
    with pytest.raises(NotFoundError):
        get_indicator("nope_not_real")


def test_unavailable_gauges_declare_no_reachable_provider():
    """USD/INR, Brent and US 10Y have no NSE listing on Upstox: they stay in
    the catalog with an explicit unavailable source and a stated reason."""
    for indicator_id in ("usd_inr", "brent_crude", "us10y"):
        meta = get_indicator(indicator_id)
        assert meta["source"] == "unavailable"
        assert meta.get("note"), f"{indicator_id} must state why it is unavailable"
        assert not meta.get("instrument_key")
        # No provider serves them — refresh is isolated, never fabricated.
        with pytest.raises(ProviderError):
            UpstoxGaugeProvider("fake-token", client=FakeGaugeClient()).fetch_indicator(indicator_id)


def test_india_vix_served_from_upstox_candles():
    candles = [
        ["2026-08-%02dT00:00:00+05:30" % (i + 1), 12.0, 12.5, 11.5, 12.0 + i * 0.1, 0]
        for i in range(10)
    ]
    provider = UpstoxGaugeProvider("fake-token", client=FakeGaugeClient(candles))
    bundle = provider.fetch_indicator("india_vix")
    assert bundle["unit"] == "index points"
    assert "upstox" in bundle["source_name"].lower()
    assert len(bundle["points"]) == 10
    assert bundle["points"][-1]["value"] == pytest.approx(12.9)
    assert bundle["points"][-1]["period_end"] == "2026-08-10"
    assert bundle["warnings"] == []


def test_india_vix_empty_candles_report_no_points():
    provider = UpstoxGaugeProvider("fake-token", client=FakeGaugeClient(empty=True))
    bundle = provider.fetch_indicator("india_vix")
    assert bundle["points"] == []
    assert bundle["warnings"]


def test_gauge_provider_wrong_kind_rejected():
    with pytest.raises(ProviderError):
        UpstoxGaugeProvider("fake-token", client=FakeGaugeClient()).fetch_indicator("repo_rate")


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
