"""yfinance adapter implementing MarketDataProvider.

Translates yfinance OHLCV frames into canonical MarketPrice models at the
boundary. NSE tickers use the `.NS` suffix from the universe configuration.
All failures raise ProviderError/ProviderUnavailableError — this adapter never
returns fabricated data.
"""

from __future__ import annotations

from datetime import date

from app.core.exceptions import ProviderError
from app.core.logging import get_logger
from app.domain.contracts.providers import MarketDataProvider
from app.domain.models.market import MarketPrice

logger = get_logger("providers.yfinance")


class YFinanceMarketProvider(MarketDataProvider):
    name = "yfinance"

    def __init__(self, symbol_to_ticker: dict[str, str] | None = None):
        # Optional mapping of internal symbol -> provider ticker. When absent,
        # the caller must pass provider tickers directly.
        self._symbol_to_ticker = symbol_to_ticker or {}
        # Reverse mapping so the canonical internal symbol can ALWAYS be
        # resolved: MarketPrice.symbol is the internal symbol (e.g. 'TCS'),
        # never the provider ticker (e.g. 'TCS.NS'). Storing the provider
        # ticker in the `symbol` column makes every internal-symbol read
        # (prices, status, agents) return zero rows.
        self._ticker_to_symbol = {t.upper(): s for s, t in self._symbol_to_ticker.items()}

    def _resolve_canonical_symbol(self, ticker: str) -> str:
        """Internal FinCortext symbol for the given symbol or provider ticker."""
        upper = ticker.upper()
        if upper in self._symbol_to_ticker:
            return upper  # already an internal symbol
        return self._ticker_to_symbol.get(upper, upper)

    def fetch_ohlcv(self, ticker: str, start: date, end: date) -> list[MarketPrice]:
        """Fetch daily OHLCV for `ticker` (internal symbol or provider ticker).

        `end` is inclusive (yfinance end is exclusive; we add one day).
        Returned bars are always keyed by the canonical internal symbol.
        """
        import pandas as pd

        provider_ticker = self._symbol_to_ticker.get(ticker.upper(), ticker)
        symbol = self._resolve_canonical_symbol(ticker)
        try:
            import yfinance as yf

            df = yf.download(
                provider_ticker,
                start=start.isoformat(),
                end=_next_day(end).isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception as exc:  # network errors, import errors, etc.
            raise ProviderError(
                f"yfinance request failed for {provider_ticker}: {exc}",
                details={"provider": self.name, "ticker": provider_ticker},
            ) from exc

        if df is None or (hasattr(df, "empty") and df.empty):
            logger.warning("yfinance returned no data for %s", provider_ticker)
            return []

        return self.normalize_frame(df, symbol=symbol, provider_ticker=provider_ticker)

    def normalize_frame(self, df, *, symbol: str, provider_ticker: str) -> list[MarketPrice]:
        """Convert a yfinance OHLCV frame to canonical MarketPrice models.

        Raises ProviderError on structurally unusable frames.
        """
        try:
            import pandas as pd

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            required = {"open", "high", "low", "close", "volume"}
            missing = required - set(df.columns)
            if missing:
                raise ProviderError(
                    f"yfinance frame for {provider_ticker} missing columns: {sorted(missing)}",
                    details={"provider": self.name, "ticker": provider_ticker},
                )
            df = df.dropna(subset=["open", "high", "low", "close"])

            bars: list[MarketPrice] = []
            for trade_date, row in df.iterrows():
                try:
                    bars.append(
                        MarketPrice(
                            symbol=symbol,
                            provider_ticker=provider_ticker,
                            trade_date=trade_date.date()
                            if hasattr(trade_date, "date")
                            else trade_date,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]) if row["volume"] == row["volume"] else 0.0,
                        )
                    )
                except Exception as row_exc:
                    # Skip malformed single rows but keep the failure visible.
                    logger.warning(
                        "Skipping malformed yfinance row %s for %s: %s",
                        trade_date, provider_ticker, row_exc,
                    )
            return bars
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Failed to normalize yfinance data for {provider_ticker}: {exc}",
                details={"provider": self.name, "ticker": provider_ticker},
            ) from exc


def _next_day(d: date) -> date:
    from datetime import timedelta

    return d + timedelta(days=1)