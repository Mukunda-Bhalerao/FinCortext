import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

describe('App demo navigation', () => {
  it('shows only Dashboard and the four intelligence entries', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation');
    expect(nav).toHaveTextContent('Dashboard');
    expect(nav).toHaveTextContent('Firm Analyst');
    expect(nav).toHaveTextContent('Industry Analyst');
    expect(nav).toHaveTextContent('Sentiment Analyst');
    expect(nav).toHaveTextContent('Combined Summary');

    // Hidden for the demo — pages/routes still exist, just not in the nav.
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

    // Dashboard → each analyst → Dashboard must keep the company correct.
    const legs: Array<{ link: string; heading: string }> = [
      { link: 'Firm Analyst', heading: 'Firm Analyst' },
      { link: 'Industry Analyst', heading: 'Industry Analyst' },
      { link: 'Sentiment Analyst', heading: 'Sentiment Analyst' },
      { link: 'Combined Summary', heading: 'Combined Intelligence Summary' },
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