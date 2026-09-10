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
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { MarketPricePoint } from '../../types/api';

const RANGES = [
  { label: '1M', bars: 22 },
  { label: '3M', bars: 66 },
  { label: '6M', bars: 132 },
  { label: '1Y', bars: 252 },
  { label: 'All', bars: Number.POSITIVE_INFINITY },
] as const;

const ANALYSIS_LINKS = [
  { label: 'Firm Analyst', to: '/intelligence/firm', hint: 'How healthy is the company?' },
  { label: 'Industry Analyst', to: '/intelligence/industry', hint: 'How does it compare with peers?' },
  { label: 'Sentiment Analyst', to: '/intelligence/sentiment', hint: 'What is financial news saying?' },
  { label: 'Combined Summary', to: '/intelligence/summary', hint: 'Three views side by side' },
] as const;

/** Cheap display-only read, cached per symbol for the session so returning
 *  to the Dashboard never refetches it. */
const filingsCountCache = new Map<string, number>();

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

const fmtPrice = (v: number): string =>
  v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtInt = (v: number): string => v.toLocaleString('en-IN');

const fmtSigned = (v: number, digits = 2): string =>
  `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(digits)}`;

/** Price-behaviour snapshot computed from stored bars only. Windows that need
 *  more history than stored render as unavailable — never extrapolated. */
function useSnapshot(prices: MarketPricePoint[]) {
  return useMemo(() => {
    if (prices.length === 0) return null;
    const last = prices[prices.length - 1];
    const prev = prices.length > 1 ? prices[prices.length - 2] : null;
    const change30 =
      prices.length >= 31 ? last.close / prices[prices.length - 31].close - 1 : null;
    const momentum90 =
      prices.length >= 91 ? last.close / prices[prices.length - 91].close - 1 : null;
    let hi = prices[0];
    let lo = prices[0];
    let volSum = 0;
    const volWindow = prices.slice(-20);
    for (const p of prices) {
      if (p.high > hi.high) hi = p;
      if (p.low < lo.low) lo = p;
    }
    for (const p of volWindow) volSum += p.volume;
    return {
      last,
      prev,
      dayChange: prev ? last.close - prev.close : null,
      dayChangePct: prev ? ((last.close - prev.close) / prev.close) * 100 : null,
      change30,
      momentum90,
      storedHigh: hi,
      storedLow: lo,
      avgVolume20: volWindow.length > 0 ? volSum / volWindow.length : null,
      dayRangePct: last.close ? ((last.high - last.low) / last.close) * 100 : null,
    };
  }, [prices]);
}

