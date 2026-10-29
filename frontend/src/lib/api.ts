import type {
  AskAnswer,
  BrokerStatus,
  PortfolioSummary,
  FeedEvent,
  GoalProjection,
  ValidationStatus,
  AuthStatus,
  Brief,
  HoldingRow,
  ObjectiveInfo,
  PortfolioPlan,
  Preferences,
  ResearchHistory,
  CandleSeries,
  Health,
  Instrument,
  LabeledQuote,
  MarketStatus,
  Movers,
  NewsFeed,
  PortfolioStatus,
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
const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  disconnect: () => request<AuthStatus>("/api/auth/upstox/disconnect", { method: "POST" }),
  marketStatus: () => request<MarketStatus>("/api/market/status"),
  indices: () => request<LabeledQuote[]>("/api/market/indices"),
  sectors: () => request<LabeledQuote[]>("/api/market/sectors"),
  movers: () => request<Movers>("/api/market/movers"),
  search: (text: string) => request<Instrument[]>(`/api/instruments/search?q=${encodeURIComponent(text)}&limit=12`),
  lookup: (key: string) => request<Instrument>(`/api/instruments/lookup?key=${q(key)}`),
  stock: (symbol: string) => request<StockSummary>(`/api/stocks/${encodeURIComponent(symbol)}`),
  liveTicks: (key: string) =>
    request<{ key: string; ticks: [number, number, number | null][]; count: number }>(`/api/live/ticks?key=${q(key)}`),
  candles: (key: string, tf: Timeframe) => request<CandleSeries>(`/api/candles?key=${q(key)}&tf=${tf}`),
  watchlist: () => request<LabeledQuote[]>("/api/watchlist"),
  watch: (key: string) => request<void>(`/api/watchlist?key=${q(key)}`, { method: "PUT" }),
  unwatch: (key: string) => request<void>(`/api/watchlist?key=${q(key)}`, { method: "DELETE" }),
  news: () => request<NewsFeed>("/api/news"),
  research: () => request<ResearchOverview>("/api/research"),
  researchFor: (symbol: string) => request<ResearchItem>(`/api/research/${encodeURIComponent(symbol)}`),
  runResearch: (symbol: string) =>
    request<ResearchItem>(`/api/research/${encodeURIComponent(symbol)}/run`, { method: "POST" }),
  portfolio: () => request<PortfolioStatus>("/api/portfolio"),
  runPortfolio: () => request<PortfolioStatus>("/api/portfolio/run", { method: "POST" }),
  researchHistory: (symbol: string) => request<ResearchHistory>(`/api/research/${encodeURIComponent(symbol)}/history`),
  objectives: () => request<ObjectiveInfo[]>("/api/portfolio/objectives"),
  preferences: () => request<Preferences>("/api/portfolio/preferences"),
  savePreferences: (prefs: Preferences) => request<Preferences>("/api/portfolio/preferences", json("PUT", prefs)),
  plan: (prefs: Preferences) => request<PortfolioPlan>("/api/portfolio/plan", json("POST", prefs)),
  holdings: () => request<HoldingRow[]>("/api/portfolio/holdings"),
  summary: () => request<PortfolioSummary>("/api/portfolio/summary"),
  syncHoldings: () => request<BrokerStatus>("/api/portfolio/holdings/sync", { method: "POST" }),
  saveHoldings: (items: { symbol: string; quantity: number; avg_cost: number | null }[]) =>
    request<HoldingRow[]>("/api/portfolio/holdings", json("PUT", items)),
  brief: () => request<Brief>("/api/portfolio/brief"),
  validation: () => request<ValidationStatus>("/api/research/validation"),
  runValidation: () => request<ValidationStatus>("/api/research/validation/run", { method: "POST" }),
  goal: (body: { preferences: Preferences; target: number; years: number; initial: number; monthly: number }) =>
    request<GoalProjection>("/api/portfolio/goal", json("POST", body)),
  events: () => request<{ events: FeedEvent[]; unread: number }>("/api/events"),
  markSeen: (ids?: string[]) => request<void>("/api/events/seen", json("POST", { ids: ids ?? null })),
  ask: (question: string, history: { role: "user" | "assistant"; content: string }[]) =>
    request<AskAnswer>("/api/assistant/ask", json("POST", { question, history })),
};

export const LOGIN_URL = "/api/auth/upstox/login";
