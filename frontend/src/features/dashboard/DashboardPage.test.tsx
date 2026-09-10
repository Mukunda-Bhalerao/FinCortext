import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, useFinCortext } from '../../app/FinCortextContext';
import CompanySelector from '../../components/common/CompanySelector';
import DashboardPage, { buildTakeaway } from './DashboardPage';
import type { AgentOutputSummary } from '../../types/api';

/**
 * The Dashboard is a company/market overview in the terminal layout. It shows
 * compact stored analyst views and a derived takeaway, but no full
 * calculations — those live on the dedicated pages. Only real backend values
 * appear; indices, market caps and scores are never invented.
 */

const universeResp = {
  universe_version: '1.0.0',
  count: 3,
  entries: [
    {
      symbol: 'TCS',
      name: 'Tata Consultancy Services',
      exchange: 'NSE',
      ticker: 'TCS.NS',
      sector: 'Information Technology',
      industry: 'IT Services & Consulting',
    },
    {
      symbol: 'RELIANCE',
      name: 'Reliance Industries',
      exchange: 'NSE',
      ticker: 'RELIANCE.NS',
      sector: 'Energy',
      industry: 'Integrated Oil & Gas',
    },
    {
      symbol: 'INFY',
      name: 'Infosys',
      exchange: 'NSE',
      ticker: 'INFY.NS',
      sector: 'Information Technology',
      industry: 'IT Services & Consulting',
    },
  ],
};

function series(symbol: string, name: string, base: number, status = 'CACHED', days = 40) {
  const prices = Array.from({ length: days }, (_, i) => {
    const close = base + i;
    return {
      date: `2026-07-${String((i % 28) + 1).padStart(2, '0')}`,
      open: close - 2,
      high: close + 5,
      low: close - 5,
      close,
      volume: 1000 + i * 10,
    };
  });
  return {
    symbol,
    name,
    status,
    count: days,
    latest_trade_date: '2026-08-28',
    prices,
  };
}

const tcsSeries = series('TCS', 'Tata Consultancy Services', 2300);
const relianceSeries = series('RELIANCE', 'Reliance Industries', 1400);
const infySeries = series('INFY', 'Infosys', 1700);

function newsFor(symbol: string, title: string) {
  return {
    symbol,
    name: symbol,
    status: 'CACHED',
    count: 1,
    provider_configured: true,
    articles: [
      {
        article_id: `${symbol}-a1`,
        title,
        description: null,
        source: 'Example News',
        source_url: null,
        published_at: '2026-08-29T10:00:00Z',
        collected_at: '2026-08-29T12:00:00Z',
        language: 'en',
        content_hash: null,
        source_type: 'news_api',
        source_name: 'NewsAPI',
      },
    ],
  };
}

function outputsFor(
  symbol: string,
  rows: Array<{
    agent: string;
    score: number | null;
    signal: AgentOutputSummary['signal'];
    confidence: number;
    status: AgentOutputSummary['status'];
  }>,
) {
  return {
    count: rows.length,
    outputs: rows.map((r, i) => ({
      output_id: `${symbol}-${r.agent}-${i}`,
      agent_id: r.agent,
      entity_id: symbol,
      score: r.score,
      signal: r.signal,
      confidence: r.confidence,
      generated_at: `2026-08-3${i}T10:00:00Z`,
      status: r.status,
    })),
  };
}

const tcsOutputs = outputsFor('TCS', [
  { agent: 'firm_analyst', score: 59.2, signal: 'buy', confidence: 0.06, status: 'DEGRADED' },
  { agent: 'industry_analyst', score: 64.1, signal: 'buy', confidence: 0.56, status: 'OK' },
  { agent: 'sentiment_analyst', score: 57.4, signal: 'buy', confidence: 0.79, status: 'OK' },
]);

const relianceOutputs = outputsFor('RELIANCE', [
  { agent: 'firm_analyst', score: 56.0, signal: 'buy', confidence: 0.06, status: 'DEGRADED' },
  { agent: 'industry_analyst', score: null, signal: 'unavailable', confidence: 0, status: 'UNAVAILABLE' },
  { agent: 'sentiment_analyst', score: 69.5, signal: 'buy', confidence: 0.71, status: 'OK' },
]);

