import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { SIGNAL_CLASS } from '../../components/common/AgentOutputCard';
import { api } from '../../services/api';
import type { AgentOutputSummary, PriceSeriesResponse } from '../../types/api';

const ANALYSTS = [
  {
    id: 'firm_analyst',
    label: 'Firm Analyst',
    to: '/intelligence/firm',
    blurb: 'Fundamentals & market behavior',
  },
  {
    id: 'industry_analyst',
    label: 'Industry Analyst',
    to: '/intelligence/industry',
    blurb: 'Peer & sector context',
  },
  {
    id: 'sentiment_analyst',
    label: 'Sentiment Analyst',
    to: '/intelligence/sentiment',
    blurb: 'Financial-news sentiment',
  },
] as const;

const PREPARE_HINT =
  'Running the Industry Analyst fetches and stores price history for the company and its sector peers automatically.';

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

const scoreClass = (score: number | null): string => {
  if (score === null) return 'score-neutral';
  if (score >= 55) return 'score-positive';
  if (score <= 45) return 'score-negative';
  return 'score-neutral';
};

/** Latest price + change + chart, drawn from the stored OHLCV series only. */
function MarketPanel({
  series,
  error,
}: {
  series: PriceSeriesResponse | null;
  error: string | null;
}) {
  const prices = series?.prices ?? [];
  const last = prices.length > 0 ? prices[prices.length - 1] : null;
  const prev = prices.length > 1 ? prices[prices.length - 2] : null;
  const dayChange = last && prev ? last.close - prev.close : null;
  const dayChangePct =
    dayChange !== null && prev ? (dayChange / prev.close) * 100 : null;
  const deltaClass =
    dayChange === null || dayChange === 0
      ? 'delta-flat'
      : dayChange > 0
        ? 'delta-up'
        : 'delta-down';

  const animatedPrice = useCountUp(last ? last.close : null);
  const animatedChange = useCountUp(dayChange);
  const chartData = useMemo(
    () => prices.map((p) => ({ date: p.date, close: p.close })),
    [prices],
  );

  if (!last) {
    return (
      <div className="dash-empty">
        <p>
          <StatusBadge status={series?.status ?? 'UNAVAILABLE'} />
        </p>
        <p className="muted">
          No stored price history for {series?.symbol ?? 'this company'} yet.{' '}
          {PREPARE_HINT}
        </p>
        {error && <p className="muted">Could not load market data: {error}</p>}
      </div>
    );
  }

  return (
    <>
      <div className="kpi-row">
        <div className="kpi">
          <span className="kpi-label">Latest close</span>
          <div className="kpi-value">
            {animatedPrice === null ? '—' : fmtPrice(animatedPrice)}
          </div>
        </div>
        <div className="kpi">
          <span className="kpi-label">Day change</span>
          <div className={`kpi-value ${deltaClass}`}>
            {animatedChange === null || dayChange === null
              ? '—'
              : `${dayChange >= 0 ? '+' : '−'}${fmtPrice(Math.abs(animatedChange))}`}
            {dayChangePct !== null && (
              <span className="kpi-sub">
                ({dayChangePct >= 0 ? '+' : '−'}
                {Math.abs(dayChangePct).toFixed(2)}%)
              </span>
            )}
          </div>
        </div>
        <div className="kpi">
          <span className="kpi-label">As of</span>
          <div className="kpi-value kpi-date">{series?.latest_trade_date ?? '—'}</div>
        </div>
        <div className="kpi">
          <span className="kpi-label">Stored days</span>
          <div className="kpi-value">{series?.count ?? 0}</div>
        </div>
      </div>

      {chartData.length > 1 ? (
        <div className="dash-chart">
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartData} margin={{ top: 10, right: 16, bottom: 0, left: 8 }}>
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
                stroke="#8fa0b8"
                fontSize={11}
                domain={['auto', 'auto']}
                tickFormatter={(v: number) => v.toLocaleString('en-IN')}
                tickLine={false}
                width={72}
              />
              <Tooltip
                contentStyle={{ background: '#141f36', border: '1px solid #22304d' }}
                labelStyle={{ color: '#e6ecf5' }}
              />
              <Area
                type="monotone"
                dataKey="close"
                stroke="#4f8cff"
                strokeWidth={2}
                fill="url(#dashCloseFill)"
                animationDuration={900}
                dot={false}
                activeDot={{ r: 4 }}
              />
              <ReferenceDot x={last.date} y={last.close} r={4} fill="#4f8cff" stroke="#0b1220" />
            </AreaChart>
          </ResponsiveContainer>
          <p className="muted dash-chart-note">
            Daily closes from stored OHLCV history ({series?.count} trading days)
          </p>
        </div>
      ) : (
        <div className="dash-empty">
          <p className="muted">
            Only one stored trading day for {series?.symbol} — a chart needs at
            least two. The value above is real; more history will appear here as
            it is collected.
          </p>
        </div>
      )}
    </>
  );
}
/** One analyst overview card backed by the latest stored AgentOutput. */
function AnalystCard({
  analyst,
  output,
  loading,
  error,
  onOpen,
}: {
  analyst: (typeof ANALYSTS)[number];
  output: AgentOutputSummary | undefined;
  loading: boolean;
  error: boolean;
  onOpen: () => void;
}) {
  return (
    <div className="dash-analyst">
      <div className="dash-analyst-head">
        <strong>{analyst.label}</strong>
        <span className="muted">{analyst.blurb}</span>
      </div>

      {output ? (
        <>
          <div className="dash-score">
            <strong className={scoreClass(output.score)}>
              {output.score === null ? '—' : Math.round(output.score)}
            </strong>
            <span>/ 100</span>
          </div>
          <div className="badge-row">
            <span className={`badge ${SIGNAL_CLASS[output.signal] ?? ''}`}>
              {output.signal.replace(/_/g, ' ').toUpperCase()}
            </span>
            <span className={`badge badge-status-${output.status.toLowerCase()}`}>
              {output.status}
            </span>
          </div>
          <p className="muted dash-confidence">
            Confidence {Math.round(output.confidence * 100)}%
          </p>
          <p className="muted dash-when">
            run {new Date(output.generated_at).toLocaleString()}
          </p>
        </>
      ) : (
        <p className="muted dash-empty-note">
          {loading
            ? 'Loading previous results…'
            : error
              ? 'Previous results could not be loaded.'
              : 'No analysis yet — run the analyst to generate the first result.'}
        </p>
      )}

      <button className="btn dash-view" onClick={onOpen}>
        View analysis →
      </button>
    </div>
  );
}


