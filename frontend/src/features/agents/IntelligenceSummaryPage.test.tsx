import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, useFinCortext } from '../../app/FinCortextContext';
import IntelligenceSummaryPage from './IntelligenceSummaryPage';
import type { AgentOutput } from '../../types/api';

function outputFor(agent: string, symbol: string, score: number | null): AgentOutput {
  return {
    agent_id: agent,
    entity_id: symbol,
    score,
    signal: score === null ? 'unavailable' : 'buy',
    confidence: 0.5,
    factors: [],
    rationale: `${agent} rationale for ${symbol}`,
    evidence: [],
    data_limitations: [],
    generated_at: '2026-09-10T10:00:00Z',
    data_version: '1.0',
    provenance: {},
    status: score === null ? 'UNAVAILABLE' : 'OK',
  };
}

function Switcher() {
  const { setSymbol } = useFinCortext();
  return <button onClick={() => setSymbol('INFY')}>switch-to-infy</button>;
}

describe('IntelligenceSummaryPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('presents three independent views side by side with no blended score', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const m = url.match(/^\/api\/agents\/(firm_analyst|industry_analyst|sentiment_analyst)\/TCS\/run$/);
      if (m) {
        return new Response(JSON.stringify(outputFor(m[1], 'TCS', 60)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter initialEntries={['/intelligence/summary']}>
        <FinCortextProvider>
          <IntelligenceSummaryPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run all analysts'));
    await waitFor(() => {
      expect(screen.getByText('firm_analyst rationale for TCS')).toBeInTheDocument();
    });
    expect(screen.getByText('industry_analyst rationale for TCS')).toBeInTheDocument();
    expect(screen.getByText('sentiment_analyst rationale for TCS')).toBeInTheDocument();
    // Three independent perspectives — never a blended investment score.
    // (The page honestly says it "does not blend", so match only invented totals.)
    expect(screen.queryByText(/blended/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/total score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/final score/i)).not.toBeInTheDocument();
  });

  it('shows only the newly selected company after a switch, never stale scores', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const m = url.match(/^\/api\/agents\/(firm_analyst|industry_analyst|sentiment_analyst)\/(TCS)\/run$/);
      if (m) {
        return new Response(JSON.stringify(outputFor(m[1], 'TCS', 60)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter initialEntries={['/intelligence/summary']}>
        <FinCortextProvider>
          <IntelligenceSummaryPage />
          <Switcher />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run all analysts'));
    await waitFor(() => {
      expect(screen.getByText('Scores — TCS')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('switch-to-infy'));
    // INFY has no runs: TCS cards vanish, honest empty state appears.
    expect(screen.queryByText('Scores — TCS')).not.toBeInTheDocument();
    expect(screen.queryByText('firm_analyst rationale for TCS')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        'Select a company and run all analysts. Analysts with missing data report UNAVAILABLE honestly instead of producing fake scores.',
      ),
    ).toBeInTheDocument();
  });
});
