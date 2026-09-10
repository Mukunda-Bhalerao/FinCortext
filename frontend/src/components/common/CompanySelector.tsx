import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useFinCortext } from '../../app/FinCortextContext';
import type { UniverseEntry } from '../../types/api';

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

/** Company search backed by the versioned universe config.
 *
 * Looks like the terminal search box (placeholder hints at symbols), behaves
 * like a combobox: typing filters, Enter picks the top match, Escape resets.
 * The universe list is cached session-wide, so mounting this on another page
 * never refetches it.
 */
export default function CompanySelector({ value, onChange, id }: CompanySelectorProps) {
  const { universe, universeError } = useFinCortext();
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const listId = useId();

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

  const suggestions = useMemo(() => {
    if (!universe) return [];
    const q = query.trim();
    if (!q || q.toUpperCase() === value.toUpperCase()) return universe;
    return universe.filter((e) => matches(e, q));
  }, [universe, query, value]);

  const pick = (symbol: string) => {
    setOpen(false);
    setQuery(symbol);
    if (symbol !== value) onChange(symbol);
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
          aria-expanded={open && suggestions.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          className="search-input"
          placeholder={
            universe ? 'Search company (e.g. TCS, RELIANCE, INFY…)' : 'Loading universe…'
          }
          value={query}
          disabled={!universe}
          onChange={(e) => onType(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown' && suggestions.length > 0) {
              e.preventDefault();
              setOpen(true);
              setHighlight((h) => (h + 1) % suggestions.length);
            } else if (e.key === 'ArrowUp' && suggestions.length > 0) {
              e.preventDefault();
              setHighlight((h) => (h - 1 + suggestions.length) % suggestions.length);
            } else if (e.key === 'Enter') {
              const target = suggestions[highlight] ?? suggestions[0];
              if (open && target) {
                e.preventDefault();
                pick(target.symbol);
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
          </ul>
        )}
        {open && universe && query.trim() && suggestions.length === 0 && (
          <div className="search-empty muted">No companies match “{query.trim()}”.</div>
        )}
      </div>
    </div>
  );
}
