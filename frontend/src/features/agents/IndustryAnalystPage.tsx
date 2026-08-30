import AgentPage from './AgentPage';

export default function IndustryAnalystPage() {
  return (
    <AgentPage
      agentId="industry_analyst"
      title="Industry Analyst"
      description="Peer/sector-relative scoring: environment momentum, relative strength, margin vs peer median, volatility regime."
      methodologyDoc="Deterministic methodology v1 — documented peer weights and thresholds."
      prerequisites={[
        'Price history for the company and its sector peers is ensured automatically before the analysis: sufficient cached data is reused, and only missing or stale history is fetched from the market provider.',
        'Ingested filings for the company and peers enable the margin-comparison factor; without them it is reported as unavailable.',
      ]}
    />
  );
}