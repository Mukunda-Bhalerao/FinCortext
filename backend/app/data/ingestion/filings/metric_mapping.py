"""Canonical metric mapping for filing ingestion.

Maps free-form metric labels from CSV/XBRL/PDF sources to FinCortext canonical
metric keys. Mapping is configuration, not hidden logic — extend the tables
here as new sources are supported.
"""

from __future__ import annotations

# Lowercased label → canonical metric key + statement type.
# Units: currency metrics carry the filing's unit; ratio/percent metrics use
# `ratio`/`percent` units.
METRIC_ALIASES: dict[str, tuple[str, str]] = {
    # --- Income statement -------------------------------------------------
    "total revenue": ("total_revenue", "income_statement"),
    "revenue": ("total_revenue", "income_statement"),
    "revenue from operations": ("total_revenue", "income_statement"),
    "sales": ("total_revenue", "income_statement"),
    "net sales": ("total_revenue", "income_statement"),
    "total income": ("total_revenue", "income_statement"),
    "net income": ("net_income", "income_statement"),
    "profit after tax": ("net_income", "income_statement"),
    "pat": ("net_income", "income_statement"),
    "net profit": ("net_income", "income_statement"),
    "profit for the year": ("net_income", "income_statement"),
    "profit before tax": ("profit_before_tax", "income_statement"),
    "pbt": ("profit_before_tax", "income_statement"),
    "operating profit": ("operating_profit", "income_statement"),
    "ebit": ("operating_profit", "income_statement"),
    "profit from operations": ("operating_profit", "income_statement"),
    "operating profit before working capital changes": ("operating_profit", "income_statement"),
    "earnings per share": ("eps", "income_statement"),
    "basic eps": ("eps", "income_statement"),
    "diluted eps": ("eps", "income_statement"),
    # --- Balance sheet ------------------------------------------------------
    "total assets": ("total_assets", "balance_sheet"),
    "total equity": ("total_equity", "balance_sheet"),
    "shareholders equity": ("total_equity", "balance_sheet"),
    "total shareholders funds": ("total_equity", "balance_sheet"),
    "net worth": ("total_equity", "balance_sheet"),
    "total debt": ("total_debt", "balance_sheet"),
    "borrowings": ("total_debt", "balance_sheet"),
    "total borrowings": ("total_debt", "balance_sheet"),
    "long term borrowings": ("total_debt", "balance_sheet"),
    "debt": ("total_debt", "balance_sheet"),
    # --- Ratios (usually from ratios section / XBRL) -------------------------
    "return on equity": ("roe", "other"),
    "roe": ("roe", "other"),
    "return on capital employed": ("roce", "other"),
    "roce": ("roce", "other"),
    "price earnings ratio": ("pe_ratio", "other"),
    "p/e": ("pe_ratio", "other"),
    "operating margin": ("operating_margin", "other"),
    "operating margin percentage": ("operating_margin", "other"),
    "net profit margin": ("net_margin", "other"),
    "net margin": ("net_margin", "other"),
}


def map_metric(label: str) -> tuple[str, str] | None:
    """Return (canonical_metric, statement_type) for a label, or None.

    Normalizes whitespace/case before lookup. Unknown labels return None —
    callers must record them as unmapped rather than guessing.
    """
    normalized = " ".join(label.lower().split())
    return METRIC_ALIASES.get(normalized)


# XBRL element-name mapping (common us-gaap / ifrs / in-gaap style local names).
XBRL_ELEMENT_ALIASES: dict[str, str] = {
    "revenues": "total_revenue",
    "revenuefromcontractwithcustomerexcludingassessedtax": "total_revenue",
    "revenuefromoperations": "total_revenue",
    "netincomeloss": "net_income",
    "profitloss": "net_income",
    "profitorloss": "net_income",
    "operatingincomeloss": "operating_profit",
    "assets": "total_assets",
    "stockholdersequity": "total_equity",
    "equity": "total_equity",
    "debtlongtermandshorttermborrowings": "total_debt",
    "longtermdebt": "total_debt",
    "earningspersharebasic": "eps",
    "earningspersharediluted": "eps",
    "returnonequity": "roe",
    "returnoncapitalemployed": "roce",
}


def map_xbrl_element(element_name: str) -> str | None:
    """Map an XBRL element local name to a canonical metric."""
    return XBRL_ELEMENT_ALIASES.get(element_name.lower().replace("_", "").replace("-", ""))