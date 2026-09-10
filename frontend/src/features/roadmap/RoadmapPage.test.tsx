import { render, screen } from '@testing-library/react';
import RoadmapPage from './RoadmapPage';

/** The roadmap is skeleton-only: every future module is explicitly marked
 *  Under Development, with scope text and zero fabricated metrics. */
describe('RoadmapPage', () => {
  it('lists future modules grouped and marked under development', () => {
    render(<RoadmapPage />);

    for (const group of [
      'Portfolio & Optimization',
      'Evaluation',
      'Asset Coverage',
      'Research',
    ]) {
      expect(screen.getByText(group)).toBeInTheDocument();
    }

    const expected = [
      'Portfolio Construction',
      'Portfolio Optimization',
      'Risk Analysis',
      'Backtesting',
      'Performance Attribution',
      'Mutual Fund Intelligence',
      'ETF Intelligence',
      'Fixed Income',
      'Gold & Commodities',
      'REITs / InvITs',
      'Multi-Asset',
      'Evidence Lab',
    ];
    for (const name of expected) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }

    // Every module carries the badge — planned, not broken, not implemented.
    expect(screen.getAllByText('Under Development').length).toBe(expected.length);
  });

  it('contains no fabricated metrics, charts or recommendations', () => {
    const { container } = render(<RoadmapPage />);
    expect(container.querySelector('svg.chart, canvas, table')).toBeNull();
    // No numeric performance figures or currency values anywhere.
    expect(screen.queryByText(/\d+(\.\d+)?%/)).toBeNull();
    expect(screen.queryByText(/₹/)).toBeNull();
  });
});
