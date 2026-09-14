import { useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import PeerTable from '../../components/common/PeerTable';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { deltaClass, fmtInt, fmtPrice, fmtSigned, snapshot } from './priceStats';
import { useFilingsCount } from './useFilingsCount';
import { useFundamentalsCoverage } from './useFundamentalsCoverage';
import { usePeerQuotes } from './usePeerQuotes';

const ANALYSTS = [
  { id: 'firm_analyst', label: 'Firm Analyst', to: '/intelligence/firm' },
  { id: 'industry_analyst', label: 'Industry Analyst', to: '/intelligence/industry' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst', to: '/intelligence/sentiment' },
] as const;

/** Company Analysis — company overview and the data behind the views.
 *
 * Identity, stored price statistics, data inventory (prices / news /
 * filings / analyst history) and the sector peer snapshot. Everything comes
 * from the running backend; unavailable data is labelled, never invented.
 * Interpretive scoring lives on the analyst pages, not here.
 */
export default function CompanyAnalysisPage() {
  const {
    symbol,
    setSymbol,
    entryFor,
    peersOf,
    ensurePrices,
    pricesOf,
    pricesErrorOf,
    ensureOutputs,
    outputsOf,
    ensureNews,
    newsOf,
    ensureMarketStatus,
    marketStatus,
  } = useFinCortext();
  const navigate = useNavigate();

  const series = pricesOf(symbol);
  const seriesError = pricesErrorOf(symbol);
  const seriesLoading = series === undefined && seriesError === null;
  const outputs = outputsOf(symbol);
  const news = newsOf(symbol);
  const filingsCount = useFilingsCount(symbol);
  const fundamentals = useFundamentalsCoverage(symbol);

  useEffect(() => {
    ensurePrices(symbol).catch(() => undefined);
    ensureOutputs(symbol).catch(() => undefined);
    ensureNews(symbol).catch(() => undefined);
    ensureMarketStatus().catch(() => undefined);
  }, [symbol, ensurePrices, ensureOutputs, ensureNews, ensureMarketStatus]);

  const entry = entryFor(symbol);
  const peers = peersOf(symbol);
  const { quotes, ready: quotesReady } = usePeerQuotes(peers.map((p) => p.symbol));

  const prices = series?.prices ?? [];
  const snap = useMemo(() => snapshot(prices), [prices]);

  const runsByAgent = useMemo(() => {
    const map = new Map<string, { count: number; latest: string }>();
    for (const out of outputs ?? []) {
      const cur = map.get(out.agent_id);
      if (!cur) {
        map.set(out.agent_id, { count: 1, latest: out.generated_at });
      } else {
        cur.count += 1;
        if ((out.generated_at ?? '') > (cur.latest ?? '')) cur.latest = out.generated_at;
      }
    }
    return map;
  }, [outputs]);

  const latestNewsDate = useMemo(() => {
    const dates = (news?.articles ?? [])
      .map((a) => a.published_at?.slice(0, 10))
      .filter(Boolean) as string[];
    return dates.length > 0 ? dates.sort().reverse()[0] : null;
  }, [news]);

  // Intelligence coverage, derived from actual stored outputs: a view counts
  // as available only when its latest stored result carries a real score.
  const coverage = useMemo(() => {
    const byAgent = new Map<string, { score: number | null }>();
    for (const out of [...(outputs ?? [])].sort((a, b) =>
      (b.generated_at ?? '').localeCompare(a.generated_at ?? ''),
    )) {
      if (!byAgent.has(out.agent_id)) byAgent.set(out.agent_id, out);
    }
    const available = ANALYSTS.filter((a) => byAgent.get(a.id)?.score != null);
    return { available: available.length, total: ANALYSTS.length };
  }, [outputs]);

  const go = (to: string) => navigate(`${to}?symbol=${encodeURIComponent(symbol)}`);
  const displayName = entry?.name ?? symbol;

  return (
    <section className="page company-analysis">
      <h2>Company Analysis</h2>
      <p className="muted page-description">
        Company overview and the data behind the views — what FinCortext holds for{' '}
        {displayName}, and what is missing. Select the company in the search bar above.
      </p>

      {/* Identity */}
      <header className="card company-head fade-in">
        <div className="dash-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{displayName}</div>
            <div className="term-chips">
              {entry ? (
                <>
                  <span className="chip">{entry.ticker}</span>
                  <span className="chip chip-sector">{entry.sector}</span>
                  <span className="chip">{entry.industry}</span>
                  <span className="chip">{entry.exchange}</span>
                </>
              ) : (
                <span className="muted">Not in the configured universe.</span>
              )}
            </div>
          </div>
        </div>
        <div className="term-side">
          <div className="term-price-block">
            <div className="term-price">
              {seriesLoading ? '…' : snap ? `₹${fmtPrice(snap.last.close)}` : '—'}
            </div>
            <div className={`term-change ${deltaClass(snap?.dayChange ?? null)}`}>
              {!snap || snap.dayChange === null
                ? '—'
                : `${fmtSigned(snap.dayChange)} (${fmtSigned(snap.dayChangePct ?? 0)}%)`}
            </div>
            <div className="muted term-asof">
              {series?.latest_trade_date
                ? `As of ${series.latest_trade_date} · ${series.count} stored days`
                : seriesError
                  ? 'Price history unavailable'
                  : 'Loading price history…'}
            </div>
          </div>
          <div className="term-status">{series && <StatusBadge status={series.status} />}</div>
        </div>
      </header>

      <div className="dash-grid">
        {/* Stored price statistics */}
        <section className="card fade-in" aria-label="Price statistics" style={{ animationDelay: '0.05s' }}>
          <h3>Price statistics</h3>
          <p className="muted dash-section-note">Computed from stored OHLCV history only.</p>
          {!snap ? (
            <p className="muted">
              {seriesLoading
                ? 'Loading price history…'
                : `No stored price history for ${symbol} yet.`}
            </p>
          ) : (
            <dl className="stat-list">
              <div>
                <dt className="muted">Stored range</dt>
                <dd>
                  {snap.firstDate} → {snap.last.date} ({prices.length} trading days)
                </dd>
              </div>
              <div>
                <dt className="muted">Last session O/H/L/C</dt>
                <dd>
                  {fmtPrice(snap.last.open)} / {fmtPrice(snap.last.high)} /{' '}
                  {fmtPrice(snap.last.low)} / {fmtPrice(snap.last.close)}
                </dd>
              </div>
              <div>
                <dt className="muted">Stored high / low</dt>
                <dd>
                  ₹{fmtPrice(snap.storedHigh.high)} ({snap.storedHigh.date}) / ₹
                  {fmtPrice(snap.storedLow.low)} ({snap.storedLow.date})
                </dd>
              </div>
              <div>
                <dt className="muted">Volume (last / avg 20 sessions)</dt>
                <dd>
                  {fmtInt(snap.last.volume)}
                  {snap.avgVolume20 !== null && <> / {fmtInt(Math.round(snap.avgVolume20))}</>}
                </dd>
              </div>
              <div>
                <dt className="muted">30-day change / 90-day momentum</dt>
                <dd>
                  {snap.change30 === null ? '—' : `${fmtSigned(snap.change30 * 100)}%`}
                  {' / '}
                  {snap.momentum90 === null ? '—' : `${fmtSigned(snap.momentum90 * 100)}%`}
                </dd>
              </div>
            </dl>
          )}
        </section>

        {/* Data inventory */}
        <section className="card fade-in" aria-label="Data inventory" style={{ animationDelay: '0.08s' }}>
          <h3>Data inventory</h3>
          <p className="muted dash-section-note">
            What the analysts can draw on for {symbol}.
          </p>
          <p className="coverage-line" aria-label="Intelligence coverage">
            <strong>
              Data coverage: {coverage.available}/{coverage.total} intelligence views available
            </strong>
            {filingsCount === 0 && (
              <span className="muted"> — Coverage: Partial, official filings unavailable.</span>
            )}
          </p>
          <dl className="stat-list">
            <div>
              <dt className="muted">Market prices</dt>
              <dd>
                {series ? (
                  <>
                    <StatusBadge status={series.status} /> {series.count} stored days
                    {series.latest_trade_date && <>, latest {series.latest_trade_date}</>}
                  </>
                ) : seriesLoading ? (
                  'Loading…'
                ) : (
                  'Unavailable — no stored history'
                )}
              </dd>
            </div>
            <div>
              <dt className="muted">Financial news</dt>
              <dd>
                {news ? (
                  <>
                    <StatusBadge status={news.status} /> {news.count} stored articles
                    {latestNewsDate && <>, latest {latestNewsDate}</>}
                  </>
                ) : (
                  'Loading…'
                )}
              </dd>
            </div>
            <div>
              <dt className="muted">Official filings</dt>
              <dd>
                {filingsCount === null
                  ? 'None ingested — fundamental factors will unlock when filings are added.'
                  : `${filingsCount} ingested official filing${filingsCount === 1 ? '' : 's'}.`}
              </dd>
            </div>
            <div>
              <dt className="muted">Fundamentals</dt>
              <dd>
                {fundamentals === null ? (
                  'Loading…'
                ) : fundamentals.metric_count === 0 ? (
                  'Unavailable — no fundamental metrics stored'
                ) : (
                  <>
                    {fundamentals.metric_count} metrics
                    {fundamentals.has_official && ' · official filings'}
                    {fundamentals.has_official && fundamentals.has_provider && ' + '}
                    {fundamentals.has_provider && 'provider data (Yahoo Finance)'}
                    {(() => {
                      const dated = Object.values(fundamentals.metrics)
                        .map((m) => m.period_end)
                        .filter((d): d is string => d !== null)
                        .sort();
                      return dated.length > 0 ? <>, latest period {dated[dated.length - 1]}</> : null;
                    })()}
                  </>
                )}
              </dd>
            </div>
            {ANALYSTS.map((a) => {
              const runs = runsByAgent.get(a.id);
              return (
                <div key={a.id}>
                  <dt className="muted">{a.label} runs</dt>
                  <dd>
                    {runs ? (
                      <>
                        {runs.count} stored run{runs.count === 1 ? '' : 's'}, latest{' '}
                        {new Date(runs.latest).toLocaleString()}{' '}
                        <button className="link-btn" onClick={() => go(a.to)}>
                          Open →
                        </button>
                      </>
                    ) : (
                      <>
                        None yet{' '}
                        <button className="link-btn" onClick={() => go(a.to)}>
                          Run analysis →
                        </button>
                      </>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        </section>
      </div>

      {/* Peers */}
      <section className="card fade-in" aria-label="Sector peers" style={{ animationDelay: '0.1s' }}>
        <div className="dash-heading">
          <h3>Sector peers{entry ? ` — ${entry.sector}` : ''}</h3>
        </div>
        <p className="muted dash-section-note">
          The Industry Analyst compares {symbol} against these peers. Select one to switch to it.
        </p>
        <PeerTable
          peers={peers}
          marketStatus={marketStatus}
          quotes={quotes}
          quotesLoading={!quotesReady}
          current={symbol}
          onSelect={setSymbol}
        />
      </section>

      <nav className="analysis-links fade-in" aria-label="Continue to analysis" style={{ animationDelay: '0.12s' }}>
        {ANALYSTS.map((a) => (
          <button key={a.to} className="analysis-link" onClick={() => go(a.to)}>
            <strong>{a.label} →</strong>
          </button>
        ))}
        <button className="analysis-link" onClick={() => go('/intelligence/summary')}>
          <strong>Combined Summary →</strong>
        </button>
        <button className="analysis-link" onClick={() => go('/portfolio')}>
          <strong>Portfolio Synthesis →</strong>
        </button>
      </nav>
    </section>
  );
}
