import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, useFinCortext } from '../../app/FinCortextContext';
import PortfolioSynthesisPage from './PortfolioSynthesisPage';
import type { PortfolioView } from '../../types/api';

const universeResp = {
  universe_version: '1.0.0',
  count: 3,
  entries: [
    { symbol: 'TCS', name: 'Tata Consultancy Services', exchange: 'NSE', ticker: 'TCS.NS', sector: 'Information Technology', industry: 'IT Services & Consulting' },
    { symbol: 'RELIANCE', name: 'Reliance Industries', exchange: 'NSE', ticker: 'RELIANCE.NS', sector: 'Energy', industry: 'Integrated Oil & Gas' },
    { symbol: 'INFY', name: 'Infosys', exchange: 'NSE', ticker: 'INFY.NS', sector: 'Information Technology', industry: 'IT Services & Consulting' },
  ],
};

function perspective(
  agentId: string,
  label: string,
  entityId: string,
  direction: string,
  signalLabel: string,
  score: number | null,
  status = 'OK',
  confidence = 0.7,
  limitations: string[] = [],
) {
  return {
    agent_id: agentId,
    label,
    entity_id: entityId,
    direction,
    signal_label: signalLabel,
    score,
    confidence,
    status,
    takeaway: `${label}: ${signalLabel}${score !== null ? ` at ${Math.round(score)}/100` : ''} (${status}, confidence ${Math.round(confidence * 100)}%).`,
    limitations,
    generated_at: '2026-09-10T10:00:00Z',
  };
}

