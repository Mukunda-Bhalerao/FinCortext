import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

describe('App demo navigation', () => {
  it('shows the investment-platform destinations in the sidebar', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(nav).toHaveTextContent('Stock Overview');
    expect(nav).toHaveTextContent('Market Data');
    expect(nav).toHaveTextContent('Fundamentals');
    expect(nav).toHaveTextContent('News');
    expect(nav).toHaveTextContent('Insights');
    expect(nav).toHaveTextContent('Portfolio Intelligence');

    // The four analysts run behind the scenes â€” they are not nav sections.
    expect(nav).not.toHaveTextContent('Firm Analyst');
    expect(nav).not.toHaveTextContent('Industry Analyst');
    expect(nav).not.toHaveTextContent('Macro Analyst');
    expect(nav).not.toHaveTextContent('Sentiment Analyst');
    expect(nav).not.toHaveTextContent('Intelligence Summary');

    // No data/backend sections in the demo UI â€” routes stay reachable by URL.
    expect(nav).not.toHaveTextContent('Data Sources');
    expect(nav).not.toHaveTextContent('Data Pipeline');
    expect(nav).not.toHaveTextContent('Filing Import');
    expect(nav).not.toHaveTextContent('Data Quality');
    expect(nav).not.toHaveTextContent('Risk & Constraints');
    expect(nav).not.toHaveTextContent('Optimization');
    expect(nav).not.toHaveTextContent('Backtesting');
    expect(nav).not.toHaveTextContent('Performance');
    expect(nav).not.toHaveTextContent('Experiments');
  });

  it('hides the roadmap from the sidebar everywhere', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    // No expansion section and no Roadmap entry anywhere in the sidebar.
    expect(screen.queryByRole('navigation', { name: 'Expansion' })).toBeNull();
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(nav).not.toHaveTextContent('Roadmap');
    expect(screen.queryByRole('link', { name: /roadmap/i })).toBeNull();
  });

  it('collapses the sidebar to icons and expands it back', () => {
    localStorage.clear();
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    );
    const sidebar = document.querySelector('.sidebar');
    expect(sidebar).not.toBeNull();
    expect(sidebar!.classList.contains('collapsed')).toBe(false);

    // Minimize: icon rail only.
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(sidebar!.classList.contains('collapsed')).toBe(true);
    expect(localStorage.getItem('fincortext:sidebar-collapsed')).toBe('1');
    // Destinations stay reachable â€” icons keep their links and tooltips.
    expect(screen.getByRole('link', { name: 'Stock Overview' })).toHaveAttribute(
      'href',
      expect.stringContaining('/'),
    );

    // Expand again.
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    expect(sidebar!.classList.contains('collapsed')).toBe(false);
    expect(localStorage.getItem('fincortext:sidebar-collapsed')).toBe('0');
    localStorage.clear();
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

  it('routes to the portfolio synthesis page (implemented, not a placeholder)', () => {
    render(
      <MemoryRouter initialEntries={['/portfolio']}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'Portfolio Synthesis' })).toBeInTheDocument();
  });

  it('keeps the selected company across Dashboard â†’ analyst â†’ Dashboard navigation', async () => {
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

    // Dashboard â†’ each demo page â†’ Dashboard must keep the company correct.
    const legs: Array<{ link: string; heading: string }> = [
      { link: 'Company Analysis', heading: 'Company Analysis' },
      { link: 'Firm Analyst', heading: 'Firm Analyst' },
      { link: 'Industry Analyst', heading: 'Industry Analyst' },
      { link: 'Macro Analyst', heading: 'Macro Analyst' },
      { link: 'Sentiment Analyst', heading: 'Sentiment Analyst' },
      { link: 'Intelligence Summary', heading: 'Combined Intelligence Summary' },
      { link: 'Portfolio Synthesis', heading: 'Portfolio Synthesis' },
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
        // Analyst page kept the company â€” no reset to TCS.
        expect(screen.getByRole('combobox')).toHaveValue('RELIANCE');

        fireEvent.click(screen.getByRole('link', { name: 'Stock Overview' }));
        await waitFor(() => {
          expect(screen.getByRole('combobox')).toHaveValue('RELIANCE');
        });
      }
    } finally {
      vi.unstubAllGlobals();
    }
  });
});