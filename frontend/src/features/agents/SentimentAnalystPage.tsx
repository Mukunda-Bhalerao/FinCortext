import { useEffect, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput, NewsStatusResponse } from '../../types/api';

const AGENT_ID = 'sentiment_analyst';

/** Sentiment Analyst — news retrieval status + agent run.
 *
 * Company selection and results are shared session-wide; returning to this
 * page restores the previous result instead of re-running the model.
 */
export default function SentimentAnalystPage() {
  const {
    symbol,
    runOf,
    runErrorOf,
    recordRun,
    recordRunError,
    invalidateNews,
  } = useFinCortext();
  const [output, setOutput] = useState<AgentOutput | null>(() => runOf(symbol, AGENT_ID) ?? null);
  const [newsStatus, setNewsStatus] = useState<NewsStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(() => runErrorOf(symbol, AGENT_ID) ?? null);

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

  useEffect(() => {
    setOutput(runOf(symbol, AGENT_ID) ?? null);
    setError(runErrorOf(symbol, AGENT_ID) ?? null);
    setMessage(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run(AGENT_ID, symbol);
      setOutput(result);
      recordRun(symbol, AGENT_ID, result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      setError(message);
      setOutput(null);
      recordRunError(symbol, AGENT_ID, message);
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
      invalidateNews(symbol);
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
        Financial-news sentiment for <strong>{symbol}</strong> — recency-weighted,
        deterministic aggregation over relevant stored articles, scored by a
        local financial-language model. Change the company in the search bar above.
      </p>

      <div className="run-bar">
        <button className="btn" onClick={refreshNews} disabled={refreshing || !symbol}>
          {refreshing ? 'Fetching news…' : 'Fetch news'}
        </button>
        <button className="btn btn-primary" onClick={run} disabled={loading || !symbol}>
          {loading ? 'Running…' : output ? 'Run fresh analysis' : 'Run analysis'}
        </button>
      </div>

      {output && !loading && (
        <p className="muted">
          Showing result from {new Date(output.generated_at).toLocaleString()} — run again
          for a fresh analysis.
        </p>
      )}

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
