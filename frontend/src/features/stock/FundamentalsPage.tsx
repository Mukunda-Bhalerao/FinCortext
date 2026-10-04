import { useState } from 'react';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { useFundamentalsCoverage } from '../company/useFundamentalsCoverage';
import { api } from '../../services/api';
import type { FundamentalsMetricCoverage } from '../../types/api';

const METRIC_LABELS: Record<string, string> = {
  total_revenue: 'Total Revenue',
  net_income: 'Net Income',
  total_assets: 'Total Assets',
  total_equity: 'Total Equity',
  total_debt: 'Total Debt',
  operating_profit: 'Operating Profit',
  eps: 'Earnings per Share',
  pe_ratio: 'P/E Ratio',
  roe: 'Return on Equity',
};

function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function fmtMetricValue(value: number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined) return 'N/A';
  if (unit === 'INR' || unit === 'INR_cr') {
    const abs = Math.abs(value);
    if (abs >= 1e7) return `₹${(value / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
    return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
  }
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

/** Source badge per metric: official filings are verified, provider
 *  statements are secondary, web-researched values are the lowest tier —
 *  the distinction always survives to the UI. */
function SourceBadge({ sourceType }: { sourceType: string | null | undefined }) {
  if (sourceType === 'official_filing') return <StatusBadge status="IMPORTED_OFFICIAL" />;
  if (sourceType === 'web_research') return <StatusBadge status="WEB_RESEARCH" />;
  if (sourceType === 'legacy_import') return <StatusBadge status="UNAVAILABLE" />;
  if (sourceType === 'provider' || sourceType) return <StatusBadge status="CACHED" />;
  return <span className="muted">N/A</span>;
}

/** Fundamentals — stored figures with per-metric provenance. */
export default function FundamentalsPage() {
  const { symbol, entryFor } = useFinCortext();
  const coverage = useFundamentalsCoverage(symbol);
  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);
  const entry = entryFor(symbol);

  const metrics: [string, FundamentalsMetricCoverage][] = coverage
    ? Object.entries(coverage.metrics).sort(([a], [b]) => a.localeCompare(b))
    : [];

  const runEnrich = () => {
    setEnriching(true);
    setEnrichError(null);
    api.fundamentals
      .enrich(symbol)
      .then(() => window.location.reload())
      .catch((e: Error) => {
        setEnrichError(e.message);
        setEnriching(false);
      });
  };

  const hasOfficial = coverage?.has_official ?? false;
  const hasAny = metrics.length > 0;

  return (
    <section className="page">
      <header className="card dash-head fade-in">
        <div className="dash-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{entry?.name ?? symbol}</div>
            <div className="term-chips">
              {entry?.sector && <span className="chip chip-sector">{entry.sector}</span>}
              {entry?.industry && <span className="chip">{entry.industry}</span>}
            </div>
          </div>
        </div>
        <div className="dash-pricecol">
          <div className="muted">Stored fundamentals</div>
          <div className="term-price" style={{ fontSize: '1.4rem' }}>
            {hasAny ? `${coverage?.metric_count ?? 0} metrics` : 'None stored'}
          </div>
          {coverage && <StatusBadge status={coverage.status} />}
        </div>
      </header>

      <div className="card fade-in" style={{ animationDelay: '0.04s' }}>
        <h3>Fundamental Figures</h3>
        {coverage === null ? (
          <div className="dash-empty">
            <p><StatusBadge status="UNAVAILABLE" /></p>
            <p className="muted">Fundamentals coverage could not be loaded — nothing is shown until real data is stored.</p>
          </div>
        ) : !hasAny ? (
          <div className="dash-empty">
            <p><StatusBadge status="UNAVAILABLE" /></p>
            <p className="muted">
              {`No fundamentals stored for ${symbol} yet — ingested official filings are the primary source, or research figures from the web (labeled).`}
            </p>
            {!enriching && (
              <button className="btn" onClick={runEnrich}>
                Research figures from the web (labeled)
              </button>
            )}
            {enriching && <p className="muted">Researching… (rate-limited on the backend)</p>}
            {enrichError && <p className="error-text">{enrichError}</p>}
          </div>
        ) : (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Value</th>
                  <th>Period</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map(([metric, m]) => (
                  <tr key={metric}>
                    <td>{metricLabel(metric)}</td>
                    <td>{fmtMetricValue(m.value, m.unit)}</td>
                    <td>{m.period_end ?? 'no statement period'}</td>
                    <td><SourceBadge sourceType={m.source_type} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!hasOfficial && (
              <p className="muted dash-section-note">
                No official filings ingested for {symbol} yet — figures above come
                from {coverage.has_provider ? 'stored provider/pre-consolidation statements' : 'web research'}.
                Ingested filings are always the primary source.
              </p>
            )}
          </>
        )}
      </div>

      <div className="card fade-in" style={{ animationDelay: '0.08s' }}>
        <h3>Where these figures come from</h3>
        <ul className="stat-list">
          <li>
            <strong>Official filings</strong> — ingested annual reports
            (IMPORTED_OFFICIAL); the primary source of truth.
          </li>
          <li>
            <strong>Stored provider statements</strong> — pre-consolidation
            imports, kept usable and labeled per metric.
          </li>
          <li>
            <strong>Web-researched figures</strong> — clearly labeled, sourced,
            and rate-limited; treat with lower confidence than official filings.
          </li>
          <li>
            Missing figures are reported as missing — never estimated, never fabricated.
          </li>
        </ul>
      </div>
    </section>
  );
}
