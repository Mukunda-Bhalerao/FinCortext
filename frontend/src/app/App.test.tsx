import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

describe('App demo navigation', () => {
  it('shows the six demo destinations in the sidebar', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Company Analysis');
    expect(nav).toHaveTextContent('Firm Analyst');
    expect(nav).toHaveTextContent('Industry Analyst');
    expect(nav).toHaveTextContent('Sentiment Analyst');
    expect(nav).toHaveTextContent('Intelligence Summary');

    // No data/backend sections in the demo UI — routes stay reachable by URL.
    expect(nav).not.toHaveTextContent('Data Sources');
    expect(nav).not.toHaveTextContent('Data Pipeline');
    expect(nav).not.toHaveTextContent('Market Data');
    expect(nav).not.toHaveTextContent('Filing Import');
    expect(nav).not.toHaveTextContent('Data Quality');
    expect(nav).not.toHaveTextContent('Macro Analyst');
    expect(nav).not.toHaveTextContent('Portfolio Agent');
    expect(nav).not.toHaveTextContent('Risk & Constraints');
    expect(nav).not.toHaveTextContent('Optimization');
    expect(nav).not.toHaveTextContent('Backtesting');
    expect(nav).not.toHaveTextContent('Performance');
    expect(nav).not.toHaveTextContent('Experiments');
  });

  it('shows a separate expansion area with the roadmap marked as upcoming', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    const expansion = screen.getByRole('navigation', { name: 'Expansion' });
    expect(expansion).toHaveTextContent('Roadmap');
    expect(expansion).toHaveTextContent('Soon');
    // Primary nav stays clean — the roadmap lives outside it.
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(nav).not.toHaveTextContent('Roadmap');
  });

  it('routes to the roadmap skeleton with under-development modules', async () => {
    render(
      <MemoryRouter initialEntries={['/roadmap']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Roadmap' })).toBeInTheDocument();
    expect(screen.getAllByText('Under Development').length).toBeGreaterThan(0);
    expect(screen.getByText('Backtesting')).toBeInTheDocument();
  });

  it('keeps hidden routes reachable (Market Data page still mounted)', () => {
    render(
      <MemoryRouter initialEntries={['/data/market']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Market Data' })).toBeInTheDocument();
  });

  it('keeps hidden routes reachable (Portfolio placeholder still mounted)', () => {
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Portfolio Agent' })).toBeInTheDocument();
  });

  it('keeps the selected company across Dashboard → analyst → Dashboard navigation', async () => {
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/universe') {
        return new Response(JSON.stringify(universeResp), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({}), { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);

    // Dashboard → each demo page → Dashboard must keep the company correct.
    const legs: Array<{ link: string; heading: string }> = [
      { link: 'Company Analysis', heading: 'Company Analysis' },
      { link: 'Firm Analyst', heading: 'Firm Analyst' },
      { link: 'Industry Analyst', heading: 'Industry Analyst' },
      { link: 'Sentiment Analyst', heading: 'Sentiment Analyst' },
      { link: 'Intelligence Summary', heading: 'Combined Intelligence Summary' },
    ];

    try {
      render(
        <MemoryRouter initialEntries={['/?symbol=RELIANCE']}>
          <App />
        </MemoryRouter>,
      );

      // Dashboard picks up the company from the URL.
      await waitFor(() => {
        expect(screen.getByRole('combobox')).toHaveValue('RELIANCE');
      });

      for (const leg of legs) {
        fireEvent.click(screen.getByRole('link', { name: leg.link }));
        await waitFor(() => {
          expect(
            screen.getByRole('heading', { name: leg.heading }),
          ).toBeInTheDocument();
        });
        // Analyst page kept the company — no reset to TCS.
        expect(screen.getByRole('combobox')).toHaveValue('RELIANCE');

        fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }));
        await waitFor(() => {
          expect(screen.getByRole('combobox')).toHaveValue('RELIANCE');
        });
      }
    } finally {
      vi.unstubAllGlobals();
    }
  });
});