function synthesisFor(symbol: string, opts: {
  firmScore?: number | null;
  firmSignal?: string;
  firmStatus?: string;
  sentimentScore?: number | null;
  sentimentSignal?: string;
  macroScore?: number | null;
  macroSignal?: string;
  missing?: string[];
} = {}): PortfolioView {
  const missing = new Set(opts.missing ?? []);
  const firmScore = opts.firmScore ?? 62;
  const firmSignal = opts.firmSignal ?? 'BUY';
  const firmStatus = opts.firmStatus ?? 'OK';
  const sentScore = opts.sentimentScore ?? 57;
  const sentSignal = opts.sentimentSignal ?? 'BUY';
  const macroScore = opts.macroScore ?? 50;
  const macroSignal = opts.macroSignal ?? 'NEUTRAL-environment';
  const perspectives = [];
  if (!missing.has('firm')) {
    perspectives.push(perspective('firm_analyst', 'Firm Analyst', symbol, firmScore !== null && firmSignal === 'BUY' ? 'positive' : 'negative', firmSignal, firmScore, firmStatus, 0.6, firmStatus === 'DEGRADED' ? ['No filings ingested.'] : []));
  } else {
    perspectives.push(perspective('firm_analyst', 'Firm Analyst', 'unknown', 'missing', 'not run', null, 'UNAVAILABLE', 0, ['Firm Analyst produced no output in this run.']));
  }
  if (!missing.has('industry')) {
    perspectives.push(perspective('industry_analyst', 'Industry Analyst', symbol, 'positive', 'BUY', 69, 'OK', 0.8));
  } else {
    perspectives.push(perspective('firm_analyst', 'Industry Analyst', 'unknown', 'missing', 'not run', null, 'UNAVAILABLE', 0, []));
  }
  if (!missing.has('sentiment')) {
    const dir = sentScore !== null && sentSignal === 'BUY' ? 'positive' : sentScore !== null && sentSignal === 'SELL' ? 'negative' : 'neutral';
    perspectives.push(perspective('sentiment_analyst', 'Sentiment Analyst', symbol, dir, sentSignal, sentScore, 'OK', 0.7));
  } else {
    perspectives.push(perspective('sentiment_analyst', 'Sentiment Analyst', 'unknown', 'missing', 'not run', null, 'UNAVAILABLE', 0, []));
  }
  if (!missing.has('macro')) {
    const dir = macroSignal.startsWith('POSITIVE') ? 'positive' : macroSignal.startsWith('NEGATIVE') ? 'negative' : 'neutral';
    perspectives.push(perspective('macro_analyst', 'Macro Analyst', 'MACRO_INDIA', dir, macroSignal, macroScore, 'OK', 0.7));
  } else {
    perspectives.push(perspective('macro_analyst', 'Macro Analyst', 'MACRO_INDIA', 'missing', 'not run', null, 'UNAVAILABLE', 0, []));
  }
  const available = perspectives.filter((p) => p.direction !== 'missing');
  const positives = available.filter((p) => p.direction === 'positive').length;
  const verdict = positives === available.length && available.length >= 2 ? 'unanimous-positive' : 'mixed';
  const conflicts =
    opts.sentimentSignal === 'SELL'
      ? [{ between: ['Firm Analyst', 'Sentiment Analyst'], description: 'Firm Analyst leans positive (BUY) while Sentiment Analyst leans negative (SELL) — both views are kept; neither is averaged away.' }]
      : [];
  return {
    agent_id: 'portfolio_agent',
    entity_id: symbol,
    generated_at: '2026-09-10T11:00:00Z',
    perspectives: perspectives as unknown as PortfolioView['perspectives'],
    agreement: {
      available_count: available.length,
      total_count: 4,
      positive_count: positives,
      neutral_count: available.length - positives,
      negative_count: 0,
      verdict,
      conflicts,
      summary: `${positives} of ${available.length} available perspectives lean positive.`,
    },
    scenarios: [
      { label: 'Base case', leaning: 'as-stated', conditions: ['Firm Analyst: BUY.'], note: 'Takes every available perspective exactly as reported.' },
      { label: 'Bull case', leaning: 'conditional-positive', conditions: ['Macro Analyst reads NEUTRAL-environment — a turn here would strengthen the overall picture.'], note: 'Conditions, not predictions.' },
      { label: 'Bear case', leaning: 'conditional-negative', conditions: ['Firm Analyst is positive (BUY) — deterioration here would weaken the overall picture.'], note: 'Conditions, not predictions.' },
    ],
    thesis: `For ${symbol}: ${positives} of ${available.length} available perspectives lean positive. Best-supported view: Industry Analyst (BUY, confidence 80%). The macro backdrop reads ${macroSignal} and applies equally to every company — it supports context, not a stock call.`,
    evidence: perspectives.filter((p) => p.direction !== 'missing').map((p) => ({
      agent_id: p.agent_id, entity_id: p.entity_id, signal: p.signal_label, score: p.score, status: p.status, generated_at: p.generated_at, note: p.takeaway,
    })),
    risks: firmStatus === 'DEGRADED' ? ['Firm Analyst is DEGRADED — treat its view as partial.', 'Firm Analyst: No filings ingested.'] : [],
    coverage: available.length / 4,
    confidence: 0.65,
    status: available.length === 0 ? 'UNAVAILABLE' : available.length < 3 ? 'DEGRADED' : 'OK',
    rationale: `Portfolio view for ${symbol}: ${positives} of ${available.length} lean positive. Coverage ${Math.round((available.length / 4) * 100)}% of perspectives available.`,
    data_limitations: missing.size > 0 ? ['Missing perspectives (shown, not filled in).', 'Synthesis only — perspectives are compared, never blended into one score.'] : ['Synthesis only — perspectives are compared, never blended into one score.'],
    provenance: { methodology: 'portfolio_agent_v1', analysts_available: available.length, analysts_total: 4 },
    methodology: 'portfolio_agent_v1',
  };
}

function Switcher({ to }: { to: string }) {
  const { setSymbol } = useFinCortext();
  return <button onClick={() => setSymbol(to)}>switch-to-{to.toLowerCase()}</button>;
}

