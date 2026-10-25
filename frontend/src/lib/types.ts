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
  overall?: "ok" | "degraded" | "down";
  started_at?: string;
  components?: HealthComponent[];
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

// Mirrors backend/app/schemas/research.py

export type AgentName = "firm" | "industry" | "macro" | "sentiment";
export type Signal = "positive" | "neutral" | "negative" | "insufficient_data";
export type ResearchState = "not_started" | "queued" | "running" | "ready" | "failed";

export interface Evidence {
  factor: string;
  metric: string;
  value: number | string | null;
  unit: string | null;
  detail: string | null;
  source: string;
  as_of: string | null;
  score: number | null;
}

export interface FactorScore {
  name: string;
  weight: number;
  score: number | null;
  note: string | null;
}

export interface AgentOutput {
  agent: AgentName;
  subject: string;
  signal: Signal;
  score: number | null;
  confidence: number;
  coverage: number;
  factors: FactorScore[];
  evidence: Evidence[];
  data_gaps: string[];
  rationale: string | null;
  rationale_source: "template" | "model";
  method: string;
  computed_at: string;
}

export interface Composite {
  signal: Signal;
  score: number | null;
  confidence: number;
  agents_used: number;
  method: string;
}

export interface ResearchReport {
  instrument: Instrument;
  classification: {
    industry: string | null;
    industry_source: string | null;
    sector_index: string | null;
    peers: string[];
    peer_basis: string | null;
  };
  agents: AgentOutput[];
  composite: Composite;
  headlines: NewsItem[];
  computed_at: string;
  duration_ms: number;
}

export interface ResearchItem {
  instrument: Instrument;
  state: ResearchState;
  error: string | null;
  stale: boolean;
  report: ResearchReport | null;
  changes?: ResearchChanges | null;
}

export interface ResearchChange {
  agent: AgentName | "composite";
  kind: "signal" | "score" | "factor" | "metric" | "headlines";
  text: string;
  direction: "better" | "worse" | "neutral";
  weight: number;
}

export interface ResearchChanges {
  since: string;
  until: string;
  previous_signal: Signal;
  previous_score: number | null;
  summary: string;
  items: ResearchChange[];
}

export interface HistoryPoint {
  date: string;
  computed_at: string;
  signal: Signal;
  score: number | null;
  confidence: number;
  agents: Record<string, { signal: Signal; score: number | null; confidence: number }>;
}

export interface ResearchHistory {
  instrument: Instrument;
  points: HistoryPoint[];
  changes: ResearchChanges | null;
  first_recorded: string | null;
}

export interface MacroIndicator {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  change: number | null;
  change_unit: string;
  change_window: string;
  as_of: string | null;
  source: string;
  stale: boolean;
  problem: string | null;
}

export interface ResearchOverview {
  items: ResearchItem[];
  macro: MacroIndicator[];
  refresh_after_hours: number;
}

// Mirrors backend/app/schemas/portfolio.py

export interface PerfStats {
  cagr: number | null;
  volatility: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  start: string | null;
  end: string | null;
  days: number;
}

export interface CurvePoint {
  time: number;
  value: number;
}

export interface BacktestResult {
  stats: PerfStats;
  benchmark: PerfStats;
  rebalances: number;
  turnover_per_year: number;
  cost_drag_per_year: number;
  curve: CurvePoint[];
  benchmark_curve: CurvePoint[];
}

export interface StrategyResult {
  key: string;
  label: string;
  description: string;
  weights: { symbol: string; weight: number; risk_contribution: number }[];
  sector_weights: Record<string, number>;
  est_volatility: number;
  diversification_ratio: number;
  effective_n: number;
  trailing: PerfStats;
  constraints_met: boolean;
  constraint_note: string | null;
  backtest: BacktestResult | null;
  backtest_note: string | null;
}

