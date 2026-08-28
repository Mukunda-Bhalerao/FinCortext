import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import StatusBadge from '../../components/common/StatusBadge';
import { api } from '../../services/api';
import type { HealthInfo, MarketStatusResponse, NewsStatusResponse } from '../../types/api';

/** Dashboard — system overview with honest data status. */
export default function DashboardPage() {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [market, setMarket] = useState<MarketStatusResponse | null>(null);
  const [news, setNews] = useState<NewsStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
    api.market
      .status()
      .then(setMarket)
      .catch(() => setMarket(null));
    api.news
      .status()
      .then(setNews)
      .catch(() => setNews(null));
  }, []);

  const symbolsWithPrices = market?.symbols.filter((s) => s.rows > 0).length ?? 0;

  return (
    <section className="page">
      <h2>Dashboard</h2>
      <p className="muted page-description">
        Research platform status. Only implemented modules are shown as
        functional; future modules are explicit placeholders.
      </p>

      {error && <p className="error-text">Backend unreachable: {error}</p>}

      <div className="card-grid">
        <div className="card">
          <h3>Backend</h3>
          {health ? (
            <>
              <p>
                <span className="badge badge-live">{health.status.toUpperCase()}</span>{' '}
                <span className="muted">
                  {health.service} v{health.version}
                </span>
              </p>
              <p className="muted">DB: {health.config.db_path}</p>
            </>
          ) : (
            !error && <p className="muted">Checking…</p>
          )}
        </div>

        <div className="card">
          <h3>Market data coverage</h3>
          {market ? (
            <>
              <p>
                <strong>
                  {symbolsWithPrices}/{market.symbols.length}
                </strong>{' '}
                <span className="muted">universe symbols with stored prices</span>
              </p>
              <p className="muted">
                Refresh per symbol from{' '}
                <Link to="/data/market">Data → Market Data</Link> (network
                required).
              </p>
            </>
          ) : (
            <p className="muted">Unavailable (backend offline?).</p>
          )}
        </div>

        <div className="card">
          <h3>News provider</h3>
          {news ? (
            <>
              <p>
                <StatusBadge status={news.configured ? 'LIVE' : 'UNAVAILABLE'} />
              </p>
              <p className="muted">{news.message ?? 'NEWS_API_KEY configured.'}</p>
            </>
          ) : (
            <p className="muted">Status unknown.</p>
          )}
        </div>

        <div className="card">
          <h3>Implemented agents</h3>
          <ul>
            <li>
              <Link to="/intelligence/firm">Firm Analyst</Link> — fundamentals + momentum
            </li>
            <li>
              <Link to="/intelligence/industry">Industry Analyst</Link> — peer/sector comparison
            </li>
            <li>
              <Link to="/intelligence/sentiment">Sentiment Analyst</Link> — FinBERT news sentiment
            </li>
          </ul>
          <p className="muted">
            <Link to="/intelligence/summary">Combined intelligence summary →</Link>
          </p>
        </div>

        <div className="card">
          <h3>Coming soon (placeholders)</h3>
          <ul className="muted">
            <li>Macro Analyst</li>
            <li>Portfolio Agent / Risk & Constraints / Optimization</li>
            <li>Backtesting · Performance · Experiments</li>
          </ul>
          <p className="muted">
            These modules are not implemented and never pretend to be.
          </p>
        </div>
      </div>
    </section>
  );
}