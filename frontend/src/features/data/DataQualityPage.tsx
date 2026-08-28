import { useEffect, useState } from 'react';
import StatusBadge from '../../components/common/StatusBadge';
import { api } from '../../services/api';
import type { MarketStatusResponse } from '../../types/api';

/** Data Quality / Status — per-symbol storage state, honestly labeled. */
export default function DataQualityPage() {
  const [status, setStatus] = useState<MarketStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.market
      .status()
      .then(setStatus)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <section className="page">
      <h2>Data Quality / Status</h2>
      <p className="muted page-description">
        Storage state per universe symbol. CACHED means stored history exists;
        UNAVAILABLE means nothing stored yet — refresh from the Market Data
        page (network required).
      </p>

      {error && <p className="error-text">Backend error: {error}</p>}
      {!status && !error && <p className="muted">Loading…</p>}

      {status && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th>Stored bars</th>
              <th>Latest trade date</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {status.symbols.map((row) => (
              <tr key={row.symbol}>
                <td>{row.symbol}</td>
                <td>{row.name}</td>
                <td>{row.rows}</td>
                <td>{row.latest_trade_date ?? '—'}</td>
                <td>
                  <StatusBadge status={row.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}