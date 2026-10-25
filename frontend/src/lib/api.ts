import type {
  AuthStatus,
  CandleSeries,
  Health,
  Instrument,
  LabeledQuote,
  MarketStatus,
  Movers,
  NewsFeed,
  ResearchItem,
  ResearchOverview,
  StockSummary,
  Timeframe,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly status: number,
  ) {
    super(message);
  }

  get needsConnection(): boolean {
    return this.code === "provider_not_connected" || this.code === "provider_token_invalid";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, { ...init, headers: { Accept: "application/json", ...init?.headers } });
  } catch {
    throw new ApiError("The FinCortext backend is not reachable.", "backend_unreachable", 0);
  }
  if (resp.status === 204) return undefined as T;
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    if (body === null && resp.status >= 500) {
      // The dev proxy answers with an empty 5xx when the backend process is down.
      throw new ApiError("The FinCortext backend is not reachable.", "backend_unreachable", resp.status);
    }
    const err = (body as { error?: { code?: string; message?: string } } | null)?.error;
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(
      err?.message ?? (typeof detail === "string" ? detail : `Request failed (${resp.status})`),
      err?.code ?? "http_error",
      resp.status,
    );
  }
  return body as T;
}

const q = (key: string) => encodeURIComponent(key);

export const api = {
  health: () => request<Health>("/api/health"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  disconnect: () => request<AuthStatus>("/api/auth/upstox/disconnect", { method: "POST" }),
  marketStatus: () => request<MarketStatus>("/api/market/status"),
  indices: () => request<LabeledQuote[]>("/api/market/indices"),
  sectors: () => request<LabeledQuote[]>("/api/market/sectors"),
  movers: () => request<Movers>("/api/market/movers"),
  search: (text: string) =>
    request<Instrument[]>(`/api/instruments/search?q=${encodeURIComponent(text)}&limit=12`),
  lookup: (key: string) => request<Instrument>(`/api/instruments/lookup?key=${q(key)}`),
  stock: (symbol: string) => request<StockSummary>(`/api/stocks/${encodeURIComponent(symbol)}`),
  candles: (key: string, tf: Timeframe) =>
    request<CandleSeries>(`/api/candles?key=${q(key)}&tf=${tf}`),
  watchlist: () => request<LabeledQuote[]>("/api/watchlist"),
  watch: (key: string) => request<void>(`/api/watchlist?key=${q(key)}`, { method: "PUT" }),
  unwatch: (key: string) => request<void>(`/api/watchlist?key=${q(key)}`, { method: "DELETE" }),
  news: () => request<NewsFeed>("/api/news"),
  research: () => request<ResearchOverview>("/api/research"),
  researchFor: (symbol: string) => request<ResearchItem>(`/api/research/${encodeURIComponent(symbol)}`),
  runResearch: (symbol: string) =>
    request<ResearchItem>(`/api/research/${encodeURIComponent(symbol)}/run`, { method: "POST" }),
};

export const LOGIN_URL = "/api/auth/upstox/login";
