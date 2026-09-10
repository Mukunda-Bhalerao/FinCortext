import type { MacroOutput, MacroSignalValue } from '../../types/api';

export const MACRO_SIGNAL_CLASS: Record<MacroSignalValue, string> = {
  positive: 'signal-buy',
  neutral: 'signal-neutral',
  negative: 'signal-sell',
  unavailable: 'signal-unavailable',
};

export const MACRO_DIAL_CLASS: Record<MacroSignalValue, string> = {
  positive: 'positive',
  neutral: '',
  negative: 'negative',
  unavailable: 'unavailable',
};

function SignalDial({ signal, status }: { signal: MacroSignalValue; status: string }) {
  return (
    <div className={`score-dial ${MACRO_DIAL_CLASS[signal]}`}>
      <span className="score-value macro-signal">
        {signal === 'unavailable' ? '—' : signal.slice(0, 3).toUpperCase()}
      </span>
      <span className="score-label">{status}</span>
    </div>
  );
}

/** Full rendering of one MacroOutput — the market-wide environment view.
 *
 *  Deliberately shows NO numeric score: the environment signal must never
 *  read as a stock recommendation.
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
        <SignalDial signal={output.overall_signal} status={output.status} />
        <div className="agent-card-title">
          <h3>Macro Environment</h3>
          <p>
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
                </span>{' '}
                <span className={`badge ${MACRO_SIGNAL_CLASS[f.signal]}`}>
                  {f.signal.toUpperCase()}
                </span>
                {f.value !== null && (
                  <span className="muted">
                    {' '}value: {f.value}
                    {f.unit ? ` ${f.unit}` : ''}
                  </span>
                )}
                <span className="muted"> · direction: {f.direction}</span>
                {f.data_as_of && (
                  <span className="muted"> · as of {f.data_as_of}</span>
                )}
                <span className="muted"> · confidence {(f.confidence * 100).toFixed(0)}%</span>
                {f.detail && <p className="factor-detail">{f.detail}</p>}
                {f.evidence.length > 0 && (
                  <ul className="evidence-list">
                    {f.evidence.map((e, i) => (
                      <li key={`${e.reference}-${i}`}>
                        <span className="badge badge-evidence">{e.indicator_id}</span>{' '}
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
        {' '}· methodology: {output.methodology}
      </footer>
    </article>
  );
}