function mockFetch(handler: (url: string) => unknown) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/universe') {
      return new Response(JSON.stringify(universeResp), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    const body = handler(url);
    if (body === undefined) return new Response(JSON.stringify({}), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
}

describe('PortfolioSynthesisPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders the stored synthesis with four perspectives and no blended score', async () => {
    const stored = synthesisFor('TCS');
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=TCS') return { count: 1, output: stored };
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=TCS']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — TCS')).toBeInTheDocument();
    });
    // Compact per-analyst rows: Firm 62 BUY, Industry 69 BUY, Sentiment 57 BUY, Macro 50 NEUTRAL.
    expect(screen.getByText('Firm Analyst')).toBeInTheDocument();
    expect(screen.getByText('Industry Analyst')).toBeInTheDocument();
    expect(screen.getByText('Sentiment Analyst')).toBeInTheDocument();
    expect(screen.getByText('Macro Analyst')).toBeInTheDocument();
    expect(screen.getByText(/Investment thesis/)).toBeInTheDocument();
    expect(screen.getByText(/applies equally to every company/)).toBeInTheDocument();
    // Never an overall/blended score header — perspectives carry their own scores.
    expect(screen.queryByText(/Overall Score:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Blended Score/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Total Score:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Final Score:/)).not.toBeInTheDocument();
  });

  it('runs a fresh synthesis when none is stored', async () => {
    const fresh = synthesisFor('RELIANCE');
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=RELIANCE') return { count: 0, output: null };
      if (url === '/api/agents/portfolio/RELIANCE/run') return fresh;
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=RELIANCE']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/No stored synthesis for RELIANCE/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Run synthesis'));
    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — RELIANCE')).toBeInTheDocument();
    });
  });

  it('shows analyst conflicts instead of hiding them', async () => {
    const stored = synthesisFor('INFY', { sentimentScore: 35, sentimentSignal: 'SELL' });
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=INFY') return { count: 1, output: stored };
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=INFY']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Disagreements \(1\)/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Firm Analyst vs Sentiment Analyst/)).toBeInTheDocument();
    expect(screen.getByText(/neither is averaged away/)).toBeInTheDocument();
  });

  it('flags a DEGRADED analyst view as a risk with its real limitation', async () => {
    const stored = synthesisFor('TCS', { firmStatus: 'DEGRADED' });
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=TCS') return { count: 1, output: stored };
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=TCS']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Firm Analyst is DEGRADED/)).toBeInTheDocument();
    });
    expect(screen.getAllByText(/No filings ingested/).length).toBeGreaterThanOrEqual(1);
  });

  it('reports missing analyst output honestly with DEGRADED coverage', async () => {
    const stored = synthesisFor('TCS', { missing: ['sentiment'] });
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=TCS') return { count: 1, output: stored };
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=TCS']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — TCS')).toBeInTheDocument();
    });
    expect(screen.getByText(/Missing perspectives/)).toBeInTheDocument();
  });

  it('keeps the macro view market-wide while company views differ', async () => {
    const tcs = synthesisFor('TCS', { firmScore: 62, macroScore: 50, macroSignal: 'NEUTRAL-environment' });
    const infy = synthesisFor('INFY', { firmScore: 35, firmSignal: 'SELL', macroScore: 50, macroSignal: 'NEUTRAL-environment' });
    vi.stubGlobal('fetch', mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=TCS') return { count: 1, output: tcs };
      if (url === '/api/portfolio/latest?symbol=INFY') return { count: 1, output: infy };
      return undefined;
    }));
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=TCS']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
          <Switcher to="INFY" />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — TCS')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('switch-to-infy'));
    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — INFY')).toBeInTheDocument();
    });
    // INFY firm view genuinely differs (SELL) while macro stays environmental.
    expect(screen.getAllByText(/NEUTRAL-environment/).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Portfolio Synthesis — TCS')).not.toBeInTheDocument();
  });

  it('loads the company from ?symbol= URL persistence', async () => {
    const stored = synthesisFor('RELIANCE');
    const fetchMock = mockFetch((url) => {
      if (url === '/api/portfolio/latest?symbol=RELIANCE') return { count: 1, output: stored };
      return undefined;
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=RELIANCE']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText('Portfolio Synthesis — RELIANCE')).toBeInTheDocument();
    });
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/portfolio/latest?symbol=RELIANCE')).toBe(true);
  });

  it('reports synthesis failures honestly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/universe') {
          return new Response(JSON.stringify(universeResp), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return new Response(JSON.stringify({}), { status: 500 });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/portfolio?symbol=TCS']}>
        <FinCortextProvider>
          <PortfolioSynthesisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText('Run synthesis'));
    await waitFor(() => {
      expect(screen.getByText(/Error:/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Portfolio Synthesis — TCS/)).not.toBeInTheDocument();
  });
});
