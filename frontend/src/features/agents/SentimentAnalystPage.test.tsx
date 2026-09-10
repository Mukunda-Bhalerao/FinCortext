import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider } from '../../app/FinCortextContext';
import SentimentAnalystPage from './SentimentAnalystPage';

const newsStatusResp = {
  provider: 'newsapi',
  configured: true,
  status: 'LIVE',
  message: null,
};

const storedNewsResp = {
  symbol: 'TCS',
  name: 'Tata Consultancy Services',
  status: 'CACHED',
  count: 3,
  provider_configured: true,
  articles: [],
};

function sentimentRun() {
  return {
    agent_id: 'sentiment_analyst',
    entity_id: 'TCS',
    score: 62.5,
    signal: 'buy',
    confidence: 0.6,
    factors: [],
    rationale: 'News sentiment for Tata Consultancy Services.',
    evidence: [],
    data_limitations: ['3 relevant of 5 stored.'],
    generated_at: '2026-09-10T10:00:00Z',
    data_version: '1.0',
    provenance: {
      methodology: 'sentiment_analyst_v1',
      articles_stored: 5,
      articles_relevant: 3,
      articles_rejected: 2,
      latest_article_date: '2026-09-05',
    },
    status: 'OK',
  };
}

describe('SentimentAnalystPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('shows the stored-news status for the company, not a decorative LIVE badge', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/news/status') {
          return new Response(JSON.stringify(newsStatusResp), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url === '/api/news/TCS?limit=5') {
          return new Response(JSON.stringify(storedNewsResp), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(JSON.stringify({}), { status: 404 });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/intelligence/sentiment']}>
        <FinCortextProvider>
          <SentimentAnalystPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    // Real stored state: 3 CACHED articles — the badge mirrors storage, while
    // the provider being configured is stated as plain text, not a LIVE badge.
    await waitFor(() => {
      expect(screen.getByText(/3 stored articles for TCS/)).toBeInTheDocument();
    });
    expect(screen.getByText('CACHED')).toBeInTheDocument();
    expect(screen.getByText(/Live financial-news retrieval is configured\./)).toBeInTheDocument();
  });

  it('runs the analysis for the selected symbol and shows news-through dates', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === '/api/news/status') {
          return new Response(JSON.stringify(newsStatusResp), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url === '/api/news/TCS?limit=5') {
          return new Response(JSON.stringify(storedNewsResp), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url === '/api/agents/sentiment_analyst/TCS/run' && init?.method === 'POST') {
          return new Response(JSON.stringify(sentimentRun()), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response(JSON.stringify({}), { status: 404 });
      }),
    );
    render(
      <MemoryRouter initialEntries={['/intelligence/sentiment']}>
        <FinCortextProvider>
          <SentimentAnalystPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run analysis'));
    await waitFor(() => {
      expect(
        screen.getByText('News sentiment for Tata Consultancy Services.'),
      ).toBeInTheDocument();
    });
    // Analysis time vs data-through date are shown separately.
    expect(screen.getByText(/news through 2026-09-05/)).toBeInTheDocument();
    expect(screen.getByText(/3 relevant of 5 stored/)).toBeInTheDocument();
  });
});
