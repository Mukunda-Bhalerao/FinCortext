import { useEffect, useRef, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import StatusBadge from '../../components/common/StatusBadge';
import { sameSymbol, useFinCortext } from '../../app/FinCortextContext';
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
    newsOf,
    newsErrorOf,
    ensureNews,
  } = useFinCortext();
  // Mid-flight guard (as in AgentPage): a run/fetch started for one company
  // must never paint under another company's header after a switch.
  const symbolRef = useRef(symbol);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

  const [output, setOutput] = useState<AgentOutput | null>(() => runOf(symbol, AGENT_ID) ?? null);
  const [newsStatus, setNewsStatus] = useState<NewsStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<{ forSymbol: string; text: string } | null>(null);
  const [error, setError] = useState<{ forSymbol: string; message: string } | null>(() => {
    const m = runErrorOf(symbol, AGENT_ID);
    return m ? { forSymbol: symbol, message: m } : null;
  });

  const cached = runOf(symbol, AGENT_ID);
  const visibleOutput =
    output && sameSymbol(output.entity_id, symbol) ? output : (cached ?? null);
  const visibleError =
    error && sameSymbol(error.forSymbol, symbol)
      ? error.message
      : (runErrorOf(symbol, AGENT_ID) ?? null);
  const visibleMessage =
    message && sameSymbol(message.forSymbol, symbol) ? message.text : null;

  // Stored articles for THIS company (drives the honest data-status line).
  const storedNews = newsOf(symbol);
  const storedNewsError = newsErrorOf(symbol);
  useEffect(() => {
    ensureNews(symbol).catch(() => undefined);
  }, [symbol, ensureNews]);

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
    const requested = symbol;
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run(AGENT_ID, requested);
      recordRun(requested, AGENT_ID, result);
      if (sameSymbol(symbolRef.current, requested)) setOutput(result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      recordRunError(requested, AGENT_ID, message);
      if (sameSymbol(symbolRef.current, requested)) {
        setOutput(null);
        setError({ forSymbol: requested, message });
      }
    } finally {
      setLoading(false);
    }
  };

  const refreshNews = async () => {
    const requested = symbol;
    setRefreshing(true);
    setMessage(null);
    setError(null);
    try {
      const result = await api.news.refresh(requested);
      invalidateNews(requested);
      // Re-read this company's stored set so the status line below is fresh.
      await ensureNews(requested, true).catch(() => undefined);
      if (sameSymbol(symbolRef.current, requested)) {
        setMessage({
          forSymbol: requested,
          text:
            result.status === 'LIVE'
              ? `Stored ${result.stored} new article(s) (${result.duplicates} duplicates skipped).`
              : result.message ?? `News status: ${result.status}`,
        });
      }
    } catch (e) {
      if (sameSymbol(symbolRef.current, requested)) {
        setError({
          forSymbol: requested,
          message: e instanceof ApiRequestError ? e.message : String(e),
        });
      }
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
          {loading ? 'Running…' : visibleOutput ? 'Run fresh analysis' : 'Run analysis'}
        </button>
      </div>

      {visibleOutput && !loading && (
        <p className="muted">
          Showing result from {new Date(visibleOutput.generated_at).toLocaleString()} — run again
          for a fresh analysis.
        </p>
      )}

      <div className="prereq-card">
        <h4>News data</h4>
        <p>
          {storedNews ? (
            <>
              <StatusBadge status={storedNews.status} />{' '}
              <span className="muted">
                {storedNews.count} stored article{storedNews.count === 1 ? '' : 's'} for{' '}
                {symbol}
                {storedNewsError ? ` — refresh failed: ${storedNewsError}` : ''}.
              </span>
            </>
          ) : (
            <span className="muted">
              {storedNewsError
                ? `Stored news could not be loaded: ${storedNewsError}`
                : 'Loading stored news…'}
            </span>
          )}
        </p>
        <p className="muted">
          {newsStatus === null
            ? 'News provider status unknown. '
            : newsStatus.configured
              ? 'Live financial-news retrieval is configured. '
              : 'Live news retrieval is not configured — stored articles are still used and nothing is fabricated. '}
          Only articles that mention {symbol} with financial/business context are
          scored; sponsorships, anecdotes and off-topic digests are excluded and
          counted. Stored articles are reused across runs.
        </p>
      </div>

      {visibleMessage && <p className="muted">{visibleMessage}</p>}
      {visibleError && <p className="error-text">Error: {visibleError}</p>}

      {visibleOutput && <AgentOutputCard output={visibleOutput} />}

      {!visibleOutput && !visibleError && !loading && (
        <p className="muted">
          Fetch recent news for the selected company, then run the analysis.
          Stored articles are reused across runs.
        </p>
      )}
    </section>
  );
}
