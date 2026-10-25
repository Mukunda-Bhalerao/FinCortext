// Mirrors backend/app/schemas/market.py

export type Freshness = "live" | "delayed" | "stale" | "last_close" | "unavailable";
export type Timeframe = "1m" | "5m" | "15m" | "1H" | "1D" | "1W" | "1M";
export const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1H", "1D", "1W", "1M"];

export interface Instrument {
  instrument_key: string;
  symbol: string;
  name: string | null;
  exchange: string;
  segment: string;
  instrument_type: string;
  isin: string | null;
}

export interface Quote {
  instrument_key: string;
  symbol: string | null;
  ltp: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  avg_price: number | null;
  upper_circuit: number | null;
  lower_circuit: number | null;
  last_trade_time: string | null;
  source: string;
  fetched_at: string;
  freshness: Freshness;
}

export interface LabeledQuote {
  label: string;
  instrument: Instrument;
  quote: Quote | null;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  oi: number | null;
}

export interface CandleSeries {
  instrument_key: string;
  timeframe: Timeframe;
  unit: string;
  interval: number;
  candles: Candle[];
  includes_current_session: boolean;
  source: string;
  fetched_at: string;
  data_gaps: string[];
}

export interface MarketStatus {
  state: "open" | "pre_open" | "closed";
  basis: "exchange_feed" | "schedule";
  detail: string;
  as_of: string;
}

export interface Movers {
  universe: string;
  gainers: LabeledQuote[];
  losers: LabeledQuote[];
  most_active: LabeledQuote[];
  advances: number;
  declines: number;
  unchanged: number;
  constituents_total: number;
  quotes_received: number;
  source: string;
  as_of: string | null;
}

export interface NewsItem {
  title: string;
  link: string;
  publisher: string;
  published_at: string | null;
}

export interface NewsFeed {
  items: NewsItem[];
  sources_ok: string[];
  sources_failed: string[];
  fetched_at: string;
}

export interface StockSummary {
  instrument: Instrument;
  quote: Quote | null;
  week52_high: number | null;
  week52_low: number | null;
  week52_basis: string | null;
  in_watchlist: boolean;
  problems: string[];
}

export interface AuthStatus {
  oauth_configured: boolean;
  connected: boolean;
  token_source: "oauth" | "env" | "none";
  user_name: string | null;
  expected_expiry: string | null;
  problem: string | null;
}

export interface LiveStatus {
  transport: "stream" | "poll" | "idle";
  state: "connected" | "connecting" | "disconnected" | "unauthorized" | "not_connected";
  detail: string | null;
  subscribed: number;
  last_message_at: string | null;
}

export interface Health {
  status: string;
  instruments: { count: number; loaded_on: string | null; error: string | null };
  upstox: AuthStatus;
  live: LiveStatus;
  market: MarketStatus;
}

export interface FeedBar {
  interval: string;
  start_ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Tick {
  type: "tick";
  key: string;
  ltp: number;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  last_trade_ms: number | null;
  volume: number | null;
  avg_price: number | null;
  bars: FeedBar[];
  transport: "stream" | "poll";
  received_at: string;
}

export interface StatusMessage extends LiveStatus {
  type: "status";
  market: MarketStatus;
}
