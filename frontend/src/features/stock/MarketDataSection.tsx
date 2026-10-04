import { useEffect, useMemo, useState } from 'react';
import CandleChart from '../../components/common/CandleChart';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import {
  deltaClass,
  fmtPrice,
  fmtSigned,
  snapshot,
} from '../company/priceStats';
import { useMarketQuote, fmtPriceNA, fmtIntNA, describeFreshness } from '../company/useMarketQuote';
import type { QuoteDepthLevel } from '../../types/api';

const RANGES = [
  { label: '1M', bars: 22 },
  { label: '3M', bars: 66 },
  { label: '6M', bars: 132 },
  { label: '1Y', bars: 252 },
  { label: 'All', bars: Number.POSITIVE_INFINITY },
] as const;

function DepthTable({ levels, side }: { levels: QuoteDepthLevel[] | null | undefined; side: 'Bid' | 'Ask' }) {
  if (!levels || levels.length === 0) return null;
  return (
    <table className="data-table depth-table-live">
      <thead>
        <tr>
          <th>{side === 'Bid' ? 'Bid Price' : 'Ask Price'}</th>
          <th>Quantity</th>
          <th>Orders</th>
        </tr>
      </thead>
      <tbody>
        {levels.map((l, i) => (
          <tr key={i}>
            <td>{l.price === null ? 'N/A' : `₹${fmtPrice(l.price)}`}</td>
            <td>{l.quantity === null ? 'N/A' : fmtIntNA(l.quantity)}</td>
            <td>{l.orders === null ? 'N/A' : fmtIntNA(l.orders)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Market Data — stored OHLCV candles, live quote stats and (when the market
 *  is open) the live 5-level order book. All numbers come from Upstox via the
 *  backend; unavailable fields render as "N/A", never fabricated. */
export default function MarketDataSection() {
  const { symbol, entryFor, ensurePrices, pricesOf, pricesErrorOf } = useFinCortext();
  const { quote, loading: quoteLoading } = useMarketQuote(symbol);
  const [rangeBars, setRangeBars] = useState<number>(66);
  const entry = entryFor(symbol);

  const series = pricesOf(symbol);
  const seriesError = pricesErrorOf(symbol);
  const seriesLoading = series === undefined && seriesError === null;

  useEffect(() => {
    ensurePrices(symbol).catch(() => undefined);
  }, [symbol, ensurePrices]);

  const prices = series?.prices ?? [];
  const snap = useMemo(() => snapshot(prices), [prices]);
  const visible = useMemo(
    () => (rangeBars === Number.POSITIVE_INFINITY ? prices : prices.slice(-rangeBars)),
    [prices, rangeBars],
  );
  const freshness = describeFreshness(
    quote?.timestamp ?? series?.quote_timestamp,
    quote?.source ?? series?.quote_source,
    series?.latest_trade_date,
    series?.source,
  );

  const live = quote?.live === true && quote?.last_price !== null && quote?.last_price !== undefined;

  return (
    <section className="page">
      <header className="card dash-head fade-in">
        <div className="dash-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{entry?.name ?? quote?.name ?? symbol}</div>
            <div className="term-chips">
              {entry?.sector && <span className="chip chip-sector">{entry.sector}</span>}
              <span className="chip">{quote?.source ? 'Market data: Upstox' : 'Market data unavailable'}</span>
            </div>
          </div>
        </div>
        <div className="dash-pricecol">
          <div className="term-price">
            {quoteLoading || seriesLoading ? (
              <span className="skeleton skeleton-price" aria-label="Loading price" />
            ) : quote?.last_price !== null && quote?.last_price !== undefined ? (
              `₹${fmtPrice(quote.last_price)}`
            ) : (
              'N/A'
            )}
          </div>
          <div className={`term-change ${deltaClass(quote?.day_change ?? null)}`}>
            {quoteLoading
              ? '…'
              : quote?.day_change === null || quote?.day_change === undefined
                ? 'N/A'
                : `${fmtSigned(quote.day_change)} (${fmtSigned(quote.day_change_pct ?? 0)}%)`}
          </div>
          <div className="muted term-asof">
            {freshness.status === 'UNAVAILABLE' ? 'Market data unavailable' : freshness.label}
          </div>
        </div>
        <dl className="dash-session">
          <div>
            <dt className="muted">Open</dt>
            <dd>{quoteLoading ? '…' : fmtPriceNA(quote?.open)}</dd>
          </div>
          <div>
            <dt className="muted">Prev Close</dt>
            <dd>{quoteLoading ? '…' : fmtPriceNA(quote?.prev_close)}</dd>
          </div>
          <div>
            <dt className="muted">Avg Price</dt>
            <dd>{quoteLoading ? '…' : fmtPriceNA(quote?.average_price)}</dd>
          </div>
          <div>
            <dt className="muted">52w High</dt>
            <dd>{quoteLoading ? '…' : fmtPriceNA(quote?.year_high)}</dd>
          </div>
          <div>
            <dt className="muted">52w Low</dt>
            <dd>{quoteLoading ? '…' : fmtPriceNA(quote?.year_low)}</dd>
          </div>
          <div>
            <dt className="muted">Circuits</dt>
            <dd>
              {quoteLoading
                ? '…'
                : quote?.upper_circuit_limit != null && quote?.lower_circuit_limit != null
                  ? `${fmtPriceNA(quote.lower_circuit_limit)} – ${fmtPriceNA(quote.upper_circuit_limit)}`
                  : 'N/A'}
            </dd>
          </div>
        </dl>
      </header>

      <section className="card chart-card fade-in" aria-label="Price chart" style={{ animationDelay: '0.04s' }}>
        <div className="chart-head">
          <h3>Price Chart</h3>
        </div>
        {seriesLoading ? (
          <div className="skeleton skeleton-chart" />
        ) : seriesError && !series ? (
          <div className="dash-empty">
            <p><StatusBadge status="UNAVAILABLE" /></p>
            <p className="muted">No stored price history for {symbol} yet — nothing is shown until real data is collected.</p>
          </div>
        ) : !snap || visible.length < 2 ? (
          <div className="dash-empty">
            <p><StatusBadge status={series?.status ?? 'UNAVAILABLE'} /></p>
            <p className="muted">Not enough stored trading days for {symbol} to draw a chart yet.</p>
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
            <CandleChart data={prices} rangeBars={rangeBars} />
            <p className="muted dash-chart-note">
              Daily candles from stored OHLCV — showing {visible.length} of {prices.length} trading days
              {snap.storedHigh && (
                <>
                  {' '}· period high ₹{fmtPrice(snap.storedHigh.high)} ({snap.storedHigh.date}) · period
                  low ₹{fmtPrice(snap.storedLow.low)} ({snap.storedLow.date})
                </>
              )}
            </p>
          </>
        )}
      </section>

      <section className="card fade-in" aria-label="Live order book" style={{ animationDelay: '0.08s' }}>
        <div className="dash-heading">
          <h3>Live Order Book</h3>
          {quoteLoading ? <span className="muted">loading…</span> : live ? <StatusBadge status="LIVE" /> : <StatusBadge status="UNAVAILABLE" />}
        </div>
        {!live ? (
          <div className="dash-empty">
            <p className="muted">
              {quoteLoading
                ? 'Loading the live quote…'
                : 'The live order book is only available from a live market quote — the current snapshot is stored/cached. Nothing is shown until a live quote is fetched.'}
            </p>
          </div>
        ) : (
          <>
            <p className="muted dash-section-note">
              Total buy qty {fmtIntNA(quote?.total_buy_quantity)} · total sell qty{' '}
              {fmtIntNA(quote?.total_sell_quantity)} · 5 levels per side
            </p>
            <div className="depth-grid-live">
              <div>
                <DepthTable levels={quote?.depth_buy} side="Bid" />
              </div>
              <div>
                <DepthTable levels={quote?.depth_sell} side="Ask" />
              </div>
            </div>
          </>
        )}
      </section>
    </section>
  );
}
