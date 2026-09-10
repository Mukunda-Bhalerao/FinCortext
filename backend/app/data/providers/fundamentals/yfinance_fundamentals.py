"""Yahoo Finance fundamentals adapter implementing FundamentalDataProvider.

Retrieves annual income-statement / balance-sheet history plus a small set of
snapshot ratios for one universe symbol and normalizes them into a documented
bundle of canonical metric candidates.

Source honesty (see docs/data_sources.md):
- This is PROVIDER data (Yahoo Finance), not an official company filing.
  Observations built from it carry source_type=yfinance and a source_name
  that says so; official filings always take precedence in the UI.
- Annual statements carry real fiscal period_end dates. Snapshot ratios
  (trailing P/E, TTM ROE from `info`) have NO statement period — consumers
  must treat their available_at (ingestion time) as the point-in-time stamp.
  The bundle flags this explicitly.

Failure handling (never fabricates values):
- yfinance/network errors      -> ProviderError
- empty/missing statements     -> ProviderError (nothing usable returned)
- missing individual labels    -> recorded in `warnings`, never guessed.
"""

from __future__ import annotations

from datetime import date

from app.core.exceptions import ProviderError
from app.data.universe.universe_config import get_universe_entry
from app.domain.contracts.providers import FundamentalDataProvider

# Provider row label → canonical metric, in priority order (first hit wins).
# Labels observed in yfinance annual statements for NSE equities.
INCOME_LABELS: dict[str, list[str]] = {
    "total_revenue": ["Total Revenue", "Operating Revenue"],
    "net_income": [
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    ],
}

BALANCE_LABELS: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "total_equity": [
        "Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ],
    "total_debt": ["Total Debt"],
}

ANNUAL_YEARS = 4  # fiscal years requested per symbol (growth needs ≥ 2)


class YFinanceFundamentalsProvider(FundamentalDataProvider):
    """Yahoo Finance fundamentals. Replaceable like every provider."""

    name = "yfinance_fundamentals"

    def __init__(self, symbol_to_ticker: dict[str, str], years: int = ANNUAL_YEARS):
        self._symbol_to_ticker = dict(symbol_to_ticker)
        self._years = max(2, years)

    def fetch_fundamentals(self, ticker: str) -> dict:
        """Fetch + normalize fundamentals for an INTERNAL symbol.

        Canonical-key convention (same as the market provider): callers pass
        the internal symbol (TCS); the provider resolves the Yahoo ticker
        (TCS.NS) via the universe mapping.
        """
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError(
                "yfinance is not installed; cannot fetch fundamentals.",
                details={"provider": self.name},
            ) from exc

        entry = get_universe_entry(ticker)
        provider_ticker = self._symbol_to_ticker.get(entry.symbol, entry.ticker)
        try:
            yf_ticker = yf.Ticker(provider_ticker)
            income = yf_ticker.financials
            balance = yf_ticker.balance_sheet
            try:
                info = yf_ticker.info or {}
            except Exception:
                info = {}
        except Exception as exc:
            raise ProviderError(
                f"Yahoo Finance fundamentals fetch failed for {entry.symbol}: {exc}",
                details={"provider": self.name, "ticker": provider_ticker},
            ) from exc

        warnings: list[str] = []
        annual = self._annual_series(income, balance, warnings)
        if not annual:
            raise ProviderError(
                f"Yahoo Finance returned no usable annual statements for {entry.symbol}.",
                details={"provider": self.name, "ticker": provider_ticker},
            )
        snapshot = self._snapshot(info, warnings)
        currency = str(info.get("financialCurrency") or info.get("currency") or "INR")
        return {
            "symbol": entry.symbol,
            "ticker": provider_ticker,
            "currency": currency,
            "annual": annual,
            "snapshot": snapshot,
            "warnings": warnings,
        }

    # -- normalization ------------------------------------------------------

    def _annual_series(self, income, balance, warnings: list[str]) -> list[dict]:
        """Newest-first annual rows with canonical metric candidates."""
        income_cols = self._sorted_columns(income, "income statement", warnings)
        balance_cols = self._sorted_columns(balance, "balance sheet", warnings)
        self._report_unmapped_labels(income, {**INCOME_LABELS}, "income", warnings)
        self._report_unmapped_labels(balance, {**BALANCE_LABELS}, "balance", warnings)
        periods = sorted(
            {c for c in income_cols + balance_cols}, reverse=True
        )[: self._years]
        rows = []
        for period in periods:
            row: dict = {"period_end": period}
            for metric, labels in INCOME_LABELS.items():
                row[metric] = self._pick_label(income, labels, period, metric, warnings)
            for metric, labels in BALANCE_LABELS.items():
                row[metric] = self._pick_label(balance, labels, period, metric, warnings)
            rows.append(row)
        return rows

    def _report_unmapped_labels(self, frame, label_table: dict, what: str, warnings: list[str]) -> None:
        """Provider rows we do not map are reported, never silently dropped."""
        if frame is None or getattr(frame, "empty", True):
            return
        known = {label.lower() for labels in label_table.values() for label in labels}
        for idx in frame.index:
            if str(idx).lower() not in known:
                warnings.append(f"Unmapped {what} label ignored: {idx!r}.")

    def _sorted_columns(self, frame, what: str, warnings: list[str]) -> list[date]:
        if frame is None or getattr(frame, "empty", True):
            warnings.append(f"Annual {what} unavailable from provider.")
            return []
        cols = []
        for col in frame.columns:
            try:
                cols.append(col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10]))
            except (ValueError, TypeError, AttributeError):
                warnings.append(f"Ignoring unparseable {what} column: {col!r}.")
        return sorted(cols)

    def _pick_label(self, frame, labels: list[str], period: date, metric: str, warnings: list[str]):
        """First available label's value at `period`; None + warning if absent."""
        if frame is None or getattr(frame, "empty", True):
            return None
        available = {str(idx): idx for idx in frame.index}
        for label in labels:
            if label in available:
                try:
                    value = frame.loc[available[label], frame.columns[
                        [str(c)[:10] for c in frame.columns].index(period.isoformat())
                    ]]
                except (KeyError, IndexError, ValueError):
                    continue
                num = self._to_float(value)
                if num is not None:
                    return num
                warnings.append(
                    f"{metric}: non-numeric {label!r} for period {period.isoformat()} ignored."
                )
                return None
        warnings.append(
            f"{metric}: none of {labels} present for period {period.isoformat()}."
        )
        return None

    def _snapshot(self, info: dict, warnings: list[str]) -> dict:
        """Point-in-time ratios from the quote snapshot (no statement period)."""
        snapshot = {}
        pe = self._to_float(info.get("trailingPE"))
        roe = self._to_float(info.get("returnOnEquity"))
        if pe is None:
            warnings.append("Snapshot trailingPE unavailable from provider.")
        if roe is None:
            warnings.append("Snapshot returnOnEquity unavailable from provider.")
        snapshot["pe_ratio"] = pe
        snapshot["roe"] = roe
        snapshot["as_of"] = date.today().isoformat()
        return snapshot

    @staticmethod
    def _to_float(value) -> float | None:
        try:
            import math

            num = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(num):
            return None
        # yfinance uses NaN for missing cells — never let one through.
        try:
            import pandas as pd

            if pd.isna(value):
                return None
        except ImportError:
            pass
        return num
