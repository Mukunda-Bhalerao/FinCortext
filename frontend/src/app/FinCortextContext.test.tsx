import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FinCortextProvider, sameSymbol, useFinCortext } from './FinCortextContext';
import type { AgentOutput } from '../types/api';

function tcsRun(): AgentOutput {
  return {
    agent_id: 'firm_analyst',
    entity_id: 'TCS',
    score: 61.9,
    signal: 'buy',
    confidence: 0.06,
    factors: [],
    rationale: 'r',
    evidence: [],
    data_limitations: [],
    generated_at: '2026-09-10T10:00:00Z',
    data_version: '1.0',
    provenance: {},
    status: 'DEGRADED',
  };
}

/** Drives the context imperatively so tests can assert cache isolation. */
function Harness() {
  const ctx = useFinCortext();
  return (
    <div>
      <span data-testid="symbol">{ctx.symbol}</span>
      <span data-testid="tcs-run">{ctx.runOf('TCS', 'firm_analyst')?.score ?? 'none'}</span>
      <span data-testid="rel-run">{ctx.runOf('RELIANCE', 'firm_analyst')?.score ?? 'none'}</span>
      <span data-testid="tcs-out">
        {ctx.outputsOf('TCS')?.map((o) => o.entity_id).join(',') ?? 'unfetched'}
      </span>
      <button onClick={() => ctx.recordRun('TCS', 'firm_analyst', tcsRun())}>
        record-tcs
      </button>
      <button onClick={() => ctx.setSymbol('RELIANCE')}>switch</button>
    </div>
  );
}

function renderHarness(initialEntries = ['/']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <FinCortextProvider>
        <Harness />
      </FinCortextProvider>
    </MemoryRouter>,
  );
}

describe('FinCortextContext', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('normalizes URL symbols to canonical uppercase for cache safety', () => {
    renderHarness(['/?symbol=tcs']);
    // Lowercase URL input must resolve to the canonical key everywhere.
    expect(screen.getByTestId('symbol')).toHaveTextContent('TCS');
  });

  it('keeps run results and history isolated per symbol', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({}), { status: 404 })),
    );
    renderHarness();

    expect(screen.getByTestId('rel-run')).toHaveTextContent('none');
    expect(screen.getByTestId('tcs-out')).toHaveTextContent('unfetched');

    fireEvent.click(screen.getByText('record-tcs'));

    await waitFor(() => {
      expect(screen.getByTestId('tcs-run')).toHaveTextContent('61.9');
    });
    // RELIANCE cache untouched; TCS history folded under TCS only.
    expect(screen.getByTestId('rel-run')).toHaveTextContent('none');
    expect(screen.getByTestId('tcs-out')).toHaveTextContent('TCS');

    // Switching companies does not move results across symbols.
    fireEvent.click(screen.getByText('switch'));
    expect(screen.getByTestId('symbol')).toHaveTextContent('RELIANCE');
    expect(screen.getByTestId('tcs-run')).toHaveTextContent('61.9');
    expect(screen.getByTestId('rel-run')).toHaveTextContent('none');
  });

  it('compares symbols case-insensitively', () => {
    expect(sameSymbol('tcs', 'TCS')).toBe(true);
    expect(sameSymbol('TCS', 'INFY')).toBe(false);
  });
});
