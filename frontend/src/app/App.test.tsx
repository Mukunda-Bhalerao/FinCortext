import { render, screen } from '@testing-library/react';
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
});