"""Refresh the committed NSE Nifty 500 industry list.

Downloads https://archives.nseindia.com/content/indices/ind_nifty500list.csv
with a browser User-Agent (NSE blocks bare requests), validates the expected
columns (Company Name, Industry, Symbol, Series, ISIN Code), and writes it to
backend/app/data/universe/nifty500_industry.csv so the demo works offline.

Usage (repo root):
    python scripts/refresh_industry_universe.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from urllib.request import Request, urlopen

NSE_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
EXPECTED_COLUMNS = ["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT_SECONDS = 30

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "backend" / "app" / "data" / "universe" / "nifty500_industry.csv"


def main() -> int:
    print(f"Downloading {NSE_URL} ...")
    request = Request(NSE_URL, headers={"User-Agent": BROWSER_USER_AGENT})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (official NSE file)
            raw = response.read().decode("utf-8-sig")
    except Exception as exc:
        print(f"ERROR: download failed: {type(exc).__name__}: {exc}")
        return 1
    lines = raw.splitlines()
    reader = csv.DictReader(lines)
    columns = list(reader.fieldnames or [])
    missing = [c for c in EXPECTED_COLUMNS if c not in columns]
    if missing:
        print(f"ERROR: missing expected columns: {missing} (got: {columns})")
        return 1
    rows = [r for r in reader if (r.get("Symbol") or "").strip()]
    if len(rows) < 400:
        print(f"ERROR: suspiciously few rows ({len(rows)}); refusing to write.")
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(raw, encoding="utf-8")
    industries = len({r["Industry"] for r in rows})
    print(f"OK: wrote {len(rows)} rows, {industries} industries -> {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
