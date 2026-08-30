import { render, screen } from '@testing-library/react';
import AgentOutputCard from './AgentOutputCard';
import type { AgentOutput } from '../../types/api';

const baseOutput: AgentOutput = {
  agent_id: 'firm_analyst',
  entity_id: 'TCS',
  score: 72.4,
  signal: 'strong_buy',
  confidence: 0.9,
  factors: [
    {
      name: 'profitability',
      description: 'Net margin',
      value: 0.18,
      contribution: 25.0,
      weight: 0.25,
      available: true,
      detail: 'net_margin = 18.00% → 100/100',
    },
    {
      name: 'valuation',
      description: 'P/E',
      value: null,
      contribution: null,
      weight: 0.1,
      available: false,
      detail: 'Missing pe_ratio — not fabricated.',
    },
  ],
  rationale: 'Firm score 72/100 (confidence 90%).',
  evidence: [
    {
      data_type: 'financial_observation',
      reference: 'TCS/net_income/2024-03-31',
      source_name: 'annual_report',
      source_type: 'official_filing',
      timestamp: null,
      note: 'net_income=45000 Cr',
    },
  ],
  data_limitations: ['Missing pe_ratio — valuation factor unavailable.'],
  generated_at: '2024-07-15T10:00:00Z',
  data_version: '1.0',
  provenance: { methodology: 'firm_analyst_v1' },
  status: 'OK',
};

describe('AgentOutputCard', () => {
  it('renders score, signal, confidence and rationale', () => {
    render(<AgentOutputCard output={baseOutput} />);
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('STRONG BUY')).toBeInTheDocument();
    // "confidence 90%" appears in the header span and inside the rationale.
    expect(screen.getAllByText(/confidence 90%/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Firm score 72\/100/i)).toBeInTheDocument();
  });

  it('shows available and missing factors distinctly', () => {
    render(<AgentOutputCard output={baseOutput} />);
    expect(screen.getByText('profitability')).toBeInTheDocument();
    // "valuation" appears as the missing factor name; "not computed" is shown
    expect(screen.getAllByText(/not computed/i).length).toBeGreaterThan(0);
    // "Missing pe_ratio" appears in the factor detail and in the limitations list.
    expect(screen.getAllByText(/Missing pe_ratio/i).length).toBeGreaterThan(0);
  });

  it('renders evidence and limitations sections', () => {
    render(<AgentOutputCard output={baseOutput} />);
    expect(screen.getByText('financial_observation')).toBeInTheDocument();
    expect(
      screen.getByText(/Missing pe_ratio — valuation factor unavailable\./),
    ).toBeInTheDocument();
  });

  it('renders a DEGRADED status badge for thin-evidence outputs', () => {
    const degraded: AgentOutput = {
      ...baseOutput,
      score: 59.2,
      signal: 'buy',
      status: 'DEGRADED',
    };
    render(<AgentOutputCard output={degraded} />);
    expect(screen.getByText('DEGRADED')).toBeInTheDocument();
  });

  it('renders an em-dash score for UNAVAILABLE outputs', () => {
    const unavailable: AgentOutput = {
      ...baseOutput,
      score: null,
      signal: 'unavailable',
      status: 'UNAVAILABLE',
      factors: [],
      evidence: [],
      data_limitations: ['No stored news articles.'],
    };
    render(<AgentOutputCard output={unavailable} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    // Status appears in both the score dial and the status badge
    expect(screen.getAllByText('UNAVAILABLE').length).toBeGreaterThanOrEqual(1);
  });
});