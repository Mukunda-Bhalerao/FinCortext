/** Typed contracts mirroring the FinCortext backend API responses. */

export type DataStatusValue =
  | 'LIVE'
  | 'CACHED'
  | 'IMPORTED_OFFICIAL'
  | 'SAMPLE'
  | 'UNAVAILABLE'
  | 'ERROR';

export interface UniverseEntry {
  symbol: string;
  name: string;
  exchange: string;
  ticker: string;
  sector: string;
  industry: string;
  instrument_key?: string | null;
}

export interface UniverseResponse {
  universe_version: string;
  count: number;
  entries: UniverseEntry[];
}

export interface HealthInfo {
  status: string;
  service: string;
  version: string;
  config: {
    db_path: string;
    news_api_configured: boolean;
    cors_origins: string[];
    log_level: string;
    market_history_days: number;
    sentiment_model_id: string;
    allow_sample_data: boolean;
  };
}

export interface MarketPricePoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceSeriesResponse {
  symbol: string;
  name: string;
  status: DataStatusValue;
  count: number;
  latest_trade_date: string | null;
  instrument_key?: string | null;
  source?: string | null;
  /** Newest live-quote snapshot carried with the series (Upstox timestamp). */
  quote_timestamp?: string | null;
  quote_source?: string | null;
  quote_last_price?: number | null;
  prices: MarketPricePoint[];
}

/** NSE equity instrument resolved via Upstox search. Field names mirror the
 *  backend search response exactly (snake_case) so valid values never become
 *  null through a rename. */
export interface UpstoxSearchResult {
  symbol: string;
  trading_symbol: string;
  name: string;
  instrument_key: string;
  exchange: string;
  segment: string;
  isin: string | null;
}

export interface UpstoxSearchResponse {
  query: string;
  count: number;
  results: UpstoxSearchResult[];
  source: string;
}

/** Live market quote. Every numeric field is nullable: a genuine gap from
 *  Upstox renders as "N/A", never as ₹0 or another fabricated value. */
export interface MarketQuote {
  symbol: string;
  name: string;
  instrument_key: string | null;
  trading_symbol: string | null;
  exchange: string | null;
  segment: string | null;
  source: string | null;
  status: DataStatusValue;
  timestamp: string | null;
  last_price: number | null;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  average_price: number | null;
  year_high: number | null;
  year_low: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  /** True when this snapshot came from a live provider fetch (not storage). */
  live?: boolean | null;
  /** Live-only market depth (5 levels per side) — never carried by a
   *  stored snapshot (ephemeral; stale depth must not present as current). */
  depth_buy?: QuoteDepthLevel[] | null;
  depth_sell?: QuoteDepthLevel[] | null;
  total_buy_quantity?: number | null;
  total_sell_quantity?: number | null;
  upper_circuit_limit?: number | null;
  lower_circuit_limit?: number | null;
  last_trade_time?: string | number | null;
}

/** One level of the live order book (price/quantity/orders; null = absent). */
export interface QuoteDepthLevel {
  price: number | null;
  quantity: number | null;
  orders: number | null;
}

/** Central Stock Context: one cached assembly per selected symbol. Every
 *  section carries an explicit status; unavailable fields are marked —
 *  never fabricated. */
export interface StockIdentity {
  symbol: string;
  name: string | null;
  trading_symbol?: string | null;
  instrument_key: string | null;
  exchange: string | null;
  segment?: string | null;
  isin?: string | null;
  exchange_token?: string | null;
  instrument_type?: string | null;
  tick_size?: number | null;
  lot_size?: number | null;
  sector: string | null;
  industry: string | null;
  dynamic?: boolean;
  status: DataStatusValue;
  error?: string;
}

export interface StockFiftyTwoWeek {
  high: number | null;
  low: number | null;
  available: boolean;
  source: string | null;
}

export interface StockHistory {
  symbol?: string;
  status: DataStatusValue;
  count: number;
  latest_trade_date?: string | null;
  prices: MarketPricePoint[];
  available: boolean;
  source?: string;
  quote_timestamp?: string | null;
  quote_source?: string | null;
  quote_last_price?: number | null;
  preparation?: unknown[];
  error?: string;
}

