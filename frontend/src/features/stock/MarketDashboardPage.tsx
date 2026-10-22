import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext, sameSymbol } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { MarketDashboardData, MarketIndex, MoverRow } from '../../types/api';

const AGENT_LABELS: Record<string, string> = {
  firm_analyst: 'Firm Analyst',
  industry_analyst: 'Industry Analyst',
  sentiment_analyst: 'Sentiment Analyst',
};

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function fmtChange(value: number | null | undefined): string {
  if (value === null || value === undefined) return '';
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}

function deltaClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return 'delta-flat';
  return value > 0 ? 'delta-up' : 'delta-down';
}

/** Pure-SVG sparkline for index closes (no chart dependency; real data only). */
function Sparkline({ points, width = 320, height = 72 }: { points: { date: string; close: number }[]; width?: number; height?: number }) {
  if (!points || points.length < 2) {
    return <div className="dash-empty muted" style={{ height }}>Not enough index history to draw a trend yet.</div>;
  }
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const stepX = width / (points.length - 1);
  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(1)},${(height - 6 - ((p.close - min) / span) * (height - 12)).toFixed(1)}`)
    .join(' ');
  const up = closes[closes.length - 1] >= closes[0];
  return (
    <svg width={width} height={height} role="img" aria-label="Index trend (daily closes)" className="sparkline">
      <path d={path} fill="none" stroke={up ? 'var(--positive)' : 'var(--negative)'} strokeWidth="1.8" />
    </svg>
  );
}

function IndexCard({ index }: { index: MarketIndex }) {
  return (
    <div className={`card index-card-live fade-in`}>
      <div className="index-card-head">
        <span className="index-name">{index.name}</span>
        <StatusBadge status={index.status} />
      </div>
      <div className="index-value-row">
        <span className="index-value">
          {index.value === null ? 'N/A' : index.value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
        </span>
        <span className={`index-change ${deltaClass(index.day_change_pct)}`}>
          {index.day_change === null ? '' : `${fmtChange(index.day_change)} (${fmtPct(index.day_change_pct)})`}
        </span>
      </div>
      {index.chart !== null && <Sparkline points={index.chart} />}
      {index.status === 'UNAVAILABLE' && (
        <p className="muted">No live index data available right now — nothing is shown until the provider responds.</p>
      )}
    </div>
  );
}

function MoverTable({
  title,
  rows,
  onSelect,
  emptyNote,
}: {
  title: string;
  rows: MoverRow[];
  onSelect: (symbol: string) => void;
  emptyNote: string;
}) {
  return (
    <div>
      <div className="dash-heading">
        <h3>{title}</h3>
      </div>
      {rows.length === 0 ? (
        <p className="muted dash-empty">{emptyNote}</p>
      ) : (
        <ul className="mover-list">
          {rows.map((r) => (
            <li key={r.symbol}>
              <button className="mover-row" onClick={() => onSelect(r.symbol)}>
                <span className="mover-symbol">{r.symbol}</span>
                <span className="muted mover-name">{r.name}</span>
                <span className="mover-price">{r.last_price === null ? 'N/A' : `₹${r.last_price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`}</span>
                <span className={`mover-change ${deltaClass(r.day_change_pct)}`}>
                  {fmtChange(r.day_change)} ({fmtPct(r.day_change_pct)})
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Market Dashboard (home) — Indian market overview from real Upstox data:
 *  index movements, gainers/losers among tracked companies, and research
 *  opportunities backed by stored analyst outputs. Nothing is fabricated;
 *  unavailable sections say so. */
export default function MarketDashboardPage() {
  const { symbol, setSymbol } = useFinCortext();
  const navigate = useNavigate();
  const [data, setData] = useState<MarketDashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .dashboard()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setLoading(false);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const indices = useMemo(() => data?.indices.items ?? [], [data]);
  const gainers = useMemo(() => data?.movers.gainers ?? [], [data]);
  const losers = useMemo(() => data?.movers.losers ?? [], [data]);
  const opportunities = useMemo(() => data?.opportunities.items ?? [], [data]);

  const select = (next: string) => {
    if (sameSymbol(next, symbol)) return;
    setSymbol(next);
    navigate(`/stock/overview?symbol=${encodeURIComponent(next)}`);
  };

  return (
    <section className="page market-dashboard">
      <header className="dash-title-row fade-in">
        <div>
          <h2>Market Dashboard</h2>
          <p className="muted page-description">
            Indian market overview — index movements, tracked-company movers and
            research opportunities from stored analyst runs. Real market data only.
          </p>
        </div>
        {data && <span className="muted">Updated {new Date(data.as_of).toLocaleTimeString('en-IN')}</span>}
      </header>

      {/* Search entry point */}
      <div className="card dash-search fade-in" style={{ animationDelay: '0.02s' }}>
        <div className="dash-search-inner">
          <span className="muted dash-search-label">Search any NSE stock</span>
          <CompanySelector value={symbol} onChange={(s) => navigate(`/stock/overview?symbol=${encodeURIComponent(s)}`)} />
        </div>
      </div>

      {loading && (
        <div className="card fade-in">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line" style={{ width: '70%' }} />
        </div>
      )}

      {error && !loading && (
        <div className="card fade-in">
          <div className="dash-empty">
            <p><StatusBadge status="ERROR" /></p>
            <p className="muted">{error} — the market overview will appear when the backend responds.</p>
          </div>
        </div>
      )}

      {data && !loading && (
        <>
          {/* Indices */}
          <div className="index-grid">
            {indices.map((i) => (
              <IndexCard key={i.key} index={i} />
            ))}
          </div>

          {/* Movers — real quotes for tracked companies only */}
          <div className="card fade-in" style={{ animationDelay: '0.06s' }}>
            <div className="dash-heading">
              <h3>Market Movers</h3>
              {data.movers.status === 'LIVE' ? (
                <StatusBadge status="LIVE" />
              ) : (
                <StatusBadge status={data.movers.status} />
              )}
            </div>
            <p className="muted dash-section-note">
              Day movement among the {data.movers.tracked} tracked companies with live quotes
              {data.movers.quoted > 0 ? ` (${data.movers.quoted} quoted just now)` : ''} — not a whole-market ranking.
            </p>
            {data.movers.status === 'UNAVAILABLE' || data.movers.status === 'ERROR' ? (
              <div className="dash-empty">
                <p className="muted">
                  Live quotes are unavailable right now — movers are never estimated, so this
                  section stays empty until the provider responds.
                </p>
              </div>
            ) : (
              <div className="mover-grid">
                <MoverTable
                  title="Top Gainers"
                  rows={gainers}
                  onSelect={select}
                  emptyNote="No tracked company is currently up — nothing is shown without a real quote."
                />
                <MoverTable
                  title="Top Losers"
                  rows={losers}
                  onSelect={select}
                  emptyNote="No tracked company is currently down — nothing is shown without a real quote."
                />
              </div>
            )}
          </div>

          {/* Research opportunities — stored analyst outputs only */}
          <div className="card fade-in" style={{ animationDelay: '0.1s' }}>
            <div className="dash-heading">
              <h3>Research Opportunities</h3>
              <StatusBadge status={data.opportunities.status} />
            </div>
            <p className="muted dash-section-note">
              Ranked by the latest stored analyst score — every entry traces back to a real
              stored analyst run. Confidence reflects data coverage; nothing here is a
              guaranteed outcome.
            </p>
            {opportunities.length === 0 ? (
              <div className="dash-empty">
                <p className="muted">
                  No stored analyst results yet — run an analyst on any stock and its
                  evidence-based view will appear here.
                </p>
              </div>
            ) : (
              <ul className="opportunity-list">
                {opportunities.map((o) => (
                  <li key={`${o.symbol}-${o.agent_id}`}>
                    <button className="opportunity-row" onClick={() => select(o.symbol)}>
                      <span className="mover-symbol">{o.symbol}</span>
                      <span className="muted mover-name">{o.name}</span>
                      <span className={`summary-card-score ${o.score !== null && o.score >= 55 ? 'pos' : o.score !== null && o.score <= 45 ? 'neg' : ''}`}>
                        {o.score === null ? '—' : `${Math.round(o.score)}/100`}
                      </span>
                      <span className="muted">{AGENT_LABELS[o.agent_id] ?? o.agent_id}</span>
                      <span className="opportunity-rationale muted">{o.rationale}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
