/** Data Pipeline — documented flow overview (static, honest description). */
export default function DataPipelinePage() {
  const stages = [
    {
      name: '1 · Ingestion',
      detail: 'Provider adapters (Upstox, NewsAPI) and official filing uploads enter through replaceable contracts.',
    },
    {
      name: '2 · Validation',
      detail: 'Market bars: positive prices, high ≥ low, range checks, duplicate detection. Rejections are reported, never silently dropped.',
    },
    {
      name: '3 · Normalization',
      detail: 'Provider payloads become canonical domain models (MarketPrice, NewsArticle, FinancialObservation) at the boundary.',
    },
    {
      name: '4 · Storage',
      detail: 'DuckDB analytical store: market_prices, financial_observations, news_articles, sentiment_results, agent_outputs, data_provenance.',
    },
    {
      name: '5 · Feature calculation',
      detail: 'Deterministic metrics (momentum, volatility, margins) computed by agents from stored canonical data — never from raw provider payloads.',
    },
    {
      name: '6 · Provenance',
      detail: 'Every ingestion records source, content hash, row counts, and timestamps in the data_provenance event log.',
    },
  ];

  return (
    <section className="page">
      <h2>Data Pipeline</h2>
      <p className="muted page-description">
        The canonical flow every dataset follows. Agents consume only stored
        canonical data via repositories — never providers directly.
      </p>
      <ol className="pipeline-list">
        {stages.map((s) => (
          <li key={s.name} className="pipeline-stage">
            <strong>{s.name}</strong>
            <p className="muted">{s.detail}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}