const marketStatusResp = {
  symbols: [
    { symbol: 'TCS', name: 'Tata Consultancy Services', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
    { symbol: 'RELIANCE', name: 'Reliance Industries', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
    { symbol: 'INFY', name: 'Infosys', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
  ],
};

const filingsResp = { count: 2, documents: [] };

const fullMocks: Record<string, unknown> = {
  '/api/universe': universeResp,
  '/api/market/prices/TCS': tcsSeries,
  '/api/market/prices/RELIANCE': relianceSeries,
  '/api/market/prices/INFY': infySeries,
  '/api/news/TCS?limit=5': newsFor('TCS', 'TCS reports steady quarter'),
  '/api/news/RELIANCE?limit=5': newsFor('RELIANCE', 'Reliance announces new energy push'),
  '/api/news/INFY?limit=5': newsFor('INFY', 'Infosys wins large deal'),
  '/api/market/status': marketStatusResp,
  '/api/filings?symbol=TCS': filingsResp,
  '/api/filings?symbol=RELIANCE': filingsResp,
  '/api/filings?symbol=INFY': filingsResp,
  '/api/agents/outputs?symbol=TCS&limit=30': tcsOutputs,
  '/api/agents/outputs?symbol=RELIANCE&limit=30': relianceOutputs,
  '/api/agents/outputs?symbol=INFY&limit=30': outputsFor('INFY', []),
};

function mockFetch(responses: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = responses[url];
    if (body === undefined) {
      return new Response(JSON.stringify({}), { status: 404, statusText: 'Not Found' });
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
}

function renderDashboard(initialEntries = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <FinCortextProvider>
        <DashboardPage />
      </FinCortextProvider>
    </MemoryRouter>,
  );
}

/** The topbar search lives in the App shell — harness it for page-level tests. */
function SelectorHarness() {
  const { symbol, setSymbol } = useFinCortext();
  return <CompanySelector value={symbol} onChange={setSymbol} />;
}

describe('DashboardPage terminal', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    // The provider persists the company to localStorage — clear it so each
    // test starts from its own URL/default instead of a previous test.
    localStorage.clear();
  });

  it('renders the TCS overview with real market data and stored intelligence', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderDashboard();

    // Company identity.
    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument(); // latest close
    });
    expect(screen.getByText('Tata Consultancy Services', { selector: '.term-name' })).toBeInTheDocument();
    expect(screen.getByText('TCS.NS')).toBeInTheDocument();
    expect(screen.getByText('Information Technology', { selector: '.chip' })).toBeInTheDocument();

    // Reference-style header stats — all real.
    expect(screen.getByText('Day High')).toBeInTheDocument();
    expect(screen.getByText('Day Low')).toBeInTheDocument();
    expect(screen.getByText('Volume')).toBeInTheDocument();
    expect(screen.getByText('▶ Analyze Company')).toBeInTheDocument();

    // Section tabs and chart ranges.
    for (const tab of ['Overview', 'Price Chart', 'Intelligence', 'News', 'Peers']) {
      expect(screen.getByText(tab, { selector: '.tab-btn' })).toBeInTheDocument();
    }
    expect(screen.getByText('Price Performance')).toBeInTheDocument();

    // Market context shows the real peer quote (INFY last close 1739).
    expect(screen.getByText('Market Context')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/₹1,739\.00/)).toBeInTheDocument();
    });

    // Compact stored intelligence — pointers, not full calculations.
    expect(screen.getByText('FinCortext Intelligence')).toBeInTheDocument();
    expect(screen.getByText('Firm Analyst', { selector: '.intel-label' })).toBeInTheDocument();
    expect(screen.getByText('DEGRADED')).toBeInTheDocument();

    // Key takeaway derived from the stored outputs.
    expect(screen.getByText('Key Takeaway')).toBeInTheDocument();
    expect(screen.getByText(/All three analyst views are stored/)).toBeInTheDocument();

    // Real stored news.
    expect(screen.getByText('TCS reports steady quarter')).toBeInTheDocument();

    // Nothing invented: no indices, no market cap, no blended score.
    expect(screen.queryByText(/nifty/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/market cap/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Contributing factors/)).not.toBeInTheDocument();
  });

  it('renders RELIANCE with its own data and an honest partial takeaway', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderDashboard(['/?symbol=RELIANCE']);

    await waitFor(() => {
      expect(screen.getByText(/₹1,439\.00/)).toBeInTheDocument();
    });
    expect(screen.getByText('Reliance Industries', { selector: '.term-name' })).toBeInTheDocument();
    expect(screen.getByText('Energy', { selector: '.chip' })).toBeInTheDocument();
    expect(screen.getByText('Reliance announces new energy push')).toBeInTheDocument();

    // Single-member sector: peer table holds only RELIANCE, no fabricated peers.
    expect(screen.queryByText('INFY', { selector: '.peer-link' })).not.toBeInTheDocument();

    // Industry view stored as UNAVAILABLE — shown as-is with its status.
    expect(
      screen.getByText('UNAVAILABLE', { selector: '.badge-status-unavailable' }),
    ).toBeInTheDocument();

    // Takeaway reports partial coverage instead of hiding it.
    expect(screen.getByText(/2 lean positive/)).toBeInTheDocument();
    expect(screen.getByText(/Coverage is partial/)).toBeInTheDocument();
  });

  it('switching companies in the search reloads the terminal with that company', async () => {
    const fetchMock = mockFetch(fullMocks);
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter initialEntries={['/']}>
        <FinCortextProvider>
          <SelectorHarness />
          <DashboardPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'INFY' } });

    await waitFor(() => {
      expect(screen.getByText(/₹1,739\.00/, { selector: '.term-price' })).toBeInTheDocument();
    });
    expect(screen.getByText('Infosys', { selector: '.term-name' })).toBeInTheDocument();
    expect(screen.getByText('Infosys wins large deal')).toBeInTheDocument();
    // Header price switched; TCS remains visible only as a real peer quote.
    expect(screen.queryByText(/₹2,339\.00/, { selector: '.term-price' })).not.toBeInTheDocument();
    expect(screen.getByText('TCS', { selector: '.peer-link' })).toBeInTheDocument();
    // The newly selected company's backend reads were issued exactly once.
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url) === '/api/market/prices/INFY').length,
    ).toBe(1);
  });

  it('renders an honest UNAVAILABLE state instead of fabricated numbers', async () => {
    vi.stubGlobal('fetch', mockFetch({ '/api/universe': universeResp }));
    renderDashboard(['/?symbol=LT']);

    await waitFor(() => {
      expect(screen.getByText(/No stored price history/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/₹2,339\.00/)).not.toBeInTheDocument();
    expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument();
  });

  it('does not refetch cached data when the page remounts (route change)', async () => {
    const fetchMock = mockFetch(fullMocks);
    vi.stubGlobal('fetch', fetchMock);

    const { rerender } = render(
      <MemoryRouter initialEntries={['/']}>
        <FinCortextProvider>
          <DashboardPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument();
    });

    rerender(
      <MemoryRouter initialEntries={['/']}>
        <FinCortextProvider>
          <span>navigated away</span>
        </FinCortextProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText('navigated away')).toBeInTheDocument();

    rerender(
      <MemoryRouter initialEntries={['/']}>
        <FinCortextProvider>
          <DashboardPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument();
    });

    expect(
      fetchMock.mock.calls.filter(([url]) => String(url) === '/api/market/prices/TCS').length,
    ).toBe(1);
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url) === '/api/news/TCS?limit=5').length,
    ).toBe(1);
  });
});

