import { useEffect, useState } from 'react';
import StatusBadge from '../../components/common/StatusBadge';
import { api } from '../../services/api';
import type { HealthInfo, NewsStatusResponse } from '../../types/api';

/** Data Sources — what feeds FinCortext and how each is configured. */
export default function DataSourcesPage() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [newsStatus, setNewsStatus] = useState<NewsStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
    api.news
      .status()
      .then(setNewsStatus)
      .catch(() => setNewsStatus(null));
  }, []);

  return (
    <section className="page">
      <h2>Data Sources</h2>
      <p className="muted page-description">
        Every source is a replaceable adapter behind a provider contract. The
        platform never fabricates data and never silently substitutes sample
        data for live data.
      </p>

      {error && <p className="error-text">Backend error: {error}</p>}

      <div className="card-grid">
        <div className="card">
          <h3>Market prices — Upstox</h3>
          <p>
            <StatusBadge status="LIVE" /> <span className="muted">on refresh (network required)</span>
          </p>
          <p className="muted">
            NSE daily OHLCV + full quotes for any searched equity via the
            <code> MarketDataProvider </code> contract. Stored in DuckDB;
            validated before storage.
          </p>
        </div>

        <div className="card">
          <h3>Official filings — upload</h3>
          <p>
            <StatusBadge status="IMPORTED_OFFICIAL" /> <span className="muted">user-imported</span>
          </p>
          <p className="muted">
            CSV / XBRL / XML (full support) and PDF (limited text-extraction
            fallback — never claims reliable parsing of arbitrary reports).
            Primary truth for fundamentals.
          </p>
        </div>

        <div className="card">
          <h3>News — NewsAPI</h3>
          {newsStatus && (
            <p>
              <StatusBadge status={newsStatus.configured ? 'LIVE' : 'UNAVAILABLE'} />
            </p>
          )}
          <p className="muted">
            Key read only from <code>NEWS_API_KEY</code>. Without it, live news
            is UNAVAILABLE — stored articles remain usable and nothing is
            fabricated.
          </p>
        </div>

        <div className="card">
          <h3>Sentiment model — FinBERT (local)</h3>
          <p>
            <StatusBadge status={health ? 'LIVE' : 'UNAVAILABLE'} />{' '}
            <span className="muted">{health ? health.config.sentiment_model_id : 'checking…'}</span>
          </p>
          <p className="muted">
            Local Hugging Face model; downloads on first use. If unavailable,
            the Sentiment Analyst reports UNAVAILABLE — the backend keeps
            running.
          </p>
        </div>
      </div>
    </section>
  );
}