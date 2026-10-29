import { describe, expect, it } from "vitest";
import { aggregateTicks, planRefresh, type FeedRow } from "./chartData";
import type { Candle } from "./types";

const c = (time: number, close = 100, volume = 10): Candle => ({
  time,
  open: 100,
  high: Math.max(100, close),
  low: Math.min(100, close),
  close,
  volume,
  oi: null,
});

describe("planRefresh", () => {
  it("updates in place when only the last bar changed or bars were added", () => {
    const shown = [c(60), c(120), c(180, 101)];
    const plan = planRefresh(shown, [c(60), c(120), c(180, 102), c(240)]);
    expect(plan.mode).toBe("tail");
    expect(plan.from).toBe(2);
    expect(plan.candles.map((x) => x.time)).toEqual([60, 120, 180, 240]);
  });

  it("keeps candles the live feed formed after the provider's last bar", () => {
    const shown = [c(60), c(120), c(180, 105)];
    const plan = planRefresh(shown, [c(60), c(120)]);
    expect(plan.candles.map((x) => x.time)).toEqual([60, 120, 180]);
    expect(plan.candles[2]!.close).toBe(105);
    expect(plan.mode).toBe("none");
  });

  it("replaces everything when an older bar was corrected", () => {
    const plan = planRefresh([c(60), c(120), c(180)], [c(60, 99), c(120), c(180)]);
    expect(plan.mode).toBe("reset");
  });
});

describe("aggregateTicks", () => {
  // 2026-10-29 10:00:00 IST in ms
  const T = Date.UTC(2026, 9, 29, 4, 30);
  it("builds OHLC and volume from consecutive cumulative volumes", () => {
    const rows: FeedRow[] = [
      [T + 100, 100, 1000],
      [T + 2100, 102, 1010],
      [T + 4900, 99, 1030],
      [T + 5200, 101, 1031],
    ];
    const out = aggregateTicks(rows, 5);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ time: T / 1000, open: 100, high: 102, low: 99, close: 99, volume: 30 });
    expect(out[1]).toMatchObject({ time: T / 1000 + 5, open: 101, close: 101, volume: 1 });
  });

  it("ignores out-of-order updates and volume resets", () => {
    const rows: FeedRow[] = [
      [T + 3000, 100, 500],
      [T + 1000, 90, 400],
      [T + 4000, 101, 100],
    ];
    const out = aggregateTicks(rows, 15);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ low: 100, high: 101, volume: 0 });
  });
});