export interface Holding {
  symbol: string;
  name: string | null;
  instrument_key: string;
  sector: string;
  history_days: number;
  research_signal: Signal | null;
  research_score: number | null;
  research_confidence: number | null;
}

export interface Validation {
  start: string;
  end: string;
  vol_without: number | null;
  vol_with: number | null;
  sharpe_without: number | null;
  sharpe_with: number | null;
  mdd_without: number | null;
  mdd_with: number | null;
}

export interface Candidate {
  symbol: string;
  name: string | null;
  instrument_key: string;
  sector: string;
  new_sector: boolean;
  avg_correlation: number;
  volatility: number;
  weight_if_added: number;
  vol_before: number;
  vol_after: number;
  dr_before: number;
  dr_after: number;
  sharpe_before: number | null;
  sharpe_after: number | null;
  rank_score: number;
  validation: Validation | null;
  research_signal: Signal | null;
  research_score: number | null;
  explanation: string;
}

export interface Replacement {
  remove: string;
  add: string;
  vol_before: number;
  vol_after: number;
  dr_before: number;
  dr_after: number;
  remove_research_score: number | null;
  add_research_score: number | null;
  explanation: string;
}

export interface PortfolioAnalysis {
  computed_at: string;
  as_of: string | null;
  holdings: Holding[];
  excluded: { symbol: string; reason: string }[];
  strategies: StrategyResult[];
  reference_strategy: string;
  correlation: { symbols: string[]; matrix: number[][]; average: number | null } | null;
  candidates: Candidate[];
  candidate_universe: string;
  candidates_screened: number;
  replacements: Replacement[];
  risk_free_rate: number;
  risk_free_source: string;
  assumptions: string[];
  limitations: string[];
  duration_ms: number;
  benchmark_label: string;
  return_basis: string;
  objectives: ObjectivePreview[];
  selection: SelectionCheck | null;
}

export interface ObjectivePreview {
  key: ObjectiveKey;
  label: string;
  tagline: string;
  volatility: number | null;
  cagr: number | null;
  after_tax_cagr: number | null;
  max_drawdown: number | null;
  top_weight_symbol: string | null;
  top_weight: number | null;
}

export interface SelectionCheck {
  portfolios: number;
  size: number;
  universe: string;
  start: string;
  end: string;
  your_cagr: number;
  median_cagr: number;
  p10_cagr: number;
  p90_cagr: number;
  percentile: number;
  note: string;
}

export type ObjectiveKey = "lower_risk" | "balanced" | "growth" | "income";

export interface Preferences {
  objective: ObjectiveKey;
  capital: number;
  max_weight: number | null;
  include: string[];
  exclude: string[];
  research_overlay: boolean;
  tax_slab: number;
}

export interface ObjectiveInfo {
  key: ObjectiveKey;
  label: string;
  tagline: string;
  method: string;
}

export interface PlanAsset {
  symbol: string;
  name: string | null;
  instrument_key: string;
  sector: string;
  role: "holding" | "added";
  weight: number;
  risk_share: number;
  volatility: number;
  momentum: number | null;
  dividend_yield: number | null;
  research_signal: Signal | null;
  research_score: number | null;
  research_confidence: number | null;
  price: number | null;
  price_basis: string | null;
}

export interface RiskSummary {
  volatility: number;
  benchmark_volatility: number | null;
  level: "low" | "moderate" | "high" | "very_high";
  level_text: string;
  diversification_ratio: number;
  diversification_score: number;
  effective_n: number;
  top_risk_symbol: string;
  top_risk_share: number;
  largest_weight_symbol: string;
  largest_weight: number;
  sector_weights: Record<string, number>;
  avg_correlation: number | null;
}

export interface YearReturn {
  year: number;
  portfolio: number;
  benchmark: number | null;
  partial: boolean;
}

