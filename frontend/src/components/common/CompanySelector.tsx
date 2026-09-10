import { useFinCortext } from '../../app/FinCortextContext';

interface CompanySelectorProps {
  value: string;
  onChange: (symbol: string) => void;
}

/** Company picker backed by the versioned universe config.
 *  The universe list is cached session-wide, so mounting this selector on
 *  another page never refetches it. */
export default function CompanySelector({ value, onChange }: CompanySelectorProps) {
  const { universe, universeError } = useFinCortext();

  if (universeError && !universe) {
    return <p className="error-text">Failed to load universe: {universeError}</p>;
  }

  return (
    <label className="company-selector">
      <span className="muted">Company</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {universe === null && <option value="">Loading universe…</option>}
        {universe?.map((entry) => (
          <option key={entry.symbol} value={entry.symbol}>
            {entry.symbol} — {entry.name} ({entry.sector})
          </option>
        ))}
      </select>
    </label>
  );
}
