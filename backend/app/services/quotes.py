"""Quote snapshots: REST snapshot merged with the latest streamed tick, plus freshness."""

import logging
from datetime import UTC, datetime, timedelta

from app.errors import AppError
from app.providers.base import MarketDataProvider, ProviderQuote
from app.schemas.market import Quote
from app.services.live import LiveHub
from app.services.session import SessionClock
from app.tools.quotes import change_from, classify_freshness

log = logging.getLogger(__name__)

TTL_OPEN = timedelta(seconds=5)
TTL_CLOSED = timedelta(minutes=2)
STREAM_PREFERRED = timedelta(seconds=15)


class QuoteService:
    def __init__(self, provider: MarketDataProvider, hub: LiveHub, clock: SessionClock):
        self._provider = provider
        self._hub = hub
        self._clock = clock
        self._snapshots: dict[str, tuple[ProviderQuote, datetime]] = {}

    async def get(self, keys: list[str]) -> dict[str, Quote]:
        """Quotes for ``keys``. Missing instruments are omitted; provider errors propagate
        only when no previous snapshot exists for any requested key."""
        await self._clock.refresh()
        session, _ = self._clock.state()
        now = datetime.now(UTC)
        ttl = TTL_OPEN if session == "open" else TTL_CLOSED
        due = [k for k in keys if k not in self._snapshots or now - self._snapshots[k][1] > ttl]
        if due:
            try:
                fetched = await self._provider.get_quotes(due)
                stamp = datetime.now(UTC)
                for key, q in fetched.items():
                    self._snapshots[key] = (q, stamp)
            except AppError:
                if not any(k in self._snapshots for k in keys):
                    raise
                log.info("quote refresh failed; serving previous snapshots")
        return {k: q for k in keys if (q := self._build(k, session, now)) is not None}

    def _build(self, key: str, session, now: datetime) -> Quote | None:
        snap = self._snapshots.get(key)
        live = self._hub.latest(key)
        if snap is None and live is None:
            return None
        base, fetched_at = snap if snap else (None, None)
        ltp = base.ltp if base else None
        prev_close = base.prev_close if base else None
        volume = base.volume if base else None
        avg = base.avg_price if base else None
        ltt = base.last_trade_time if base else None
        observed_at = fetched_at
        source = "upstox.rest.market-quote"
        streamed = False
        # A recent streamed tick wins even if a REST snapshot was fetched a moment later:
        # the snapshot is no fresher, and preferring it would flip the label to "polled".
        recent_stream = (
            live is not None
            and live.transport == "stream"
            and now - live.received_at < STREAM_PREFERRED
        )
        if live and (observed_at is None or live.received_at > observed_at or recent_stream):
            t = live.tick
            ltp, prev_close = t.ltp, t.prev_close or prev_close
            volume = t.volume_today or volume
            avg = t.avg_price or avg
            if t.last_trade_ms:
                ltt = datetime.fromtimestamp(t.last_trade_ms / 1000, tz=UTC)
            observed_at = live.received_at
            streamed = live.transport == "stream"
            source = "upstox.feed.v3" if streamed else "upstox.rest.market-quote (polled)"
        change, change_pct = change_from(ltp, prev_close)
        assert observed_at is not None
        return Quote(
            instrument_key=key,
            symbol=base.symbol if base else None,
            ltp=ltp,
            prev_close=prev_close,
            change=change,
            change_pct=change_pct,
            open=base.open if base else None,
            high=max(base.high, ltp)
            if base and base.high and ltp
            else (base.high if base else None),
            low=min(base.low, ltp) if base and base.low and ltp else (base.low if base else None),
            volume=volume,
            avg_price=avg,
            upper_circuit=base.upper_circuit if base else None,
            lower_circuit=base.lower_circuit if base else None,
            last_trade_time=ltt,
            source=source,
            fetched_at=observed_at,
            freshness=classify_freshness(
                has_price=ltp is not None,
                session=session,
                observed_at=observed_at,
                now=now,
                streamed=streamed,
            ),
        )
