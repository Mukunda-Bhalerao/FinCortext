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
  server_ms?: number | null;
}

export interface FeedLatency {
  samples: number;
  provider_p50_ms: number | null;
  provider_p90_ms: number | null;
  transit_p50_ms: number | null;
  transit_p90_ms: number | null;
  clock_offset_ms: number | null;
}

export interface StatusMessage extends LiveStatus {
  type: "status";
  market: MarketStatus;
  latency?: FeedLatency;
  silent?: string[];
}

/** Provider timeframes plus seconds intervals built from streamed updates in the browser. */
export type ChartTimeframe = Timeframe | "5s" | "15s" | "30s";
export const CHART_TIMEFRAMES: ChartTimeframe[] = ["5s", "15s", "30s", ...TIMEFRAMES];

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
  dividend_yield?: number | null;
  diversification_score?: number | null;
  top_risk_symbol?: string | null;
  top_risk_share?: number | null;
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
  custom_weights?: Record<string, number> | null;
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
  halves: {
    label: string;
    start: string;
    end: string;
    cagr: number | null;
    benchmark_cagr: number | null;
    max_drawdown: number | null;
  }[];
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
  source: "manual" | "upstox";
  invested: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  day_change_pct: number | null;
  weight: number | null;
}

export interface PortfolioSummary {
  holdings: HoldingRow[];
  total_value: number | null;
  total_invested: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  day_change: number | null;
  cost_coverage: number;
  priced_at: string;
  notes: string[];
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
  calls_today: number;
  daily_limit: number;
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
  custom_weights?: Record<string, number> | null;
  label: string | null;
}

