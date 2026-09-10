import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider } from '../../app/FinCortextContext';
import CompanyAnalysisPage from './CompanyAnalysisPage';

/** Company Analysis shows company details and data inventory from the real
 *  backend — never scores, never invented values. */

const universeResp = {
  universe_version: '1.0.0',
  count: 2,
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
      symbol: 'INFY',
      name: 'Infosys',
      exchange: 'NSE',
      ticker: 'INFY.NS',
      sector: 'Information Technology',
      industry: 'IT Services & Consulting',
    },
  ],
};

const prices = Array.from({ length: 40 }, (_, i) => {
  const close = 2300 + i;
  return {
    date: `2026-07-${String((i % 28) + 1).padStart(2, '0')}`,
    open: close - 2,
    high: close + 5,
    low: close - 5,
    close,
    volume: 1000 + i * 10,
  };
});

const fullMocks: Record<string, unknown> = {
  '/api/universe': universeResp,
  '/api/market/prices/TCS': {
    symbol: 'TCS',
    name: 'Tata Consultancy Services',
    status: 'CACHED',
    count: 40,
    latest_trade_date: '2026-08-28',
    prices,
  },
  '/api/market/prices/INFY': {
    symbol: 'INFY',
    name: 'Infosys',
    status: 'CACHED',
    count: 40,
    latest_trade_date: '2026-08-28',
    prices,
  },
  '/api/news/TCS?limit=5': {
    symbol: 'TCS',
    name: 'Tata Consultancy Services',
    status: 'CACHED',
    count: 2,
    provider_configured: true,
    articles: [],
  },
  '/api/market/status': {
    symbols: [
      { symbol: 'TCS', name: 'Tata Consultancy Services', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
      { symbol: 'INFY', name: 'Infosys', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
    ],
  },
  '/api/filings?symbol=TCS': { count: 0, documents: [] },
  '/api/agents/outputs?symbol=TCS&limit=30': {
    count: 2,
    outputs: [
      {
        output_id: 'o2',
        agent_id: 'firm_analyst',
        entity_id: 'TCS',
        score: 59.2,
        signal: 'buy',
        confidence: 0.06,
        generated_at: '2026-08-30T10:00:00Z',
        status: 'DEGRADED',
      },
      {
        output_id: 'o1',
        agent_id: 'firm_analyst',
        entity_id: 'TCS',
        score: 55.0,
        signal: 'buy',
        confidence: 0.06,
        generated_at: '2026-08-29T10:00:00Z',
        status: 'DEGRADED',
      },
    ],
  },
};

describe('CompanyAnalysisPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders company details, price statistics and data inventory', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const body = fullMocks[String(input)];
        if (body === undefined) {
          return new Response(JSON.stringify({}), { status: 404 });
        }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/company']}>
        <FinCortextProvider>
          <CompanyAnalysisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/, { selector: '.term-price' })).toBeInTheDocument();
    });

    // Identity.
    expect(screen.getByText('Tata Consultancy Services', { selector: '.term-name' })).toBeInTheDocument();
    expect(screen.getByText('TCS.NS')).toBeInTheDocument();

    // Price statistics from stored bars.
    expect(screen.getByText('Price statistics')).toBeInTheDocument();
    expect(screen.getByText('Stored range')).toBeInTheDocument();
    expect(screen.getByText('Stored high / low')).toBeInTheDocument();

    // Data inventory: real counts, honest gaps.
    expect(screen.getByText('Data inventory')).toBeInTheDocument();
    expect(screen.getAllByText(/40 stored days/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2 stored articles/)).toBeInTheDocument();
    expect(screen.getByText(/0 ingested official filings/)).toBeInTheDocument();
    expect(screen.getByText(/2 stored runs/)).toBeInTheDocument();

    // Peer snapshot with real quotes.
    expect(screen.getByText('Sector peers — Information Technology')).toBeInTheDocument();
    expect(screen.getByText('INFY', { selector: '.peer-link' })).toBeInTheDocument();

    // No invented market data, no analyst scores here.
    expect(screen.queryByText(/nifty/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/market cap/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
  });

  it('shows fundamentals coverage with honest source labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/fundamentals/TCS') {
          return new Response(
            JSON.stringify({
              symbol: 'TCS',
              name: 'Tata Consultancy Services',
              status: 'CACHED',
              metric_count: 7,
              has_official: false,
              has_provider: true,
              metrics: {
                total_revenue: {
                  value: 2670210000000,
                  unit: 'INR',
                  period_end: '2026-03-31',
                  source_type: 'yfinance',
                  source_name: 'yfinance fundamentals (annual statements)',
                  available_at: '2026-09-10T10:00:00Z',
                },
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        const body = fullMocks[url];
        if (body === undefined) {
          return new Response(JSON.stringify({}), { status: 404 });
        }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/company']}>
        <FinCortextProvider>
          <CompanyAnalysisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/7 metrics/)).toBeInTheDocument();
    });
    // Provider data is labeled as such — never presented as official filings.
    expect(screen.getByText(/provider data \(Yahoo Finance\)/)).toBeInTheDocument();
    expect(screen.getByText(/latest period 2026-03-31/)).toBeInTheDocument();
  });

  it('derives the coverage indicator from actual stored intelligence', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const body = fullMocks[String(input)];
        if (body === undefined) {
          return new Response(JSON.stringify({}), { status: 404 });
        }
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/company']}>
        <FinCortextProvider>
          <CompanyAnalysisPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    // Only the firm view has a stored score → 1/3, with the filings caveat
    // (the fixture reports zero ingested filings).
    await waitFor(() => {
      expect(
        screen.getByText('Data coverage: 1/3 intelligence views available'),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Coverage: Partial, official filings unavailable\./),
    ).toBeInTheDocument();
  });
});
