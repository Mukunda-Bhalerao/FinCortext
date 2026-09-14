import type { PortfolioView } from '../../types/api';

/** Full rendering of one PortfolioView — the Central Orchestrator synthesis.
 *
 *  Shows how the four analyst perspectives fit together for ONE company:
 *  compact per-perspective scores, agreement/conflicts, thesis, evidence,
 *  risks, conditional scenarios and the reasoning behind the interpretation.
 *  Never blends scores into an overall rating — disagreement is shown.
 */
export default function PortfolioViewCard({ view }: { view: PortfolioView }) {
  const newestEvidence =
    view.evidence
      .map((e) => e.generated_at)
      .filter((d): d is string => !!d)
      .sort()
      .reverse()[0] ?? null;

  return (
    <article className={`agent-card status-${view.status.toLowerCase()}`}>
      <header className="agent-card-header">
        <div className="agent-card-title">
          <h3>Portfolio Synthesis — {view.entity_id}</h3>
          <p>
            <span className={`badge badge-status-${view.status.toLowerCase()}`}>
              {view.status}
            </span>{' '}
            <span className="muted">
              coverage {Math.round(view.coverage * 100)}% · confidence{' '}
              {Math.round(view.confidence * 100)}%
            </span>
          </p>
          <p className="muted">
            {view.agreement.available_count} of {view.agreement.total_count} perspectives available —{' '}
            {view.agreement.summary}
          </p>
        </div>
      </header>

      <section>
        <h4>Perspectives</h4>
        <ul className="factor-list">
          {view.perspectives.map((p) => (
            <li key={p.agent_id}>
              <strong>{p.label}</strong>{' '}
              <span className="muted">
                {p.score !== null && p.score !== undefined ? `${Math.round(p.score)}/100` : 'unavailable'}
              </span>{' '}
              <span className="badge badge-evidence">{p.signal_label}</span>{' '}
              <span className={`badge badge-status-${p.status.toLowerCase()}`}>{p.status}</span>{' '}
              <span className="muted">confidence {Math.round(p.confidence * 100)}%</span>
              <p className="factor-detail">{p.takeaway}</p>
              {p.limitations.length > 0 && (
                <ul className="limitations-list">
                  {p.limitations.map((lim, i) => (
                    <li key={i}>{lim}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>Investment thesis</h4>
        <p className="agent-rationale">{view.thesis}</p>
      </section>

      {view.agreement.conflicts.length > 0 && (
        <section>
          <h4>Disagreements ({view.agreement.conflicts.length})</h4>
          <ul className="limitations-list">
            {view.agreement.conflicts.map((c, i) => (
              <li key={i}>
                <strong>{c.between.join(' vs ')}</strong> — {c.description}
              </li>
            ))}
          </ul>
        </section>
      )}

      {view.scenarios.length > 0 && (
        <section>
          <h4>Scenarios</h4>
          <ul className="factor-list">
            {view.scenarios.map((s) => (
              <li key={s.label}>
                <strong>{s.label}</strong> <span className="muted">({s.leaning})</span>
                <ul className="evidence-list">
                  {s.conditions.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
                <p className="muted">{s.note}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {view.evidence.length > 0 && (
        <section>
          <h4>Supporting evidence</h4>
          <ul className="evidence-list">
            {view.evidence.map((e, i) => (
              <li key={`${e.agent_id}-${i}`}>
                <span className="badge badge-evidence">{e.agent_id}</span>{' '}
                {e.note ?? `${e.signal ?? ''} ${e.score ?? ''}`}
                {e.status && <span className="muted"> — {e.status}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {view.risks.length > 0 && (
        <section>
          <h4>Key risks</h4>
          <ul className="limitations-list">
            {view.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      {view.data_limitations.length > 0 && (
        <section>
          <h4>Limitations</h4>
          <ul className="limitations-list">
            {view.data_limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h4>Why this interpretation</h4>
        <p className="agent-rationale">{view.rationale}</p>
      </section>

      <footer className="agent-card-footer muted">
        Synthesised {new Date(view.generated_at).toLocaleString()}
        {newestEvidence && <> · underlying views through {newestEvidence}</>}
        {' '}· methodology: {view.methodology}
      </footer>
    </article>
  );
}
