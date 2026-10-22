import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider } from '../../app/FinCortextContext';
import MarketDashboardPage from './MarketDashboardPage';

/**
 * The Market Dashboard (home) — Indian market overview from real Upstox
 * data. Indices and movers come from the backend; rankings never cover
 * more than the tracked companies that actually have live quotes; research
 * opportunities trace back to stored analyst outputs. Nothing fabricated.
 */

const dashboardResp = {
  indices: {
    items: [
      {
        key: 'NSE_INDEX|Nifty 50',
        name: 'Nifty 50',
        value: 22687.65,
        day_change: -77.6,
        day_change_pct: -0.34,
        open: 22687.75,
        high: 22785.0,
        low: 22554.85,
        chart: [
          { date: '2026-09-20', close: 22800 },
          { date: '2026-09-21', close: 22750 },
          { date: '2026-09-22', close: 22687.65 },
        ],
        status: 'LIVE',
        source: 'upstox',
      },
      {
        key: 'NSE_INDEX|Nifty Bank',
        name: 'Nifty Bank',
        value: 54925.7,
        day_change: -511.2,
        day_change_pct: -0.92,
        open: null,
        high: null,
        low: null,
        chart: null,
        status: 'LIVE',
        source: 'upstox',
      },
    ],
  },
  movers: {
    status: 'LIVE',
    tracked: 44,
    quoted: 44,
    gainers: [
      {
        symbol: 'ICICIBANK',
        name: 'ICICI Bank',
        instrument_key: 'NSE_EQ|INE090A01021',
        status: 'LIVE',
        last_price: 1398.5,
        day_change: 13.5,
        day_change_pct: 0.97,
        volume: 1000,
      },
    ],
    losers: [
      {
        symbol: 'ZEEL',
        name: 'Zee Entertainment',
        instrument_key: 'NSE_EQ|INE256A01028',
        status: 'LIVE',
        last_price: 68.46,
        day_change: -3.9,
        day_change_pct: -5.39,
        volume: 2000,
      },
    ],
  },
  opportunities: {
    status: 'CACHED',
    count: 1,
    items: [
      {
        symbol: 'LT',
        name: 'Larsen & Toubro',
        agent_id: 'sentiment_analyst',
        score: 91.4,
        signal: 'strong_buy',
        confidence: 0.8,
        status: 'OK',
        generated_at: '2026-10-01T10:00:00Z',
        rationale: 'News sentiment for Larsen & Toubro: score 91/100 (confidence 80%)',
      },
    ],
  },
  tracked_count: 44,
  as_of: '2026-10-12T10:00:00+00:00',
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

function renderDashboard(initial: string = '/') {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <FinCortextProvider>
        <MarketDashboardPage />
      </FinCortextProvider>
    </MemoryRouter>,
  );
}

describe('MarketDashboardPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders indices with real movements and the index sparkline', async () => {
    vi.stubGlobal('fetch', mockFetch({ '/api/market/dashboard': dashboardResp }));
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Market Dashboard' })).toBeInTheDocument();
    });
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('22,687.65')).toBeInTheDocument();
    expect(screen.getByText('−77.6 (-0.34%)')).toBeInTheDocument();
    expect(screen.getByText('Nifty Bank')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Index trend/ })).toBeInTheDocument();
  });

  it('labels movers as tracked-company rankings and renders both sides', async () => {
    vi.stubGlobal('fetch', mockFetch({ '/api/market/dashboard': dashboardResp }));
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText(/44 tracked companies/)).toBeInTheDocument();
    });
    expect(screen.getByText('Top Gainers')).toBeInTheDocument();
    expect(screen.getByText('Top Losers')).toBeInTheDocument();
    expect(screen.getByText('ICICIBANK')).toBeInTheDocument();
    expect(screen.getByText('ZEEL')).toBeInTheDocument();
    // Never claims a whole-market ranking.
    expect(screen.queryByText(/whole market/i)).not.toBeInTheDocument();
  });

  it('renders research opportunities backed by stored analyst runs', async () => {
    vi.stubGlobal('fetch', mockFetch({ '/api/market/dashboard': dashboardResp }));
    renderDashboard();

    await waitFor(() => {
      expect(screen.getByText('Research Opportunities')).toBeInTheDocument();
    });
    expect(screen.getByText('LT')).toBeInTheDocument();
    expect(screen.getByText('91/100')).toBeInTheDocument();
    expect(screen.getByText('Sentiment Analyst')).toBeInTheDocument();
    expect(screen.getByText(/score 91\/100/)).toBeInTheDocument();
  });

  it('renders an honest error state when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network down'); }));
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/market overview will appear when the backend responds/)).toBeInTheDocument();
    });
    expect(screen.queryByText('Nifty 50')).not.toBeInTheDocument();
  });

  it('renders an honest empty movers state when live quotes are unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        '/api/market/dashboard': {
          ...dashboardResp,
          movers: { status: 'ERROR', tracked: 44, quoted: 0, gainers: [], losers: [] },
        },
      }),
    );
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/movers are never estimated/)).toBeInTheDocument();
    });
    expect(screen.queryByText('Top Gainers')).not.toBeInTheDocument();
  });
});
