import { useEffect, useState } from 'react';
import { api } from '../../services/api';

/** Cheap display-only read, cached per symbol for the session. */
const cache = new Map<string, number>();

/** Number of ingested official filings for a symbol (null = unknown/failed). */
export function useFilingsCount(symbol: string): number | null {
  const [count, setCount] = useState<number | null>(() =>
    symbol && cache.has(symbol) ? (cache.get(symbol) as number) : null,
  );

  useEffect(() => {
    if (!symbol) {
      setCount(null);
      return;
    }
    const cached = cache.get(symbol);
    if (cached !== undefined) {
      setCount(cached);
      return;
    }
    let cancelled = false;
    api.filings
      .list(symbol)
      .then((r) => {
        if (cancelled) return;
        cache.set(symbol, r.count);
        setCount(r.count);
      })
      .catch(() => {
        if (!cancelled) setCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  return count;
}