export interface PlanBacktest {
  start: string;
  end: string;
  years: number;
  limited_by: string | null;
  pre_tax: PerfStats;
  after_tax: PerfStats | null;
  benchmark: PerfStats;
  benchmark_label: string;
  baseline: PerfStats | null;
  baseline_label: string | null;
  curve: CurvePoint[];
  after_tax_curve: CurvePoint[];
  benchmark_curve: CurvePoint[];
  baseline_curve: CurvePoint[];
  costs_per_year: number;
  taxes_per_year: number | null;
  dividends_per_year: number;
  turnover_per_year: number;
  rebalances: number;
  years_table: YearReturn[];
  uncertainty: { excess_low: number; excess_high: number; prob_outperform: number; method: string } | null;
  return_basis: string;
}

export interface StressResult {
  key: string;
  name: string;
  kind: "episode" | "worst_month";
  start: string;
  end: string;
  portfolio: number | null;
  portfolio_drawdown: number | null;
  benchmark: number | null;
  covered: boolean;
  note: string | null;
}

export interface TradeLine {
  symbol: string;
  instrument_key: string;
  price: number | null;
  current_qty: number;
  current_value: number;
  current_weight: number;
  target_weight: number;
  target_value: number;
  delta_value: number;
  delta_qty: number;
  action: "buy" | "sell" | "hold";
}

export interface TradePlan {
  basis: "holdings" | "capital";
  total_value: number;
  lines: TradeLine[];
  est_costs: number;
  cash_left: number;
  realised_gain: number | null;
  note: string;
}

export interface PortfolioPlan {
  preferences: Preferences;
  objective: ObjectiveInfo;
  computed_at: string;
  as_of: string | null;
  assets: PlanAsset[];
  excluded: { symbol: string; reason: string }[];
  risk: RiskSummary | null;
  backtest: PlanBacktest | null;
  backtest_note: string | null;
  stress: StressResult[];
  trades: TradePlan | null;
  current: {
    label: string;
    volatility: number;
    diversification_ratio: number;
    cagr: number | null;
    max_drawdown: number | null;
  } | null;
  explanation: string[];
  weight_note: string | null;
  assumptions: string[];
  limitations: string[];
  duration_ms: number;
}

export interface HoldingRow {
  symbol: string;
  instrument_key: string;
  name: string | null;
  quantity: number;
  avg_cost: number | null;
  price: number | null;
  price_basis: string | null;
  value: number | null;
  updated_at: string;
}

export type FactBasis = "measured" | "estimate" | "observed" | "replay";

export interface Fact {
  id: string;
  text: string;
  source: string;
  basis: FactBasis;
  as_of: string | null;
}

export interface InsightAction {
  kind: "add" | "remove" | "objective" | "open_stock" | "holdings" | "research";
  label: string;
  symbol: string | null;
  objective: ObjectiveKey | null;
}

export interface Insight {
  id: string;
  kind: "risk" | "opportunity" | "change" | "performance" | "data";
  severity: "high" | "medium" | "low";
  title: string;
  body: string;
  facts: string[];
  action: InsightAction | null;
}

export interface AIStatus {
  enabled: boolean;
  model: string | null;
  detail: string | null;
}

export interface Brief {
  generated_at: string;
  analysis_at: string | null;
  headline: string;
  insights: Insight[];
  facts: Fact[];
  narrative: { text: string; cited: string[]; model: string } | null;
  ai: AIStatus;
}

export interface Scenario {
  objective: ObjectiveKey | null;
  include: string[];
  exclude: string[];
  max_weight: number | null;
  label: string | null;
}

export interface AskAnswer {
  answer: string;
  cited: Fact[];
  scenario: Scenario | null;
  grounded: boolean;
  model: string | null;
  generated_at: string;
}

export interface HealthComponent {
  key: string;
  label: string;
  status: "ok" | "degraded" | "down" | "unknown" | "off";
  detail: string | null;
}

export interface PortfolioStatus {
  state: ResearchState;
  error: string | null;
  stale: boolean;
  result: PortfolioAnalysis | null;
}
