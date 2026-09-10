import { useEffect, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import { useFinCortext } from '../../app/FinCortextContext';
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
  const [output, setOutput] = useState<AgentOutput | null>(() => runOf(symbol, agentId) ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(() => runErrorOf(symbol, agentId) ?? null);

  // Switching companies restores that company's previous result (if any)
  // instead of clearing the page or re-running the analysis.
  useEffect(() => {
    setOutput(runOf(symbol, agentId) ?? null);
    setError(runErrorOf(symbol, agentId) ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, agentId]);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run(agentId, symbol);
      setOutput(result);
      recordRun(symbol, agentId, result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      setError(message);
      setOutput(null);
      recordRunError(symbol, agentId, message);
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

      <div className="run-bar">
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

      {error && <p className="error-text">Error: {error}</p>}

      {output && <AgentOutputCard output={output} />}

      {!output && !error && !loading && (
        <p className="muted">Select a company and run the analysis to see results.</p>
      )}
    </section>
  );
}
