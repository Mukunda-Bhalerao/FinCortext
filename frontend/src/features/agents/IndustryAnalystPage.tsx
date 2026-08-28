import AgentPage from './AgentPage';

export default function IndustryAnalystPage() {
  return (
    <AgentPage
      agentId="industry_analyst"
      title="Industry Analyst"
      description="Peer/sector-relative scoring: environment momentum, relative strength, margin vs peer median, volatility regime."
      methodologyDoc="backend/app/agents/industry/methodology.py · docs/industry_methodology.md"
      prerequisites={[
        'Stored market prices for the company AND its sector peers (Data → Market Data → Refresh universe).',
        'Ingested filings for the company and peers enable the margin comparison factor.',
      ]}
    />
  );
}