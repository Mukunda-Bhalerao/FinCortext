import type { MacroDirectionValue, MacroOutput, MacroSignalValue } from '../../types/api';

const DIRECTION_LABELS: Record<MacroDirectionValue, string> = {
  up: 'rising',
  down: 'falling',
  flat: 'flat',
  unknown: 'unknown',
};

function directionLabel(direction: MacroDirectionValue): string {
  return DIRECTION_LABELS[direction] ?? 'unknown';
}

export const MACRO_SIGNAL_CLASS: Record<MacroSignalValue, string> = {
  positive: 'signal-buy',
  neutral: 'signal-neutral',
  negative: 'signal-sell',
  unavailable: 'signal-unavailable',
};

function ScoreDial({ score, status }: { score: number | null; status: string }) {
  if (score === null || score === undefined) {
    return (
      <div className="score-dial unavailable">
        <span className="score-value">—</span>
        <span className="score-label">{status}</span>
      </div>
    );
  }
  const tone = score > 50 ? 'positive' : score < 50 ? 'negative' : '';
  return (
    <div className={`score-dial ${tone}`}>
      <span className="score-value">{score.toFixed(0)}</span>
      <span className="score-label">/ 100</span>
    </div>
  );
}

/** Full rendering of one MacroOutput — the market-wide environment view.
 *
 *  Shows the Macro Environment Score (0–100) alongside the environment
 *  signal, status and confidence — visually consistent with the company
 *  analyst cards. The score describes the macro environment only and is
 *  never a stock recommendation.
 */
export default function MacroOutputCard({ output }: { output: MacroOutput }) {
  const availableFactors = output.factors.filter((f) => f.available);
  const missingFactors = output.factors.filter((f) => !f.available);
  const throughEntries = Object.entries(output.data_through ?? {});
  const newestThrough =
    throughEntries.length > 0
      ? throughEntries.map(([, d]) => d).sort().reverse()[0]
      : null;

  return (
    <article className={`agent-card status-${output.status.toLowerCase()}`}>
      <header className="agent-card-header">
        <ScoreDial score={output.score} status={output.status} />
        <div className="agent-card-title">
          <h3>Macro Environment</h3>
          <p>
            {output.score !== null && output.score !== undefined ? (
              <span className="muted">Macro Environment Score: {output.score.toFixed(0)} / 100 · </span>
            ) : (
              <span className="muted">Macro Environment Score: unavailable · </span>
            )}
            <span className={`badge ${MACRO_SIGNAL_CLASS[output.overall_signal]}`}>
              {output.overall_signal.replace(/_/g, ' ').toUpperCase()}
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
          <h4>Macro areas</h4>
          <ul className="factor-list">
            {availableFactors.map((f) => (
              <li key={f.name}>
                <strong>{f.label}</strong>{' '}
                <span className={`badge ${MACRO_SIGNAL_CLASS[f.signal]}`}>
                  {f.signal.toUpperCase()}
                </span>
                {f.value !== null && (
                  <span className="muted">
                    {' '}value: {f.value}
                    {f.unit ? ` ${f.unit}` : ''}
                  </span>
                )}
                <span className="muted"> · direction: {directionLabel(f.direction)}</span>
                {f.data_as_of && (
                  <span className="muted"> · as of {f.data_as_of}</span>
                )}
                <span className="muted"> · confidence {(f.confidence * 100).toFixed(0)}%</span>
                {f.detail && <p className="factor-detail">{f.detail}</p>}
                {f.evidence.length > 0 && (
                  <ul className="evidence-list">
                    {f.evidence.map((e, i) => (
                      <li key={`${e.reference}-${i}`}>
                        <span className="badge badge-evidence">evidence</span>{' '}
                        {e.note ?? e.reference}
                        {e.source_name && <span className="muted"> — {e.source_name}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {f.limitations.length > 0 && (
                  <ul className="limitations-list">
                    {f.limitations.map((lim, i) => (
                      <li key={i}>{lim}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
            {missingFactors.map((f) => (
              <li key={f.name} className="factor-missing">
                <strong>{f.label}</strong> — not computed
                {f.limitations.length > 0 ? (
                  <p className="factor-detail">{f.limitations[0]}</p>
                ) : null}
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
        Analysed {new Date(output.generated_at).toLocaleString()}
        {newestThrough && <> · macro data through {newestThrough}</>}
      </footer>
    </article>
  );
}
