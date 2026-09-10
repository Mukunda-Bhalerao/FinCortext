import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { FundamentalsCoverageResponse } from '../../types/api';

/** Cheap display-only read, cached per symbol for the session. */
const cache = new Map<string, FundamentalsCoverageResponse>();

/** Latest fundamental metric coverage for a symbol (null = unknown/failed). */
export function useFundamentalsCoverage(symbol: string): FundamentalsCoverageResponse | null {
  const [coverage, setCoverage] = useState<FundamentalsCoverageResponse | null>(() =>
    symbol && cache.has(symbol) ? (cache.get(symbol) as FundamentalsCoverageResponse) : null,
  );

  useEffect(() => {
    if (!symbol) {
      setCoverage(null);
      return;
    }
    const cached = cache.get(symbol);
    if (cached !== undefined) {
      setCoverage(cached);
      return;
    }
    let cancelled = false;
    api.fundamentals
      .coverage(symbol)
      .then((r) => {
        if (cancelled) return;
        cache.set(symbol, r);
        setCoverage(r);
      })
      .catch(() => {
        if (!cancelled) setCoverage(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return coverage;
}
