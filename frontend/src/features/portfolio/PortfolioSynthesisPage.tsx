import { useEffect, useRef, useState } from 'react';
import PortfolioViewCard from '../../components/common/PortfolioViewCard';
import { sameSymbol, useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { PortfolioView } from '../../types/api';

/** Portfolio / Central Orchestrator — synthesis of the four analysts.
 *
 *  Runs Firm + Industry + Sentiment + Macro for the selected company and
 *  explains how their views fit together (agreement, conflicts, thesis,
 *  evidence, risks, scenarios). No overall score is ever produced — the
 *  perspectives are compared, never blended. The macro perspective is
 *  market-wide (identical for every company) and is labeled as context.
 *
 *  Per-company by design: switching companies loads that company's own
 *  stored synthesis. A run started under one symbol never paints under
 *  another.
 */
export default function PortfolioSynthesisPage() {
  const { symbol } = useFinCortext();
  const symbolRef = useRef(symbol);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

  const [view, setView] = useState<PortfolioView | null>(null);
  const [viewSymbol, setViewSymbol] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingStored, setLoadingStored] = useState(true);
  const [error, setError] = useState<{ forSymbol: string; message: string } | null>(null);

  // Load this company's stored synthesis on mount / company switch.
  useEffect(() => {
    let cancelled = false;
    const requested = symbol;
    setLoadingStored(true);
    api.portfolio
      .latest(requested)
      .then((r) => {
        if (cancelled || !sameSymbol(symbolRef.current, requested)) return;
        setView(r.output);
        setViewSymbol(r.output ? requested : null);
        setError(null);
      })
      .catch(() => {
        if (cancelled || !sameSymbol(symbolRef.current, requested)) return;
        setView(null);
        setViewSymbol(null);
      })
      .finally(() => {
        if (!cancelled && sameSymbol(symbolRef.current, requested)) setLoadingStored(false);
      });
    return () => {
      cancelled = true;
    };
  }, [symbol]);

  const visibleError = error && sameSymbol(error.forSymbol, symbol) ? error.message : null;
  const isCurrent = viewSymbol === null || sameSymbol(viewSymbol, symbol);
  const visible = isCurrent ? view : null;

  const run = async () => {
    const requested = symbol;
    setLoading(true);
    setError(null);
    try {
      const result = await api.portfolio.run(requested);
      if (sameSymbol(symbolRef.current, requested)) {
        setView(result);
        setViewSymbol(requested);
      }
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      if (sameSymbol(symbolRef.current, requested)) {
        setView(null);
        setViewSymbol(null);
        setError({ forSymbol: requested, message });
      }
    } finally {
      if (sameSymbol(symbolRef.current, requested)) setLoading(false);
    }
  };

  return (
    <section className="page">
      <h2>Portfolio Synthesis</h2>
      <p className="muted page-description">
        Central Orchestrator for <strong>{symbol}</strong> — how the Firm, Industry,
        Sentiment and Macro views fit together. Agreement and disagreement are shown
        with the underlying evidence; nothing is averaged into an overall score. The
        macro backdrop is market-wide context, not a stock call.
      </p>

      <div className="run-bar">
        <button className="btn btn-primary" onClick={run} disabled={loading}>
          {loading ? 'Running…' : visible ? 'Run fresh synthesis' : 'Run synthesis'}
        </button>
      </div>

      {visible && !loading && viewSymbol && (
        <p className="muted">
          Showing synthesis for {viewSymbol} from{' '}
          {new Date(visible.generated_at).toLocaleString()} — run again for a fresh synthesis.
        </p>
      )}

      <div className="prereq-card">
        <h4>What this synthesis uses</h4>
        <ul>
          <li>Firm Analyst (company fundamentals + market behaviour).</li>
          <li>Industry Analyst (sector/peer-relative view).</li>
          <li>Sentiment Analyst (relevant financial-news tone).</li>
          <li>Macro Analyst (market-wide environment — same for every company).</li>
          <li>Missing or DEGRADED analyst views are flagged explicitly, never hidden.</li>
        </ul>
        <p className="muted">Deterministic synthesis v1 — compared, never blended.</p>
      </div>

      {visibleError && <p className="error-text">Error: {visibleError}</p>}

      {loadingStored ? (
        <p className="muted">Loading stored synthesis…</p>
      ) : (
        visible && <PortfolioViewCard view={visible} />
      )}

      {!visible && !visibleError && !loading && !loadingStored && (
        <p className="muted">
          No stored synthesis for {symbol} yet. Run the synthesis to explain how the four
          analyst views fit together — nothing is inferred from missing data.
        </p>
      )}
    </section>
  );
}
