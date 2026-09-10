import AgentPage from './AgentPage';

export default function FirmAnalystPage() {
  return (
    <AgentPage
      agentId="firm_analyst"
      title="Firm Analyst"
      description="Deterministic fundamental + market-behavior scoring from ingested official filings and stored prices."
      methodologyDoc="Deterministic methodology v1 — documented weights, thresholds and confidence rules."
      prerequisites={[
        'Fundamentals come from ingested official filings (primary) supplemented by provider annual-statement data — each observation carries its source.',
        'Stored market history drives the 90-day momentum factor.',
        'Missing inputs are reported as limitations — values are never fabricated.',
      ]}
    />
  );
}