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

# Curated same-sector candidate peers for dynamic industry-peer discovery.
# These are real NSE-listed companies (configuration metadata, like UNIVERSE
# itself) — every candidate is validated live through Upstox search before use
# and skipped when Upstox returns no NSE equity for it, so peers are never
# invented. Ordered: same-industry names first, then broader sector names.
# Each tuple: (symbol, company name, industry).
SECTOR_PEER_CANDIDATES: dict[str, list[tuple[str, str, str]]] = {
    "Information Technology": [
        ("WIPRO", "Wipro", "IT Services & Consulting"),
        ("HCLTECH", "HCL Technologies", "IT Services & Consulting"),
        ("TECHM", "Tech Mahindra", "IT Services & Consulting"),
        ("LTIM", "LTIMindtree", "IT Services & Consulting"),
        ("PERSISTENT", "Persistent Systems", "IT Services & Consulting"),
        ("COFORGE", "Coforge", "IT Services & Consulting"),
    ],
    "Financial Services": [
        ("KOTAKBANK", "Kotak Mahindra Bank", "Private Sector Bank"),
        ("AXISBANK", "Axis Bank", "Private Sector Bank"),
        ("INDUSINDBK", "IndusInd Bank", "Private Sector Bank"),
        ("BANKBARODA", "Bank of Baroda", "Public Sector Bank"),
        ("PNB", "Punjab National Bank", "Public Sector Bank"),
        ("CANBK", "Canara Bank", "Public Sector Bank"),
        ("UNIONBANK", "Union Bank of India", "Public Sector Bank"),
        ("HDFCLIFE", "HDFC Life Insurance", "Life Insurance"),
        ("SBILIFE", "SBI Life Insurance", "Life Insurance"),
        ("BAJFINANCE", "Bajaj Finance", "NBFC"),
        ("BAJAJFINSV", "Bajaj Finserv", "NBFC"),
    ],
    "Energy": [
        ("ONGC", "Oil & Natural Gas Corporation", "Oil & Gas Exploration"),
        ("NTPC", "NTPC", "Power Generation"),
        ("POWERGRID", "Power Grid Corporation", "Power Transmission"),
        ("COALINDIA", "Coal India", "Coal Mining"),
        ("BPCL", "Bharat Petroleum", "Refining & Marketing"),
        ("IOC", "Indian Oil Corporation", "Refining & Marketing"),
        ("GAIL", "GAIL (India)", "Gas Distribution"),
        ("TATAPOWER", "Tata Power", "Power Generation"),
    ],
    "Telecommunication": [
        ("BHARTIHEXA", "Bharti Hexacom", "Telecom Services"),
        ("IDEA", "Vodafone Idea", "Telecom Services"),
        ("INDUSTOWER", "Indus Towers", "Telecom Infrastructure"),
        ("TATACOMM", "Tata Communications", "Telecom Services"),
    ],
    "Fast Moving Consumer Goods": [
        ("NESTLEIND", "Nestle India", "Food & Beverages"),
        ("BRITANNIA", "Britannia Industries", "Food & Beverages"),
        ("DABUR", "Dabur India", "Household & Personal Products"),
        ("GODREJCP", "Godrej Consumer Products", "Household & Personal Products"),
        ("MARICO", "Marico", "Household & Personal Products"),
        ("TATACONSUM", "Tata Consumer Products", "Food & Beverages"),
    ],
    "Construction": [
        ("ULTRACEMCO", "UltraTech Cement", "Cement"),
        ("GRASIM", "Grasim Industries", "Cement & Diversified"),
        ("SHREECEM", "Shree Cement", "Cement"),
        ("AMBUJACEM", "Ambuja Cements", "Cement"),
    ],
    "Automobile": [
        ("MARUTI", "Maruti Suzuki", "Passenger Vehicles"),
        ("TATAMOTORS", "Tata Motors", "Passenger & Commercial Vehicles"),
        ("M&M", "Mahindra & Mahindra", "Passenger & Commercial Vehicles"),
        ("HEROMOTOCO", "Hero MotoCorp", "Two Wheelers"),
        ("EICHERMOT", "Eicher Motors", "Two Wheelers"),
        ("BAJAJ-AUTO", "Bajaj Auto", "Two & Three Wheelers"),
    ],
    "Pharmaceuticals": [
        ("SUNPHARMA", "Sun Pharmaceutical", "Pharmaceuticals"),
        ("DRREDDY", "Dr. Reddy's Laboratories", "Pharmaceuticals"),
        ("CIPLA", "Cipla", "Pharmaceuticals"),
        ("DIVISLAB", "Divi's Laboratories", "Pharmaceuticals"),
        ("LUPIN", "Lupin", "Pharmaceuticals"),
    ],
    "Metals & Mining": [
        ("TATASTEEL", "Tata Steel", "Steel"),
        ("JSWSTEEL", "JSW Steel", "Steel"),
        ("HINDALCO", "Hindalco Industries", "Aluminium"),
        ("VEDL", "Vedanta", "Diversified Metals"),
        ("HINDZINC", "Hindustan Zinc", "Zinc Mining"),
    ],
}


def get_sector_peer_candidates(sector: str) -> list[tuple[str, str, str]]:
    """Curated same-sector candidate (symbol, name, industry) rows."""
    return list(SECTOR_PEER_CANDIDATES.get(sector or "", []))

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
        # Provider-style ticker so legacy key-repair paths (rows stored under
        # provider tickers) keep working; not a data source — Upstox calls
        # use instrument_key.
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