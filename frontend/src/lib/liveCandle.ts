// Applies a verified live tick to the last candle of a series.
// Rules:
// - Intraday timeframes: a tick inside the last candle's window updates high/low/close;
//   a tick in a later window starts a new candle at the window boundary (anchored on the
//   last provider candle so session alignment such as 09:15 for hourly bars is preserved).
//   Volume is accumulated from deltas of the provider's cumulative day volume.
// - 1D: same IST day updates high/low/close and sets volume to the day volume.
//   A new day candle is created only when the feed supplies the day's OHLC bar.
// - 1W / 1M: only the current candle is updated; new periods come from the next refetch.

import type { Candle, ChartTimeframe, Tick } from "./types";

const IST_OFFSET = 19800;
const BUCKET: Partial<Record<ChartTimeframe, number>> = {
  "5s": 5,
  "15s": 15,
  "30s": 30,
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1H": 3600,
};

export interface LiveCandleState {
  lastVolume: number | null;
}

const istDay = (unix: number) => Math.floor((unix + IST_OFFSET) / 86400);

function istMonth(unix: number): number {
  const d = new Date((unix + IST_OFFSET) * 1000);
  return d.getUTCFullYear() * 12 + d.getUTCMonth();
}

/** Returns the candle to upsert (same `time` as last = update), or null to ignore the tick. */
export function applyTick(
  last: Candle | undefined,
  tick: Tick,
  timeframe: ChartTimeframe,
  state: LiveCandleState,
): Candle | null {
  if (!tick.last_trade_ms || !(tick.ltp > 0)) return null;
  const t = Math.floor(tick.last_trade_ms / 1000);
  if (!last) {
    // Only seconds candles may start from nothing: they have no provider history to anchor on.
    const sec = BUCKET[timeframe];
    if (!sec || sec >= 60) return null;
    if (tick.volume != null) state.lastVolume = tick.volume;
    const start = Math.floor(t / sec) * sec;
    const p = tick.ltp;
    return { time: start, open: p, high: p, low: p, close: p, volume: 0, oi: null };
  }
  if (t < last.time) return null;
  const price = tick.ltp;

  const volumeDelta =
    tick.volume != null && state.lastVolume != null && tick.volume >= state.lastVolume
      ? tick.volume - state.lastVolume
      : 0;
  if (tick.volume != null) state.lastVolume = tick.volume;

  const bucket = BUCKET[timeframe];
  if (bucket) {
    if (t < last.time + bucket) {
      return {
        ...last,
        high: Math.max(last.high, price),
        low: Math.min(last.low, price),
        close: price,
        volume: last.volume + volumeDelta,
      };
    }
    // Seconds buckets align to the clock; minute and hour buckets follow the provider's last
    // candle so session alignment (09:15 for hourly bars) is preserved.
    const start =
      bucket < 60 ? Math.floor(t / bucket) * bucket : last.time + Math.floor((t - last.time) / bucket) * bucket;
    return { time: start, open: price, high: price, low: price, close: price, volume: volumeDelta, oi: null };
  }

  if (timeframe === "1D") {
    if (istDay(t) === istDay(last.time)) {
      return {
        ...last,
        high: Math.max(last.high, price),
        low: Math.min(last.low, price),
        close: price,
        volume: tick.volume ?? last.volume,
      };
    }
    const day = tick.bars.find((b) => b.interval === "1d");
    if (day && istDay(Math.floor(day.start_ms / 1000)) === istDay(t)) {
      return {
        time: Math.floor(day.start_ms / 1000),
        open: day.open,
        high: Math.max(day.high, price),
        low: Math.min(day.low, price),
        close: price,
        volume: tick.volume ?? day.volume,
        oi: null,
      };
    }
    return null;
  }

  const sameWeek = timeframe === "1W" && t < last.time + 7 * 86400;
  const sameMonth = timeframe === "1M" && istMonth(t) === istMonth(last.time);
  if (sameWeek || sameMonth) {
    return { ...last, high: Math.max(last.high, price), low: Math.min(last.low, price), close: price };
  }
  return null;
}
