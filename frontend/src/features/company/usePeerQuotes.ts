import { useEffect } from 'react';
import { useFinCortext } from '../../app/FinCortextContext';
import { peerQuote, type PeerQuote } from './priceStats';

/** Warm the shared per-symbol cache for every sector peer and derive their
 *  latest real stored quotes. `ready` is false while any peer is unfetched.
 *
 *  Derived values are computed inline (peer lists are tiny) so they can never
 *  go stale behind a memo when cached data arrives.
 */
export function usePeerQuotes(peerSymbols: string[]): {
  quotes: Record<string, PeerQuote | undefined>;
  ready: boolean;
} {
  const { pricesOf, ensurePrices } = useFinCortext();
  const key = peerSymbols.join(',');

  useEffect(() => {
    if (!key) return;
    for (const s of key.split(',')) {
      if (s) ensurePrices(s).catch(() => undefined);
    }
    // `key` intentionally collapses the symbol list to one stable dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const quotes: Record<string, PeerQuote | undefined> = {};
  let ready = true;
  for (const s of peerSymbols) {
    const srs = pricesOf(s);
    if (srs === undefined) {
      ready = false;
      continue;
    }
    if (srs !== null) quotes[s] = peerQuote(s, srs.prices);
  }
  if (peerSymbols.length === 0) ready = true;

  return { quotes, ready };
}
