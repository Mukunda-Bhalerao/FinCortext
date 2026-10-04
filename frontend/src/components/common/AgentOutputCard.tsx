import type { AgentOutput } from '../../types/api';

export const SIGNAL_CLASS: Record<string, string> = {
  strong_buy: 'signal-strong-buy',
  buy: 'signal-buy',
  neutral: 'signal-neutral',
  sell: 'signal-sell',
  strong_sell: 'signal-strong-sell',
  unavailable: 'signal-unavailable',
};

const AGENT_LABELS: Record<string, string> = {
  firm_analyst: 'Firm Analyst',
  industry_analyst: 'Industry Analyst',
  sentiment_analyst: 'Sentiment Analyst',
  macro_analyst: 'Macro Analyst',
};

const DATA_TYPE_LABELS: Record<string, string> = {
  financial_observation: 'financial data',
  market_price: 'price history',
  news_article: 'news article',
  market_data: 'market data',
  stored_prices: 'stored prices',
  peer_price_history: 'peer price history',
  research_report: 'web research',
  filing_document: 'official filing',
};

function agentLabel(agentId: string): string {
  return AGENT_LABELS[agentId] ?? agentId.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function dataTypeLabel(dataType: string): string {
  return DATA_TYPE_LABELS[dataType] ?? dataType.replace(/_/g, ' ');
}

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
  // Analysis time and data-through dates are different things: the run may be
  // fresh while the stored market/news data ends on an earlier trading date.
  // Both come from the backend provenance — never invented here.
  const provenance = (output.provenance ?? {}) as Record<string, unknown>;
  const marketThrough =
    typeof provenance.market_latest_date === 'string' ? provenance.market_latest_date : null;
  const newsThrough =
    typeof provenance.latest_article_date === 'string' ? provenance.latest_article_date : null;

  return (
    <article className={`agent-card status-${output.status.toLowerCase()}`}>
      <header className="agent-card-header">
        <ScoreDial score={output.score} status={output.status} />
        <div className="agent-card-title">
          <h3>{agentLabel(output.agent_id)}</h3>
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
                <span className="badge badge-evidence">{dataTypeLabel(e.data_type)}</span>{' '}
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
        Analysed {new Date(output.generated_at).toLocaleString()}
        {marketThrough && <> · market data through {marketThrough}</>}
        {newsThrough && <> · news through {newsThrough}</>}
      </footer>
    </article>
  );
}