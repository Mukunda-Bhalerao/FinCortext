"""Market-derived macro series via the existing yfinance infrastructure.

Daily closes for fixed macro tickers (FX, crude, US rates, India VIX).
Same failure contract as the market provider: ProviderError on any failure,
empty frames yield zero points (reported, never synthesized).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.data.macro.indicators import MARKET_LOOKBACK_DAYS, get_indicator
from app.domain.contracts.providers import MacroDataProvider

logger = get_logger("providers.macro_yfinance")


class YFinanceMacroProvider(MacroDataProvider):
    """Market macro gauges through yfinance (no new dependencies)."""

    name = "yfinance_macro"

    def __init__(self, lookback_days: int = MARKET_LOOKBACK_DAYS):
        self._lookback_days = max(30, lookback_days)

    def fetch_indicator(self, indicator_id: str) -> dict:
        meta = get_indicator(indicator_id)  # raises NotFoundError if unknown
        if meta.get("source") != "yfinance" or not meta.get("ticker"):
            raise ProviderError(
                f"Indicator '{indicator_id}' is not a yfinance market series.",
                details={"provider": self.name},
            )
        ticker = meta["ticker"]
        end = date.today()
        start = end - timedelta(days=self._lookback_days)
        try:
            import yfinance as yf

            df = yf.download(
                ticker,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception as exc:
            raise ProviderError(
                f"yfinance request failed for macro ticker {ticker}: {exc}",
                details={"provider": self.name, "ticker": ticker},
            ) from exc
        if df is None or (hasattr(df, "empty") and df.empty):
            logger.warning("yfinance returned no data for macro ticker %s", ticker)
            return {
                "indicator_id": indicator_id,
                "unit": meta["unit"],
                "source_name": f"yfinance market data ({ticker})",
                "points": [],
                "warnings": [f"No rows returned for {ticker}."],
            }
        try:
            import pandas as pd

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            closes = df["Close"].dropna()
        except Exception as exc:
            raise ProviderError(
                f"Unusable yfinance frame for macro ticker {ticker}: {exc}",
                details={"provider": self.name, "ticker": ticker},
            ) from exc
        points = []
        for trade_date, close in closes.items():
            try:
                day = trade_date.date() if hasattr(trade_date, "date") else trade_date
                value = float(close)
            except (TypeError, ValueError):
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
                    "notes": f"daily close {ticker}",
                }
            )
        return {
            "indicator_id": indicator_id,
            "unit": meta["unit"],
            "source_name": f"yfinance market data ({ticker})",
            "points": points,
            "warnings": [],
        }
