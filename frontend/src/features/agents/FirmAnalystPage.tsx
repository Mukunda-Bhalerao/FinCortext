import AgentPage from './AgentPage';

export default function FirmAnalystPage() {
  return (
    <AgentPage
      agentId="firm_analyst"
      title="Firm Analyst"
      description="Deterministic fundamental + market-behavior scoring from ingested official filings and stored prices."
      methodologyDoc="backend/app/agents/firm/methodology.py"
      prerequisites={[
        'Ingested official filings (Data → Filing Import) for profitability, growth, leverage, ROE, valuation.',
        'Stored market prices (Data → Market Data → Refresh) for the 90-day momentum factor.',
      ]}
    />
  );
}