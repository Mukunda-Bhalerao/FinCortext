from datetime import UTC, datetime, timedelta

from app.services.auth import expected_expiry
from app.tools.candles import merge_candles, parse_candle_rows, parse_timestamp, trailing_range
from app.tools.market_hours import scheduled_state, state_from_feed
from app.tools.quotes import change_from, classify_freshness


def ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5, minutes=30)


def test_timestamp_iso_with_ist_offset_becomes_utc():
    assert parse_timestamp("2025-01-02T09:15:00+05:30") == int(
        datetime(2025, 1, 2, 3, 45, tzinfo=UTC).timestamp()
    )
    assert parse_timestamp("1697624972130") == 1697624972
    assert parse_timestamp(1697624972130) == 1697624972


def test_candles_sorted_deduplicated_and_invalid_rows_dropped():
    rows = [
        ["2025-01-02T09:16:00+05:30", 101, 102, 100, 101.5, 900, 0],
        ["2025-01-02T09:15:00+05:30", 100, 101, 99, 100.5, 1200, 0],
        ["2025-01-02T09:15:00+05:30", 100, 101, 99, 100.7, 1300, 0],  # duplicate ts, later wins
        ["2025-01-02T09:17:00+05:30", 0, 0, 0, 0, 0, 0],  # zero prices
        ["2025-01-02T09:18:00+05:30", 100, 99, 101, 100, 5, 0],  # high < low
        ["short"],
    ]
    candles = parse_candle_rows(rows)
    assert [c.close for c in candles] == [100.7, 101.5]
    assert candles[0].time < candles[1].time
    assert candles[0].volume == 1300


def test_merge_prefers_current_session():
    hist = parse_candle_rows([["2025-01-02T00:00:00+05:30", 1, 2, 1, 2, 10, 0]])
    cur = parse_candle_rows(
        [
            ["2025-01-02T00:00:00+05:30", 1, 3, 1, 3, 20, 0],
            ["2025-01-03T00:00:00+05:30", 3, 4, 3, 4, 5, 0],
        ]
    )
    merged = merge_candles(hist, cur)
    assert [c.close for c in merged] == [3, 4]


def test_trailing_range_uses_only_window():
    now = datetime(2025, 6, 1, tzinfo=UTC)
    old = (now - timedelta(days=400)).isoformat()
    recent = (now - timedelta(days=10)).isoformat()
    candles = parse_candle_rows([[old, 50, 500, 40, 60, 1, 0], [recent, 100, 120, 90, 110, 1, 0]])
    assert trailing_range(candles, now) == (120, 90)
    assert trailing_range([], now) is None


def test_change_from_previous_close():
    change, pct = change_from(110.0, 100.0)
    assert change == 10.0 and abs(pct - 10.0) < 1e-9
    assert change_from(None, 100.0) == (None, None)
    assert change_from(100.0, 0) == (None, None)


def test_scheduled_session_boundaries():
    assert scheduled_state(ist(2025, 1, 6, 9, 14)) == "pre_open"  # Monday
    assert scheduled_state(ist(2025, 1, 6, 9, 15)) == "open"
    assert scheduled_state(ist(2025, 1, 6, 15, 29)) == "open"
    assert scheduled_state(ist(2025, 1, 6, 15, 30)) == "closed"
    assert scheduled_state(ist(2025, 1, 4, 11, 0)) == "closed"  # Saturday
    assert state_from_feed("NORMAL_OPEN") == "open"
    assert state_from_feed("NORMAL_CLOSE") == "closed"
    assert state_from_feed("SOMETHING_NEW") is None


def test_freshness_classification():
    now = datetime(2025, 1, 6, 6, 0, tzinfo=UTC)
    kw = dict(has_price=True, observed_at=now - timedelta(seconds=5), now=now)
    assert classify_freshness(session="open", streamed=True, **kw) == "live"
    assert classify_freshness(session="open", streamed=False, **kw) == "delayed"
    assert classify_freshness(session="closed", streamed=True, **kw) == "last_close"
    old = dict(kw, observed_at=now - timedelta(minutes=5))
    assert classify_freshness(session="open", streamed=True, **old) == "stale"
    assert (
        classify_freshness(has_price=False, session="open", observed_at=now, now=now, streamed=True)
        == "unavailable"
    )


def test_token_expiry_is_next_0330_ist():
    assert expected_expiry(ist(2025, 1, 6, 10, 0)) == ist(2025, 1, 7, 3, 30)
    assert expected_expiry(ist(2025, 1, 6, 2, 0)) == ist(2025, 1, 6, 3, 30)
