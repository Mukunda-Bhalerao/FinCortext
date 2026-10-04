"""Upstox-backed market gauges for the Macro Analyst.

Serves the market-derived gauge series FinCortext can obtain from Upstox
(India VIX index candles, verified live against the Historical Candle V3
endpoint). Gauges with no NSE instrument (USD/INR spot, Brent crude, US 10Y
yield) are NOT served here — they report UNAVAILABLE honestly rather than
being proxied or fabricated.

Upstox API -> UpstoxGaugeProvider -> MacroService -> DuckDB
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.data.macro.indicators import MARKET_LOOKBACK_DAYS, get_indicator
from app.domain.contracts.providers import MacroDataProvider

logger = get_logger("providers.upstox_gauges")


class UpstoxGaugeProvider(MacroDataProvider):
    """Market gauges through Upstox index candles (no new dependencies)."""

    name = "upstox_gauges"

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = "https://api.upstox.com",
        timeout_seconds: int = 10,
        lookback_days: int = MARKET_LOOKBACK_DAYS,
        client=None,
    ) -> None:
        if client is None:
            from app.data.providers.market.upstox_client import UpstoxHttpClient

            client = UpstoxHttpClient(
                access_token, base_url=base_url, timeout_seconds=timeout_seconds
            )
        self._client = client
        self._lookback_days = max(30, lookback_days)

    @property
    def is_configured(self) -> bool:
        return bool(self._client.is_configured)

    def fetch_indicator(self, indicator_id: str) -> dict:
        meta = get_indicator(indicator_id)  # raises NotFoundError if unknown
        if meta.get("source") != "upstox" or not meta.get("instrument_key"):
            raise ProviderError(
                f"Indicator '{indicator_id}' is not an Upstox market gauge.",
                details={"provider": self.name},
            )
        key = meta["instrument_key"]
        end = date.today()
        start = end - timedelta(days=self._lookback_days)
        candles = self._client.fetch_daily_candles(key, start, end)
        if not candles:
            logger.warning("Upstox returned no candles for gauge %s", key)
            return {
                "indicator_id": indicator_id,
                "unit": meta["unit"],
                "source_name": f"Upstox market data ({key})",
                "points": [],
                "warnings": [f"No candles returned for {key}."],
            }
        points = []
        for candle in candles:
            if not isinstance(candle, (list, tuple)) or len(candle) < 5:
                continue
            try:
                day = date.fromisoformat(str(candle[0])[:10])
                value = float(candle[4])
            except (TypeError, ValueError, IndexError):
                continue
            if value != value or value in (float("inf"), float("-inf")):
                continue  # NaN/inf guard — never store non-finite points
            points.append(
                {
                    "period_start": None,
                    "period_end": day.isoformat(),
                    "value": value,
                    "published_at": None,
                    "source_url": None,
                    "notes": f"daily index close {key}",
                }
            )
        points.sort(key=lambda p: p["period_end"])
        return {
            "indicator_id": indicator_id,
            "unit": meta["unit"],
            "source_name": f"Upstox market data ({key})",
            "points": points,
            "warnings": [],
        }
