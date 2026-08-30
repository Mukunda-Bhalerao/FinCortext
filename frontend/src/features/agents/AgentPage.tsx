import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import CompanySelector from '../../components/common/CompanySelector';
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
 * The selected company is kept in the URL (`?symbol=`) so a choice made on
 * the Dashboard or any intelligence page carries across the demo flow.
 */
export default function AgentPage({
  agentId,
  title,
  description,
  methodologyDoc,
  prerequisites,
}: AgentPageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const symbol = searchParams.get('symbol') ?? 'TCS';
  const setSymbol = (next: string) =>
    setSearchParams(next ? { symbol: next } : {}, { replace: true });
  const [output, setOutput] = useState<AgentOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.agents.run(agentId, symbol);
      setOutput(result);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      setError(message);
      setOutput(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="page">
      <h2>{title}</h2>
      <p className="muted page-description">{description}</p>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button className="btn btn-primary" onClick={run} disabled={loading || !symbol}>
          {loading ? 'Running…' : 'Run analysis'}
        </button>
      </div>

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