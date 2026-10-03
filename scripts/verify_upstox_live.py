"""One-off Phase 0/1 verification: Upstox reachability for quotes + history.

Checks that Upstox serves (a) a live quote and (b) historical daily candles
for a few canonical symbols, using only the configured Upstox token.
Never prints the token. Run from repo root:
    backend/.venv/Scripts/python.exe scripts/verify_upstox_live.py
"""

import sys
from datetime import date, timedelta

sys.path.insert(0, "backend")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.core.config import settings  # noqa: E402
from app.data.providers.market.upstox_client import UpstoxHttpClient  # noqa: E402
from app.data.providers.market.upstox_provider import UpstoxMarketProvider  # noqa: E402

SYMBOLS = ["TCS", "RELIANCE", "INFY", "HDFCBANK"]


def main() -> int:
    if not settings.upstox_access_token:
        print("UPSTOX_ACCESS_TOKEN not configured -> cannot verify live reachability")
        return 2

    client = UpstoxHttpClient(
        settings.upstox_access_token,
        base_url=settings.upstox_base_url,
        timeout_seconds=settings.upstox_timeout_seconds,
    )
    provider = UpstoxMarketProvider(
        settings.upstox_access_token,
        base_url=settings.upstox_base_url,
        timeout_seconds=settings.upstox_timeout_seconds,
    )

    ok = 0
    end = date.today()
    start = end - timedelta(days=30)
    for sym in SYMBOLS:
        try:
            quote = provider.fetch_quote_for_symbol(sym)
            key = quote.get("instrument_key") or ""
            lp = quote.get("last_price")
            yh = quote.get("year_high")
            yl = quote.get("year_low")
            vol = quote.get("volume")
            candles = client.fetch_daily_candles(key, start, end)
            print(
                f"OK   {sym}: last={lp} year_high={yh} year_low={yl} vol={vol} "
                f"candles_30d={len(candles)} key={key}"
            )
            ok += 1
        except Exception as exc:
            name = type(exc).__name__
            msg = getattr(exc, "message", "") or str(exc)
            print(f"FAIL {sym}: {name}: {msg[:200]}")
    print(f"\n{ok}/{len(SYMBOLS)} symbols verified via Upstox only")
    return 0 if ok >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
