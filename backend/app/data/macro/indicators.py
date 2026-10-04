"""Macro indicator catalog — the fixed vocabulary of the Macro Analyst.

Each indicator declares where its observations come from and how stale they
may be before the factor engine treats them as outdated (FRESHNESS_DAYS).
Market-derived series refresh continuously; official curated series move on
release calendars (CPI ~monthly, GDP quarterly, MPC bimonthly).
"""

from __future__ import annotations

# indicator_id → metadata. `source` is "curated" (versioned CSV under
# data/macro/, transcribed from official releases with per-row provenance),
# "upstox" (market-derived daily index candles via Upstox Historical Candle V3),
# or "unavailable" (no reachable provider serves the series; reported honestly,
# never proxied or fabricated).
MACRO_INDICATORS: dict[str, dict] = {
    "gdp_real_yoy": {
        "label": "Real GDP growth (YoY)",
        "unit": "%",
        "source": "curated",
        "source_name": "MoSPI national accounts releases (curated)",
        "csv": "gdp_real_yoy.csv",
        "freshness_days": 120,
    },
    "cpi_yoy": {
        "label": "CPI inflation (YoY, combined)",
        "unit": "%",
        "source": "curated",
        "source_name": "MoSPI CPI releases (curated)",
        "csv": "cpi_yoy.csv",
        "freshness_days": 45,
    },
    "repo_rate": {
        "label": "RBI policy repo rate",
        "unit": "%",
        "source": "curated",
        "source_name": "RBI MPC statements (curated)",
        "csv": "rbi_repo_rate.csv",
        "freshness_days": 120,
    },
    "usd_inr": {
        "label": "USD/INR exchange rate",
        "unit": "INR per USD",
        "source": "unavailable",
        "note": (
            "No reachable provider serves this series (Upstox instruments are "
            "NSE-listed; the USD/INR spot rate is not among them). Stored "
            "pre-consolidation history remains usable; no new data is fetched."
        ),
        "freshness_days": 14,
    },
    "brent_crude": {
        "label": "Brent crude oil",
        "unit": "USD/bbl",
        "source": "unavailable",
        "note": (
            "No reachable provider serves this series (Brent trades on ICE, "
            "not NSE). Stored pre-consolidation history remains usable; no "
            "new data is fetched."
        ),
        "freshness_days": 14,
    },
    "us10y": {
        "label": "US 10-year Treasury yield",
        "unit": "%",
        "source": "unavailable",
        "note": (
            "No reachable provider serves this series (US Treasuries are not "
            "NSE-listed). Stored pre-consolidation history remains usable; no "
            "new data is fetched."
        ),
        "freshness_days": 14,
    },
    "india_vix": {
        "label": "India VIX (volatility gauge)",
        "unit": "index points",
        "source": "upstox",
        "instrument_key": "NSE_INDEX|India VIX",
        "freshness_days": 14,
    },
}

# Curated official datasets live versioned under data/macro/ (repo root).
CURATED_DIRNAME = "macro"


def curated_dir():
    """Repository data/macro directory holding the curated official CSVs."""
    from app.core.config import REPO_ROOT

    return REPO_ROOT / "data" / CURATED_DIRNAME

# How far back market providers fetch on a full refresh (trading days ≈ 1Y).
MARKET_LOOKBACK_DAYS = 365
# Minimum stored daily points before a market series is usable in factors.
MIN_MARKET_POINTS = 66  # ≈ one quarter of trading days


def indicator_ids() -> list[str]:
    return list(MACRO_INDICATORS)


def get_indicator(indicator_id: str) -> dict:
    try:
        return MACRO_INDICATORS[indicator_id]
    except KeyError:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"Unknown macro indicator '{indicator_id}'") from None
