"""Industry classification for ANY NSE symbol (no Gemini dependency).

Resolution order for a symbol:
  1. configured static universe entry with a known sector (unchanged);
  2. official NSE Nifty 500 industry list (committed CSV) — NSE's "Industry"
     becomes the peer-group key, mapped into both sector and industry fields;
  3. yfinance ``Ticker("{SYMBOL}.NS").info`` sector/industry (stocks outside
     Nifty 500; network failures skip honestly, results cached in-memory);
  4. Gemini research (existing preparation path, last resort, only if wired);
  5. otherwise honestly "Unknown" (existing UNAVAILABLE peer factors).

Peers for a classified company are the other CSV symbols sharing its NSE
Industry (cap 8, self excluded); every peer must still pass the live
Upstox/yfinance validation gate with real price history before it counts —
this module never fabricates listings.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.data.universe.universe_config import get_universe_entry

logger = get_logger("data.industry_classifier")

CSV_PATH = Path(__file__).resolve().parent / "nifty500_industry.csv"

CSV_SOURCE = "nse_nifty500_csv"
CSV_CONFIDENCE = 0.9
YFINANCE_SOURCE = "yfinance_info"
YFINANCE_CONFIDENCE = 0.7
PEER_LIMIT = 8


@dataclass
class Classification:
    """One deterministic classification result."""

    symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    source: str
    confidence: float
    isin: str | None = None
    extras: dict = field(default_factory=dict)


def _clean(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


class IndustryClassifier:
    """NSE-CSV-first industry classification with yfinance fallback."""

    def __init__(
        self,
        csv_path: str | Path | None = None,
        yfinance_fetcher=None,
    ) -> None:
        self._csv_path = Path(csv_path) if csv_path else CSV_PATH
        self._yfinance_fetcher = yfinance_fetcher or _default_yfinance_fetch
        self._rows: list[dict] | None = None
        self._by_symbol: dict[str, dict] = {}
        self._by_isin: dict[str, dict] = {}
        # In-memory cache for yfinance lookups (per process; classifications
        # are persisted separately via the research/metadata storage).
        self._yfinance_cache: dict[str, dict | None] = {}

    # -- CSV ---------------------------------------------------------------------

    def _load_rows(self) -> list[dict]:
        if self._rows is None:
            rows: list[dict] = []
            try:
                with open(self._csv_path, encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        symbol = (row.get("Symbol") or "").strip().upper()
                        if not symbol:
                            continue
                        rows.append(row)
            except OSError as exc:
                logger.warning("Nifty 500 industry CSV unreadable (%s): %s", self._csv_path, exc)
            self._rows = rows
            self._by_symbol = {}
            self._by_isin = {}
            for row in rows:
                symbol = (row.get("Symbol") or "").strip().upper()
                # Prefer EQ series rows when a symbol repeats.
                if symbol not in self._by_symbol or (row.get("Series") or "").strip().upper() == "EQ":
                    self._by_symbol[symbol] = row
                isin = (row.get("ISIN Code") or "").strip().upper()
                if isin and isin not in self._by_isin:
                    self._by_isin[isin] = row
        return self._rows

    def row_count(self) -> int:
        """Number of loaded CSV rows (0 when the file is missing)."""
        return len(self._load_rows())

    # -- classification --------------------------------------------------------------

    def classify(
        self,
        symbol: str,
        *,
        company_name: str | None = None,
        isin: str | None = None,
    ) -> Classification | None:
        """Classify one symbol; None when no structured source knows it.

        Never raises for lookup problems (missing file, network failure) —
        callers treat None as "try the next source".
        """
        sym = (symbol or "").strip().upper()
        if not sym:
            return None
        # 1. Static universe entry with a known sector (unchanged behavior).
        try:
            entry = get_universe_entry(sym)
            if entry.sector not in {"Unknown", "Dynamic"}:
                return Classification(
                    symbol=entry.symbol,
                    company_name=entry.name,
                    sector=entry.sector,
                    industry=entry.industry,
                    source="universe",
                    confidence=1.0,
                )
        except Exception:
            pass
        # 2. Official NSE Nifty 500 list (by symbol, then ISIN).
        self._load_rows()
        row = self._by_symbol.get(sym)
        if row is None and isin:
            row = self._by_isin.get((isin or "").strip().upper())
        if row is not None:
            industry = _clean(row.get("Industry"))
            if industry:
                return Classification(
                    symbol=sym,
                    company_name=_clean(row.get("Company Name")) or company_name,
                    # NSE publishes Industry only: it becomes the peer-group
                    # key in both fields so sector AND industry peer lookups
                    # group these companies together.
                    sector=industry,
                    industry=industry,
                    source=CSV_SOURCE,
                    confidence=CSV_CONFIDENCE,
                    isin=_clean(row.get("ISIN Code")),
                )
        # 3. yfinance instrument metadata (outside Nifty 500).
        info = self._cached_yfinance_info(sym)
        if info:
            sector = _clean(info.get("sector"))
            industry = _clean(info.get("industry")) or sector
            if sector:
                return Classification(
                    symbol=sym,
                    company_name=_clean(info.get("longName")) or company_name,
                    sector=sector,
                    industry=industry,
                    source=YFINANCE_SOURCE,
                    confidence=YFINANCE_CONFIDENCE,
                )
        return None

    # -- peers -------------------------------------------------------------------------

    def peers_for_industry(
        self,
        industry: str,
        *,
        exclude: set[str] | None = None,
        limit: int = PEER_LIMIT,
    ) -> list[tuple[str, str]]:
        """Other CSV symbols sharing an NSE Industry: [(symbol, name)].

        Capped, self-excluded by the caller via `exclude`. Listing reality is
        NOT verified here — every peer must still pass the live Upstox gate
        with real price history before it counts.
        """
        target = (industry or "").strip()
        if not target:
            return []
        skip = {s.upper() for s in (exclude or set())}
        out: list[tuple[str, str]] = []
        for row in self._load_rows():
            if (row.get("Industry") or "").strip() != target:
                continue
            if (row.get("Series") or "").strip().upper() not in ("", "EQ"):
                continue
            symbol = (row.get("Symbol") or "").strip().upper()
            if not symbol or symbol in skip:
                continue
            out.append((symbol, (row.get("Company Name") or "").strip() or symbol))
            if len(out) >= max(1, int(limit or PEER_LIMIT)):
                break
        return out

    # -- yfinance --------------------------------------------------------------------------

    def _cached_yfinance_info(self, symbol: str) -> dict | None:
        if symbol in self._yfinance_cache:
            return self._yfinance_cache[symbol]
        try:
            info = self._yfinance_fetcher(symbol) or {}
            info = dict(info) if isinstance(info, dict) else {}
        except Exception as exc:
            logger.info("yfinance classification skipped for %s: %s", symbol, type(exc).__name__)
            info = {}
        self._yfinance_cache[symbol] = info or None
        return self._yfinance_cache[symbol]


def _default_yfinance_fetch(symbol: str) -> dict:
    """Live yfinance instrument metadata (network; exceptions propagate to
    the cached wrapper, which converts them to an honest skip)."""
    import yfinance as yf

    return yf.Ticker(f"{symbol}.NS").info or {}
