import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useFinCortext } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { UniverseEntry, UpstoxSearchResult } from '../../types/api';

interface CompanySelectorProps {
  value: string;
  onChange: (symbol: string) => void;
  id?: string;
}

function matches(entry: UniverseEntry, q: string): boolean {
  const hay = `${entry.symbol} ${entry.name} ${entry.sector}`.toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((tok) => hay.includes(tok));
}

/** Company search: versioned universe first, Upstox NSE equities on demand.
 *
 * Typing filters the cached universe instantly; for queries with 2+ chars a
 * debounced backend search (Upstox NSE EQ) offers ANY valid Indian stock.
 * Every selection runs the central company preparation (quote, history,
 * fundamentals, news, peers) so analyst tabs find ready data instead of
 * racing ahead; the input shows "Preparing company data…" meanwhile.
 * Loading and error states are explicit; nothing is fabricated.
 */
export default function CompanySelector({ value, onChange, id }: CompanySelectorProps) {
  const { universe, universeError, mergeUniverseEntry, invalidatePrices, ensurePreparation } =
    useFinCortext();
  const [preparing, setPreparing] = useState<string | null>(null);
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [remote, setRemote] = useState<UpstoxSearchResult[] | null>(null);
  const [remoteLoading, setRemoteLoading] = useState(false);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Follow external selection changes (navigation, peer switching).
  useEffect(() => {
    setQuery(value);
    setOpen(false);
  }, [value]);

  // Close suggestions on outside click.
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery(value);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [value]);

  // Debounced Upstox search for non-empty queries not exactly matching.
  useEffect(() => {
    const q = query.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q || q.length < 2) {
      setRemote(null);
      setRemoteError(null);
      setRemoteLoading(false);
      return;
    }
    // Exact universe hit needs no remote search (avoids noise + 404s).
    const exactHit = (universe ?? []).some((e) => e.symbol.toUpperCase() === q.toUpperCase());
    if (exactHit) {
      setRemote(null);
      setRemoteError(null);
      setRemoteLoading(false);
      return;
    }
    setRemoteLoading(true);
    setRemoteError(null);
    debounceRef.current = setTimeout(() => {
      api.market
        .search(q, 12)
        .then((r) => {
          // Hide rows already in the static universe to avoid duplicates.
          const known = new Set((universe ?? []).map((e) => e.symbol));
          setRemote((r.results ?? []).filter((x) => !known.has(x.symbol)));
          setRemoteError(null);
        })
        .catch((e) => {
          setRemote(null);
          setRemoteError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => setRemoteLoading(false));
    }, 320);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, universe]);

  const suggestions = useMemo(() => {
    if (!universe) return [];
    const q = query.trim();
    if (!q || q.toUpperCase() === value.toUpperCase()) return universe;
    return universe.filter((e) => matches(e, q));
  }, [universe, query, value]);

  const runPreparation = (symbol: string) => {
    setPreparing(symbol);
    // Fire-and-forget: the preparation cache records readiness and the
    // analyst tabs render it; a failure never blocks company selection.
    ensurePreparation(symbol, true)
      .catch(() => undefined)
      .finally(() => {
        setPreparing((cur) => (cur === symbol ? null : cur));
      });
  };

  const pick = (symbol: string) => {
    setOpen(false);
    setQuery(symbol);
    if (symbol !== value) {
      runPreparation(symbol);
      onChange(symbol);
    }
  };

  const pickRemote = (row: UpstoxSearchResult) => {
    setResolving(row.symbol);
    setRemoteError(null);
    api.market
      .resolve(row.symbol, row.instrument_key)
      .then((r) => {
        const resolved = r.resolved;
        mergeUniverseEntry({
          symbol: resolved.symbol,
          name: resolved.name,
          exchange: resolved.exchange,
          ticker: resolved.ticker,
          sector: resolved.sector,
          industry: resolved.industry,
          instrument_key: resolved.instrument_key,
        });
        invalidatePrices(resolved.symbol);
        setOpen(false);
        setQuery(resolved.symbol);
        if (resolved.symbol !== value) {
          // /resolve already warmed history+quote; run the full central
          // preparation (fundamentals, news, peers) before selecting.
          setPreparing(resolved.symbol);
          ensurePreparation(resolved.symbol, true)
            .catch(() => undefined)
            .finally(() => {
              setPreparing((cur) => (cur === resolved.symbol ? null : cur));
            });
          onChange(resolved.symbol);
        }
      })
      .catch((e) => {
        setRemoteError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setResolving(null));
  };

  const onType = (next: string) => {
    setQuery(next);
    setOpen(true);
    setHighlight(0);
    // Programmatic/exact entry (tests, paste): select immediately.
    const exact = universe?.find((e) => e.symbol.toUpperCase() === next.trim().toUpperCase());
    if (exact && exact.symbol !== value) {
      pick(exact.symbol);
    }
  };

  if (universeError && !universe) {
    return <p className="error-text">Failed to load universe: {universeError}</p>;
  }

  const showRemote = (remote !== null && remote.length > 0) || remoteLoading || remoteError;
  const totalRows = Math.min(suggestions.length, 8) + (remote?.length ?? 0);

  return (
    <div className="company-search" ref={boxRef}>
      <label className="muted" htmlFor={id ?? 'company-search'}>
        Company
      </label>
      <div className="search-wrap">
        <svg className="search-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <line x1="11" y1="11" x2="14.5" y2="14.5" stroke="currentColor" strokeWidth="1.6" />
        </svg>
        <input
          id={id ?? 'company-search'}
          role="combobox"
          aria-expanded={open && totalRows > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          className="search-input"
          placeholder={
            universe ? 'Search company (e.g. TCS, RELIANCE, INFY…)' : 'Loading universe…'
          }
          value={resolving ? `Resolving ${resolving}…` : query}
          disabled={!universe || resolving !== null}
          onChange={(e) => onType(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown' && totalRows > 0) {
              e.preventDefault();
              setOpen(true);
              setHighlight((h) => (h + 1) % totalRows);
            } else if (e.key === 'ArrowUp' && totalRows > 0) {
              e.preventDefault();
              setHighlight((h) => (h - 1 + totalRows) % totalRows);
            } else if (e.key === 'Enter') {
              const local = suggestions.slice(0, 8);
              if (open && highlight < local.length && local[highlight]) {
                e.preventDefault();
                pick(local[highlight].symbol);
              } else if (open && remote && remote[highlight - local.length]) {
                e.preventDefault();
                pickRemote(remote[highlight - local.length]);
              } else if (open && (suggestions[0] ?? remote?.[0])) {
                e.preventDefault();
                const first = suggestions[0];
                if (first) pick(first.symbol);
                else if (remote?.[0]) pickRemote(remote[0]);
              }
            } else if (e.key === 'Escape') {
              setQuery(value);
              setOpen(false);
            }
          }}
        />
        {open && suggestions.length > 0 && (
          <ul className="search-results" id={listId} role="listbox" aria-label="Matching companies">
            {suggestions.slice(0, 8).map((entry, i) => (
              <li key={entry.symbol} role="option" aria-selected={entry.symbol === value}>
                <button
                  type="button"
                  className={`search-option${i === highlight ? ' highlighted' : ''}${
                    entry.symbol === value ? ' current' : ''
                  }`}
                  onMouseEnter={() => setHighlight(i)}
                  onClick={() => pick(entry.symbol)}
                >
                  <strong>{entry.symbol}</strong>
                  <span className="muted">
                    {entry.name} · {entry.sector}
                  </span>
                </button>
              </li>
            ))}
            {remote !== null && remote.length > 0 && (
              <li className="search-section" aria-hidden="true">
                <span className="muted">Upstox NSE results</span>
              </li>
            )}
            {(remote ?? []).map((row, j) => {
              const i = suggestions.slice(0, 8).length + j;
              return (
                <li key={row.instrument_key} role="option" aria-selected={row.symbol === value}>
                  <button
                    type="button"
                    className={`search-option search-option-remote${i === highlight ? ' highlighted' : ''}`}
                    onMouseEnter={() => setHighlight(i)}
                    onClick={() => pickRemote(row)}
                    disabled={resolving !== null}
                  >
                    <strong>{row.trading_symbol}</strong>
                    <span className="muted">
                      {row.name} · NSE EQ{row.isin ? ` · ${row.isin}` : ''}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {open && showRemote && suggestions.length === 0 && remote !== null && remote.length > 0 && (
          <ul className="search-results" id={`${listId}-remote`} role="listbox" aria-label="Upstox matches">
            <li className="search-section" aria-hidden="true">
              <span className="muted">Upstox NSE results</span>
            </li>
            {remote.map((row, j) => (
              <li key={row.instrument_key} role="option" aria-selected={row.symbol === value}>
                <button
                  type="button"
                  className={`search-option search-option-remote${j === highlight ? ' highlighted' : ''}`}
                  onMouseEnter={() => setHighlight(j)}
                  onClick={() => pickRemote(row)}
                  disabled={resolving !== null}
                >
                  <strong>{row.trading_symbol}</strong>
                  <span className="muted">
                    {row.name} · NSE EQ{row.isin ? ` · ${row.isin}` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {open && universe && query.trim() && suggestions.length === 0 && !remoteLoading && !remoteError && (!remote || remote.length === 0) && (
          <div className="search-empty muted">No companies match “{query.trim()}”.</div>
        )}
        {open && remoteLoading && (
          <div className="search-empty muted">Searching Upstox NSE…</div>
        )}
        {open && remoteError && (
          <div className="search-empty error-text">Upstox search failed: {remoteError}</div>
        )}
      </div>
      {preparing && (
        <div className="muted preparation-hint" role="status">
          Preparing company data for {preparing}…
        </div>
      )}
    </div>
  );
}
