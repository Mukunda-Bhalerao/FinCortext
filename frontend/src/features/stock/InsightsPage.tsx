import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import StatusBadge from '../../components/common/StatusBadge';
import { useFinCortext } from '../../app/FinCortextContext';
import { api } from '../../services/api';
import type { AgentOutput, AgentOutputSummary, MacroOutput } from '../../types/api';

const ANALYSTS = [
  { id: 'firm_analyst', label: 'Firm Analyst' },
  { id: 'industry_analyst', label: 'Industry Analyst' },
  { id: 'sentiment_analyst', label: 'Sentiment Analyst' },
] as const;

function factorLabel(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function signalLabel(signal: string): string {
  return signal.replace(/_/g, ' ');
}

interface ParsedFactors {
  factors?: { name: string; contribution: number | null; available: boolean; detail?: string }[];
  data_limitations?: string[];
}

export interface InsightItem {
  analyst: string;
  factor: string | null;
  text: string;
}

/** Deterministic insights derived ONLY from stored agent outputs.
 *  Every item traces back to a real AgentOutput factor/limitation —
 *  nothing is invented, no guaranteed-outcome language is used. */
export function buildInsights(
  companyOutputs: AgentOutputSummary[],
): { opportunities: InsightItem[]; risks: InsightItem[]; stored: number; degraded: number } {
  const opportunities: InsightItem[] = [];
  const risks: InsightItem[] = [];
  let degraded = 0;

  for (const row of companyOutputs) {
    const label = ANALYSTS.find((a) => a.id === row.agent_id)?.label ?? row.agent_id;
    let parsed: ParsedFactors | null = null;
    if (row.factors_json) {
      try {
        parsed = JSON.parse(row.factors_json);
      } catch {
        parsed = null;
      }
    }
    if (row.status !== 'OK') degraded += 1;
    if (parsed?.factors) {
      for (const f of parsed.factors) {
        if (!f.available) {
          risks.push({
            analyst: label,
            factor: factorLabel(f.name),
            text: f.detail || `${factorLabel(f.name)} is unavailable — no analyzable data.`,
          });
        } else if (typeof f.contribution === 'number' && f.contribution > 0) {
          opportunities.push({
            analyst: label,
            factor: factorLabel(f.name),
            text: f.detail || `${factorLabel(f.name)} supports the ${label.toLowerCase()} view.`,
          });
        } else if (typeof f.contribution === 'number' && f.contribution < 0) {
          risks.push({
            analyst: label,
            factor: factorLabel(f.name),
            text: f.detail || `${factorLabel(f.name)} weighs against the ${label.toLowerCase()} view.`,
          });
        }
      }
    }
    for (const lim of parsed?.data_limitations ?? []) {
      risks.push({ analyst: label, factor: null, text: lim });
    }
  }
  return {
    opportunities,
    risks,
    stored: companyOutputs.filter((o) => o.score !== null).length,
    degraded,
  };
}

/** Insights — risks, opportunities and signals derived from the stored
 *  analyst outputs. The four analysts run behind the scenes; their stored
 *  outputs feed this page. Every item is evidence-based; nothing is a
 *  guaranteed outcome. */
export default function InsightsPage() {
  const {
    symbol,
    entryFor,
    outputsOf,
    outputsErrorOf,
    ensureOutputs,
    runErrorOf,
    recordRun,
    recordRunError,
  } = useFinCortext();

  const outputs = outputsOf(symbol);
  const outputsError = outputsErrorOf(symbol);
  const loading = outputs === undefined && outputsError === null;
  const entry = entryFor(symbol);

  const [macro, setMacro] = useState<MacroOutput | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  useEffect(() => {
    ensureOutputs(symbol).catch(() => undefined);
  }, [symbol, ensureOutputs]);

  useEffect(() => {
    let cancelled = false;
    api.macro
      .latest()
      .then((r) => {
        if (!cancelled) setMacro(r.output ?? null);
      })
      .catch(() => {
        if (!cancelled) setMacro(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Latest stored output per analyst (rows arrive newest-first).
  const latestByAgent = useMemo(() => {
    const map = new Map<string, AgentOutputSummary>();
    const sorted = [...(outputs ?? [])].sort((a, b) =>
      (b.generated_at ?? '').localeCompare(a.generated_at ?? ''),
    );
    for (const out of sorted) {
      if (!map.has(out.agent_id)) map.set(out.agent_id, out);
    }
    return map;
  }, [outputs]);

  const insights = useMemo(() => buildInsights([...latestByAgent.values()]), [latestByAgent]);

  const runAgent = (agentId: string) => {
    if (running) return;
    recordRunError(symbol, agentId, '');
    setRunning(agentId);
    api.agents
      .run(agentId, symbol)
      .then((out: AgentOutput) => {
        recordRun(symbol, agentId, out);
        setRunning(null);
      })
      .catch((e: Error) => {
        recordRunError(symbol, agentId, e.message);
        setRunning(null);
      });
  };

  const firstError = ANALYSTS.map((a) => runErrorOf(symbol, a.id)).find((e) => e) ?? outputsError;

  return (
    <section className="page">
      <header className="card dash-head fade-in">
        <div className="dash-identity">
          <div className="term-symbol">{symbol}</div>
          <div>
            <div className="term-name">{entry?.name ?? symbol}</div>
            <div className="term-chips">
              <span className="chip">Risks · Opportunities · Signals</span>
            </div>
          </div>
        </div>
        <div className="dash-pricecol">
          <div className="muted">Stored intelligence views</div>
          <div className="term-price" style={{ fontSize: '1.4rem' }}>
            {loading ? '…' : `${insights.stored} of 3`}
          </div>
          {insights.degraded > 0 && <StatusBadge status="DEGRADED" />}
        </div>
        <div className="insights-actions">
          {ANALYSTS.map((a) => (
            <button key={a.id} className="btn" onClick={() => runAgent(a.id)} disabled={running !== null}>
              {running === a.id ? 'Running…' : `▶ ${a.label.replace(' Analyst', '')}`}
            </button>
          ))}
        </div>
      </header>

      {firstError && <p className="error-text fade-in">{firstError}</p>}

      {/* Signals — backed by stored outputs only */}
      <div className="card fade-in" style={{ animationDelay: '0.04s' }}>
        <div className="dash-heading">
          <h3>Signals</h3>
        </div>
        <p className="muted dash-section-note">
          Each signal is a stored analyst result with its factors, evidence and
          limitations attached — confidence reflects data coverage.
        </p>
        {loading ? (
          <div className="skeleton skeleton-line" />
        ) : latestByAgent.size === 0 ? (
          <div className="dash-empty">
            <p className="muted">
              No analyst results stored for {entry?.name ?? symbol} yet. Run an
              analyst above — every signal shown here comes from a real stored run.
            </p>
          </div>
        ) : (
          <div className="summary-grid-live">
            {ANALYSTS.map((a) => {
              const out = latestByAgent.get(a.id);
              if (!out) {
                return (
                  <div key={a.id} className="summary-card-live summary-card-missing">
                    <div className="summary-card-label">{a.label}</div>
                    <div className="muted">Not run yet — use the button above.</div>
                  </div>
                );
              }
              return (
                <div key={a.id} className={`summary-card-live signal-${out.signal}`}>
                  <div className="summary-card-label">{a.label}</div>
                  <div className="summary-card-score">
                    {out.score === null ? '—' : `${Math.round(out.score)}/100`}
                  </div>
                  <div className="summary-card-signal">{signalLabel(out.signal)}</div>
                  <div className="muted summary-card-meta">
                    confidence {Math.round(out.confidence * 100)}% · {out.status}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <p className="muted dash-section-note">
          Full evidence and limitations for each view:{' '}
          <Link to={`/intelligence/firm?symbol=${encodeURIComponent(symbol)}`}>Firm</Link>
          {' · '}
          <Link to={`/intelligence/industry?symbol=${encodeURIComponent(symbol)}`}>Industry</Link>
          {' · '}
          <Link to={`/intelligence/sentiment?symbol=${encodeURIComponent(symbol)}`}>Sentiment</Link>
          {' · '}
          <Link to={`/portfolio?symbol=${encodeURIComponent(symbol)}`}>Portfolio Intelligence</Link>
        </p>
      </div>

      {/* Market environment — context only, never a stock call */}
      {macro && (
        <div className="card fade-in" style={{ animationDelay: '0.06s' }}>
          <div className="dash-heading">
            <h3>Market Environment</h3>
            <span className={`chip ${macro.overall_signal === 'positive' ? 'chip-sector' : ''}`}>
              {signalLabel(macro.overall_signal)}
            </span>
          </div>
          <p className="muted dash-section-note">
            Market-wide context for every company — an environment view, never a
            recommendation for any stock.
            {typeof macro.score === 'number' && ` Environment score ${Math.round(macro.score)}/100.`}
          </p>
        </div>
      )}

      {/* Opportunities — derived from real positive factors */}
      <div className="card fade-in" style={{ animationDelay: '0.08s' }}>
        <div className="dash-heading">
          <h3>Opportunities</h3>
        </div>
        {loading ? (
          <div className="skeleton skeleton-line" />
        ) : insights.opportunities.length === 0 ? (
          <div className="dash-empty">
            <p className="muted">
              {latestByAgent.size === 0
                ? 'No stored analyst results yet — run an analyst to generate evidence.'
                : 'No stored factor currently leans positive — nothing is presented without evidence.'}
            </p>
          </div>
        ) : (
          <ul className="stat-list">
            {insights.opportunities.map((item, i) => (
              <li key={i}>
                <strong>{item.factor}</strong>
                <span className="muted"> — {item.text}</span>
                <span className="muted"> ({item.analyst})</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Risks — derived from real adverse factors and stored limitations */}
      <div className="card fade-in" style={{ animationDelay: '0.12s' }}>
        <div className="dash-heading">
          <h3>Risks & Limitations</h3>
        </div>
        {loading ? (
          <div className="skeleton skeleton-line" />
        ) : insights.risks.length === 0 ? (
          <div className="dash-empty">
            <p className="muted">
              {latestByAgent.size === 0
                ? 'No stored analyst results yet — run an analyst to generate evidence.'
                : 'No stored factor currently leans negative and no limitations were recorded.'}
            </p>
          </div>
        ) : (
          <ul className="stat-list">
            {insights.risks.map((item, i) => (
              <li key={i}>
                {item.factor && <strong>{item.factor}</strong>}
                {item.factor ? (
                  <span className="muted"> — {item.text}</span>
                ) : (
                  <span className="muted">{item.text}</span>
                )}
                <span className="muted"> ({item.analyst})</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
