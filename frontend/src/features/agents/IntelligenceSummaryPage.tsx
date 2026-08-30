import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import CompanySelector from '../../components/common/CompanySelector';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput } from '../../types/api';

const AGENTS = [
  { id: 'firm_analyst', label: 'Firm Analyst' },
  { id: 'industry_analyst', label: 'Industry Analyst' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst' },
] as const;

/** Combined intelligence: run all three implemented agents, show scores together.
 *
 * The selected company is kept in the URL (`?symbol=`) so a choice made on
 * the Dashboard or any intelligence page carries across the demo flow.
 */
export default function IntelligenceSummaryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const symbol = searchParams.get('symbol') ?? 'TCS';
  const setSymbol = (next: string) =>
    setSearchParams(next ? { symbol: next } : {}, { replace: true });
  const [outputs, setOutputs] = useState<Record<string, AgentOutput | { error: string }>>({});
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const runAll = async () => {
    setRunning(true);
    setRunError(null);
    setOutputs({});
    const results: Record<string, AgentOutput | { error: string }> = {};
    for (const agent of AGENTS) {
      try {
        results[agent.id] = await api.agents.run(agent.id, symbol);
      } catch (e) {
        results[agent.id] = {
          error: e instanceof ApiRequestError ? e.message : String(e),
        };
      }
      setOutputs({ ...results });
    }
    setRunning(false);
  };

  const scoreOf = (id: string): number | null => {
    const out = outputs[id];
    if (!out || 'error' in out) return null;
    return out.score;
  };

  const anyResult = Object.keys(outputs).length > 0;

  return (
    <section className="page">
      <h2>Combined Intelligence Summary</h2>
      <p className="muted page-description">
        Runs the three analysts for the selected company and shows their
        standardized scores side by side. Each analyst is independent — they
        share only the transparent AgentOutput contract.
      </p>

      <div className="run-bar">
        <CompanySelector value={symbol} onChange={setSymbol} />
        <button className="btn btn-primary" onClick={runAll} disabled={running || !symbol}>
          {running ? 'Running all analysts…' : 'Run all analysts'}
        </button>
      </div>

      {runError && <p className="error-text">{runError}</p>}

      {anyResult && (
        <div className="card summary-card">
          <h3>Scores — {symbol}</h3>
          <div className="summary-scores">
            {AGENTS.map((agent) => {
              const score = scoreOf(agent.id);
              const out = outputs[agent.id];
              const failed = out && 'error' in out;
              return (
                <div key={agent.id} className="summary-score">
                  <span className="muted">{agent.label}</span>
                  <strong className={score === null ? 'muted' : ''}>
                    {failed ? 'error' : score === null ? 'unavailable' : score.toFixed(0)}
                  </strong>
                </div>
              );
            })}
          </div>
          <p className="muted">
            Each perspective is reported with its own evidence and limitations —
            FinCortext does not generate portfolio recommendations or weights.
          </p>
        </div>
      )}

      <div className="agent-grid">
        {AGENTS.map((agent) => {
          const out = outputs[agent.id];
          if (!out) return null;
          if ('error' in out) {
            return (
              <div key={agent.id} className="card">
                <h3>{agent.label}</h3>
                <p className="error-text">{out.error}</p>
              </div>
            );
          }
          return <AgentOutputCard key={agent.id} output={out} />;
        })}
      </div>

      {!anyResult && !running && (
        <p className="muted">
          Select a company and run all analysts. Analysts with missing data
          report UNAVAILABLE honestly instead of producing fake scores.
        </p>
      )}
    </section>
  );
}