import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider } from '../../app/FinCortextContext';
import DashboardPage from './DashboardPage';

/**
 * The Dashboard is a market terminal: identity, price action, history,
 * peers, news, freshness. It shows NO analyst scores (those live on their
 * dedicated pages) and only real backend values — never invented numbers.
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

const marketStatusResp = {
  symbols: [
    { symbol: 'TCS', name: 'Tata Consultancy Services', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
    { symbol: 'RELIANCE', name: 'Reliance Industries', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
    { symbol: 'INFY', name: 'Infosys', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
  ],
};

const filingsResp = { count: 2, documents: [] };

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

const mocksFor = (symbol: string, s: unknown, title: string) => ({
  '/api/universe': universeResp,
  [`/api/market/prices/${symbol}`]: s,
  [`/api/news/${symbol}?limit=5`]: newsFor(symbol, title),
  '/api/market/status': marketStatusResp,
  [`/api/filings?symbol=${symbol}`]: filingsResp,
});

function renderDashboard(initialEntries = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <FinCortextProvider>
        <DashboardPage />
      </FinCortextProvider>
    </MemoryRouter>,
  );
}

describe('DashboardPage terminal', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    // The provider persists the company to localStorage — clear it so each
    // test starts from its own URL/default instead of a previous test.
    localStorage.clear();
  });

  it('renders the TCS terminal with real price action and no analyst scores', async () => {
    vi.stubGlobal('fetch', mockFetch(mocksFor('TCS', tcsSeries, 'TCS reports steady quarter')));
    renderDashboard();

    // Company identity.
    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument(); // latest close
    });
    expect(
      screen.getByText('Tata Consultancy Services', { selector: '.term-name' }),
    ).toBeInTheDocument();
    expect(screen.getByText('TCS.NS')).toBeInTheDocument();
    expect(screen.getByText('Information Technology', { selector: '.chip' })).toBeInTheDocument();
    expect(screen.getByText('Day high')).toBeInTheDocument();
    expect(screen.getByText('Day low')).toBeInTheDocument();
    expect(screen.getByText('Volume')).toBeInTheDocument();
    expect(screen.getByText('30-day change')).toBeInTheDocument();
    expect(screen.getByText('90-day momentum')).toBeInTheDocument();
    // Latest trade date appears in the header, peers and chart note.
    expect(screen.getAllByText('2026-08-28').length).toBeGreaterThanOrEqual(1);

    // Real stored news.
    expect(screen.getByText('TCS reports steady quarter')).toBeInTheDocument();

    // Sector peers (IT: TCS + INFY) with peer switching available.
    expect(screen.getByText('INFY', { selector: '.peer-link' })).toBeInTheDocument();

    // Freshness evidence, including ingested filings.
    expect(screen.getByText(/2 ingested official filings/)).toBeInTheDocument();

    // No analyst duplication on the Dashboard.
    expect(screen.queryByText(/Confidence/)).not.toBeInTheDocument();
    expect(screen.queryByText('Combined Intelligence')).not.toBeInTheDocument();
    expect(screen.queryByText(/Firm Analyst.*score/i)).not.toBeInTheDocument();

    // Navigation aids point at the dedicated pages instead.
    expect(screen.getByText('Firm Analyst →')).toBeInTheDocument();
    expect(screen.getByText('Combined Summary →')).toBeInTheDocument();
  });

  it('renders RELIANCE with its own data and single-member sector', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(mocksFor('RELIANCE', relianceSeries, 'Reliance announces new energy push')),
    );
    renderDashboard(['/?symbol=RELIANCE']);

    await waitFor(() => {
      expect(screen.getByText(/₹1,439\.00/)).toBeInTheDocument();
    });
    expect(
      screen.getByText('Reliance Industries', { selector: '.term-name' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Energy', { selector: '.chip' })).toBeInTheDocument();
    expect(screen.getByText('Reliance announces new energy push')).toBeInTheDocument();
    // Single-member sector: peer table holds only RELIANCE, no fabricated peers.
    expect(screen.queryByText('INFY', { selector: '.peer-link' })).not.toBeInTheDocument();
  });

  it('switching companies in the selector reloads the terminal with that company', async () => {
    const fetchMock = mockFetch({
      ...mocksFor('TCS', tcsSeries, 'TCS reports steady quarter'),
      ...mocksFor('INFY', infySeries, 'Infosys wins large deal'),
    });
    vi.stubGlobal('fetch', fetchMock);
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/₹2,339\.00/)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'INFY' } });

    await waitFor(() => {
      expect(screen.getByText(/₹1,739\.00/)).toBeInTheDocument();
    });
    expect(
      screen.getByText('Infosys', { selector: '.term-name' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Infosys wins large deal')).toBeInTheDocument();
    expect(screen.queryByText(/₹2,339\.00/)).not.toBeInTheDocument();
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
    const fetchMock = mockFetch(mocksFor('TCS', tcsSeries, 'TCS reports steady quarter'));
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
