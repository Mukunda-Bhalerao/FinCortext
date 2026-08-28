import { useEffect, useState } from 'react';

interface HealthInfo {
  status: string;
  service: string;
  version: string;
  config: Record<string, unknown>;
}

/** Dashboard — system overview. Full data/agent cards arrive in M8. */
export default function DashboardPage() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/health')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <section className="page">
      <h2>Dashboard</h2>
      <div className="card-grid">
        <div className="card">
          <h3>Backend status</h3>
          {error && <p className="badge badge-error">ERROR — {error}</p>}
          {!error && !health && <p className="muted">Checking…</p>}
          {health && (
            <>
              <p>
                <span className="badge badge-live">{health.status.toUpperCase()}</span>{' '}
                <span className="muted">{health.service} v{health.version}</span>
              </p>
              <p className="muted">
                News API configured: {String(health.config.news_api_configured)}
              </p>
            </>
          )}
        </div>
        <div className="card">
          <h3>Implemented agents (V1)</h3>
          <ul>
            <li>Firm Analyst — deterministic fundamental scoring</li>
            <li>Industry Analyst — peer/sector comparison</li>
            <li>Sentiment Analyst — financial news sentiment</li>
          </ul>
          <p className="muted">Macro Analyst and Portfolio Agent: coming soon.</p>
        </div>
      </div>
    </section>
  );
}