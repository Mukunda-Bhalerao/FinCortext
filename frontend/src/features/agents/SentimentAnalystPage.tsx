import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput, NewsStatusResponse } from '../../types/api';

/** Sentiment Analyst — news retrieval status + agent run.
 *
 * The selected company is kept in the URL (`?symbol=`) so a choice made on
 * the Dashboard or any intelligence page carries across the demo flow.
 */
export default function SentimentAnalystPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const symbol = searchParams.get('symbol') ?? 'TCS';
  const setSymbol = (next: string) =>
    setSearchParams(next ? { symbol: next } : {}, { replace: true });
  const [output, setOutput] = useState<AgentOutput | null>(null);
  const [newsStatus, setNewsStatus] = useState<NewsStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadNewsStatus = () => {
    api.news
      .status()
      .then(setNewsStatus)
      .catch(() => setNewsStatus(null));
  };

  useEffect(() => {
    loadNewsStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run('sentiment_analyst', symbol);
      setOutput(result);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : String(e));
      setOutput(null);
    } finally {
      setLoading(false);
    }
  };

  const refreshNews = async () => {
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.news.refresh(symbol);
      setMessage(
        result.status === 'LIVE'
          ? `Stored ${result.stored} new article(s) (${result.duplicates} duplicates skipped).`
          : result.message ?? `News status: ${result.status}`,
      );
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setRefreshing(false);
      loadNewsStatus();
    }
  };

  return (
    <section className="page">
      <h2>Sentiment Analyst</h2>
      <p className="muted page-description">
        Financial-news sentiment for the selected company — recency-weighted,
        deterministic aggregation over relevant stored articles, scored by a
        local financial-language model.
      </p>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button className="btn" onClick={refreshNews} disabled={refreshing || !symbol}>
          {refreshing ? 'Fetching news…' : 'Fetch news'}
        </button>
        <button className="btn btn-primary" onClick={run} disabled={loading || !symbol}>
          {loading ? 'Running…' : 'Run analysis'}
        </button>
      </div>

      {newsStatus && (
        <div className="prereq-card">
          <h4>News data</h4>
          <p>
            <StatusBadge status={newsStatus.configured ? 'LIVE' : 'UNAVAILABLE'} />{' '}
            <span className="muted">
              {newsStatus.configured
                ? 'Live financial-news retrieval is configured.'
                : 'Live news retrieval is not configured — stored articles are still used and nothing is fabricated.'}
            </span>
          </p>
          <p className="muted">
            Stored articles are reused across runs; the first analysis loads the
            local sentiment model (one-time setup). Missing data is reported
            honestly — news is never fabricated.
          </p>
        </div>
      )}

      {message && <p className="muted">{message}</p>}
      {error && <p className="error-text">Error: {error}</p>}

      {output && <AgentOutputCard output={output} />}

      {!output && !error && !loading && (
        <p className="muted">
          Fetch recent news for the selected company, then run the analysis.
          Stored articles are reused across runs.
        </p>
      )}
    </section>
  );
}