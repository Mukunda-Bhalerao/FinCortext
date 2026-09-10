import { useEffect, useRef, useState } from 'react';
import MacroOutputCard from '../../components/common/MacroOutputCard';
import { sameSymbol, useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { MacroOutput } from '../../types/api';

/** Macro Analyst — the market-wide environment view.
 *
 *  The result is identical for every company (macro data is not keyed by
 *  symbol), so switching companies never invalidates it — the page simply
 *  notes the request context. A run started under one symbol never paints
 *  an error under another.
 */
export default function MacroAnalystPage() {
  const { symbol } = useFinCortext();
  const symbolRef = useRef(symbol);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

  const [output, setOutput] = useState<MacroOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ forSymbol: string; message: string } | null>(null);

  const visibleError =
    error && sameSymbol(error.forSymbol, symbol) ? error.message : null;

  const run = async () => {
    const requested = symbol;
    setLoading(true);
    setError(null);
    try {
      const result = await api.macro.run(requested);
      if (sameSymbol(symbolRef.current, requested)) setOutput(result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      if (sameSymbol(symbolRef.current, requested)) {
        setOutput(null);
        setError({ forSymbol: requested, message });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="page">
      <h2>Macro Analyst</h2>
      <p className="muted page-description">
        Deterministic view of the Indian macro environment — growth, inflation,
        rates, liquidity, policy, global markets and dated events. Market-wide:
        the same result applies to <strong>{symbol}</strong> and every other
        company. This is an environment signal, never a stock recommendation.
      </p>

      <div className="run-bar">
        <button className="btn btn-primary" onClick={run} disabled={loading}>
          {loading ? 'Running…' : output ? 'Run fresh analysis' : 'Run analysis'}
        </button>
      </div>

      {output && !loading && (
        <p className="muted">
          Showing result from {new Date(output.generated_at).toLocaleString()} — run again
          for a fresh analysis.
        </p>
      )}

      <div className="prereq-card">
        <h4>What this analyst uses</h4>
        <ul>
          <li>MoSPI GDP and CPI releases plus RBI repo-rate decisions (curated official history with per-row provenance).</li>
          <li>Market gauges (USD/INR, Brent crude, US 10-year yield, India VIX) from stored market data.</li>
          <li>Liquidity and fiscal event feeds are not configured — those gaps stay visible as unavailable.</li>
          <li>Missing inputs are reported as limitations — values are never fabricated.</li>
        </ul>
        <p className="muted">
          Deterministic methodology v1 — documented benchmarks, materiality floors and
          majority-vote signal rules.
        </p>
      </div>

      {visibleError && <p className="error-text">Error: {visibleError}</p>}

      {output && <MacroOutputCard output={output} />}

      {!output && !visibleError && !loading && (
        <p className="muted">Run the analysis to see the current macro environment view.</p>
      )}
    </section>
  );
}
