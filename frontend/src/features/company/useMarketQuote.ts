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

/** Format an Upstox quote timestamp as Indian market time.
 *  "2026-09-28T15:30:00+05:30" -> "28 Sep 2026, 3:30 PM". Null when unparseable. */
export function fmtQuoteTime(ts: string | null | undefined): string | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'Asia/Kolkata',
    }).format(d);
  } catch {
    return null;
  }
}

/** Freshness window: a quote newer than this counts as current market data. */
export const QUOTE_FRESH_MS = 45 * 60 * 1000;

export interface Freshness {
  status: 'LIVE' | 'CACHED' | 'UNAVAILABLE';
  /** "Live as of …" when fresh, else "Last updated …" / fallback text. */
  label: string;
  source: string | null;
  /** True when the label comes from the Upstox quote timestamp itself. */
  fromQuote: boolean;
}

/** Describe market-data freshness from the newest valid observation.
 *
 * Priority: Upstox quote timestamp → stored series date. Never the server
 * startup time, never the page-load time, never manufactured. */
export function describeFreshness(
  quoteTimestamp: string | null | undefined,
  quoteSource: string | null | undefined,
  seriesDate: string | null | undefined,
  seriesSource?: string | null | undefined,
): Freshness {
  const quoteLabel = fmtQuoteTime(quoteTimestamp);
  if (quoteLabel && quoteTimestamp) {
    const age = Date.now() - new Date(quoteTimestamp).getTime();
    if (age >= 0 && age <= QUOTE_FRESH_MS) {
      return {
        status: 'LIVE',
        label: `Live as of ${quoteLabel}`,
        source: quoteSource ?? null,
        fromQuote: true,
      };
    }
    return {
      status: 'CACHED',
      label: `Last updated ${quoteLabel}`,
      source: quoteSource ?? null,
      fromQuote: true,
    };
  }
  if (seriesDate) {
    return {
      status: 'CACHED',
      label: `As of ${seriesDate}`,
      source: seriesSource ?? null,
      fromQuote: false,
    };
  }
  return { status: 'UNAVAILABLE', label: 'Market data unavailable', source: null, fromQuote: false };
}

/** Newest observation wins: the quote timestamp when present, else the series date. */
export function newestMarketTimestamp(
  quoteTimestamp: string | null | undefined,
  seriesDate: string | null | undefined,
): string | null {
  if (quoteTimestamp && fmtQuoteTime(quoteTimestamp)) return quoteTimestamp;
  return seriesDate ?? null;
}
