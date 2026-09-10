"""Unit tests: YFinanceFundamentalsProvider normalization (no network).

yfinance is replaced with a stub module serving fixed pandas frames, so the
mapping from provider labels → canonical metrics is tested deterministically.
"""

from datetime import date

import pandas as pd
import pytest

from app.core.exceptions import ProviderError
from app.data.providers.fundamentals.yfinance_fundamentals import (
    YFinanceFundamentalsProvider,
)


def _frame(rows: dict[str, list], dates: list[str]) -> pd.DataFrame:
    cols = [pd.Timestamp(d) for d in dates]
    return pd.DataFrame({c: [rows[r][i] for r in rows] for i, c in enumerate(cols)}, index=list(rows))


INCOME_ROWS = {
    "Total Revenue": [1000.0, 900.0],
    "Net Income": [150.0, 120.0],
    "Unmapped Weird Line": [1.0, 2.0],
}
BALANCE_ROWS = {
    "Total Assets": [2000.0, 1900.0],
    "Stockholders Equity": [800.0, 750.0],
    "Total Debt": [200.0, 180.0],
}
DATES = ["2025-03-31", "2024-03-31"]


class _StubTicker:
    def __init__(self, income=None, balance=None, info=None, fail=False):
        self._income = income
        self._balance = balance
        self._info = info or {}
        self._fail = fail

    @property
    def financials(self):
        if self._fail:
            raise RuntimeError("yahoo exploded")
        return self._income

    @property
    def balance_sheet(self):
        if self._fail:
            raise RuntimeError("yahoo exploded")
        return self._balance

    @property
    def info(self):
        return dict(self._info)


@pytest.fixture()
def stub_yfinance(monkeypatch):
    """Install a stub `yfinance` module returning canned frames."""
    import sys
    import types

    state = {"ticker": _StubTicker(_frame(INCOME_ROWS, DATES), _frame(BALANCE_ROWS, DATES), {"trailingPE": 22.5, "returnOnEquity": 0.19, "financialCurrency": "INR"})}

    module = types.ModuleType("yfinance")

    class Ticker:
        def __init__(self, symbol):
            state["seen"] = symbol
            stub = state["ticker"]
            self._stub = stub

        @property
        def financials(self):
            return self._stub.financials

        @property
        def balance_sheet(self):
            return self._stub.balance_sheet

        @property
        def info(self):
            return self._stub.info

    module.Ticker = Ticker
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return state


def _provider():
    return YFinanceFundamentalsProvider({"TCS": "TCS.NS"})


def test_normalizes_annual_statements_to_canonical_metrics(stub_yfinance):
    bundle = _provider().fetch_fundamentals("TCS")
    assert bundle["symbol"] == "TCS"
    assert bundle["ticker"] == "TCS.NS"
    assert bundle["currency"] == "INR"
    assert len(bundle["annual"]) == 2
    newest = bundle["annual"][0]
    assert newest["period_end"] == date(2025, 3, 31)
    assert newest["total_revenue"] == 1000.0
    assert newest["net_income"] == 150.0
    assert newest["total_assets"] == 2000.0
    assert newest["total_equity"] == 800.0
    assert newest["total_debt"] == 200.0
    assert bundle["annual"][1]["total_revenue"] == 900.0
    # Snapshot ratios with fetch-date stamp.
    assert bundle["snapshot"]["pe_ratio"] == 22.5
    assert bundle["snapshot"]["roe"] == 0.19
    assert bundle["snapshot"]["as_of"] == date.today().isoformat()


def test_internal_symbol_resolves_to_provider_ticker(stub_yfinance):
    _provider().fetch_fundamentals("tcs")  # lowercase works like the market provider
    assert stub_yfinance["seen"] == "TCS.NS"


def test_missing_labels_reported_never_guessed(stub_yfinance):
    bundle = _provider().fetch_fundamentals("TCS")
    # Provider rows we do not map are surfaced as warnings, not dropped silently.
    assert any("Unmapped income label" in w for w in bundle["warnings"])
    # No label in the bundle maps to e.g. operating_profit — absence is explicit.
    assert all("operating_profit" not in row for row in bundle["annual"])


def test_empty_statements_raise_provider_error(stub_yfinance, monkeypatch):
    import sys

    stub = stub_yfinance["ticker"]
    object.__setattr__(stub, "_income", pd.DataFrame())
    object.__setattr__(stub, "_balance", pd.DataFrame())
    with pytest.raises(ProviderError):
        _provider().fetch_fundamentals("TCS")


def test_provider_failure_wrapped(stub_yfinance):
    object.__setattr__(stub_yfinance["ticker"], "_fail", True)
    with pytest.raises(ProviderError):
        _provider().fetch_fundamentals("TCS")


def test_unknown_symbol_rejected():
    with pytest.raises(Exception):
        _provider().fetch_fundamentals("NOPE")
