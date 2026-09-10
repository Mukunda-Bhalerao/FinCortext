import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, useFinCortext } from '../../app/FinCortextContext';
import AgentPage from './AgentPage';
import type { AgentOutput } from '../../types/api';

function outputFor(symbol: string, score: number): AgentOutput {
  return {
    agent_id: 'firm_analyst',
    entity_id: symbol,
    score,
    signal: 'buy',
    confidence: 0.5,
    factors: [],
    rationale: `${symbol} rationale`,
    evidence: [],
    data_limitations: [],
    generated_at: '2026-09-10T10:00:00Z',
    data_version: '1.0',
    provenance: {},
    status: 'OK',
  };
}

function Switcher() {
  const { setSymbol } = useFinCortext();
  return <button onClick={() => setSymbol('RELIANCE')}>switch-to-reliance</button>;
}

function renderPage(initialEntries = ['/intelligence/firm']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <FinCortextProvider>
        <AgentPage
          agentId="firm_analyst"
          title="Firm Analyst"
          description="Test analyst."
          methodologyDoc="Test methodology."
          prerequisites={[]}
        />
        <Switcher />
      </FinCortextProvider>
    </MemoryRouter>,
  );
}

describe('AgentPage company isolation', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('never displays another company result after switching', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/agents/firm_analyst/TCS/run') {
        return new Response(JSON.stringify(outputFor('TCS', 61.9)), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.click(screen.getByText('Run analysis'));
    await waitFor(() => {
      expect(screen.getByText('TCS rationale')).toBeInTheDocument();
    });

    // Switch company: the TCS result must vanish immediately (no stale frame),
    // replaced by RELIANCE's own (empty) state.
    fireEvent.click(screen.getByText('switch-to-reliance'));
    expect(screen.queryByText('TCS rationale')).not.toBeInTheDocument();
    expect(
      screen.getByText('Select a company and run the analysis to see results.'),
    ).toBeInTheDocument();
  });

  it('records a mid-flight run under its own symbol without painting it elsewhere', async () => {
    let resolveRun!: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      resolveRun = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/agents/firm_analyst/TCS/run') return gate;
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    // Start a TCS run, switch away before it completes, then let it land.
    fireEvent.click(screen.getByText('Run analysis'));
    fireEvent.click(screen.getByText('switch-to-reliance'));
    resolveRun(
      new Response(JSON.stringify(outputFor('TCS', 61.9)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await waitFor(() => {
      // RELIANCE view stays clean — the landed TCS result is cached, not shown.
      expect(
        screen.getByText('Select a company and run the analysis to see results.'),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText('TCS rationale')).not.toBeInTheDocument();
  });
});
