import type { MarketPricePoint } from '../../types/api';
import { deltaClass, peerQuote, snapshot } from './priceStats';

function bars(n: number, base = 100): MarketPricePoint[] {
  return Array.from({ length: n }, (_, i) => ({
    date: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`,
    open: base + i - 1,
    high: base + i + 2,
    low: base + i - 2,
    close: base + i,
    volume: 1000 + i,
  }));
}

describe('priceStats', () => {
  it('returns null for empty history', () => {
    expect(snapshot([])).toBeNull();
    expect(peerQuote('TCS', []).close).toBeNull();
  });

  it('computes day change and stored range from real bars', () => {
    const snap = snapshot(bars(100, 100))!;
    expect(snap.last.close).toBe(199);
    expect(snap.dayChange).toBe(1);
    expect(snap.dayChangePct).toBeCloseTo((1 / 198) * 100, 6);
    expect(snap.storedHigh.high).toBe(201);
    expect(snap.storedLow.low).toBe(98);
    expect(snap.avgVolume20).toBeCloseTo(1000 + 89.5, 6);
    expect(snap.change30).toBeCloseTo(199 / 169 - 1, 10);
    expect(snap.momentum90).toBeCloseTo(199 / 109 - 1, 10);
  });

  it('reports short windows as unavailable instead of extrapolating', () => {
    const snap = snapshot(bars(40, 100))!;
    expect(snap.change30).not.toBeNull();
    expect(snap.momentum90).toBeNull();
    const tiny = snapshot(bars(5, 100))!;
    expect(tiny.change30).toBeNull();
    expect(tiny.momentum90).toBeNull();
  });

  it('handles a single bar without crashing', () => {
    const snap = snapshot(bars(1, 50))!;
    expect(snap.dayChange).toBeNull();
    expect(snap.dayChangePct).toBeNull();
    expect(snap.last.close).toBe(50);
  });

  it('computes peer quotes honestly', () => {
    const q = peerQuote('INFY', bars(10, 200));
    expect(q.close).toBe(209);
    expect(q.dayChangePct).toBeCloseTo((1 / 208) * 100, 6);
    expect(deltaClass(1)).toBe('delta-up');
    expect(deltaClass(-0.5)).toBe('delta-down');
    expect(deltaClass(null)).toBe('delta-flat');
    expect(deltaClass(0)).toBe('delta-flat');
  });
});
