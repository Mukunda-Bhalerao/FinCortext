/** Typed API service layer — the ONLY place the frontend touches the backend. */

import type {
  AgentOutput,
  AgentOutputSummary,
  FilingsListResponse,
  FilingImportResult,
  FundamentalsCoverageResponse,
  HealthInfo,
  MacroIndicatorCoverage,
  MacroOutput,
  MarketStatusResponse,
  NewsListResponse,
  NewsRefreshResponse,
  NewsStatusResponse,
  PriceSeriesResponse,
  RefreshResult,
  UniverseResponse,
} from '../types/api';

class ApiRequestError extends Error {
  code: string;
  details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiRequestError('network_error', 'Backend is unreachable. Is it running?');
  }
  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = `Request failed (HTTP ${response.status})`;
    let details: Record<string, unknown> = {};
    try {
      const body = await response.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        details = body.error.details ?? details;
      }
    } catch {
      /* non-JSON error body — keep defaults */
    }
    throw new ApiRequestError(code, message, details);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthInfo>('/health'),

  universe: () => request<UniverseResponse>('/api/universe'),

  market: {
    status: () => request<MarketStatusResponse>('/api/market/status'),
    prices: (symbol: string) =>
      request<PriceSeriesResponse>(`/api/market/prices/${encodeURIComponent(symbol)}`),
    refreshSymbol: (symbol: string) =>
      request<RefreshResult>(`/api/market/refresh/${encodeURIComponent(symbol)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(null),
      }),
  },

  filings: {
    list: (symbol?: string) =>
      request<FilingsListResponse>(
        `/api/filings${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`,
      ),
    import: (
      file: File,
      symbol: string,
      sourceName: string,
      filingDate?: string,
      publishedAt?: string,
    ) => {
      const form = new FormData();
      form.append('file', file);
      form.append('symbol', symbol);
      form.append('source_name', sourceName);
      if (filingDate) form.append('filing_date', filingDate);
      if (publishedAt) form.append('published_at', publishedAt);
      return request<FilingImportResult>('/api/filings/import', {
        method: 'POST',
        body: form,
      });
    },
  },

  news: {
    status: () => request<NewsStatusResponse>('/api/news/status'),
    list: (symbol: string, limit = 50) =>
      request<NewsListResponse>(
        `/api/news/${encodeURIComponent(symbol)}?limit=${limit}`,
      ),
    refresh: (symbol: string, days = 7) =>
      request<NewsRefreshResponse>(
        `/api/news/refresh/${encodeURIComponent(symbol)}?days=${days}`,
        { method: 'POST' },
      ),
  },

  fundamentals: {
    coverage: (symbol: string) =>
      request<FundamentalsCoverageResponse>(
        `/api/fundamentals/${encodeURIComponent(symbol)}`,
      ),
  },

  agents: {
    run: (agentId: string, symbol: string) =>
      request<AgentOutput>(
        `/api/agents/${encodeURIComponent(agentId)}/${encodeURIComponent(symbol)}/run`,
        { method: 'POST' },
      ),
    outputs: (agentId?: string, symbol?: string, limit = 50) => {
      const params = new URLSearchParams();
      if (agentId) params.set('agent_id', agentId);
      if (symbol) params.set('symbol', symbol);
      params.set('limit', String(limit));
      return request<{ count: number; outputs: AgentOutputSummary[] }>(
        `/api/agents/outputs?${params.toString()}`,
      );
    },
  },

  macro: {
    /** Market-wide run. `symbol` is request context only — the result is
     *  identical for every company and never a company score. */
    run: (symbol: string) =>
      request<MacroOutput>(
        `/api/agents/macro/${encodeURIComponent(symbol)}/run`,
        { method: 'POST' },
      ),
    latest: () =>
      request<{ count: number; output: MacroOutput | null }>('/api/macro/latest'),
    history: (limit = 20) =>
      request<{ count: number; outputs: Record<string, unknown>[] }>(
        `/api/macro/history?limit=${limit}`,
      ),
    coverage: () =>
      request<{ indicators: MacroIndicatorCoverage[] }>('/api/macro/indicators'),
  },
};

export { ApiRequestError };