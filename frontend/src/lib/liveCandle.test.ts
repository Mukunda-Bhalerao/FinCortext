import { describe, expect, it } from "vitest";
import { applyTick } from "./liveCandle";
import type { Candle, Tick } from "./types";

// 2025-01-06 10:00 IST = 04:30 UTC
const T0 = Date.UTC(2025, 0, 6, 4, 30) / 1000;

const candle = (time: number, close = 100, volume = 1000): Candle => ({
  time,
  open: 100,
  high: 101,
  low: 99,
  close,
  volume,
  oi: null,
});

const tick = (unix: number, ltp: number, volume: number | null = null): Tick => ({
  type: "tick",
  key: "NSE_EQ|X",
  ltp,
  prev_close: 95,
  change: ltp - 95,
  change_pct: ((ltp - 95) / 95) * 100,
  last_trade_ms: unix * 1000,
  volume,
  avg_price: null,
  bars: [],
  transport: "stream",
  received_at: new Date(unix * 1000).toISOString(),
});

describe("applyTick", () => {
  it("updates the open intraday candle in place", () => {
    const state = { lastVolume: null };
    const next = applyTick(candle(T0), tick(T0 + 120, 102.5), "5m", state);
    expect(next).toMatchObject({ time: T0, open: 100, high: 102.5, low: 99, close: 102.5 });
  });

  it("starts a new candle at the window boundary with volume from cumulative deltas", () => {
    const state = { lastVolume: null as number | null };
    applyTick(candle(T0), tick(T0 + 10, 100, 50_000), "5m", state);
    const next = applyTick(candle(T0), tick(T0 + 610, 98, 50_400), "5m", state);
    expect(next).toMatchObject({ time: T0 + 600, open: 98, high: 98, low: 98, close: 98, volume: 400 });
  });

  it("keeps hourly windows aligned to the last provider candle (09:15 session start)", () => {
    const h915 = Date.UTC(2025, 0, 6, 3, 45) / 1000; // 09:15 IST
    const next = applyTick(candle(h915), tick(h915 + 3600 + 30, 101), "1H", { lastVolume: null });
    expect(next?.time).toBe(h915 + 3600); // 10:15 IST
  });

  it("ignores ticks older than the last candle", () => {
    expect(applyTick(candle(T0), tick(T0 - 60, 101), "1m", { lastVolume: null })).toBeNull();
  });

  it("uses day volume on the daily candle and never invents a new day without the day bar", () => {
    const day = Date.UTC(2025, 0, 5, 18, 30) / 1000; // 2025-01-06 00:00 IST
    const same = applyTick(candle(day), tick(T0, 103, 2_000_000), "1D", { lastVolume: null });
    expect(same).toMatchObject({ time: day, close: 103, high: 103, volume: 2_000_000 });
    const nextDay = applyTick(candle(day), tick(T0 + 86400, 104), "1D", { lastVolume: null });
    expect(nextDay).toBeNull();
  });

  it("only updates the current monthly candle", () => {
    const month = Date.UTC(2024, 11, 31, 18, 30) / 1000; // 2025-01-01 00:00 IST
    expect(applyTick(candle(month), tick(T0, 97), "1M", { lastVolume: null })).toMatchObject({ low: 97, close: 97 });
    const feb = Date.UTC(2025, 1, 3, 4, 30) / 1000;
    expect(applyTick(candle(month), tick(feb, 97), "1M", { lastVolume: null })).toBeNull();
  });
});
