import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import PeerTable from '../../components/common/PeerTable';
import StatusBadge from '../../components/common/StatusBadge';
import { MACRO_SIGNAL_CLASS } from '../../components/common/MacroOutputCard';
import { SIGNAL_CLASS } from '../../components/common/AgentOutputCard';
import { useFinCortext } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { AgentOutputSummary, MacroOutput } from '../../types/api';
import {
  deltaClass,
  fmtInt,
  fmtPrice,
  fmtSigned,
  snapshot,
} from '../company/priceStats';
import { useFilingsCount } from '../company/useFilingsCount';
import { usePeerQuotes } from '../company/usePeerQuotes';

const RANGES = [
  { label: '1M', bars: 22 },
  { label: '3M', bars: 66 },
  { label: '6M', bars: 132 },
  { label: '1Y', bars: 252 },
  { label: 'All', bars: Number.POSITIVE_INFINITY },
] as const;

const ANALYSTS = [
  { id: 'firm_analyst', label: 'Firm Analyst', to: '/intelligence/firm' },
  { id: 'industry_analyst', label: 'Industry Analyst', to: '/intelligence/industry' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst', to: '/intelligence/sentiment' },
] as const;

const TABS = [
  { label: 'Overview', target: 'dash-overview' },
  { label: 'Price Chart', target: 'dash-price' },
  { label: 'Intelligence', target: 'dash-intelligence' },
  { label: 'News', target: 'dash-news' },
  { label: 'Peers', target: 'dash-peers' },
] as const;

/** Animate a number from 0 to `target` once real data arrives (subtle, eased). */
function useCountUp(target: number | null, duration = 600): number | null {
  const [value, setValue] = useState<number | null>(null);
  useEffect(() => {
    if (target === null) {
      setValue(null);
      return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = performance.now();
    const tick = () => {
      const t = Math.min(1, (performance.now() - startedAt) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) {
        timer = setTimeout(tick, 16);
      } else {
        setValue(target);
      }
    };
    tick();
    return () => {
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [target, duration]);
  return value;
}

/** Deterministic takeaway composed ONLY from stored analyst outputs.
 *  Never invents: missing views are reported as missing. */
export function buildTakeaway(
  symbol: string,
  displayName: string,
  latest: Map<string, AgentOutputSummary>,
): { headline: string; lines: string[]; complete: boolean } {
  const present = ANALYSTS.filter((a) => latest.has(a.id));
  if (present.length === 0) {
    return {
      headline: `No analyst results stored for ${displayName} yet.`,
      lines: [
        'Run the Firm, Industry and Sentiment analysts — their stored views will be summarized here.',
      ],
      complete: false,
    };
  }
  const leaning = (id: string): 'positive' | 'negative' | 'neutral' | 'missing' => {
    const out = latest.get(id);
    if (!out || out.score === null) return 'missing';
    if (out.signal === 'strong_buy' || out.signal === 'buy') return 'positive';
    if (out.signal === 'sell' || out.signal === 'strong_sell') return 'negative';
    return 'neutral';
  };
  const pos = present.filter((a) => leaning(a.id) === 'positive').length;
  const neg = present.filter((a) => leaning(a.id) === 'negative').length;
  const partial =
    present.some((a) => (latest.get(a.id)?.status ?? '') !== 'OK') ||
    present.length < ANALYSTS.length;
  const scope =
    present.length === ANALYSTS.length
      ? 'All three analyst views are stored'
      : `${present.length} of ${ANALYSTS.length} analyst views are stored`;
  const direction =
    pos > 0 && neg === 0
      ? `${pos} lean${pos === 1 ? 's' : ''} positive`
      : neg > 0 && pos === 0
        ? `${neg} lean${neg === 1 ? 's' : ''} negative`
        : pos > 0 && neg > 0
          ? `${pos} lean${pos === 1 ? 's' : ''} positive and ${neg} lean${neg === 1 ? 's' : ''} negative`
          : 'none leans clearly positive or negative';
  const lines = present.map((a) => {
    const out = latest.get(a.id)!;
    const score = out.score === null ? 'unavailable' : `${Math.round(out.score)}/100`;
    return (
      `${a.label}: ${out.signal.replace(/_/g, ' ')} at ${score}, ` +
      `confidence ${Math.round(out.confidence * 100)}% (${out.status}).`
    );
  });
  if (partial) {
    lines.push(
      'Coverage is partial — DEGRADED or missing views rest on thin evidence. ' +
        'See the limitations on each analyst page before acting on this summary.',
    );
  }
  return {
    headline: `${scope} for ${displayName} (${symbol}); ${direction}.`,
    lines,
    complete: !partial,
  };
}

/** Compact market-wide macro indicator. Symbol-independent by design:
 *  the same stored view applies to every company, so company switching
 *  can never corrupt it. */
function MacroStrip({ onOpen }: { onOpen: () => void }) {
  const [macro, setMacro] = useState<MacroOutput | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api.macro
      .latest()
      .then((r) => {
        if (!cancelled) setMacro(r.output);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return null;
  if (macro === null) {
    return (
      <div className="macro-strip">
        <span className="muted">Macro environment — no stored view yet.</span>
        <button className="link-btn" onClick={onOpen}>
          Open Macro Analyst →
        </button>
      </div>
    );
  }
  const newestThrough =
    Object.values(macro.data_through ?? {}).sort().reverse()[0] ?? null;
  return (
    <button className="macro-strip macro-strip-live" onClick={onOpen}>
      <span className="muted">Macro Environment</span>
      <strong className={`badge ${MACRO_SIGNAL_CLASS[macro.overall_signal]}`}>
        {macro.overall_signal.toUpperCase()}
      </strong>
      <span className="muted">
        {Math.round(macro.confidence * 100)}% · {macro.status}
        {newestThrough ? ` · through ${newestThrough}` : ''}
      </span>
      <span className="link-btn">Open Macro Analyst →</span>
    </button>
  );
}

/** Dashboard — company/market overview in the terminal layout.
 *
 * All numbers come from the running backend: stored OHLCV
 * (GET /api/market/prices/{symbol}), stored analyst results
 * (GET /api/agents/outputs), stored news (GET /api/news/{symbol}) and
 * storage coverage (GET /api/market/status). Analyst scores shown here are
 * compact pointers to stored results — full calculations live on their
 * dedicated pages. Unavailable data is labelled honestly, never replaced.
 */
export default function DashboardPage() {
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
    outputsErrorOf,
    ensureNews,
    newsOf,
    newsErrorOf,
    ensureMarketStatus,
    marketStatus,
  } = useFinCortext();
  const navigate = useNavigate();

  const series = pricesOf(symbol);
  const seriesError = pricesErrorOf(symbol);
  const seriesLoading = series === undefined && seriesError === null;
  const outputs = outputsOf(symbol);
  const outputsError = outputsErrorOf(symbol);
  const outputsLoading = outputs === undefined && outputsError === null;
  const news = newsOf(symbol);
  const newsError = newsErrorOf(symbol);
  const newsLoading = news === undefined && newsError === null;

  const [rangeBars, setRangeBars] = useState<number>(Number.POSITIVE_INFINITY);
  const filingsCount = useFilingsCount(symbol);

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
  const visible = useMemo(
    () => (rangeBars === Number.POSITIVE_INFINITY ? prices : prices.slice(-rangeBars)),
    [prices, rangeBars],
  );
  const chartData = useMemo(
    () => visible.map((p) => ({ date: p.date, close: p.close, volume: p.volume })),
    [visible],
  );

  const animatedPrice = useCountUp(snap ? snap.last.close : null);
  const animatedChange = useCountUp(snap?.dayChange ?? null);

  // Rows arrive newest-first; keep the first stored result per analyst.
  const latestByAgent = useMemo(() => {
    const map = new Map<string, AgentOutputSummary>();
    const sorted = [...(outputs ?? [])].sort((a, b) =>
      (b.generated_at ?? '').localeCompare(a.generated_at ?? ''),
    );
    for (const out of sorted) {
      if (!map.has(out.agent_id)) map.set(out.agent_id, out);
    }
    return map;
  }, [outputs]);

  const coverageCount = useMemo(
    () => marketStatus?.symbols.filter((s) => s.rows > 0).length ?? null,
    [marketStatus],
  );

  const takeaway = useMemo(
    () => buildTakeaway(symbol, entry?.name ?? symbol, latestByAgent),
    [symbol, entry, latestByAgent],
  );

  const go = (to: string) => navigate(`${to}?symbol=${encodeURIComponent(symbol)}`);
  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const displayName = entry?.name ?? symbol;

  return (
    <section className="page dashboard">
      {/* Identity + price + Analyze */}
      <header id="dash-overview" className="card dash-head fade-in">
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
        <div className="dash-pricecol">
          <div className="term-price">
            {seriesLoading ? (
              <span className="skeleton skeleton-price" aria-label="Loading price" />
            ) : animatedPrice === null ? (
              '—'
            ) : (
              `₹${fmtPrice(animatedPrice)}`
            )}
          </div>
          <div className={`term-change ${deltaClass(snap?.dayChange ?? null)}`}>
            {!snap || snap.dayChange === null || animatedChange === null
              ? '—'
              : `${fmtSigned(animatedChange)} (${fmtSigned(snap.dayChangePct ?? 0)}%)`}
          </div>
          <div className="muted term-asof">
            {series?.latest_trade_date
              ? `As of ${series.latest_trade_date} · ${series.count} stored days`
              : seriesError
                ? 'Price history unavailable'
                : 'Loading price history…'}
          </div>
        </div>
        <dl className="dash-session">
          <div>
            <dt className="muted">Day High</dt>
            <dd>{snap ? `₹${fmtPrice(snap.last.high)}` : '—'}</dd>
          </div>
          <div>
            <dt className="muted">Day Low</dt>
            <dd>{snap ? `₹${fmtPrice(snap.last.low)}` : '—'}</dd>
          </div>
          <div>
            <dt className="muted">Volume</dt>
            <dd>{snap ? fmtInt(snap.last.volume) : '—'}</dd>
          </div>
        </dl>
        <button className="btn btn-primary btn-analyze" onClick={() => go('/company')}>
          ▶ Analyze Company
        </button>
      </header>

      {/* Section tabs (anchor navigation) */}
      <nav className="dash-tabs fade-in" aria-label="Dashboard sections" style={{ animationDelay: '0.04s' }}>
        {TABS.map((t) => (
          <button key={t.target} className="tab-btn" onClick={() => scrollTo(t.target)}>
            {t.label}
          </button>
        ))}
      </nav>

      <div className="dash-grid">
        {/* Price performance */}
        <section id="dash-price" className="card chart-card fade-in" aria-label="Price performance" style={{ animationDelay: '0.06s' }}>
          <div className="chart-head">
            <h3>Price Performance</h3>
            <span className="muted from-stored">◇ From Stored Data</span>
          </div>
          {seriesLoading ? (
            <div className="skeleton skeleton-chart" />
          ) : seriesError && !series ? (
            <div className="dash-empty">
              <p>
                <StatusBadge status="UNAVAILABLE" />
              </p>
              <p className="muted">
                No stored price history for {symbol} yet — nothing is shown until
                real data is collected.
              </p>
            </div>
          ) : !snap || chartData.length < 2 ? (
            <div className="dash-empty">
              <p>
                <StatusBadge status={series?.status ?? 'UNAVAILABLE'} />
              </p>
              <p className="muted">
                Not enough stored trading days for {symbol} to draw a chart yet.
              </p>
            </div>
          ) : (
            <>
              <div className="range-bar" role="group" aria-label="Chart range">
                {RANGES.map((r) => (
                  <button
                    key={r.label}
                    className={`range-btn${rangeBars === r.bars ? ' active' : ''}`}
                    onClick={() => setRangeBars(r.bars)}
                    disabled={r.bars !== Number.POSITIVE_INFINITY && prices.length <= r.bars}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={chartData} margin={{ top: 10, right: 8, bottom: 0, left: 8 }}>
                  <defs>
                    <linearGradient id="dashCloseFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#2ecc8f" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#2ecc8f" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1c2942" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="#8fa0b8"
                    fontSize={11}
                    minTickGap={48}
                    tickLine={false}
                  />
                  <YAxis
                    yAxisId="price"
                    stroke="#8fa0b8"
                    fontSize={11}
                    domain={['auto', 'auto']}
                    tickFormatter={(v: number) => v.toLocaleString('en-IN')}
                    tickLine={false}
                    width={72}
                  />
                  <YAxis yAxisId="volume" orientation="right" hide />
                  <Tooltip
                    contentStyle={{ background: '#141f36', border: '1px solid #22304d' }}
                    labelStyle={{ color: '#e6ecf5' }}
                    formatter={(value: number | string, name: string) =>
                      name === 'volume'
                        ? [fmtInt(Number(value)), 'Volume']
                        : [`₹${fmtPrice(Number(value))}`, 'Close']
                    }
                  />
                  <Bar yAxisId="volume" dataKey="volume" fill="#22304d" opacity={0.55} isAnimationActive={false} />
                  <Area
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke="#2ecc8f"
                    strokeWidth={2}
                    fill="url(#dashCloseFill)"
                    animationDuration={900}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                  <ReferenceDot x={snap.last.date} y={snap.last.close} yAxisId="price" r={4} fill="#2ecc8f" stroke="#0b1220" />
                </ComposedChart>
              </ResponsiveContainer>
              <p className="muted dash-chart-note">
                Daily closes from stored OHLCV history — showing {visible.length} of{' '}
                {series?.count} trading days
                {snap.storedHigh && (
                  <>
                    {' '}· stored high ₹{fmtPrice(snap.storedHigh.high)} ({snap.storedHigh.date}) · stored
                    low ₹{fmtPrice(snap.storedLow.low)} ({snap.storedLow.date})
                  </>
                )}
              </p>
            </>
          )}
        </section>

        {/* Market context — real sector peers only */}
        <section id="dash-peers" className="card fade-in" aria-label="Market context" style={{ animationDelay: '0.08s' }}>
          <div className="dash-heading">
            <h3>Market Context</h3>
          </div>
          <p className="muted dash-section-note">
            {entry ? `Sector · ${entry.sector}` : 'Sector unavailable'}
            {coverageCount !== null
              ? ` · ${coverageCount} of ${marketStatus?.symbols.length ?? ''} companies hold stored prices.`
              : ''}
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
      </div>

      <div className="dash-grid">
        {/* Compact intelligence overview — stored results only */}
        <section id="dash-intelligence" className="card fade-in" aria-label="FinCortext intelligence" style={{ animationDelay: '0.1s' }}>
          <div className="dash-heading">
            <h3>FinCortext Intelligence</h3>
            <button className="link-btn" onClick={() => go('/intelligence/summary')}>
              View Detailed Analysis →
            </button>
          </div>
          <p className="muted dash-section-note">
            Latest stored analyst views for {symbol} — full evidence on each analyst page.
          </p>
          {outputsLoading ? (
            <div className="intel-cards">
              <div className="skeleton intel-skeleton" />
              <div className="skeleton intel-skeleton" />
              <div className="skeleton intel-skeleton" />
            </div>
          ) : outputsError ? (
            <p className="muted">Stored results could not be loaded.</p>
          ) : (
            <div className="intel-cards">
              {ANALYSTS.map((a) => {
                const out = latestByAgent.get(a.id);
                return (
                  <button key={a.id} className="intel-card" onClick={() => go(a.to)}>
                    <span className="intel-label">{a.label}</span>
                    <strong className={out && out.score !== null ? '' : 'muted'}>
                      {out && out.score !== null ? Math.round(out.score) : '—'}
                      <span className="muted intel-den">/100</span>
                    </strong>
                    {out ? (
                      <span className="badge-row">
                        <span className={`badge ${SIGNAL_CLASS[out.signal] ?? ''}`}>
                          {out.signal.replace(/_/g, ' ').toUpperCase()}
                        </span>
                        <span className={`badge badge-status-${out.status.toLowerCase()}`}>
                          {out.status}
                        </span>
                      </span>
                    ) : (
                      <span className="muted">Not run yet</span>
                    )}
                    <span className="muted intel-conf">
                      {out ? `Confidence ${Math.round(out.confidence * 100)}%` : 'Open the analyst to run it'}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          <MacroStrip onOpen={() => go('/intelligence/macro')} />
        </section>

        {/* Recent financial news */}
        <section id="dash-news" className="card dash-news fade-in" aria-label="Recent financial news" style={{ animationDelay: '0.12s' }}>
          <div className="dash-heading">
            <h3>Recent News</h3>
            <button className="link-btn" onClick={() => go('/intelligence/sentiment')}>
              View All →
            </button>
          </div>
          {newsLoading ? (
            <div className="skeleton skeleton-line" />
          ) : news && news.articles.length > 0 ? (
            <ul className="news-list">
              {news.articles.map((a) => (
                <li key={a.article_id}>
                  {a.source_url ? (
                    <a href={a.source_url} target="_blank" rel="noreferrer" className="news-title">
                      {a.title}
                    </a>
                  ) : (
                    <span className="news-title">{a.title}</span>
                  )}
                  <span className="muted news-meta">
                    {[a.source, a.published_at?.slice(0, 10)].filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              {newsError
                ? 'Stored news could not be loaded.'
                : `No stored articles for ${symbol} yet. Use Fetch news on the Sentiment Analyst page — nothing is shown until real articles exist.`}
            </p>
          )}
        </section>
      </div>

      {/* Key takeaway — composed from stored outputs only */}
      <section className="card takeaway fade-in" aria-label="Key takeaway" style={{ animationDelay: '0.14s' }}>
        <div className="takeaway-icon" aria-hidden="true">◉</div>
        <div>
          <h3>Key Takeaway</h3>
          {outputsLoading ? (
            <div className="skeleton skeleton-line" />
          ) : (
            <>
              <p>
                <strong>{takeaway.headline}</strong>
              </p>
              <ul className="takeaway-lines">
                {takeaway.lines.map((line, i) => (
                  <li key={i} className="muted">
                    {line}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <button className="btn" onClick={() => go('/intelligence/summary')}>
          View Full Summary →
        </button>
      </section>

      <p className="muted evidence-strip">
        Data behind this view:{' '}
        {series
          ? `${series.status} · latest ${series.latest_trade_date ?? '—'} · ${series.count} stored trading days`
          : 'no price data'}
        {' · '}{news ? `${news.count} stored articles` : 'news unavailable'}
        {filingsCount !== null && <> · {filingsCount} ingested official filings</>}
      </p>
    </section>
  );
}
