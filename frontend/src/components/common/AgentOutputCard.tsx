import type { AgentOutput } from '../../types/api';

const SIGNAL_CLASS: Record<string, string> = {
  strong_buy: 'signal-strong-buy',
  buy: 'signal-buy',
  neutral: 'signal-neutral',
  sell: 'signal-sell',
  strong_sell: 'signal-strong-sell',
  unavailable: 'signal-unavailable',
};

function ScoreDial({ score, status }: { score: number | null; status: string }) {
  if (score === null) {
    return (
      <div className="score-dial unavailable">
        <span className="score-value">—</span>
        <span className="score-label">{status}</span>
      </div>
    );
  }
  return (
    <div className={`score-dial ${score >= 55 ? 'positive' : score <= 45 ? 'negative' : ''}`}>
      <span className="score-value">{score.toFixed(0)}</span>
      <span className="score-label">/ 100</span>
    </div>
  );
}

/** Full, honest rendering of one standardized AgentOutput. */
export default function AgentOutputCard({ output }: { output: AgentOutput }) {
  const availableFactors = output.factors.filter((f) => f.available);
  const missingFactors = output.factors.filter((f) => !f.available);

  return (
    <article className={`agent-card status-${output.status.toLowerCase()}`}>
      <header className="agent-card-header">
        <ScoreDial score={output.score} status={output.status} />
        <div className="agent-card-title">
          <h3>{output.agent_id.replace(/_/g, ' ')}</h3>
          <p>
            <span className={`badge ${SIGNAL_CLASS[output.signal] ?? ''}`}>
              {output.signal.replace(/_/g, ' ').toUpperCase()}
            </span>{' '}
            <span className={`badge badge-status-${output.status.toLowerCase()}`}>
              {output.status}
            </span>{' '}
            <span className="muted">confidence {(output.confidence * 100).toFixed(0)}%</span>
          </p>
        </div>
      </header>

      <p className="agent-rationale">{output.rationale}</p>

      {output.factors.length > 0 && (
        <section>
          <h4>Contributing factors</h4>
          <ul className="factor-list">
            {availableFactors.map((f) => (
              <li key={f.name}>
                <strong>{f.name.replace(/_/g, ' ')}</strong>
                {f.value !== null && (
                  <span className="muted"> value: {f.value}</span>
                )}
                {f.contribution !== null && (
                  <span className="muted"> · contribution: {f.contribution.toFixed(1)}</span>
                )}
                {f.detail && <p className="factor-detail">{f.detail}</p>}
              </li>
            ))}
            {missingFactors.map((f) => (
              <li key={f.name} className="factor-missing">
                <strong>{f.name.replace(/_/g, ' ')}</strong> — not computed
                {f.detail ? <p className="factor-detail">{f.detail}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      )}

      {output.evidence.length > 0 && (
        <section>
          <h4>Evidence</h4>
          <ul className="evidence-list">
            {output.evidence.map((e, i) => (
              <li key={`${e.reference}-${i}`}>
                <span className="badge badge-evidence">{e.data_type}</span>{' '}
                {e.note ?? e.reference}
                {e.source_name && <span className="muted"> — {e.source_name}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {output.data_limitations.length > 0 && (
        <section>
          <h4>Limitations</h4>
          <ul className="limitations-list">
            {output.data_limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="agent-card-footer muted">
        Generated {new Date(output.generated_at).toLocaleString()} · methodology:{' '}
        {String(output.provenance?.methodology ?? output.data_version)}
      </footer>
    </article>
  );
}