export interface StockProfile {
  name: string | null;
  sector: string | null;
  industry: string | null;
  business_description: string | null;
  source: string | null;
  confidence: number | null;
  sources: ResearchSource[];
  status: DataStatusValue;
}

export interface StockFundamentals {
  symbol?: string;
  name?: string;
  status: DataStatusValue;
  metric_count: number;
  has_official?: boolean;
  has_provider?: boolean;
  metrics: Record<string, FundamentalsMetricCoverage>;
  available: boolean;
  note?: string | null;
  error?: string;
}

export interface StockNews {
  status: DataStatusValue;
  count: number;
  articles: NewsArticleSummary[];
  available: boolean;
  note?: string | null;
  error?: string;
}

export interface StockContext {
  symbol: string;
  name: string;
  generated_at: string;
  identity: StockIdentity;
  quote: MarketQuote & { available?: boolean; error?: string };
  fifty_two_week: StockFiftyTwoWeek;
  history: StockHistory;
  profile: StockProfile;
  fundamentals: StockFundamentals;
  news: StockNews;
  /** Fields a full platform expects that Upstox does not provide for NSE
   *  equities — surfaced explicitly, never fabricated. */
  unavailable_from_upstox: string[];
}

/** Market Dashboard — Indian market overview (real Upstox data only). */
export interface IndexPoint {
  date: string;
  close: number;
}

export interface MarketIndex {
  key: string;
  name: string;
  value: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  chart: IndexPoint[] | null;
  status: DataStatusValue;
  source: string | null;
}

export interface MoverRow {
  symbol: string;
  name: string;
  instrument_key: string | null;
  status: DataStatusValue;
  last_price: number | null;
  day_change: number | null;
  day_change_pct: number | null;
  volume: number | null;
}

export interface OpportunityItem {
  symbol: string;
  name: string;
  agent_id: string;
  score: number | null;
  signal: string;
  confidence: number | null;
  status: string;
  generated_at: string;
  rationale: string;
}

export interface MarketDashboardData {
  indices: { items: MarketIndex[] };
  movers: {
    status: DataStatusValue;
    tracked: number;
    quoted: number;
    gainers: MoverRow[];
    losers: MoverRow[];
  };
  opportunities: {
    status: DataStatusValue;
    count: number;
    items: OpportunityItem[];
  };
  tracked_count: number;
  as_of: string;
}

/** One preparation area inside a company-preparation response. */
export interface PreparationArea {
  status: DataStatusValue;
  [key: string]: unknown;
}

/** Central preparation result: readiness of every analyst input for a company.
 *  `readiness` is `ready` (quote+history usable), `partial` (something
 *  prepared) or `unavailable` (nothing usable) — never fabricated.
 *  `components` reports per-domain readiness (market, fundamentals,
 *  company_metadata, industry, peers, news, web_research) as
 *  READY / PARTIAL / UNAVAILABLE. */
export interface CompanyPreparation {
  symbol: string;
  name: string;
  instrument_key: string | null;
  sector?: string | null;
  industry?: string | null;
  readiness: 'ready' | 'partial' | 'unavailable' | string;
  areas: Record<string, PreparationArea>;
  components?: Record<string, 'READY' | 'PARTIAL' | 'UNAVAILABLE' | string>;
}

/** One web-research evidence item (Gemini grounded search — labeled, unscored). */
export interface ResearchItem {
  title: string;
  summary?: string | null;
  url?: string | null;
  source?: string | null;
  published_at?: string | null;
}

export interface ResearchSource {
  title?: string | null;
  url: string;
  domain?: string | null;
  retrieved_at?: string | null;
}

export interface ResearchReport {
  report_id: string;
  entity_id: string;
  report_type: 'company_profile' | 'peer_discovery' | 'news_digest' | string;
  subject: string;
  payload?: Record<string, unknown> | null;
  confidence?: number | null;
  sources?: ResearchSource[] | null;
  model?: string | null;
  source_name?: string | null;
  created_at?: string | null;
}

