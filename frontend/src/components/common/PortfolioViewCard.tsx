import { Link } from 'react-router-dom';
import type { PerspectiveView, PortfolioView } from '../../types/api';

const ANALYST_ROUTES: Record<string, string> = {
  firm_analyst: '/intelligence/firm',
  industry_analyst: '/intelligence/industry',
  sentiment_analyst: '/intelligence/sentiment',
  macro_analyst: '/intelligence/macro',
};

const DIRECTION_BADGE: Record<string, string> = {
  positive: 'signal-buy',
  neutral: 'signal-neutral',
  negative: 'signal-sell',
  missing: 'signal-unavailable',
};

function MiniDial({ perspective }: { perspective: PerspectiveView }) {
  if (perspective.direction === 'missing' || perspective.score === null || perspective.score === undefined) {
    return (
      <div className="score-dial unavailable">
        <span className="score-value">—</span>
        <span className="score-label">{perspective.status}</span>
      </div>
    );
  }
  const tone = perspective.direction === 'positive' ? 'positive' : perspective.direction === 'negative' ? 'negative' : '';
  return (
    <div className={`score-dial ${tone}`}>
      <span className="score-value">{perspective.score.toFixed(0)}</span>
      <span className="score-label">/ 100</span>
    </div>
  );
}

/** One analyst's perspective as a distinct card: score, signal, confidence
 *  and status, plus a link to that analyst's detail page. The macro card is
 *  presented as "Market Environment" with the bare signal (NEUTRAL) and an
 *  explicit market-wide warning — display only, the underlying backend
 *  wording is preserved verbatim in the thesis and evidence sections.
 */
function PerspectiveCard({ perspective, company }: { perspective: PerspectiveView; company: string }) {
  const isMacro = perspective.agent_id === 'macro_analyst';
  const route = ANALYST_ROUTES[perspective.agent_id] ?? '/intelligence/summary';
  const displaySignal = isMacro
    ? perspective.signal_label.replace(/-environment$/i, '')
    : perspective.signal_label;
  return (
    <article
      className={`agent-card perspective-card status-${perspective.status.toLowerCase()}${isMacro ? ' macro-perspective' : ''}`}
      data-testid={`perspective-${perspective.agent_id}`}
    >
      <header className="agent-card-header">
        <MiniDial perspective={perspective} />
        <div className="agent-card-title">
          <h3>{isMacro ? 'Market Environment' : perspective.label}</h3>
          {isMacro && <p className="muted macro-sub">Macro Analyst · market-wide</p>}
          <p>
            <span className={`badge ${DIRECTION_BADGE[perspective.direction] ?? ''}`}>
              {displaySignal}
            </span>{' '}
            <span className={`badge badge-status-${perspective.status.toLowerCase()}`}>
              {perspective.status}
            </span>
          </p>
        </div>
      </header>
      <dl className="perspective-facts">
        <div>
          <dt className="muted">Score</dt>
          <dd>
            {perspective.score !== null && perspective.score !== undefined
              ? `${perspective.score.toFixed(0)} / 100`
              : 'unavailable'}
          </dd>
        </div>
        <div>
          <dt className="muted">Signal</dt>
          <dd>{displaySignal}</dd>
        </div>
        <div>
          <dt className="muted">Confidence</dt>
          <dd>{(perspective.confidence * 100).toFixed(0)}%</dd>
        </div>
        <div>
          <dt className="muted">Status</dt>
          <dd>{perspective.status}</dd>
        </div>
      </dl>
      {isMacro ? (
        <p className="muted macro-note">Market environment — not a stock recommendation.</p>
      ) : null}
      {perspective.direction === 'missing' ? (
        <p className="factor-detail">{perspective.takeaway}</p>
      ) : null}
      <Link className="link-btn" to={`${route}?symbol=${encodeURIComponent(company)}`}>
        Open {perspective.label} →
      </Link>
    </article>
  );
}

/** Full rendering of one PortfolioView — the Central Orchestrator synthesis.
 *
 *  Shows how the four analyst perspectives fit together for ONE company:
 *  four distinct perspective cards, an agreement/thesis panel, conditional
 *  scenario cards, and collapsible evidence/risks grouped by analyst.
 *  Never blends scores into an overall rating — disagreement is shown.
 */
