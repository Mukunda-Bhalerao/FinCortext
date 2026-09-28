import { useEffect, useRef, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import PreparationStatus from '../../components/common/PreparationStatus';
import { sameSymbol, useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput } from '../../types/api';

interface AgentPageProps {
  agentId: 'firm_analyst' | 'industry_analyst' | 'sentiment_analyst';
  title: string;
  description: string;
  methodologyDoc: string;
  prerequisites: string[];
}

/** Shared page for one implemented analyst: run + explain output honestly.
 *
 * The selected company is shared session-wide (mirrored to `?symbol=` so it
 * carries across the demo flow), and the last result per company is kept —
 * returning to this page shows the previous result with its timestamp instead
 * of demanding a fresh model run.
 */
export default function AgentPage({
  agentId,
  title,
  description,
  methodologyDoc,
  prerequisites,
}: AgentPageProps) {
  const { symbol, runOf, runErrorOf, recordRun, recordRunError } = useFinCortext();
  // Tracks the selected company across async runs: a run started for TCS
  // must never paint TCS data under a RELIANCE header if the user switches
  // mid-flight. The run is still recorded under its own symbol.
  const symbolRef = useRef(symbol);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

  const [output, setOutput] = useState<AgentOutput | null>(() => runOf(symbol, agentId) ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ forSymbol: string; message: string } | null>(() => {
    const message = runErrorOf(symbol, agentId);
    return message ? { forSymbol: symbol, message } : null;
  });

  // Displayed result/error always belongs to the CURRENT company: the raw
  // state may briefly hold another company's run (switch mid-flight), which
  // must never be mistaken for this company's result.
  const cached = runOf(symbol, agentId);
  const visibleOutput =
    output && sameSymbol(output.entity_id, symbol) ? output : (cached ?? null);
  const visibleError =
    error && sameSymbol(error.forSymbol, symbol)
      ? error.message
      : (runErrorOf(symbol, agentId) ?? null);

  const run = async () => {
    const requested = symbol;
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run(agentId, requested);
      recordRun(requested, agentId, result);
      if (sameSymbol(symbolRef.current, requested)) setOutput(result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      recordRunError(requested, agentId, message);
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
      <h2>{title}</h2>
      <p className="muted page-description">
        {description} Analysing <strong>{symbol}</strong> — change the company in the
        search bar above.
      </p>

      <PreparationStatus symbol={symbol} />

      <div className="run-bar">
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
        <h4>What this analyst uses</h4>
        <ul>
          {prerequisites.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
        <p className="muted">
          Missing data is never fabricated — unavailable factors are listed as
          limitations. {methodologyDoc}
        </p>
      </div>

      {visibleError && <p className="error-text">Error: {visibleError}</p>}

      {visibleOutput && <AgentOutputCard output={visibleOutput} />}

      {!visibleOutput && !visibleError && !loading && (
        <p className="muted">Select a company and run the analysis to see results.</p>
      )}
    </section>
  );
}
