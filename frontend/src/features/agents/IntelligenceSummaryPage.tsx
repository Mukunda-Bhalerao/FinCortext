import { useEffect, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import { useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput } from '../../types/api';

const AGENTS = [
  { id: 'firm_analyst', label: 'Firm Analyst' },
  { id: 'industry_analyst', label: 'Industry Analyst' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst' },
] as const;

type Entry = AgentOutput | { error: string };

/** Combined intelligence: run all three implemented agents, show scores together.
 *
 * Company selection and every result are shared session-wide — navigating
 * away and back restores the previous results with no re-run.
 */
export default function IntelligenceSummaryPage() {
  const { symbol, runOf, runErrorOf, recordRun, recordRunError } = useFinCortext();
  const restore = (s: string): Record<string, Entry> => {
    const restored: Record<string, Entry> = {};
    for (const agent of AGENTS) {
      const cached = runOf(s, agent.id);
      if (cached) restored[agent.id] = cached;
      else {
        const err = runErrorOf(s, agent.id);
        if (err) restored[agent.id] = { error: err };
      }
    }
    return restored;
  };
  const [outputs, setOutputs] = useState<Record<string, Entry>>(() => restore(symbol));
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(() => Object.keys(restore(symbol)).length > 0);

  useEffect(() => {
    const restored = restore(symbol);
    setOutputs(restored);
    setFromCache(Object.keys(restored).length > 0);
    setRunError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const runAll = async () => {
    setRunning(true);
    setRunError(null);
    setOutputs({});
    setFromCache(false);
    const results: Record<string, Entry> = {};
    for (const agent of AGENTS) {
      try {
        const out = await api.agents.run(agent.id, symbol);
        results[agent.id] = out;
        recordRun(symbol, agent.id, out);
      } catch (e) {
        const message = e instanceof ApiRequestError ? e.message : String(e);
        results[agent.id] = { error: message };
        recordRunError(symbol, agent.id, message);
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
        The three analysts read <strong>{symbol}</strong> through different evidence —
        fundamentals, industry peers, and news tone. Their views sit side by side;
        FinCortext does not blend them into one overall score. Change the company
        in the search bar above.
      </p>

      <div className="run-bar">
        <button className="btn btn-primary" onClick={runAll} disabled={running || !symbol}>
          {running ? 'Running all analysts…' : anyResult ? 'Run fresh analysis' : 'Run all analysts'}
        </button>
      </div>

      {runError && <p className="error-text">{runError}</p>}

      {anyResult && fromCache && !running && (
        <p className="muted">
          Showing previous results for {symbol} — run again for a fresh analysis.
        </p>
      )}

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
