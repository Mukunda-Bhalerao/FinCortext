// Pure helpers for chart data: merging a provider refresh into what is on screen without
// disturbing the view, and building seconds-based candles from streamed feed updates.

import type { Candle } from "./types";

export type SecondsTimeframe = "5s" | "15s" | "30s";
export const SECONDS: Record<SecondsTimeframe, number> = { "5s": 5, "15s": 15, "30s": 30 };
export const isSeconds = (tf: string): tf is SecondsTimeframe => tf in SECONDS;

const same = (a: Candle, b: Candle) =>
  a.time === b.time &&
  a.open === b.open &&
  a.high === b.high &&
  a.low === b.low &&
  a.close === b.close &&
  a.volume === b.volume;

export interface RefreshPlan {
  candles: Candle[];
  /** "none": nothing changed; "tail": update bars from `from` onwards; "reset": replace all. */
  mode: "none" | "tail" | "reset";
  from: number;
}

/**
 * Merge a provider refresh into the displayed candles. Bars the live feed has formed after the
 * provider's last bar are kept (provider candles for the current minute arrive late), and
 * when only the last bar changed or bars were appended the chart can update in place.
 */
export function planRefresh(displayed: Candle[], incoming: Candle[]): RefreshPlan {
  if (!incoming.length) return { candles: displayed, mode: displayed.length ? "none" : "reset", from: 0 };
  const lastIncoming = incoming[incoming.length - 1]!.time;
  const live = displayed.filter((c) => c.time > lastIncoming);
  const candles = live.length ? [...incoming, ...live] : incoming;
  if (!displayed.length || candles.length < displayed.length) return { candles, mode: "reset", from: 0 };
  // Everything before the displayed last bar must be unchanged for an in-place update.
  const keep = displayed.length - 1;
  for (let i = 0; i < keep; i++) {
    if (!same(candles[i]!, displayed[i]!)) return { candles, mode: "reset", from: 0 };
  }
  const tailSame = candles.length === displayed.length && same(candles[keep]!, displayed[keep]!);
  return { candles, mode: tailSame ? "none" : "tail", from: keep };
}

/** One recorded feed update: [exchange trade time ms, price, cumulative day volume]. */
export type FeedRow = [number, number, number | null];

/**
 * Seconds candles from recorded feed updates. Each update is a genuine last-trade price with
 * its exchange timestamp; volume is the change in the provider's cumulative day volume between
 * consecutive updates. Prices between updates are not known, so brief extremes can be missed.
 */
export function aggregateTicks(rows: FeedRow[], seconds: number): Candle[] {
  const out: Candle[] = [];
  let lastVol: number | null = null;
  let lastMs = -Infinity;
  for (const [ms, price, vol] of rows) {
    if (!(price > 0) || ms < lastMs) continue; // out of order: skip
    lastMs = ms;
    const delta = vol != null && lastVol != null && vol >= lastVol ? vol - lastVol : 0;
    if (vol != null) lastVol = vol;
    const t = Math.floor(ms / 1000 / seconds) * seconds;
    const cur = out[out.length - 1];
    if (cur && cur.time === t) {
      cur.high = Math.max(cur.high, price);
      cur.low = Math.min(cur.low, price);
      cur.close = price;
      cur.volume += delta;
    } else {
      out.push({ time: t, open: price, high: price, low: price, close: price, volume: delta, oi: null });
    }
  }
  return out;
}
