import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { UniverseEntry } from '../../types/api';

interface CompanySelectorProps {
  value: string;
  onChange: (symbol: string) => void;
}

/** Company picker backed by the versioned universe config. */
export default function CompanySelector({ value, onChange }: CompanySelectorProps) {
  const [entries, setEntries] = useState<UniverseEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .universe()
      .then((r) => setEntries(r.entries))
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return <p className="error-text">Failed to load universe: {error}</p>;
  }

  return (
    <label className="company-selector">
      <span className="muted">Company</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {entries.length === 0 && <option value="">Loading universe…</option>}
        {entries.map((entry) => (
          <option key={entry.symbol} value={entry.symbol}>
            {entry.symbol} — {entry.name} ({entry.sector})
          </option>
        ))}
      </select>
    </label>
  );
}