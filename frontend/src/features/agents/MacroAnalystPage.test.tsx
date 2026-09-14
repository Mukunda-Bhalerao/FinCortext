import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, useFinCortext } from '../../app/FinCortextContext';
import MacroAnalystPage from './MacroAnalystPage';
import type { MacroOutput } from '../../types/api';

function macroOutput(): MacroOutput {
  return {
    agent_id: 'macro_analyst',
    entity_id: 'MACRO_INDIA',
    requested_symbol: 'TCS',
    score: 50,
    overall_signal: 'neutral',
    confidence: 0.62,
    status: 'OK',
    factors: [
      {
        name: 'growth',
        label: 'Growth',
        value: 7.8,
        unit: '%',
        direction: 'up',
        signal: 'positive',
        confidence: 0.9,
        available: true,
        data_as_of: '2026-06-30',
        detail: 'Latest real GDP growth 7.8%.',
        evidence: [
          {
            indicator_id: 'gdp_real_yoy',
            reference: 'gdp_real_yoy@2026-06-30',
            value: 7.8,
            unit: '%',
            period: '2026-06-30',
            source_name: 'MoSPI releases (curated)',
            source_url: null,
            note: 'Real GDP YoY 7.8%',
          },
        ],
        limitations: [],
      },
      {
        name: 'liquidity_credit',
        label: 'Liquidity & Credit',
        value: null,
        unit: null,
        direction: 'unknown',
        signal: 'unavailable',
        confidence: 0,
        available: false,
        data_as_of: null,
        detail: null,
        evidence: [],
        limitations: ['No reliable liquidity/credit series is configured.'],
      },
    ],
    rationale: 'Macro Environment Signal is NEUTRAL from 6/7 areas. Interpretation: mixed.',
    data_limitations: ['Fiscal developments are not covered.'],
    generated_at: '2026-09-10T10:00:00Z',
    data_through: { gdp_real_yoy: '2026-06-30', repo_rate: '2026-06-05' },
    provenance: {},
    methodology: 'macro_analyst_v1',
  };
}

function Switcher() {
  const { setSymbol } = useFinCortext();
  return <button onClick={() => setSymbol('INFY')}>switch-to-infy</button>;
}

describe('MacroAnalystPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('renders the environment view with factors, evidence and dates', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(macroOutput()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    );
    render(
      <MemoryRouter initialEntries={['/intelligence/macro']}>
        <FinCortextProvider>
          <MacroAnalystPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run analysis'));
    await waitFor(() => {
      expect(screen.getByText('Macro Environment')).toBeInTheDocument();
    });
    // Environment vocabulary with full score/signal presentation — never buy/sell.
    expect(screen.getByText('NEUTRAL')).toBeInTheDocument();
    expect(screen.queryByText(/BUY/i)).not.toBeInTheDocument();
    // Numeric environment score, signal, status and confidence are all shown.
    expect(screen.getByText(/Macro Environment Score: 50 \/ 100/)).toBeInTheDocument();
    expect(screen.getByText(/Signal: NEUTRAL/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 62%/)).toBeInTheDocument();
    // No cryptic three-letter dial.
    expect(screen.queryByText('NEU', { selector: '.score-value' })).not.toBeInTheDocument();
    // Factor with value, direction, as-of date, evidence and source.
    expect(screen.getByText('Growth')).toBeInTheDocument();
    expect(screen.getByText(/as of 2026-06-30/)).toBeInTheDocument();
    expect(screen.getByText(/MoSPI releases \(curated\)/)).toBeInTheDocument();
    // Unavailable factor stays visible as missing, not hidden.
    expect(screen.getByText('Liquidity & Credit')).toBeInTheDocument();
    expect(screen.getByText(/No reliable liquidity/)).toBeInTheDocument();
    // Analysis time vs data-through dates are distinct.
    expect(screen.getByText(/macro data through 2026-06-30/)).toBeInTheDocument();
    expect(screen.getByText(/Fiscal developments are not covered/)).toBeInTheDocument();
  });

  it('keeps the market-wide result across company switches', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(macroOutput()), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    );
    render(
      <MemoryRouter initialEntries={['/intelligence/macro']}>
        <FinCortextProvider>
          <MacroAnalystPage />
          <Switcher />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run analysis'));
    await waitFor(() => {
      expect(screen.getByText('Macro Environment')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('switch-to-infy'));
    // Same market-wide view — still shown, now under the new company header.
    expect(screen.getByText('Macro Environment')).toBeInTheDocument();
    expect(screen.getByText(/Macro Environment Signal is NEUTRAL/)).toBeInTheDocument();
  });

  it('reports run failures honestly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({}), { status: 500 })),
    );
    render(
      <MemoryRouter initialEntries={['/intelligence/macro']}>
        <FinCortextProvider>
          <MacroAnalystPage />
        </FinCortextProvider>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText('Run analysis'));
    await waitFor(() => {
      expect(screen.getByText(/Error:/)).toBeInTheDocument();
    });
    expect(screen.queryByText('Macro Environment')).not.toBeInTheDocument();
  });
});
