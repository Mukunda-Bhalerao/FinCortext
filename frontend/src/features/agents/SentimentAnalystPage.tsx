import { useEffect, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import CompanySelector from '../../components/common/CompanySelector';
import StatusBadge from '../../components/common/StatusBadge';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput, NewsStatusResponse } from '../../types/api';

/** Sentiment Analyst — news retrieval status + agent run. */
export default function SentimentAnalystPage() {
  const [symbol, setSymbol] = useState('TCS');
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
        Local FinBERT financial sentiment over stored, relevant news articles —
        recency-weighted, deterministic aggregation. No paid LLM API.
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
          <h4>News provider</h4>
          <p>
            <StatusBadge status={newsStatus.configured ? 'LIVE' : 'UNAVAILABLE'} />{' '}
            <span className="muted">{newsStatus.message ?? 'Configured via NEWS_API_KEY.'}</span>
          </p>
          <p className="muted">
            Without NEWS_API_KEY the agent reports UNAVAILABLE — it never
            fabricates news. The first sentiment run downloads the local FinBERT
            model (~440 MB) into the configured cache directory.
          </p>
        </div>
      )}

      {message && <p className="muted">{message}</p>}
      {error && <p className="error-text">Error: {error}</p>}

      {output && <AgentOutputCard output={output} />}

      {!output && !error && !loading && (
        <p className="muted">
          Fetch news (requires NEWS_API_KEY), then run the analysis. Stored
          articles are reused across runs.
        </p>
      )}
    </section>
  );
}