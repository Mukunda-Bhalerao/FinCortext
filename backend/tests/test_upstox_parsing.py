from app.providers.upstox import parse_instruments, parse_quotes
from app.providers.upstox_feed import decode_feed_message
from app.providers.upstox_proto import MarketDataFeed_pb2 as pb

# Shape taken from the documented /v2/market-quote/quotes example response.
QUOTE_RESPONSE = {
    "status": "success",
    "data": {
        "NSE_EQ:NHPC": {
            "ohlc": {"open": 53.4, "high": 53.8, "low": 51.75, "close": 52.05},
            "timestamp": "2023-10-19T05:21:51.099+05:30",
            "instrument_token": "NSE_EQ|INE848E01016",
            "symbol": "NHPC",
            "last_price": 52.04999923706055,
            "volume": 24123697,
            "average_price": 52.56,
            "net_change": -1.0500000000000043,
            "lower_circuit_limit": 42.5,
            "upper_circuit_limit": 63.7,
            "last_trade_time": "1697624972130",
        },
        "NSE_EQ:EMPTY": {"instrument_token": "NSE_EQ|INE000000000", "last_price": 0},
    },
}


def test_quotes_keyed_by_instrument_key_with_previous_close():
    quotes = parse_quotes(QUOTE_RESPONSE)
    q = quotes["NSE_EQ|INE848E01016"]
    assert q.symbol == "NHPC"
    assert abs(q.prev_close - 53.1) < 1e-6  # last_price - net_change
    assert q.volume == 24123697
    assert q.last_trade_time.timestamp() == 1697624972.13
    # A zero price means no trade: reported as missing, never as 0.
    assert quotes["NSE_EQ|INE000000000"].ltp is None


def test_instrument_filter_keeps_nse_equities_and_indices_only():
    rows = [
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "instrument_key": "NSE_EQ|A",
            "trading_symbol": "A",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "SG",
            "instrument_key": "NSE_EQ|G",
            "trading_symbol": "G",
        },
        {
            "segment": "NSE_FO",
            "instrument_type": "CE",
            "instrument_key": "NSE_FO|1",
            "trading_symbol": "X",
        },
        {
            "segment": "NSE_INDEX",
            "instrument_type": "INDEX",
            "instrument_key": "NSE_INDEX|Nifty 50",
            "trading_symbol": "NIFTY",
        },
        {
            "segment": "BSE_INDEX",
            "instrument_type": "INDEX",
            "instrument_key": "BSE_INDEX|SENSEX",
            "trading_symbol": "SENSEX",
        },
        {
            "segment": "BSE_EQ",
            "instrument_type": "A",
            "instrument_key": "BSE_EQ|B",
            "trading_symbol": "B",
        },
    ]
    keys = {r.instrument_key for r in parse_instruments(rows)}
    assert keys == {"NSE_EQ|A", "NSE_INDEX|Nifty 50", "BSE_INDEX|SENSEX"}


def test_decode_full_feed_equity_index_and_market_info():
    msg = pb.FeedResponse(type=pb.live_feed, currentTs=1700000000000)
    eq = msg.feeds["NSE_EQ|INE002A01018"].fullFeed.marketFF
    eq.ltpc.ltp, eq.ltpc.cp, eq.ltpc.ltt = 2900.5, 2880.0, 1700000000123
    eq.vtt, eq.atp = 1234567, 2895.2
    bar = eq.marketOHLC.ohlc.add()
    bar.interval, bar.open, bar.high, bar.low, bar.close, bar.vol, bar.ts = (
        "1d",
        2885.0,
        2910.0,
        2870.0,
        2900.5,
        1234567,
        1699900000000,
    )
    idx = msg.feeds["NSE_INDEX|Nifty 50"].fullFeed.indexFF
    idx.ltpc.ltp, idx.ltpc.cp, idx.ltpc.ltt = 22000.25, 21900.0, 1700000000456
    msg.feeds["NSE_EQ|NOTRADE"].ltpc.ltp = 0  # no price -> skipped
    msg.marketInfo.segmentStatus["NSE_EQ"] = pb.NORMAL_OPEN

    event = decode_feed_message(msg.SerializeToString())
    ticks = {t.instrument_key: t for t in event.ticks}
    assert set(ticks) == {"NSE_EQ|INE002A01018", "NSE_INDEX|Nifty 50"}
    t = ticks["NSE_EQ|INE002A01018"]
    assert (t.ltp, t.prev_close, t.volume_today, t.last_trade_ms) == (
        2900.5,
        2880.0,
        1234567,
        1700000000123,
    )
    assert t.bars[0].interval == "1d" and t.bars[0].open == 2885.0
    assert ticks["NSE_INDEX|Nifty 50"].volume_today is None
    assert event.segment_status == {"NSE_EQ": "NORMAL_OPEN"}
    assert event.server_ms == 1700000000000
