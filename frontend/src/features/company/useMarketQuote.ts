import { useEffect } from 'react';
import { useFinCortext } from '../../app/FinCortextContext';
import type { MarketQuote } from '../../types/api';

/** Live market quote for one symbol (Upstox primary, honest N/A for gaps).
 *
 * Wraps the shared per-symbol quote cache: `quote` is undefined while the
 * first fetch is in flight, null when the backend reports no data, and an
 * object otherwise. Numeric gaps inside the object stay null so callers
 * render "N/A" instead of ₹0.
 */
export function useMarketQuote(symbol: string): {
  quote: MarketQuote | null | undefined;
  error: string | null;
  loading: boolean;
} {
  const { quoteOf, quoteErrorOf, ensureQuote } = useFinCortext();

  useEffect(() => {
    if (symbol) ensureQuote(symbol).catch(() => undefined);
  }, [symbol, ensureQuote]);

  const quote = quoteOf(symbol);
  const error = quoteErrorOf(symbol);
  return { quote, error, loading: quote === undefined && error === null };
}

/** Format a nullable price: real values as ₹, genuine gaps as "N/A". */
export function fmtPriceNA(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return `₹${v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Format a nullable integer (volume): gaps as "N/A". */
export function fmtIntNA(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return Math.round(v).toLocaleString('en-IN');
}
