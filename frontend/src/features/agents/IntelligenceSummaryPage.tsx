import { useEffect, useRef, useState } from 'react';
import AgentOutputCard from '../../components/common/AgentOutputCard';
import MacroOutputCard from '../../components/common/MacroOutputCard';
import { sameSymbol, useFinCortext } from '../../app/FinCortextContext';
import { api, ApiRequestError } from '../../services/api';
import type { AgentOutput, MacroOutput } from '../../types/api';

const AGENTS = [
  { id: 'firm_analyst', label: 'Firm Analyst' },
  { id: 'industry_analyst', label: 'Industry Analyst' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst' },
] as const;

type Entry = AgentOutput | { error: string };
type MacroEntry = MacroOutput | { error: string };

/** Combined intelligence: the three company analysts plus the market-wide
 *  macro view, shown side by side with no blending.
 *
 *  Company selection and every company result are shared session-wide —
 *  navigating away and back restores the previous results with no re-run.
 *  The macro result is market-wide (identical for every company), so it
 *  persists across company switches with an explicit note; only transient
 *  macro errors clear on switch.
 */
export default function IntelligenceSummaryPage() {
  const { symbol, runOf, runErrorOf, recordRun, recordRunError } = useFinCortext();
  // Mid-flight guard: a run-all started for one company records under its
  // own symbol but never paints under another company's header.
  const symbolRef = useRef(symbol);
  useEffect(() => {
    symbolRef.current = symbol;
  }, [symbol]);

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
  // Which company the entries above belong to — anything else falls back to
  // that company's restored results, never stale foreign data.
  const [outputsSymbol, setOutputsSymbol] = useState(symbol);
  const [runningSymbol, setRunningSymbol] = useState<string | null>(null);
  const [completedRunSymbol, setCompletedRunSymbol] = useState<string | null>(null);
  const [runError, setRunError] = useState<{ forSymbol: string; message: string } | null>(null);
  // Macro view: market-wide, shared across companies. Errors are transient
  // request failures, so they clear on switch; successful results persist.
  const [macro, setMacro] = useState<MacroEntry | null>(null);
  useEffect(() => {
    setMacro((cur) => (cur && 'error' in cur ? null : cur));
  }, [symbol]);

  const running = runningSymbol !== null && sameSymbol(runningSymbol, symbol);
  const isCurrent = sameSymbol(outputsSymbol, symbol);
  const visible = isCurrent ? outputs : restore(symbol);
  const anyResult = Object.keys(visible).length > 0;
  const showCacheNote =
    anyResult &&
    !running &&
    (!isCurrent || !sameSymbol(completedRunSymbol ?? '\0', symbol));
  const visibleRunError =
    runError && sameSymbol(runError.forSymbol, symbol) ? runError.message : null;

  const runAll = async () => {
    const requested = symbol;
    setRunningSymbol(requested);
    setRunError(null);
    setOutputs({});
    setOutputsSymbol(requested);
    setCompletedRunSymbol(null);
    setMacro(null);
    const results: Record<string, Entry> = {};
    for (const agent of AGENTS) {
      try {
        const out = await api.agents.run(agent.id, requested);
        recordRun(requested, agent.id, out);
        if (sameSymbol(symbolRef.current, requested)) {
          results[agent.id] = out;
          setOutputs({ ...results });
        }
      } catch (e) {
        const message = e instanceof ApiRequestError ? e.message : String(e);
        recordRunError(requested, agent.id, message);
        if (sameSymbol(symbolRef.current, requested)) {
          results[agent.id] = { error: message };
          setOutputs({ ...results });
        }
      }
    }
    try {
      const macroOut = await api.macro.run(requested);
      if (sameSymbol(symbolRef.current, requested)) setMacro(macroOut);
    } catch (e) {
      const message = e instanceof ApiRequestError ? e.message : String(e);
      if (sameSymbol(symbolRef.current, requested)) setMacro({ error: message });
    }
    if (sameSymbol(symbolRef.current, requested)) {
      setCompletedRunSymbol(requested);
    }
    setRunningSymbol((cur) => (cur !== null && sameSymbol(cur, requested) ? null : cur));
  };

  const scoreOf = (id: string): number | null => {
    const out = visible[id];
    if (!out || 'error' in out) return null;
    return out.score;
  };

  return (
    <section className="page">
      <h2>Combined Intelligence Summary</h2>
      <p className="muted page-description">
        Four independent perspectives on <strong>{symbol}</strong> — company
        fundamentals, industry peers, news tone, plus the market-wide macro
        environment. Their views sit side by side; FinCortext does not blend
        them into one overall score. For the explained synthesis, open{' '}
        <a href={`/portfolio?symbol=${encodeURIComponent(symbol)}`}>Portfolio Synthesis →</a>.
        Change the company in the search bar above.
      </p>

      <div className="run-bar">
        <button className="btn btn-primary" onClick={runAll} disabled={running || !symbol}>
          {running ? 'Running all analysts…' : anyResult ? 'Run fresh analysis' : 'Run all analysts'}
        </button>
      </div>

      {visibleRunError && <p className="error-text">{visibleRunError}</p>}

      {showCacheNote && (
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
              const out = visible[agent.id];
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
            <div className="summary-score">
              <span className="muted">Macro Analyst</span>
              <strong className={macro && !('error' in macro) ? '' : 'muted'}>
                {macro
                  ? 'error' in macro
                    ? 'error'
                    : macro.score !== null && macro.score !== undefined
                      ? `${macro.score.toFixed(0)}`
                      : macro.overall_signal.toUpperCase()
                  : '—'}
              </strong>
              {macro && !('error' in macro) && (
                <span className="muted">{macro.overall_signal.toUpperCase()}</span>
              )}
            </div>
          </div>
          <p className="muted">
            Each perspective is reported with its own evidence and limitations —
            the <a href={`/portfolio?symbol=${encodeURIComponent(symbol)}`}>Portfolio Synthesis</a>{' '}
            explains how they fit together without blending them.
          </p>
        </div>
      )}

      <div className="agent-grid">
        {AGENTS.map((agent) => {
          const out = visible[agent.id];
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
        {macro &&
          ('error' in macro ? (
            <div className="card">
              <h3>Macro Analyst</h3>
              <p className="error-text">{macro.error}</p>
            </div>
          ) : (
            <MacroOutputCard key="macro_analyst" output={macro} />
          ))}
      </div>

      {!anyResult && !macro && !running && (
        <p className="muted">
          Select a company and run all analysts. Analysts with missing data
          report UNAVAILABLE honestly instead of producing fake scores.
        </p>
      )}
    </section>
  );
}
