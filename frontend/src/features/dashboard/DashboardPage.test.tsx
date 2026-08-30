import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DashboardPage from './DashboardPage';

/**
 * The Dashboard consumes real backend data via `fetch` (through api.ts).
 * These tests pin the data-honesty contract: available values are shown
 * as-is, and UNAVAILABLE states explain why instead of fabricating numbers.
 */

const universeResp = {
  universe_version: '1.0.0',
  count: 1,
  entries: [
    {
      symbol: 'TCS',
      name: 'Tata Consultancy Services',
      exchange: 'NSE',
      ticker: 'TCS.NS',
      sector: 'Information Technology',
      industry: 'IT Services & Consulting',
    },
  ],
};

const liveSeries = {
  symbol: 'TCS',
  name: 'Tata Consultancy Services',
  status: 'LIVE',
  count: 2,
  latest_trade_date: '2026-08-28',
  prices: [
    { date: '2026-08-27', open: 2300, high: 2330, low: 2290, close: 2320, volume: 1000 },
    { date: '2026-08-28', open: 2320, high: 2350, low: 2310, close: 2342, volume: 1100 },
  ],
};

const unavailableSeries = {
  symbol: 'LT',
  name: 'Larsen & Toubro',
  status: 'UNAVAILABLE',
  count: 0,
  latest_trade_date: null,
  prices: [],
};

const outputsResp = {
  count: 1,
  outputs: [
    {
      output_id: 'o1',
      agent_id: 'firm_analyst',
      entity_id: 'TCS',
      score: 59.2,
      signal: 'buy',
      confidence: 0.06,
      generated_at: '2026-08-30T10:00:00Z',
      status: 'DEGRADED',
    },
  ],
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

describe('DashboardPage data honesty', () => {
  it('renders real LIVE market values and stored analyst results', async () => {
    const fetchMock = mockFetch({
      '/api/universe': universeResp,
      '/api/market/prices/TCS': liveSeries,
      // api.agents.outputs builds `?symbol=TCS&limit=30` (limit set last).
      '/api/agents/outputs?symbol=TCS&limit=30': outputsResp,
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/']}>
        <DashboardPage />
      </MemoryRouter>,
    );

    // Real stored values appear — not placeholders.
    await waitFor(() => {
      expect(screen.getByText(/2,342\.00/)).toBeInTheDocument(); // latest close from API
    });
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    // "DEGRADED" appears in the analyst card badge and the combined-scores row.
    expect(screen.getAllByText('DEGRADED').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('BUY')).toBeInTheDocument();
    expect(screen.getByText(/Confidence 6%/)).toBeInTheDocument();
    expect(screen.getByText('2026-08-28')).toBeInTheDocument();
    // Never shows fake/sample midpoint for a real close.
    expect(screen.queryByText(/50/)).not.toBeInTheDocument();
  });

  it('renders an honest UNAVAILABLE state instead of fabricated numbers', async () => {
    const fetchMock = mockFetch({
      '/api/universe': universeResp,
      '/api/market/prices/LT': unavailableSeries,
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/']}>
        <DashboardPage />
      </MemoryRouter>,
    );

    // The page starts on TCS but no TCS data is mocked → still renders the
    // UNAVAILABLE explanation after the fetch resolves empty.
    await waitFor(() => {
      expect(
        screen.getByText(/No stored price history/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/2,342\.00/)).not.toBeInTheDocument();
    expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument();
  });
});