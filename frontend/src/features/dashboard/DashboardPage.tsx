import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import CandleChart from '../../components/common/CandleChart';
import PeerTable from '../../components/common/PeerTable';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import type { AgentOutputSummary } from '../../types/api';
import {
  deltaClass,
  fmtPrice,
  fmtSigned,
  snapshot,
} from '../company/priceStats';
import { useFilingsCount } from '../company/useFilingsCount';
import { useMarketQuote, fmtPriceNA, fmtIntNA, describeFreshness } from '../company/useMarketQuote';
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
  { label: 'News', target: 'dash-news' },
  { label: 'Peers', target: 'dash-peers' },
] as const;

/** Provider names are shown to users — never raw lowercase internal ids. */
function sourceLabel(source: string): string {
  if (!source) return '';
  return source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

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
    ensureMarketStatus,
    marketStatus,
  } = useFinCortext();
  const navigate = useNavigate();

  const series = pricesOf(symbol);
  const seriesError = pricesErrorOf(symbol);
  const seriesLoading = series === undefined && seriesError === null;
  const { quote, loading: quoteLoading } = useMarketQuote(symbol);
  const outputs = outputsOf(symbol);
  const outputsError = outputsErrorOf(symbol);
  const outputsLoading = outputs === undefined && outputsError === null;
  const news = newsOf(symbol);

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
  // Live quote (Upstox primary) preferred; stored snapshot backs it up.
  // Every nullable gap renders as "N/A" — never ₹0 or a fabricated value.
  const livePrice = quote?.last_price ?? snap?.last.close ?? null;
  const livePrevClose = quote?.prev_close ?? snap?.prev?.close ?? null;
  const liveChange = quote?.day_change ?? snap?.dayChange ?? null;
  const liveChangePct = quote?.day_change_pct ?? snap?.dayChangePct ?? null;
  const liveHigh = quote?.high ?? snap?.last.high ?? null;
  const liveLow = quote?.low ?? snap?.last.low ?? null;
  const liveVolume = quote?.volume ?? snap?.last.volume ?? null;
  // Current-day candle from the live Upstox quote (real OHLC, never
  // fabricated): appended when newer than stored history, or merged into the
  // same-date bar when the quote is the fresher truth for that day. Skipped
  // entirely when any live OHLC leg is missing.
  const liveCandle = useMemo(() => {
    const ts = quote?.timestamp;
    if (
      ts === null ||
      ts === undefined ||
      quote?.open === null ||
      quote?.open === undefined ||
      quote?.high === null ||
      quote?.high === undefined ||
      quote?.low === null ||
      quote?.low === undefined ||
      quote?.close === null ||
      quote?.close === undefined
    ) {
      return null;
    }
    return {
      date: String(ts).slice(0, 10),
      open: quote.open,
      high: quote.high,
      low: quote.low,
      close: quote.close,
      volume: quote.volume ?? 0,
    };
  }, [quote]);
  const chartPrices = useMemo(() => {
    if (liveCandle === null || prices.length === 0) {
      return liveCandle === null ? prices : [...prices, liveCandle];
    }
    const lastDate = prices[prices.length - 1].date;
    if (liveCandle.date > lastDate) {
      return [...prices, liveCandle];
    }
    if (liveCandle.date === lastDate) {
      return [...prices.slice(0, -1), liveCandle];
    }
    return prices;
  }, [prices, liveCandle]);
  const hasLiveCandle =
    liveCandle !== null &&
    chartPrices.length > 0 &&
    chartPrices[chartPrices.length - 1].date === liveCandle.date;
  const visible = useMemo(
    () => (rangeBars === Number.POSITIVE_INFINITY ? chartPrices : chartPrices.slice(-rangeBars)),
    [chartPrices, rangeBars],
  );
  const animatedPrice = useCountUp(livePrice, 600);
  const animatedChange = useCountUp(liveChange);

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

  const displayName = entry?.name ?? quote?.name ?? symbol;
  const priceLoading = seriesLoading || quoteLoading;
  // Freshness: the Upstox quote timestamp wins over the stored series date —
  // an old cached date is never shown when newer quote data exists.
  const freshness = describeFreshness(
    quote?.timestamp ?? series?.quote_timestamp,
    quote?.source ?? series?.quote_source,
    series?.latest_trade_date,
    series?.source,
  );

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
            {priceLoading ? (
              <span className="skeleton skeleton-price" aria-label="Loading price" />
            ) : livePrice === null ? (
              'N/A'
            ) : (
              `₹${fmtPrice(animatedPrice ?? livePrice)}`
            )}
          </div>
          <div className={`term-change ${deltaClass(liveChange)}`}>
            {priceLoading
              ? '…'
              : liveChange === null || animatedChange === null
                ? 'N/A'
                : `${fmtSigned(animatedChange)} (${fmtSigned(liveChangePct ?? 0)}%)`}
          </div>
          <div className="muted term-asof">
            {priceLoading ? (
              'Loading price history…'
            ) : freshness.status === 'UNAVAILABLE' ? (
              'Price history unavailable'
            ) : (
              <>
                {freshness.label} · {series?.count ?? 0} stored days
                {freshness.source ? ` · Source: ${sourceLabel(freshness.source)}` : ''}
              </>
            )}
          </div>
          {livePrevClose !== null && livePrevClose !== undefined && (
            <div className="muted term-prevclose">
              Prev close {fmtPriceNA(livePrevClose)}
            </div>
          )}
          {livePrevClose === null && !priceLoading && (
            <div className="muted term-prevclose">Prev close N/A</div>
          )}
        </div>
        <dl className="dash-session">
          <div>
            <dt className="muted">Day High</dt>
            <dd>{priceLoading ? '…' : fmtPriceNA(liveHigh)}</dd>
          </div>
          <div>
            <dt className="muted">Day Low</dt>
            <dd>{priceLoading ? '…' : fmtPriceNA(liveLow)}</dd>
          </div>
          <div>
            <dt className="muted">Volume</dt>
            <dd>{priceLoading ? '…' : fmtIntNA(liveVolume)}</dd>
          </div>
          <div>
            <dt className="muted">52w High</dt>
            <dd>{priceLoading ? '…' : fmtPriceNA(quote?.year_high)}</dd>
          </div>
          <div>
            <dt className="muted">52w Low</dt>
            <dd>{priceLoading ? '…' : fmtPriceNA(quote?.year_low)}</dd>
          </div>
        </dl>
        <button className="btn btn-primary btn-analyze" onClick={() => go('/stock/insights')}>
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

      {/* Price performance — OHLC candlesticks over stored history */}
      <section id="dash-price" className="card chart-card fade-in" aria-label="Price performance" style={{ animationDelay: '0.06s' }}>
          <div className="chart-head">
            <h3>Price Performance</h3>
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
        ) : !snap || visible.length < 2 ? (
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
            <CandleChart data={chartPrices} rangeBars={rangeBars} />
            <p className="muted dash-chart-note">
              Daily candles from stored OHLCV history{hasLiveCandle ? ' plus the live Upstox candle' : ''} — showing {visible.length} of{' '}
              {chartPrices.length} trading days
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

      {/* Latest news — real stored articles, linked to the full News page */}
      <section id="dash-news" className="card fade-in" aria-label="Latest news" style={{ animationDelay: '0.11s' }}>
        <div className="dash-heading">
          <h3>Latest News</h3>
          {news && news.count > 0 && (
            <button className="btn" onClick={() => go('/stock/news')}>
              All news →
            </button>
          )}
        </div>
        {!news || news.count === 0 ? (
          <div className="dash-empty">
            <p className="muted">
              {news === undefined
                ? 'Loading news…'
                : `No stored news for ${displayName} yet — nothing is shown until real articles are collected.`}
            </p>
          </div>
        ) : (
          <ul className="news-list-live">
            {(news.articles ?? []).slice(0, 3).map((a) => (
              <li key={a.article_id} className="news-item-live">
                <a href={a.source_url ?? '#'} target="_blank" rel="noreferrer" className="news-item-title">
                  {a.title}
                </a>
                <p className="muted news-item-meta">
                  {a.source ?? 'source unavailable'}
                  {a.published_at
                    ? ` · ${new Date(a.published_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
                    : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Market context — full width below the chart, real sector peers only */}
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
        <button className="btn" onClick={() => go('/portfolio')}>
          View Portfolio Intelligence →
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