export interface AskAnswer {
  answer: string;
  cited: Fact[];
  scenario: Scenario | null;
  grounded: boolean;
  model: string | null;
  generated_at: string;
  tool: "scenario" | "compare" | "investigate" | "goal" | null;
  title: string | null;
  data: Record<string, unknown> | null;
  answered_by: "model" | "engine";
  notice: string | null;
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

export type Verdict = "evidence" | "negative" | "inconclusive" | "insufficient";

export interface SignalTest {
  key: string;
  label: string;
  agent: string;
  kind: "composite" | "agent" | "factor";
  inputs: string;
  months: number;
  avg_stocks: number;
  first_date: string | null;
  last_date: string | null;
  mean_ic: number | null;
  ic_t: number | null;
  ic_low: number | null;
  ic_high: number | null;
  hit_rate: number | null;
  first_half_ic: number | null;
  second_half_ic: number | null;
  spread_annual: number | null;
  spread_t: number | null;
  by_year: { year: number; ic: number; months: number }[];
  verdict: Verdict;
  verdict_text: string;
}

export interface SignalValidation {
  computed_at: string;
  universe: string;
  stocks: number;
  start: string | null;
  end: string | null;
  horizon_sessions: number;
  tests: SignalTest[];
  untestable: { agent: string; component: string; reason: string }[];
  tracking: {
    snapshots: number;
    with_outcomes: number;
    months_covered: number;
    first_snapshot: string | null;
    outcomes_from: string | null;
    pooled_ic: number | null;
    by_agent: Record<string, number | null>;
    status: string;
    recorded_snapshots: number;
    scored_snapshots: number;
    first_recorded: string | null;
    recorded: { key: string; label: string; snapshots: number; mean_ic: number | null; verdict: Verdict }[];
  };
  headline: string;
  method: string[];
  limitations: string[];
  duration_ms: number;
}

export interface ValidationStatus {
  state: "not_started" | "queued" | "running" | "ready" | "failed";
  error: string | null;
  progress: string | null;
  result: SignalValidation | null;
}

export interface GoalProjection {
  target: number;
  years: number;
  initial: number;
  monthly: number;
  invested: number;
  probability: number;
  p10: number;
  p50: number;
  p90: number;
  benchmark_probability: number | null;
  benchmark_p50: number | null;
  path: { year: number; p10: number; p50: number; p90: number; invested: number }[];
  history_from: string | null;
  history_to: string | null;
  method: string;
  caveats: string[];
}

export interface FeedEvent {
  id: string;
  kind: "research" | "market" | "portfolio" | "opportunity" | "data" | "results";
  severity: "high" | "medium" | "low";
  symbol: string | null;
  title: string;
  body: string;
  facts: Fact[];
  created_at: string;
  seen: boolean;
}

// --- tracked portfolios ---------------------------------------------------------------------

export type ReviewPeriod = "last_visit" | "today" | "1w" | "1m" | "start";

export interface TrackedPosition {
  id: string;
  symbol: string;
  name: string | null;
  instrument_key: string;
  sector: string;
  quantity: number;
  entry_price: number;
  entry_at: string;
  entry_basis: string;
  price: number | null;
  price_basis: string | null;
  value: number | null;
  cost: number;
  pnl: number | null;
  pnl_pct: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  weight: number | null;
  charges: number;
  reason: string | null;
  tag: string | null;
  break_even: number | null;
}

export interface TrackedPortfolio {
  id: string;
  name: string;
  kind: "paper" | "tracking";
  plan: string;
  starting_cash: number | null;
  cash: number | null;
  reserved: number;
  account_value: number | null;
  account_return: number | null;
  realized: number;
  charges_paid: number;
  created_at: string;
  last_viewed_at: string | null;
  positions: TrackedPosition[];
  value: number | null;
  cost: number;
  pnl: number | null;
  pnl_pct: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  priced_at: string;
}

export interface TrackedPortfolioRow {
  id: string;
  name: string;
  kind: "paper" | "tracking";
  cash: number | null;
  account_value: number | null;
  account_return: number | null;
  created_at: string;
  last_viewed_at: string | null;
  positions: number;
  value: number | null;
  cost: number;
  pnl: number | null;
  pnl_pct: number | null;
  day_change_pct: number | null;
}

export interface PositionInput {
  symbol: string;
  quantity?: number | null;
  amount?: number | null;
  entry_date?: string | null;
  entry_price?: number | null;
}

export interface ReviewMove {
  date: string;
  change_pct: number;
  live: boolean;
}

export interface ReviewHeadline {
  title: string;
  link: string;
  publisher: string;
  published_at: string | null;
  tone: "positive" | "negative" | "neutral";
  near_move: string | null;
}

export interface StockReview {
  symbol: string;
  name: string | null;
  sector: string;
  quantity: number;
  start_price: number;
  start_basis: string;
  end_price: number;
  return_pct: number;
  contribution: number;
  contribution_share: number;
  market_return: number | null;
  sector_label: string | null;
  sector_return: number | null;
  stock_specific: number | null;
  driver: "market" | "sector" | "stock" | "mixed";
  moves: ReviewMove[];
  headlines: ReviewHeadline[];
  dividends: { ex_date: string; amount: number }[];
  research: {
    before_signal: string | null;
    after_signal: string;
    before_score: number | null;
    after_score: number | null;
    summary: string;
    since: string | null;
  } | null;
  events: string[];
  explanation: string;
}

export interface PortfolioReview {
  portfolio_id: string;
  period: ReviewPeriod;
  period_label: string;
  start: string;
  start_basis: string;
  end: string;
  start_value: number;
  end_value: number;
  change: number;
  change_pct: number | null;
  benchmark_label: string;
  benchmark_return: number | null;
  market_part: number | null;
  selection_part: number | null;
  headline: string;
  points: string[];
  stocks: StockReview[];
  value_series: CurvePoint[];
  cost_series: CurvePoint[];
  facts: Fact[];
  narrative: { text: string; cited: string[]; model: string } | null;
  gaps: string[];
  computed_at: string;
}

// --- IPOs -------------------------------------------------------------------------------------

export type IpoStage = "upcoming" | "open" | "closed" | "listed";

export interface IpoSubscription {
  qib: number | null;
  nii: number | null;
  nii_big: number | null;
  nii_small: number | null;
  retail: number | null;
  employee: number | null;
  shareholder: number | null;
  total: number | null;
}

export interface ListingOdds {
  measure: "qib" | "total";
  bucket: string;
  sample: number;
  above_issue: number;
  average_gain: number;
  median_gain: number;
  worst: number;
  best: number;
  text: string;
}

export interface IpoListing {
  instrument_key: string | null;
  listing_open: number | null;
  listing_close: number | null;
  listing_gain: number | null;
  price: number | null;
  price_basis: string | null;
  since_issue: number | null;
}

export interface IpoIssue {
  symbol: string;
  company: string;
  board: "mainboard" | "sme";
  stage: IpoStage;
  open_date: string | null;
  close_date: string | null;
  listing_date: string | null;
  price_low: number | null;
  price_high: number | null;
  issue_price: number | null;
  lot_size: number | null;
  min_investment: number | null;
  industry: string | null;
  subscription: IpoSubscription | null;
  subscription_note: string | null;
  odds: ListingOdds | null;
  listing: IpoListing | null;
  signals: string[];
}

export interface IpoMood {
  days: number;
  listed: number;
  above_issue_at_open: number | null;
  median_listing_gain: number | null;
  above_issue_now: number | null;
}

export interface IpoOverview {
  open: IpoIssue[];
  upcoming: IpoIssue[];
  awaiting_listing: IpoIssue[];
  recent_listings: IpoIssue[];
  strongest: string[];
  mood: IpoMood[];
  odds_table: ListingOdds[];
  history_size: number;
  history_complete: boolean;
  news: ReviewHeadline[];
  as_of: string;
  gaps: string[];
}

export interface IpoDetail {
  issue: IpoIssue;
  facts: Record<string, string>;
  lead_managers: string[];
  documents: Record<string, string>;
  price_series: CurvePoint[];
  news: ReviewHeadline[];
  as_of: string;
  gaps: string[];
}

// --- paper trading ---------------------------------------------------------------------------

export type OrderSide = "BUY" | "SELL";
export type OrderKind = "MARKET" | "LIMIT" | "SL";

export interface OrderInput {
  symbol: string;
  side: OrderSide;
  kind: OrderKind;
  validity: "DAY" | "GTC";
  quantity?: number | null;
  amount?: number | null;
  limit_price?: number | null;
  trigger_price?: number | null;
  reason?: string | null;
  tag?: string | null;
  target_price?: number | null;
  stop_price?: number | null;
}

export interface Charges {
  brokerage: number;
  stt: number;
  exchange: number;
  sebi: number;
  stamp: number;
  gst: number;
  dp: number;
  total: number;
}

export interface OrderPreview {
  symbol: string;
  side: OrderSide;
  quantity: number;
  price: number;
  price_basis: string;
  value: number;
  charges: Charges;
  total: number;
  break_even: number | null;
  cash_after: number;
  market_open: boolean;
  fills: string;
  warnings: string[];
}

export interface PaperOrder {
  id: string;
  symbol: string;
  instrument_key: string;
  side: OrderSide;
  kind: OrderKind;
  validity: "DAY" | "GTC";
  quantity: number;
  limit_price: number | null;
  trigger_price: number | null;
  status: "OPEN" | "FILLED" | "CANCELLED" | "EXPIRED" | "REJECTED";
  created_at: string;
  session: string;
  fill_price: number | null;
  filled_at: string | null;
  fill_basis: string | null;
  charges: Charges | null;
  reason: string | null;
  tag: string | null;
  target_price: number | null;
  stop_price: number | null;
  parent_id: string | null;
  source: string;
  message: string | null;
}

export interface ClosedTrade {
  id: string;
  symbol: string;
  quantity: number;
  buy_price: number;
  buy_at: string;
  sell_price: number;
  sell_at: string;
  charges: number;
  gross: number;
  net: number;
  return_pct: number;
  holding_days: number;
  term: "short" | "long";
  buy_reason: string | null;
  buy_tag: string | null;
  sell_reason: string | null;
  index_return: number | null;
  beat_index: boolean | null;
  source: string | null;
}

export interface JournalEntry {
  kind: "open" | "closed";
  symbol: string;
  at: string;
  quantity: number;
  price: number;
  reason: string | null;
  tag: string | null;
  outcome_pct: number | null;
  outcome: number | null;
  index_return: number | null;
  verdict: string;
  source: string | null;
}

export interface Scorecard {
  closed_trades: number;
  open_positions: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  average_win: number | null;
  average_loss: number | null;
  best: ClosedTrade | null;
  worst: ClosedTrade | null;
  profit_factor: number | null;
  realized_net: number;
  charges_paid: number;
  charges_share_of_gross: number | null;
  days_held_winners: number | null;
  days_held_losers: number | null;
  beat_index: number;
  compared: number;
  index_equivalent: number | null;
  by_tag: { tag: string; trades: number; wins: number; net: number; average_return: number }[];
  tax: {
    year: string;
    short_term_gain: number;
    long_term_gain: number;
    estimated_tax: number;
    note: string;
  }[];
  lessons: string[];
}

export interface AccountActivity {
  orders: PaperOrder[];
  trades: ClosedTrade[];
  journal: JournalEntry[];
  scorecard: Scorecard;
}

// --- strategy lab ----------------------------------------------------------------------------

export type ConditionKind = "price_vs_sma" | "sma_cross" | "rsi" | "return" | "from_high";
export type ConditionOp = "above" | "below" | "crosses_above" | "crosses_below";

export interface RuleCondition {
  kind: ConditionKind;
  op: ConditionOp;
  n: number;
  m?: number | null;
  value?: number | null;
}

export interface StrategyRules {
  entry: RuleCondition[];
  exit: RuleCondition[];
  stop_loss: number | null;
  take_profit: number | null;
  max_days: number | null;
}

export interface BacktestTrade {
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  exit_reason: string;
  quantity: number;
  net: number;
  return_pct: number;
  days: number;
}

export interface BacktestSymbol {
  symbol: string;
  start: string;
  end: string;
  final_value: number;
  total_return: number;
  cagr: number | null;
  max_drawdown: number;
  trades: BacktestTrade[];
  win_rate: number | null;
  average_win: number | null;
  average_loss: number | null;
  exposure: number;
  charges: number;
  hold_return: number;
  index_return: number | null;
  equity: CurvePoint[];
  hold: CurvePoint[];
  index: CurvePoint[];
  segments: {
    label: string;
    start: string;
    end: string;
    strategy_return: number;
    hold_return: number;
    trades: number;
  }[];
  verdict: string;
  open_trade: boolean;
}

export interface BacktestResult {
  rules_text: string[];
  results: BacktestSymbol[];
  skipped: string[];
  summary: string;
  assumptions: string[];
  computed_at: string;
}

export interface SavedStrategy {
  id: string;
  name: string;
  rules: StrategyRules;
  rules_text: string[];
  symbols: string[];
  created_at: string;
  portfolio_id: string | null;
  portfolio_name: string | null;
  per_trade: number | null;
  active: boolean;
  last_run: string | null;
  last_note: string | null;
}
