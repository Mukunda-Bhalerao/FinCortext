import { useCallback, useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { api, ApiRequestError } from '../../services/api';
import type { PriceSeriesResponse, RefreshResult } from '../../types/api';

/** Market Data — inspect stored prices, refresh from provider, honest status. */
export default function MarketDataPage() {
  const [symbol, setSymbol] = useState('TCS');
  const [series, setSeries] = useState<PriceSeriesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((sym: string) => {
    if (!sym) return;
    setLoading(true);
    setError(null);
    api.market
      .prices(sym)
      .then(setSeries)
      .catch((e: Error) => {
        setError(e instanceof ApiRequestError ? e.message : e.message);
        setSeries(null);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(symbol);
  }, [symbol, load]);

  const refresh = async () => {
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result: RefreshResult = await api.market.refreshSymbol(symbol);
      setMessage(
        result.status === 'LIVE'
          ? `Stored ${result.rows_stored ?? 0} bars (${result.rows_rejected ?? 0} rejected by validation).`
          : result.message ?? result.error ?? `Status: ${result.status}`,
      );
      load(symbol);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const chartData = (series?.prices ?? []).map((p) => ({
    date: p.date,
    close: p.close,
  }));

  return (
    <section className="page">
      <h2>Market Data</h2>
      <p className="muted page-description">
        Stored daily OHLCV with explicit data status. Refreshing calls the
        yfinance provider live (network required); otherwise you see cached
        data or an explicit UNAVAILABLE state.
      </p>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button className="btn btn-primary" onClick={refresh} disabled={refreshing || !symbol}>
          {refreshing ? 'Refreshing…' : 'Refresh from provider'}
        </button>
      </div>

      {message && <p className="muted">{message}</p>}
      {error && <p className="error-text">Error: {error}</p>}
      {loading && <p className="muted">Loading prices…</p>}

      {series && !loading && (
        <div className="card">
          <h3>
            {series.symbol} — {series.name}{' '}
            <StatusBadge status={series.status} />
          </h3>
          <p className="muted">
            {series.count} stored bars
            {series.latest_trade_date ? ` · latest ${series.latest_trade_date}` : ''}
          </p>
          {chartData.length > 1 ? (
            <div className="chart-container">
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                  <XAxis dataKey="date" stroke="#8fa0b8" fontSize={11} minTickGap={48} />
                  <YAxis
                    stroke="#8fa0b8"
                    fontSize={11}
                    domain={['auto', 'auto']}
                    tickFormatter={(v: number) => v.toFixed(0)}
                  />
                  <Tooltip
                    contentStyle={{ background: '#141f36', border: '1px solid #22304d' }}
                    labelStyle={{ color: '#e6ecf5' }}
                  />
                  <Line type="monotone" dataKey="close" stroke="#4f8cff" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="muted">
              Not enough stored bars for a chart. Use “Refresh from provider”
              (network required) to fetch history.
            </p>
          )}
        </div>
      )}
    </section>
  );
}