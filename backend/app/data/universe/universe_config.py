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
        # Bare "Reliance" is case-sensitive: capitalized it overwhelmingly
        # denotes this company in business headlines, while lowercase
        # "reliance" is the common noun ("banks' reliance on deposits").
        # The financial-context gate rejects any residue.
        aliases=["RIL", "Reliance Jio", "Jio Platforms", "Mukesh Ambani"],
        strict_aliases=["Reliance"],
    ),
    UniverseEntry(
        symbol="TCS",
        name="Tata Consultancy Services",
        exchange="NSE",
        ticker="TCS.NS",
        sector="Information Technology",
        industry="IT Services & Consulting",
        # Bare "Tata" deliberately excluded: Tata Motors/Tata Steel/etc.
        aliases=["TCS", "Tata Consultancy"],
    ),
    UniverseEntry(
        symbol="INFY",
        name="Infosys",
        exchange="NSE",
        ticker="INFY.NS",
        sector="Information Technology",
        industry="IT Services & Consulting",
        aliases=["INFY"],
    ),
    UniverseEntry(
        symbol="HDFCBANK",
        name="HDFC Bank",
        exchange="NSE",
        ticker="HDFCBANK.NS",
        sector="Financial Services",
        industry="Private Sector Bank",
        # Bare "HDFC" excluded: HDFC Life / HDFC AMC are separate companies.
        aliases=["HDFC Bank", "HDFCBANK"],
    ),
    UniverseEntry(
        symbol="ICICIBANK",
        name="ICICI Bank",
        exchange="NSE",
        ticker="ICICIBANK.NS",
        sector="Financial Services",
        industry="Private Sector Bank",
        # Bare "ICICI" excluded: ICICI Prudential / ICICI Lombard differ.
        aliases=["ICICI Bank", "ICICIBANK"],
    ),
    UniverseEntry(
        symbol="BHARTIARTL",
        name="Bharti Airtel",
        exchange="NSE",
        ticker="BHARTIARTL.NS",
        sector="Telecommunication",
        industry="Telecom Services",
        # Bare "Bharti" excluded: Bharti Hexacom is separately listed.
        aliases=["Bharti Airtel", "Airtel", "BHARTIARTL", "Sunil Mittal"],
    ),
    UniverseEntry(
        symbol="ITC",
        name="ITC",
        exchange="NSE",
        ticker="ITC.NS",
        sector="Fast Moving Consumer Goods",
        industry="Diversified FMCG",
        aliases=["ITC", "ITC Ltd", "ITC Limited", "ITC Infotech"],
    ),
    UniverseEntry(
        symbol="LT",
        name="Larsen & Toubro",
        exchange="NSE",
        ticker="LT.NS",
        sector="Construction",
        industry="Engineering & Construction",
        # Bare "LT" excluded: two-letter tokens collide constantly
        # (e.g. "LT Foods", abbreviations). "L&T" is the press standard.
        aliases=["Larsen & Toubro", "Larsen and Toubro", "L&T"],
    ),
    UniverseEntry(
        symbol="SBIN",
        name="State Bank of India",
        exchange="NSE",
        ticker="SBIN.NS",
        sector="Financial Services",
        industry="Public Sector Bank",
        aliases=["State Bank", "SBI", "SBIN"],
    ),
    UniverseEntry(
        symbol="HINDUNILVR",
        name="Hindustan Unilever",
        exchange="NSE",
        ticker="HINDUNILVR.NS",
        sector="Fast Moving Consumer Goods",
        industry="Household & Personal Products",
        aliases=["Hindustan Unilever", "HUL", "HINDUNILVR"],
    ),
]

_BY_SYMBOL: dict[str, UniverseEntry] = {e.symbol: e for e in UNIVERSE}

# Dynamic NSE equities resolved via Upstox search at runtime. Static universe
# entries stay untouched; dynamic entries let ANY valid Upstox NSE equity be
# analyzed without manually editing the hardcoded list.
_DYNAMIC_BY_SYMBOL: dict[str, UniverseEntry] = {}


def get_static_universe() -> list[UniverseEntry]:
    """Return the hardcoded static universe (ordered)."""
    return list(UNIVERSE)


def get_universe() -> list[UniverseEntry]:
    """Return static + dynamically registered entries (static order first)."""
    dynamics = sorted(_DYNAMIC_BY_SYMBOL.values(), key=lambda e: e.symbol)
    return list(UNIVERSE) + dynamics


def register_dynamic_entry(entry: UniverseEntry) -> UniverseEntry:
    """Register (or refresh) a dynamic company context. Idempotent."""
    entry.symbol = entry.symbol.upper()
    _DYNAMIC_BY_SYMBOL[entry.symbol] = entry
    return entry


def clear_dynamic_registry() -> None:
    """Test helper: drop all dynamically registered entries."""
    _DYNAMIC_BY_SYMBOL.clear()


def build_dynamic_entry(
    *,
    symbol: str,
    name: str,
    instrument_key: str | None = None,
    exchange: str = "NSE",
    sector: str = "Unknown",
    industry: str = "Unknown",
) -> UniverseEntry:
    """Build a UniverseEntry for a valid Upstox NSE equity not in the static list."""
    sym = (symbol or "").strip().upper()
    return UniverseEntry(
        symbol=sym,
        name=(name or sym).strip() or sym,
        exchange=(exchange or "NSE").strip().upper(),
        # yfinance-compatible ticker so the yfinance fallback/research path
        # keeps working for dynamic symbols; Upstox calls use instrument_key.
        ticker=f"{sym}.NS",
        sector=sector or "Unknown",
        industry=industry or "Unknown",
        aliases=[],
        strict_aliases=[],
        instrument_key=(instrument_key or "").strip() or None,
    )


def get_universe_entry(symbol: str) -> UniverseEntry:
    """Look up one entry (static first, then dynamic); raises NotFoundError."""
    key = (symbol or "").strip().upper()
    # Allow provider tickers ("TCS.NS") and bare keys to resolve.
    if key.endswith(".NS"):
        key = key[:-3]
    entry = _BY_SYMBOL.get(key)
    if entry is not None:
        return entry
    entry = _DYNAMIC_BY_SYMBOL.get(key)
    if entry is not None:
        return entry
    raise NotFoundError(f"Symbol '{symbol}' is not in the configured universe")


def is_dynamic_symbol(symbol: str) -> bool:
    return (symbol or "").strip().upper() in _DYNAMIC_BY_SYMBOL


def get_sector_peers(symbol: str) -> list[UniverseEntry]:
    """All universe entries in the same sector as `symbol` (including itself)."""
    entry = get_universe_entry(symbol)
    # Dynamic entries carry sector "Unknown": grouping unrelated dynamics as
    # peers would be misleading, so they compare against themselves only.
    if entry.sector in {"Unknown", "Dynamic"}:
        return [entry]
    return [e for e in get_universe() if e.sector == entry.sector]


def get_industry_peers(symbol: str) -> list[UniverseEntry]:
    """All universe entries in the same industry as `symbol` (including itself)."""
    entry = get_universe_entry(symbol)
    if entry.industry in {"Unknown", "Dynamic"}:
        return [entry]
    return [e for e in get_universe() if e.industry == entry.industry]