/** Company terminal: identity, price action, history, peers, news.
 *
 * All numbers come from the running backend: stored OHLCV
 * (GET /api/market/prices/{symbol}), stored news (GET /api/news/{symbol}),
 * storage coverage (GET /api/market/status) and filing counts. This page
 * deliberately shows NO analyst scores — those live on their dedicated
 * pages. Unavailable data is labelled honestly, never replaced.
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
  const news = newsOf(symbol);
  const newsError = newsErrorOf(symbol);
  const newsLoading = news === undefined && newsError === null;

  const [rangeBars, setRangeBars] = useState<number>(Number.POSITIVE_INFINITY);
  const [filingsCount, setFilingsCount] = useState<number | null>(null);

  useEffect(() => {
    ensurePrices(symbol).catch(() => undefined);
    ensureNews(symbol).catch(() => undefined);
    ensureMarketStatus().catch(() => undefined);
  }, [symbol, ensurePrices, ensureNews, ensureMarketStatus]);

  useEffect(() => {
    const cached = filingsCountCache.get(symbol);
    if (cached !== undefined) {
      setFilingsCount(cached);
      return;
    }
    let cancelled = false;
    api.filings
      .list(symbol)
      .then((r) => {
        if (cancelled) return;
        filingsCountCache.set(symbol, r.count);
        setFilingsCount(r.count);
      })
      .catch(() => {
        if (!cancelled) setFilingsCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const entry = entryFor(symbol);
  const peers = peersOf(symbol);
  const prices = series?.prices ?? [];
  const snap = useSnapshot(prices);
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
  const deltaClass =
    !snap || snap.dayChange === null || snap.dayChange === 0
      ? 'delta-flat'
      : snap.dayChange > 0
        ? 'delta-up'
        : 'delta-down';

  const statusRow = useMemo(
    () => marketStatus?.symbols.find((s) => s.symbol === symbol),
    [marketStatus, symbol],
  );
  const coverageCount = useMemo(
    () => marketStatus?.symbols.filter((s) => s.rows > 0).length ?? null,
    [marketStatus],
  );
  const peerRows = useMemo(() => {
    const bySymbol = new Map((marketStatus?.symbols ?? []).map((s) => [s.symbol, s]));
    return peers.map((p) => ({ entry: p, status: bySymbol.get(p.symbol) ?? null }));
  }, [peers, marketStatus]);

  const go = (to: string) => navigate(`${to}?symbol=${encodeURIComponent(symbol)}`);

  return (
    <section className="page terminal">
      {/* Company identity */}
      <header className="term-head fade-in">
        <div className="term-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{entry?.name ?? symbol}</div>
            <div className="term-chips">
              {entry && (
                <>
                  <span className="chip">{entry.ticker}</span>
                  <span className="chip chip-sector">{entry.sector}</span>
                  <span className="chip">{entry.industry}</span>
                  <span className="chip">{entry.exchange}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="term-side">
          <div className="term-price-block">
            <div className="term-price">
              {animatedPrice === null ? '—' : `₹${fmtPrice(animatedPrice)}`}
            </div>
            <div className={`term-change ${deltaClass}`}>
              {snap?.dayChange === null || snap?.dayChange === undefined || animatedChange === null
                ? '—'
                : `${fmtSigned(animatedChange)} (${fmtSigned(snap.dayChangePct ?? 0)}%)`}
            </div>
            <div className="muted term-asof">
              {series?.latest_trade_date
                ? `As of ${series.latest_trade_date} · ${series.count} stored days`
                : 'No stored price history yet'}
            </div>
          </div>
          <div className="term-status">
            {series && <StatusBadge status={series.status} />}
            {series?.status === 'LIVE' && (
              <span className="live-dot" title="Latest available data" aria-label="Latest available data" />
            )}
          </div>
        </div>
      </header>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button
          className="btn btn-primary"
          onClick={() => go('/intelligence/firm')}
          disabled={!symbol}
        >
          Analyze Company
        </button>
      </div>

      {/* Market KPIs */}
      <section aria-label="Market snapshot">
        {seriesLoading ? (
          <div className="kpi-row">
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
          </div>
        ) : seriesError && !series ? (
          <div className="dash-empty">
            <p>
              <StatusBadge status="UNAVAILABLE" />
            </p>
            <p className="muted">
              No stored price history for {symbol} yet — nothing is shown until
              real data is collected.
            </p>
            <p className="muted">Could not load market data: {seriesError}</p>
          </div>
        ) : !snap ? (
          <div className="dash-empty">
            <p>
              <StatusBadge status={series?.status ?? 'UNAVAILABLE'} />
            </p>
            <p className="muted">
              No stored price history for {series?.symbol ?? symbol} yet. Running the
              Industry Analyst fetches and stores price history for the company and its
              sector peers automatically.
            </p>
          </div>
        ) : (
          <div className="kpi-row term-kpis">
            <div className="kpi">
              <span className="kpi-label">Day high</span>
              <div className="kpi-value">₹{fmtPrice(snap.last.high)}</div>
            </div>
            <div className="kpi">
              <span className="kpi-label">Day low</span>
              <div className="kpi-value">₹{fmtPrice(snap.last.low)}</div>
            </div>
            <div className="kpi">
              <span className="kpi-label">Volume</span>
              <div className="kpi-value">{fmtInt(snap.last.volume)}</div>
            </div>
            <div className="kpi">
              <span className="kpi-label">Day range</span>
              <div className="kpi-value">
                {snap.dayRangePct === null ? '—' : `${snap.dayRangePct.toFixed(2)}%`}
              </div>
            </div>
            <div className="kpi">
              <span className="kpi-label">30-day change</span>
              <div className={`kpi-value ${(snap.change30 ?? 0) >= 0 ? 'delta-up' : 'delta-down'}`}>
                {snap.change30 === null ? '—' : `${fmtSigned(snap.change30 * 100)}%`}
              </div>
            </div>
            <div className="kpi">
              <span className="kpi-label">90-day momentum</span>
              <div className={`kpi-value ${(snap.momentum90 ?? 0) >= 0 ? 'delta-up' : 'delta-down'}`}>
                {snap.momentum90 === null ? '—' : `${fmtSigned(snap.momentum90 * 100)}%`}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Price history */}
      {snap && chartData.length > 1 && (
        <section className="dash-section fade-in" aria-label="Price history" style={{ animationDelay: '0.06s' }}>
          <div className="dash-chart">
            <div className="chart-head">
              <h3>Price history</h3>
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
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={chartData} margin={{ top: 10, right: 8, bottom: 0, left: 8 }}>
                <defs>
                  <linearGradient id="dashCloseFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4f8cff" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#4f8cff" stopOpacity={0.02} />
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
                    name === 'volume' ? [fmtInt(Number(value)), 'Volume'] : [`₹${fmtPrice(Number(value))}`, 'Close']
                  }
                />
                <Bar yAxisId="volume" dataKey="volume" fill="#22304d" opacity={0.55} isAnimationActive={false} />
                <Area
                  yAxisId="price"
                  type="monotone"
                  dataKey="close"
                  stroke="#4f8cff"
                  strokeWidth={2}
                  fill="url(#dashCloseFill)"
                  animationDuration={900}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
                <ReferenceDot x={snap.last.date} y={snap.last.close} yAxisId="price" r={4} fill="#4f8cff" stroke="#0b1220" />
              </ComposedChart>
            </ResponsiveContainer>
            <p className="muted dash-chart-note">
              Daily closes from stored OHLCV history — showing {visible.length} of {series?.count} trading days
              {snap.storedHigh && (
                <> · stored high ₹{fmtPrice(snap.storedHigh.high)} ({snap.storedHigh.date}) · stored low ₹{fmtPrice(snap.storedLow.low)} ({snap.storedLow.date})</>
              )}
              {snap.avgVolume20 !== null && <> · avg volume (20 sessions) {fmtInt(Math.round(snap.avgVolume20))}</>}
            </p>
          </div>
        </section>
      )}

      <div className="dash-two-col fade-in" style={{ animationDelay: '0.1s' }}>
        {/* Sector / peer context */}
        <section className="dash-section" aria-label="Sector context">
          <div className="card peer-card">
            <div className="dash-heading">
              <h3>Sector{entry ? ` — ${entry.sector}` : ''}</h3>
            </div>
            <p className="muted dash-section-note">
              {coverageCount !== null
                ? `${coverageCount} of ${marketStatus?.symbols.length ?? ''} companies hold stored price history. `
                : ''}
              Select a peer to switch the terminal to it.
            </p>
            {peerRows.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Peer</th>
                    <th>Stored days</th>
                    <th>Latest date</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {peerRows.map(({ entry: peer, status }) => (
                    <tr key={peer.symbol} className={peer.symbol === symbol ? 'peer-self' : undefined}>
                      <td>
                        <button
                          className="peer-link"
                          onClick={() => setSymbol(peer.symbol)}
                          disabled={peer.symbol === symbol}
                          title={peer.symbol === symbol ? 'This company' : `Switch terminal to ${peer.symbol}`}
                        >
                          {peer.symbol}
                        </button>{' '}
                        <span className="muted">{peer.name}</span>
                      </td>
                      <td>{status ? status.rows : '—'}</td>
                      <td>{status?.latest_trade_date ?? '—'}</td>
                      <td>{status ? <StatusBadge status={status.status} /> : <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">Sector information is unavailable.</p>
            )}
          </div>
        </section>

        {/* Recent financial news */}
        <section className="dash-section" aria-label="Recent financial news">
          <div className="card dash-news">
            <div className="dash-heading">
              <h3>Recent news — {symbol}</h3>
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
            <button className="btn dash-view" onClick={() => go('/intelligence/sentiment')}>
              Open Sentiment Analyst →
            </button>
          </div>
        </section>
      </div>

      {/* Continue to analysis — navigation only, no scores here */}
      <section className="analysis-links fade-in" aria-label="Continue to analysis" style={{ animationDelay: '0.14s' }}>
        {ANALYSIS_LINKS.map((a) => (
          <button key={a.to} className="analysis-link" onClick={() => go(a.to)}>
            <strong>{a.label} →</strong>
            <span className="muted">{a.hint}</span>
          </button>
        ))}
      </section>

      <p className="muted evidence-strip">
        Data freshness: {series ? `${series.status} · latest ${series.latest_trade_date ?? '—'} · ${series.count} stored trading days` : 'no price data'}
        {' · '}{news ? `${news.count} stored articles` : 'news unavailable'}
        {filingsCount !== null && <> · {filingsCount} ingested official filings</>}
        {statusRow && statusRow.rows === 0 && <> · {symbol} has no stored prices yet</>}
      </p>
    </section>
  );
}