export interface ResearchListResponse {
  symbol: string;
  name: string;
  count: number;
  provider: string;
  provider_configured: boolean;
  reports: ResearchReport[];
}

export interface ResearchStatusResponse {
  provider: string;
  configured: boolean;
  model?: string | null;
  status: DataStatusValue;
  message: string | null;
}

export interface CompanyPeer {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  relation: string;
  rows: number;
  latest_trade_date: string | null;
}

export interface CompanyPeersResponse {
  symbol: string;
  sector: string;
  industry: string;
  count: number;
  peers: CompanyPeer[];
}

export interface MarketResolveResponse {
  resolved: {
    symbol: string;
    name: string;
    exchange: string;
    ticker: string;
    sector: string;
    industry: string;
    instrument_key: string | null;
    dynamic: boolean;
    source: string;
  };
  refresh: RefreshResult & { error?: string };
  quote: MarketQuote & { error?: string };
}

export interface MarketStatusRow {
  symbol: string;
  name: string;
  rows: number;
  latest_trade_date: string | null;
  status: DataStatusValue;
}

export interface MarketStatusResponse {
  symbols: MarketStatusRow[];
}

export interface RefreshResult {
  symbol?: string;
  status: DataStatusValue;
  rows_stored?: number;
  rows_rejected?: number;
  provider?: string;
  message?: string;
  error?: string;
  symbols_requested?: number;
  symbols_ok?: number;
  results?: RefreshResult[];
}

export interface NewsArticleSummary {
  article_id: string;
  title: string;
  description: string | null;
  source: string | null;
  source_url: string | null;
  published_at: string | null;
  collected_at: string;
  language: string | null;
  content_hash: string | null;
  source_type: string;
  source_name: string;
}

export interface NewsListResponse {
  symbol: string;
  name: string;
  status: DataStatusValue;
  count: number;
  provider_configured: boolean;
  articles: NewsArticleSummary[];
}

export interface NewsStatusResponse {
  provider: string;
  configured: boolean;
  status: DataStatusValue;
  message: string | null;
}

export interface NewsRefreshResponse {
  symbol: string;
  status: DataStatusValue;
  fetched: number;
  stored: number;
  duplicates: number;
  provider: string;
  message?: string;
  query?: string;
}

export type SignalValue =
  | 'strong_buy'
  | 'buy'
  | 'neutral'
  | 'sell'
  | 'strong_sell'
  | 'unavailable';

export interface AgentFactor {
  name: string;
  description: string;
  value: number | null;
  contribution: number | null;
  weight: number | null;
  available: boolean;
  detail: string | null;
}

export interface AgentEvidence {
  data_type: string;
  reference: string;
  source_name: string | null;
  source_type: string | null;
  timestamp: string | null;
  note: string | null;
}

export interface AgentOutput {
  agent_id: string;
  entity_id: string;
  score: number | null;
  signal: SignalValue;
  confidence: number;
  factors: AgentFactor[];
  rationale: string;
  evidence: AgentEvidence[];
  data_limitations: string[];
  generated_at: string;
  data_version: string;
  provenance: Record<string, unknown>;
  status: 'OK' | 'DEGRADED' | 'UNAVAILABLE';
}

export interface FilingDocumentSummary {
  document_id: string;
  entity_id: string;
  document_type: string;
  file_name: string;
  content_hash: string;
  source_name: string;
  filing_date: string | null;
  published_at: string | null;
  ingested_at: string;
  observation_count: number;
  parse_warnings: string[];
}

export interface FilingsListResponse {
  count: number;
  documents: FilingDocumentSummary[];
}

export interface FilingImportResult {
  document_id?: string;
  entity_id?: string;
  status?: string;
  observations_stored?: number;
  warnings?: string[];
  message?: string;
  detail?: Record<string, unknown>;
}

export interface FundamentalsMetricCoverage {
  value: number;
  unit: string;
  period_end: string | null;
  source_type: string;
  source_name: string;
  available_at: string | null;
}

