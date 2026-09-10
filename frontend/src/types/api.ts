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
  prices: MarketPricePoint[];
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