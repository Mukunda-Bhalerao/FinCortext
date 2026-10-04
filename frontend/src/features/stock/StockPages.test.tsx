import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider } from '../../app/FinCortextContext';
import FundamentalsPage from './FundamentalsPage';
import NewsPage from './NewsPage';
import MarketDataSection from './MarketDataSection';
import InsightsPage from './InsightsPage';
import type { AgentOutputSummary } from '../../types/api';

/**
 * The stock pages (Market Data / Fundamentals / News / Insights) form the
 * investment-platform journey. Only real backend values appear; every
 * insight traces back to a stored agent output; nothing is fabricated.
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

function series(symbol: string, base: number, days = 40) {
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
    name: symbol,
    status: 'CACHED',
    count: days,
    latest_trade_date: '2026-08-28',
    prices,
    source: 'upstox',
  };
}

const quoteResp = {
  symbol: 'TCS',
  name: 'Tata Consultancy Services',
  instrument_key: 'NSE_EQ|INE467B01029',
  status: 'LIVE',
  source: 'upstox',
  timestamp: '2026-09-28T15:30:00+05:30',
  last_price: 2339.0,
  prev_close: 2320.0,
  open: 2325.0,
  high: 2350.0,
  low: 2310.0,
  close: 2339.0,
  volume: 1234567,
  average_price: 2330.0,
  year_high: 3350.0,
  year_low: 1976.8,
  day_change: 19.0,
  day_change_pct: 0.82,
  live: true,
  depth_buy: [
    { price: 2338.0, quantity: 500, orders: 4 },
    { price: 2337.0, quantity: 300, orders: 2 },
  ],
  depth_sell: [{ price: 2339.0, quantity: 529, orders: 18 }],
  total_buy_quantity: 800,
  total_sell_quantity: 529,
  upper_circuit_limit: 2552.5,
  lower_circuit_limit: 2087.5,
};

const coverageResp = {
  symbol: 'TCS',
  name: 'Tata Consultancy Services',
  status: 'CACHED',
  metric_count: 2,
  has_official: false,
  has_provider: true,
  metrics: {
    total_revenue: {
      value: 2670210000000,
      unit: 'INR',
      period_end: '2026-03-31',
      source_type: 'provider',
      source_name: 'provider fundamentals (annual statements)',
      available_at: '2026-09-10T10:00:00Z',
    },
    roe: {
      value: 0.51,
      unit: 'ratio',
      period_end: null,
      source_type: 'web_research',
      source_name: 'Gemini web research (annual figures)',
      available_at: '2026-09-10T10:00:00Z',
    },
  },
};

const newsResp = {
  symbol: 'TCS',
  name: 'Tata Consultancy Services',
  status: 'CACHED',
  count: 1,
  provider_configured: true,
  articles: [
    {
      article_id: 'a1',
      title: 'TCS reports steady quarter',
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

function outputRow(
  agent: string,
  score: number | null,
  signal: AgentOutputSummary['signal'],
  status: AgentOutputSummary['status'],
  factors?: unknown,
): AgentOutputSummary {
  return {
    output_id: `${agent}-1`,
    agent_id: agent,
    entity_id: 'TCS',
    score,
    signal,
    confidence: 0.5,
    factors_json: factors ? JSON.stringify(factors) : undefined,
    generated_at: '2026-08-30T10:00:00Z',
    status,
  };
}

const outputsResp = {
  count: 2,
  outputs: [
    outputRow('firm_analyst', 62, 'buy', 'OK', {
      factors: [
        { name: 'profitability', contribution: 12.5, available: true, detail: 'Margins above peers' },
        { name: 'valuation', contribution: -4.0, available: true, detail: 'P/E above the sector median' },
        { name: 'market_momentum', contribution: null, available: false, detail: 'Momentum needs 2 price points' },
      ],
      data_limitations: ['Valuation rests on snapshot ratios'],
    }),
    outputRow('industry_analyst', null, 'unavailable', 'UNAVAILABLE'),
  ],
};

const marketStatusResp = {
  symbols: [
    { symbol: 'TCS', name: 'Tata Consultancy Services', rows: 40, latest_trade_date: '2026-08-28', status: 'CACHED' },
  ],
};

const fullMocks: Record<string, unknown> = {
  '/api/universe': universeResp,
  '/api/market/prices/TCS': series('TCS', 2300),
  '/api/market/quote/TCS?instrument_key=NSE_EQ%7CINE467B01029': quoteResp,
  '/api/market/quote/TCS': quoteResp,
  '/api/fundamentals/TCS': coverageResp,
  '/api/news/TCS?limit=5': newsResp,
  '/api/news/TCS?limit=50': newsResp,
  '/api/news/status': { news_api_configured: true, google_rss_configured: true },
  '/api/market/status': marketStatusResp,
  '/api/filings?symbol=TCS': { count: 0, documents: [] },
  '/api/agents/outputs?symbol=TCS&limit=30': outputsResp,
  '/api/macro/latest': { count: 0, output: null },
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

function renderPage(ui: React.ReactElement, initial = ['/']) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <FinCortextProvider>{ui}</FinCortextProvider>
    </MemoryRouter>,
  );
}

describe('InsightsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('derives opportunities and risks from real stored agent output', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderPage(<InsightsPage />);

    await waitFor(() => {
      expect(screen.getByText('1 of 3')).toBeInTheDocument();
    });
    // Signals strip: backed by stored outputs, unavailable analyst explicit.
    expect(screen.getByText('Firm Analyst', { selector: '.summary-card-label' })).toBeInTheDocument();
    expect(screen.getByText('62/100')).toBeInTheDocument();
    expect(screen.getByText('Industry Analyst', { selector: '.summary-card-label' })).toBeInTheDocument();
    expect(screen.getByText('Not run yet — use the button above.')).toBeInTheDocument();
    // Opportunities from real positive factors.
    expect(screen.getByText('Profitability')).toBeInTheDocument();
    expect(screen.getByText(/Margins above peers/)).toBeInTheDocument();
    // Risks from real adverse factors + stored limitations + missing factors.
    expect(screen.getByText('Valuation')).toBeInTheDocument();
    expect(screen.getByText(/P\/E above the sector median/)).toBeInTheDocument();
    expect(screen.getByText(/Valuation rests on snapshot ratios/)).toBeInTheDocument();
    expect(screen.getByText(/Momentum needs 2 price points/)).toBeInTheDocument();
  });

  it('shows an honest empty state with no fabricated insights', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        '/api/universe': universeResp,
        '/api/agents/outputs?symbol=TCS&limit=30': { count: 0, outputs: [] },
        '/api/market/prices/TCS': series('TCS', 2300),
        '/api/market/quote/TCS': quoteResp,
        '/api/market/status': marketStatusResp,
        '/api/macro/latest': { count: 0, output: null },
      }),
    );
    renderPage(<InsightsPage />);
    await waitFor(() => {
      expect(screen.getByText(/No analyst results stored for TCS yet/)).toBeInTheDocument();
    });
    expect(screen.getAllByText(/No stored analyst results yet/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/will rise/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/guaranteed/i)).not.toBeInTheDocument();
  });
});

describe('FundamentalsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders metrics with per-metric source labels', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderPage(<FundamentalsPage />);
    await waitFor(() => {
      expect(screen.getByText('Total Revenue')).toBeInTheDocument();
    });
    expect(screen.getByText('₹2,67,021.00 Cr')).toBeInTheDocument();
    expect(screen.getByText('Return on Equity')).toBeInTheDocument();
    expect(screen.getByText('WEB-RESEARCHED')).toBeInTheDocument();
    expect(screen.getByText('IMPORTED OFFICIAL DATA')).not.toBeInTheDocument();
  });

  it('renders an honest unavailable state when nothing is stored', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        '/api/universe': universeResp,
        '/api/fundamentals/TCS': {
          symbol: 'TCS',
          name: 'Tata Consultancy Services',
          status: 'UNAVAILABLE',
          metric_count: 0,
          has_official: false,
          has_provider: false,
          metrics: {},
        },
      }),
    );
    renderPage(<FundamentalsPage />);
    await waitFor(() => {
      expect(screen.getByText(/No fundamentals stored for TCS yet/)).toBeInTheDocument();
    });
    expect(screen.getByText('Research figures from the web (labeled)')).toBeInTheDocument();
  });
});

describe('NewsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders stored articles with sources and dates', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderPage(<NewsPage />);
    await waitFor(() => {
      expect(screen.getByText('TCS reports steady quarter')).toBeInTheDocument();
    });
    expect(screen.getByText('Example News')).toBeInTheDocument();
  });

  it('renders an honest unavailable state when nothing is stored', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch({
        '/api/universe': universeResp,
        '/api/news/TCS?limit=5': {
          symbol: 'TCS',
          name: 'Tata Consultancy Services',
          status: 'UNAVAILABLE',
          count: 0,
          provider_configured: true,
          articles: [],
        },
        '/api/news/status': { news_api_configured: true, google_rss_configured: true },
      }),
    );
    renderPage(<NewsPage />);
    await waitFor(() => {
      expect(screen.getByText(/No stored news for TCS yet/)).toBeInTheDocument();
    });
  });
});

describe('MarketDataSection', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders the candle chart, live order book and quote stats', async () => {
    vi.stubGlobal('fetch', mockFetch(fullMocks));
    renderPage(<MarketDataSection />);
    await waitFor(() => {
      expect(screen.getByText('Price Chart')).toBeInTheDocument();
    });
    expect(screen.getByText('Live Order Book')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Bid Price')).toBeInTheDocument();
    });
    expect(screen.getByText('Ask Price')).toBeInTheDocument();
    expect(screen.getByText(/Total buy qty/)).toBeInTheDocument();
    expect(screen.getByText('52w High')).toBeInTheDocument();
  });

  it('renders an honest empty order book when the quote is not live', async () => {
    const notLive = { ...quoteResp, live: false, status: 'CACHED', depth_buy: null, depth_sell: null };
    vi.stubGlobal(
      'fetch',
      mockFetch({
        ...fullMocks,
        '/api/market/quote/TCS?instrument_key=NSE_EQ%7CINE467B01029': notLive,
        '/api/market/quote/TCS': notLive,
      }),
    );
    renderPage(<MarketDataSection />);
    await waitFor(() => {
      expect(screen.getByText(/only available from a live market quote/)).toBeInTheDocument();
    });
    expect(screen.queryByText('Bid Price')).not.toBeInTheDocument();
  });
});