export interface FundamentalsCoverageResponse {
  symbol: string;
  name: string;
  status: DataStatusValue;
  metric_count: number;
  has_official: boolean;
  has_provider: boolean;
  metrics: Record<string, FundamentalsMetricCoverage>;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
}

/** Flattened `agent_outputs` row returned by GET /api/agents/outputs
 *  (SELECT * ordered by generated_at DESC — latest first). */
export interface AgentOutputSummary {
  output_id: string;
  agent_id: string;
  entity_id: string;
  score: number | null;
  signal: SignalValue;
  confidence: number;
  factors_json?: string;
  rationale?: string;
  generated_at: string;
  data_version?: string;
  status: 'OK' | 'DEGRADED' | 'UNAVAILABLE';
}

/** Macro environment vocabulary — deliberately NOT buy/sell signals.
 *  A POSITIVE macro environment is never a recommendation for any stock. */
export type MacroSignalValue = 'positive' | 'neutral' | 'negative' | 'unavailable';

export type MacroDirectionValue = 'up' | 'down' | 'flat' | 'unknown';

export interface MacroEvidence {
  indicator_id: string;
  reference: string;
  value: number | null;
  unit: string | null;
  period: string | null;
  source_name: string | null;
  source_url: string | null;
  note: string | null;
}

export interface MacroFactor {
  name: string;
  label: string;
  value: number | null;
  unit: string | null;
  direction: MacroDirectionValue;
  signal: MacroSignalValue;
  confidence: number;
  available: boolean;
  data_as_of: string | null;
  detail: string | null;
  evidence: MacroEvidence[];
  limitations: string[];
}

export interface MacroOutput {
  agent_id: string;
  entity_id: string;
  requested_symbol: string | null;
  /** 0–100 Macro Environment Score (None when unavailable). Environment only. */
  score: number | null;
  overall_signal: MacroSignalValue;
  confidence: number;
  status: 'OK' | 'DEGRADED' | 'UNAVAILABLE';
  factors: MacroFactor[];
  rationale: string;
  data_limitations: string[];
  generated_at: string;
  data_through: Record<string, string>;
  provenance: Record<string, unknown>;
  methodology: string;
}

export interface MacroIndicatorCoverage {
  indicator_id: string;
  count: number;
  latest_period: string | null;
  latest_observed: string | null;
  latest_available: string | null;
}

/** Portfolio synthesis — the Central Orchestrator's output contract.
 *
 *  Explains how the four analyst perspectives fit together for ONE company.
 *  Contains NO overall score and NO overall signal: perspectives are shown,
 *  compared and traced — never blended into a single rating.
 */
export type PortfolioDirection = 'positive' | 'neutral' | 'negative' | 'missing';

export interface PerspectiveView {
  agent_id: string;
  label: string;
  entity_id: string;
  direction: PortfolioDirection;
  signal_label: string;
  score: number | null;
  confidence: number;
  status: string;
  takeaway: string;
  limitations: string[];
  generated_at: string | null;
}

export interface AgreementView {
  available_count: number;
  total_count: number;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  verdict: string;
  conflicts: Array<{ between: string[]; description: string }>;
  summary: string;
}

export interface ScenarioView {
  label: string;
  leaning: string;
  conditions: string[];
  note: string;
}

export interface PortfolioEvidence {
  agent_id: string;
  entity_id: string;
  signal: string | null;
  score: number | null;
  status: string | null;
  generated_at: string | null;
  note: string | null;
}

export interface PortfolioView {
  agent_id: string;
  entity_id: string;
  generated_at: string;
  perspectives: PerspectiveView[];
  agreement: AgreementView;
  scenarios: ScenarioView[];
  thesis: string;
  evidence: PortfolioEvidence[];
  risks: string[];
  coverage: number;
  confidence: number;
  status: 'OK' | 'DEGRADED' | 'UNAVAILABLE';
  rationale: string;
  data_limitations: string[];
  provenance: Record<string, unknown>;
  methodology: string;
}