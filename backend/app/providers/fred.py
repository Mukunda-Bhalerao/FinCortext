"""Macro time series from FRED (Federal Reserve Bank of St. Louis) public CSV downloads."""

import csv
import io
from datetime import date

import httpx

from app.errors import ProviderUnavailable

SOURCE = "FRED, Federal Reserve Bank of St. Louis"
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_HEADERS = {"User-Agent": "Mozilla/5.0 (FinCortext research client)", "Accept": "text/csv"}


def parse_series(text: str) -> list[tuple[date, float]]:
    """Rows of (observation date, value); FRED marks missing observations with '.'."""
    rows = csv.reader(io.StringIO(text))
    next(rows, None)
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            out.append((date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue
    return out


async def fetch_series(series_id: str, start: date) -> list[tuple[date, float]]:
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
            resp = await client.get(_URL, params={"id": series_id, "cosd": start.isoformat()})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"Could not download {series_id} from FRED.") from exc
    return parse_series(resp.text)
