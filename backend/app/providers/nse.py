"""NSE public index constituent lists (CSV files published on nsearchives.nseindia.com)."""

import csv
import io
from dataclasses import dataclass

import httpx

from app.errors import ProviderUnavailable

CONSTITUENT_FILES = {
    "NIFTY 50": "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
}
_HEADERS = {"User-Agent": "Mozilla/5.0 (FinCortext research client)", "Accept": "text/csv"}


@dataclass(frozen=True)
class Constituent:
    symbol: str
    isin: str
    company: str
    industry: str | None


def parse_constituents(text: str) -> list[Constituent]:
    rows = csv.DictReader(io.StringIO(text))
    out = []
    for r in rows:
        isin = (r.get("ISIN Code") or "").strip()
        symbol = (r.get("Symbol") or "").strip()
        if isin and symbol:
            out.append(
                Constituent(
                    symbol=symbol,
                    isin=isin,
                    company=(r.get("Company Name") or "").strip(),
                    industry=(r.get("Industry") or "").strip() or None,
                )
            )
    return out


async def fetch_constituents(index_name: str) -> list[Constituent]:
    url = CONSTITUENT_FILES[index_name]
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(
            f"Could not download {index_name} constituents from NSE."
        ) from exc
    return parse_constituents(resp.text)