/** Dashboard — investment research overview.
 *
 * All numbers come from the running backend: stored OHLCV
 * (GET /api/market/prices/{symbol}) and stored analyst results
 * (GET /api/agents/outputs). Unavailable data is labelled honestly and never
 * replaced with placeholder values.
 */
export default function DashboardPage() {
  const [symbol, setSymbol] = useState('TCS');
  const [series, setSeries] = useState<PriceSeriesResponse | null>(null);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(true);
  const [outputs, setOutputs] = useState<AgentOutputSummary[] | null>(null);
  const [outputsError, setOutputsError] = useState<string | null>(null);
  const [outputsLoading, setOutputsLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;

    setSeriesLoading(true);
    setSeriesError(null);
    setSeries(null);
    api.market
      .prices(symbol)
      .then((s) => {
        if (!cancelled) setSeries(s);
      })
      .catch((e: Error) => {
        if (!cancelled) setSeriesError(e.message);
      })
      .finally(() => {
        if (!cancelled) setSeriesLoading(false);
      });

    setOutputsLoading(true);
    setOutputsError(null);
    setOutputs(null);
    api.agents
      .outputs(undefined, symbol, 30)
      .then((r) => {
        if (!cancelled) setOutputs(r.outputs);
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setOutputs([]);
          setOutputsError(e.message);
        }
      })
      .finally(() => {
        if (!cancelled) setOutputsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol]);

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

  const go = (to: string) => navigate(`${to}?symbol=${encodeURIComponent(symbol)}`);
return (
    <section className="page">
      <h2>Dashboard</h2>
      <p className="dash-lede">
        Research a company from three angles — its fundamentals, its industry
        position, and the financial news around it.
      </p>
      <p className="muted page-description">
        FinCortext brings the evidence together so you can see what is driving
        the view.
      </p>

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

      <section className="dash-section fade-in" aria-label="Market overview">
        <div className="dash-heading">
          <h3>{symbol} market</h3>
          {series && <StatusBadge status={series.status} />}
        </div>
        {seriesLoading ? (
          <div className="kpi-row">
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
            <div className="skeleton kpi-skeleton" />
          </div>
        ) : (
          <MarketPanel series={series} error={seriesError} />
        )}
      </section>

      <section
        className="dash-section fade-in"
        aria-label="Analyst overview"
        style={{ animationDelay: '0.08s' }}
      >
        <div className="dash-heading">
          <h3>Latest analyst views — {symbol}</h3>
        </div>
        <p className="muted dash-section-note">
          Stored results from previous runs. Open an analyst to run a fresh one
          — scores are never invented.
        </p>
        <div className="dash-analysts">
          {ANALYSTS.map((analyst) => (
            <AnalystCard
              key={analyst.id}
              analyst={analyst}
              output={latestByAgent.get(analyst.id)}
              loading={outputsLoading}
              error={outputsError !== null}
              onOpen={() => go(analyst.to)}
            />
          ))}
        </div>
      </section>

      <section
        className="dash-section fade-in"
        aria-label="Combined intelligence"
        style={{ animationDelay: '0.16s' }}
      >
        <div className="card dash-combined">
          <h3>Combined Intelligence</h3>
          <p className="muted">
            Each analyst looks at {symbol || 'the company'} through its own
            evidence — fundamentals, industry peers, and news tone. They are
            shown side by side; FinCortext does not blend them into a single
            overall score.
          </p>
          {outputsLoading ? (
            <div className="kpi-row">
              <div className="skeleton kpi-skeleton" />
              <div className="skeleton kpi-skeleton" />
              <div className="skeleton kpi-skeleton" />
            </div>
          ) : (
            <div className="dash-combined-scores">
              {ANALYSTS.map((analyst) => {
                const out = latestByAgent.get(analyst.id);
                return (
                  <div className="dash-combined-score" key={analyst.id}>
                    <span className="muted">{analyst.label}</span>
                    <strong>
                      {out && out.score !== null ? Math.round(out.score) : '—'}
                    </strong>
                    <span className="muted">
                      {out ? out.status : 'not run yet'}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          <button className="btn btn-primary" onClick={() => go('/intelligence/summary')}>
            Open Combined Summary →
          </button>
        </div>
      </section>
    </section>
  );
}