import type { MarketPricePoint } from '../../types/api';

/** Pure, deterministic price statistics over stored OHLCV bars.
 *
 * Everything here is computed from bars already in the backend — no network,
 * no fabrication. Windows that need more history than stored return `null`
 * so callers render an honest unavailable state instead of extrapolating.
 */

export interface PriceSnapshot {
  last: MarketPricePoint;
  prev: MarketPricePoint | null;
  dayChange: number | null;
  dayChangePct: number | null;
  change30: number | null;
  momentum90: number | null;
  storedHigh: MarketPricePoint;
  storedLow: MarketPricePoint;
  avgVolume20: number | null;
  dayRangePct: number | null;
  firstDate: string;
}

export function snapshot(prices: MarketPricePoint[]): PriceSnapshot | null {
  if (prices.length === 0) return null;
  const last = prices[prices.length - 1];
  const prev = prices.length > 1 ? prices[prices.length - 2] : null;
  const change30 =
    prices.length >= 31 ? last.close / prices[prices.length - 31].close - 1 : null;
  const momentum90 =
    prices.length >= 91 ? last.close / prices[prices.length - 91].close - 1 : null;
  let hi = prices[0];
  let lo = prices[0];
  let volSum = 0;
  const volWindow = prices.slice(-20);
  for (const p of prices) {
    if (p.high > hi.high) hi = p;
    if (p.low < lo.low) lo = p;
  }
  for (const p of volWindow) volSum += p.volume;
  return {
    last,
    prev,
    dayChange: prev ? last.close - prev.close : null,
    dayChangePct: prev && prev.close ? ((last.close - prev.close) / prev.close) * 100 : null,
    change30,
    momentum90,
    storedHigh: hi,
    storedLow: lo,
    avgVolume20: volWindow.length > 0 ? volSum / volWindow.length : null,
    dayRangePct: last.close ? ((last.high - last.low) / last.close) * 100 : null,
    firstDate: prices[0].date,
  };
}

export interface PeerQuote {
  symbol: string;
  close: number | null;
  dayChangePct: number | null;
}

/** Latest close + day change for one stored series (nulls when uncomputable). */
export function peerQuote(symbol: string, prices: MarketPricePoint[]): PeerQuote {
  if (prices.length === 0) return { symbol, close: null, dayChangePct: null };
  const last = prices[prices.length - 1];
  const prev = prices.length > 1 ? prices[prices.length - 2] : null;
  return {
    symbol,
    close: last.close,
    dayChangePct:
      prev && prev.close ? ((last.close - prev.close) / prev.close) * 100 : null,
  };
}

export const fmtPrice = (v: number): string =>
  v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const fmtInt = (v: number): string => v.toLocaleString('en-IN');

export const fmtSigned = (v: number, digits = 2): string =>
  `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}`;

export function deltaClass(v: number | null): string {
  if (v === null || v === 0) return 'delta-flat';
  return v > 0 ? 'delta-up' : 'delta-down';
}
