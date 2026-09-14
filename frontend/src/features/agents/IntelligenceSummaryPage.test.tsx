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

function macroOutput() {
  return {
    agent_id: 'macro_analyst',
    entity_id: 'MACRO_INDIA',
    requested_symbol: 'TCS',
    score: 50,
    overall_signal: 'neutral',
    confidence: 0.62,
    status: 'OK',
    factors: [],
    rationale: 'Macro Environment Signal is NEUTRAL from 6/7 areas.',
    data_limitations: [],
    generated_at: '2026-09-10T10:00:00Z',
    data_through: { repo_rate: '2026-06-05' },
    provenance: {},
    methodology: 'macro_analyst_v1',
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

  it('presents four independent views side by side with no blended score', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const m = url.match(/^\/api\/agents\/(firm_analyst|industry_analyst|sentiment_analyst)\/TCS\/run$/);
      if (m) {
        return new Response(JSON.stringify(outputFor(m[1], 'TCS', 60)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === '/api/agents/macro/TCS/run') {
        return new Response(JSON.stringify(macroOutput()), {
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
    // Macro view joins side by side with its environment vocabulary.
    expect(screen.getByText('Macro Environment')).toBeInTheDocument();
    expect(screen.getByText(/Macro Environment Signal is NEUTRAL/)).toBeInTheDocument();
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
