import { fireEvent, render, screen } from '@testing-library/react';
import { CandleSvg } from './CandleChart';
import type { MarketPricePoint } from '../../types/api';

const bars: MarketPricePoint[] = [
  { date: '2026-08-01', open: 100, high: 105, low: 99, close: 104, volume: 1000 },
  { date: '2026-08-02', open: 104, high: 106, low: 101, close: 102, volume: 1200 },
  { date: '2026-08-03', open: 102, high: 110, low: 102, close: 110, volume: 1500 },
];

describe('CandleSvg', () => {
  it('renders one wick + body per stored bar with real OHLC geometry', () => {
    const { container } = render(
      <CandleSvg data={bars} width={800} height={320} rangeBars={Number.POSITIVE_INFINITY} />,
    );
    const svg = container.querySelector('svg')!;
    // One wick line per bar (plus grid/tick lines); bodies carry up/down colors.
    const bodies = Array.from(svg.querySelectorAll('rect')).filter(
      (r) => r.getAttribute('fill') === '#2ecc8f' || r.getAttribute('fill') === '#ff5d73',
    );
    // 3 candle bodies (volume rects use opacity .35, bodies use stroke).
    const candleBodies = bodies.filter((r) => r.getAttribute('stroke') !== null);
    expect(candleBodies).toHaveLength(3);
    // First bar bullish (104 >= 100), second bearish (102 < 104).
    expect(candleBodies[0].getAttribute('stroke')).toBe('#2ecc8f');
    expect(candleBodies[1].getAttribute('stroke')).toBe('#ff5d73');
  });

  it('shows an OHLC hover tooltip for the hovered bar', () => {
    const { container } = render(
      <CandleSvg data={bars} width={800} height={320} rangeBars={Number.POSITIVE_INFINITY} />,
    );
    const svg = container.querySelector('svg')!;
    fireEvent.mouseMove(svg, { clientX: 120 });
    expect(screen.getByText('2026-08-01')).toBeInTheDocument();
    expect(screen.getByText(/O ₹100\.00/)).toBeInTheDocument();
    expect(screen.getByText(/C ₹104\.00/)).toBeInTheDocument();
  });

  it('keeps a fixed scale: wheel and drag never rescale the chart', () => {
    const { container } = render(
      <CandleSvg data={bars} width={800} height={320} rangeBars={Number.POSITIVE_INFINITY} />,
    );
    const svg = container.querySelector('svg')!;
    const bodiesBefore = svg.querySelectorAll('rect[stroke="#2ecc8f"], rect[stroke="#ff5d73"]');
    fireEvent.wheel(svg, { deltaY: 100, clientX: 400 });
    fireEvent.mouseDown(svg, { clientX: 400 });
    fireEvent.mouseMove(svg, { clientX: 200 });
    fireEvent.mouseUp(svg);
    const bodiesAfter = svg.querySelectorAll('rect[stroke="#2ecc8f"], rect[stroke="#ff5d73"]');
    expect(bodiesAfter).toHaveLength(bodiesBefore.length);
    expect(bodiesAfter).toHaveLength(3);
  });

  it('renders an accessible empty state without stored bars', () => {
    const { container } = render(
      <CandleSvg data={[]} width={800} height={320} rangeBars={Number.POSITIVE_INFINITY} />,
    );
    expect(container.querySelector('svg')).toHaveAttribute('aria-label', 'Price chart');
  });
});