export default function PortfolioViewCard({ view }: { view: PortfolioView }) {
  const available = view.perspectives.filter((p) => p.direction !== 'missing');
  const missing = view.perspectives.filter((p) => p.direction === 'missing');

  // Strongest-supported = highest confidence among available views;
  // most uncertain = a missing view, else the lowest confidence available.
  // Deterministic derivation from the perspectives themselves — no new data.
  const strongest =
    available.length > 0
      ? available.reduce((a, b) => (b.confidence > a.confidence ? b : a), available[0])
      : null;
  const weakest =
    missing.length > 0
      ? missing[0]
      : available.length > 0
        ? available.reduce((a, b) => (b.confidence < a.confidence ? b : a), available[0])
        : null;

  // The generic synthesis disclaimer is stated on the page itself — only
  // genuine synthesis limitations (missing perspectives, coverage gaps)
  // get a Limitations section. Nothing is hidden: the full backend list is
  // the source, this is a display filter for one boilerplate sentence.
  const synthesisLimitations = view.data_limitations.filter(
    (lim) => !/^synthesis only\b/i.test(lim.trim()),
  );

  // Risks grouped by analyst label, in perspective order; anything else under
  // "General". Exact duplicates are shown once.
  const riskGroups: Array<{ label: string; risks: string[] }> = view.perspectives.map((p) => ({
    label: p.label,
    risks: [...new Set(view.risks.filter((r) => r.startsWith(p.label)))],
  }));
  const grouped = new Set(riskGroups.flatMap((g) => g.risks));
  const generalRisks = [...new Set(view.risks.filter((r) => !grouped.has(r)))];
  if (generalRisks.length > 0) riskGroups.push({ label: 'General', risks: generalRisks });
  const shownRiskGroups = riskGroups.filter((g) => g.risks.length > 0);

  // Evidence grouped by analyst, in perspective order (compact traceability
  // pointers — the takeaway sentence already lives on each perspective card).
  const evidenceGroups = view.perspectives
    .map((p) => ({
      label: p.label,
      items: view.evidence.filter((e) => e.agent_id === p.agent_id),
    }))
    .filter((g) => g.items.length > 0);

  // Scenarios in Base → Bull → Bear order. Each condition names the analyst
  // whose evidence it depends on — surfaced as tags by matching perspective
  // labels in the backend's own wording (display only, nothing invented).
  const scenarioOrder = ['Base case', 'Bull case', 'Bear case'];
  const scenarios = [...view.scenarios].sort(
    (a, b) => scenarioOrder.indexOf(a.label) - scenarioOrder.indexOf(b.label),
  );
  const analystTags = (text: string): string[] =>
    view.perspectives.map((p) => p.label).filter((label) => text.includes(label));

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
        </div>
      </header>

      <section aria-label="Analyst perspectives">
        <h4>Perspectives</h4>
        <div className="perspective-grid">
          {view.perspectives.map((p) => (
            <PerspectiveCard key={p.agent_id} perspective={p} company={view.entity_id} />
          ))}
        </div>
      </section>

      <section className="card thesis-card" aria-label="Investment thesis">
        <h4>Investment thesis</h4>
        <p className="thesis-counts" data-testid="agreement-counts">
          <span className="badge signal-buy">{view.agreement.positive_count} positive</span>{' '}
          <span className="badge signal-neutral">{view.agreement.neutral_count} neutral</span>{' '}
          <span className="badge signal-sell">{view.agreement.negative_count} negative</span>{' '}
          <span className="badge badge-evidence">{view.agreement.verdict}</span>
        </p>
        {strongest && (
          <p className="factor-detail" data-testid="strongest-perspective">
            Strongest-supported: {strongest.label} ({strongest.signal_label}, confidence{' '}
            {Math.round(strongest.confidence * 100)}%).
          </p>
        )}
        {weakest && (
          <p className="factor-detail" data-testid="weakest-perspective">
            {weakest.direction === 'missing' ? (
              <>Most uncertain: {weakest.label} — no result in this run.</>
            ) : (
              <>
                Most uncertain: {weakest.label} ({weakest.signal_label}, confidence{' '}
                {Math.round(weakest.confidence * 100)}% — lowest of the available views).
              </>
            )}
          </p>
        )}
        <p className="agent-rationale">{view.thesis}</p>
        {view.agreement.conflicts.length > 0 && (
          <div>
            <h4>Disagreements ({view.agreement.conflicts.length})</h4>
            <ul className="limitations-list">
              {view.agreement.conflicts.map((c, i) => (
                <li key={i}>
                  <strong>{c.between.join(' vs ')}</strong> — {c.description}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="factor-detail">Why this interpretation: {view.rationale}</p>
      </section>

      {scenarios.length > 0 && (
        <section aria-label="Scenarios">
          <h4>Scenarios</h4>
          <p className="muted dash-section-note">
            Conditional scenarios — what would have to change, not predictions.
          </p>
          <div className="card-grid">
            {scenarios.map((s) => (
              <article key={s.label} className="card scenario-card" data-testid={`scenario-${s.label}`}>
                <h4>{s.label}</h4>
                <p>
                  <span className="badge badge-evidence">{s.leaning}</span>
                </p>
                <ul className="evidence-list">
                  {s.conditions.map((c, i) => (
                    <li key={i}>
                      {c}
                      {analystTags(c).length > 0 && (
                        <span className="badge-row">
                          {analystTags(c).map((label) => (
                            <span key={label} className="badge badge-evidence">
                              {label}
                            </span>
                          ))}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="muted">{s.note}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      {evidenceGroups.length > 0 && (
        <details className="portfolio-details">
          <summary>Supporting evidence ({view.evidence.length})</summary>
          {evidenceGroups.map((g) => (
            <div key={g.label}>
              <h4>{g.label}</h4>
              <ul className="evidence-list">
                {g.items.map((e, i) => (
                  <li key={`${e.agent_id}-${i}`}>
                    <span className="badge badge-evidence">{e.signal ?? e.agent_id}</span>{' '}
                    {e.score !== null && e.score !== undefined ? `${Math.round(e.score)}/100` : 'unavailable'}
                    {e.status && <span className="muted"> · {e.status}</span>}
                    <span className="muted"> · {e.entity_id}</span>
                    {e.generated_at && <span className="muted"> · {e.generated_at}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}

      {shownRiskGroups.length > 0 && (
        <details className="portfolio-details" open={view.risks.length <= 3}>
          <summary>Key risks ({view.risks.length})</summary>
          {shownRiskGroups.map((g) => (
            <div key={g.label}>
              <h4>{g.label}</h4>
              <ul className="limitations-list">
                {g.risks.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}

      {synthesisLimitations.length > 0 && (
        <details className="portfolio-details">
          <summary>Limitations ({synthesisLimitations.length})</summary>
          <ul className="limitations-list">
            {synthesisLimitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </details>
      )}

      <footer className="agent-card-footer muted">
        Synthesised {new Date(view.generated_at).toLocaleString()}
        {newestEvidence && <> · underlying views through {newestEvidence}</>}
        {' '}· methodology: {view.methodology}
      </footer>
    </article>
  );
}