describe('buildTakeaway', () => {
  const row = (
    agent: string,
    score: number | null,
    signal: AgentOutputSummary['signal'],
    status: AgentOutputSummary['status'],
  ): AgentOutputSummary => ({
    output_id: `${agent}-1`,
    agent_id: agent,
    entity_id: 'TCS',
    score,
    signal,
    confidence: 0.5,
    generated_at: '2026-08-30T10:00:00Z',
    status,
  });

  it('reports missing coverage instead of inventing a summary', () => {
    const t = buildTakeaway('TCS', 'Tata Consultancy Services', new Map());
    expect(t.complete).toBe(false);
    expect(t.headline).toMatch(/No analyst results stored/);
  });

  it('counts leaning views from real stored outputs only', () => {
    const t = buildTakeaway(
      'TCS',
      'Tata Consultancy Services',
      new Map([
        ['firm_analyst', row('firm_analyst', 59, 'buy', 'DEGRADED')],
        ['industry_analyst', row('industry_analyst', 64, 'buy', 'OK')],
        ['sentiment_analyst', row('sentiment_analyst', 40, 'sell', 'OK')],
      ]),
    );
    expect(t.headline).toMatch(/All three analyst views are stored/);
    expect(t.headline).toMatch(/2 lean positive and 1 leans negative/);
    expect(t.complete).toBe(false); // DEGRADED present
    expect(t.lines.join(' ')).toMatch(/Coverage is partial/);
  });
});
