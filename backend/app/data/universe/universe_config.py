"""Versioned stock universe configuration.

The universe is a single source of truth: internal symbol, company name,
exchange, provider ticker, sector and industry. No code hardcodes these
symbols — everything reads from here (later: from the DB mirror).
"""

from __future__ import annotations

from app.core.exceptions import NotFoundError
from app.domain.models.universe import UniverseEntry

UNIVERSE_VERSION = "1.0.0"

UNIVERSE: list[UniverseEntry] = [
    UniverseEntry(
        symbol="RELIANCE",
        name="Reliance Industries",
        exchange="NSE",
        ticker="RELIANCE.NS",
        sector="Energy",
        industry="Integrated Oil & Gas",
    ),
    UniverseEntry(
        symbol="TCS",
        name="Tata Consultancy Services",
        exchange="NSE",
        ticker="TCS.NS",
        sector="Information Technology",
        industry="IT Services & Consulting",
    ),
    UniverseEntry(
        symbol="INFY",
        name="Infosys",
        exchange="NSE",
        ticker="INFY.NS",
        sector="Information Technology",
        industry="IT Services & Consulting",
    ),
    UniverseEntry(
        symbol="HDFCBANK",
        name="HDFC Bank",
        exchange="NSE",
        ticker="HDFCBANK.NS",
        sector="Financial Services",
        industry="Private Sector Bank",
    ),
    UniverseEntry(
        symbol="ICICIBANK",
        name="ICICI Bank",
        exchange="NSE",
        ticker="ICICIBANK.NS",
        sector="Financial Services",
        industry="Private Sector Bank",
    ),
    UniverseEntry(
        symbol="BHARTIARTL",
        name="Bharti Airtel",
        exchange="NSE",
        ticker="BHARTIARTL.NS",
        sector="Telecommunication",
        industry="Telecom Services",
    ),
    UniverseEntry(
        symbol="ITC",
        name="ITC",
        exchange="NSE",
        ticker="ITC.NS",
        sector="Fast Moving Consumer Goods",
        industry="Diversified FMCG",
    ),
    UniverseEntry(
        symbol="LT",
        name="Larsen & Toubro",
        exchange="NSE",
        ticker="LT.NS",
        sector="Construction",
        industry="Engineering & Construction",
    ),
    UniverseEntry(
        symbol="SBIN",
        name="State Bank of India",
        exchange="NSE",
        ticker="SBIN.NS",
        sector="Financial Services",
        industry="Public Sector Bank",
    ),
    UniverseEntry(
        symbol="HINDUNILVR",
        name="Hindustan Unilever",
        exchange="NSE",
        ticker="HINDUNILVR.NS",
        sector="Fast Moving Consumer Goods",
        industry="Household & Personal Products",
    ),
]

_BY_SYMBOL: dict[str, UniverseEntry] = {e.symbol: e for e in UNIVERSE}


def get_universe() -> list[UniverseEntry]:
    """Return the full universe (ordered)."""
    return list(UNIVERSE)


def get_universe_entry(symbol: str) -> UniverseEntry:
    """Look up one entry; raises NotFoundError for unknown symbols."""
    entry = _BY_SYMBOL.get(symbol.upper())
    if entry is None:
        raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe")
    return entry


def get_sector_peers(symbol: str) -> list[UniverseEntry]:
    """All universe entries in the same sector as `symbol` (including itself)."""
    entry = get_universe_entry(symbol)
    return [e for e in UNIVERSE if e.sector == entry.sector]


def get_industry_peers(symbol: str) -> list[UniverseEntry]:
    """All universe entries in the same industry as `symbol` (including itself)."""
    entry = get_universe_entry(symbol)
    return [e for e in UNIVERSE if e.industry == entry.industry]