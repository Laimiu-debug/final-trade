export type Market = 'sh' | 'sz' | 'bj'
export type ScreenerMode = 'strict' | 'loose'
export type TrendClass = 'A' | 'A_B' | 'B' | 'Unknown'
export type ThemeStage = '发酵中' | '高潮' | '退潮' | 'Unknown'
export type SignalType = 'A' | 'B' | 'C'
export type SignalScanMode = 'trend_pool' | 'full_market'
export type MarketDataSource = 'tdx_only' | 'tdx_then_akshare' | 'akshare_only'
export type MarketSyncProvider = 'baostock'
export type MarketSyncMode = 'incremental' | 'full'
export type PriceSource = 'vwap' | 'approx'

export interface ApiErrorPayload {
  code: string
  message: string
  degraded?: boolean
  degraded_reason?: string
  trace_id?: string
}

export interface DataProviderStatus {
  source: 'primary' | 'secondary' | 'cache'
  degraded: boolean
  degraded_reason?: string
  refreshed_at: string
}

export interface ScreenerParams {
  markets: Market[]
  mode: ScreenerMode
  return_window_days: number
  top_n: number
  turnover_threshold: number
  amount_threshold: number
  amplitude_threshold: number
}

export interface ScreenerResult {
  symbol: string
  name: string
  latest_price: number
  day_change: number
  day_change_pct: number
  score: number
  ret40: number
  turnover20: number
  amount20: number
  amplitude20: number
  retrace20: number
  pullback_days: number
  ma10_above_ma20_days: number
  ma5_above_ma10_days: number
  price_vs_ma20: number
  vol_slope20: number
  up_down_volume_ratio: number
  pullback_volume_ratio: number
  has_blowoff_top: boolean
  has_divergence_5d: boolean
  has_upper_shadow_risk: boolean
  ai_confidence: number
  theme_stage: ThemeStage
  trend_class: TrendClass
  stage: 'Early' | 'Mid' | 'Late'
  labels: string[]
  reject_reasons: string[]
  degraded: boolean
  degraded_reason?: string
}

export type ScreenerPoolKey = 'input' | 'step1' | 'step2' | 'step3' | 'step4' | 'final'

export interface ScreenerStepSummary {
  input_count: number
  step1_count: number
  step2_count: number
  step3_count: number
  step4_count: number
  final_count?: number
}

export interface ScreenerStepPools {
  input: ScreenerResult[]
  step1: ScreenerResult[]
  step2: ScreenerResult[]
  step3: ScreenerResult[]
  step4: ScreenerResult[]
  final: ScreenerResult[]
}

export interface ScreenerRunResponse {
  run_id: string
}

export interface ScreenerRunDetail {
  run_id: string
  created_at: string
  params: ScreenerParams
  step_summary: ScreenerStepSummary
  step_pools: ScreenerStepPools
  results: ScreenerResult[]
  degraded: boolean
  degraded_reason?: string
}

export interface CandlePoint {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  price_source?: PriceSource
}

export interface IntradayPoint {
  time: string
  price: number
  avg_price: number
  volume: number
  price_source?: PriceSource
}

export interface IntradayPayload {
  symbol: string
  date: string
  points: IntradayPoint[]
  degraded: boolean
  degraded_reason?: string
}

export interface TrendClassification {
  trend_class: TrendClass
  confidence: number
  reason: string
}

export interface StockAnalysis {
  symbol: string
  suggest_start_date: string
  suggest_stage: 'Early' | 'Mid' | 'Late'
  suggest_trend_class: TrendClass
  confidence: number
  reason: string
  theme_stage: ThemeStage
  degraded: boolean
  degraded_reason?: string
}

export interface StockAnnotation {
  symbol: string
  start_date: string
  stage: 'Early' | 'Mid' | 'Late'
  trend_class: TrendClass
  decision: '保留' | '排除'
  notes: string
  updated_by: 'manual' | 'auto'
}

export interface SignalResult {
  symbol: string
  name: string
  primary_signal: SignalType
  secondary_signals: SignalType[]
  trigger_date: string
  expire_date: string
  trigger_reason: string
  priority: number
  wyckoff_phase?: string
  wyckoff_signal?: string
  structure_hhh?: string
  wy_event_count?: number
  wy_sequence_ok?: boolean
  entry_quality_score?: number
  wy_events?: string[]
  wy_risk_events?: string[]
  phase_hint?: string
  scan_mode?: SignalScanMode
  event_strength_score?: number
  phase_score?: number
  structure_score?: number
  trend_score?: number
  volatility_score?: number
}

export interface SignalsResponse {
  items: SignalResult[]
  mode: SignalScanMode
  generated_at: string
  cache_hit: boolean
  degraded: boolean
  degraded_reason?: string
  source_count: number
}

export interface SimTradeOrder {
  order_id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  signal_date: string
  submit_date: string
  status: 'pending' | 'filled' | 'cancelled' | 'rejected'
  expected_fill_date?: string
  filled_date?: string
  estimated_price?: number
  cash_impact?: number
  status_reason?: string
  reject_reason?: string
}

export interface SimTradeFill {
  order_id: string
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  fill_date: string
  fill_price: number
  price_source: PriceSource
  gross_amount: number
  net_amount: number
  fee_commission: number
  fee_stamp_tax: number
  fee_transfer: number
  warning?: string
}

export interface SimTradingConfig {
  initial_capital: number
  commission_rate: number
  min_commission: number
  stamp_tax_rate: number
  transfer_fee_rate: number
  slippage_rate: number
}

export interface SimOrdersResponse {
  items: SimTradeOrder[]
  total: number
  page: number
  page_size: number
}

export interface SimFillsResponse {
  items: SimTradeFill[]
  total: number
  page: number
  page_size: number
}

export interface SimSettleResponse {
  settled_count: number
  filled_count: number
  pending_count: number
  as_of_date: string
  last_settle_at: string
}

export interface SimResetResponse {
  success: true
  as_of_date: string
  cash: number
}

export interface PortfolioPosition {
  symbol: string
  name: string
  quantity: number
  available_quantity: number
  avg_cost: number
  current_price: number
  market_value: number
  pnl_amount: number
  pnl_ratio: number
  holding_days: number
}

export interface PortfolioSnapshot {
  as_of_date: string
  total_asset: number
  cash: number
  position_value: number
  realized_pnl: number
  unrealized_pnl: number
  pending_order_count: number
  positions: PortfolioPosition[]
}

export interface ReviewStats {
  win_rate: number
  total_return: number
  max_drawdown: number
  avg_pnl_ratio: number
  trade_count: number
  win_count: number
  loss_count: number
  profit_factor: number
}

export interface TradeRecord {
  symbol: string
  buy_date: string
  buy_price: number
  sell_date: string
  sell_price: number
  quantity: number
  holding_days: number
  pnl_amount: number
  pnl_ratio: number
}

export interface EquityPoint {
  date: string
  equity: number
  realized_pnl: number
}

export interface DrawdownPoint {
  date: string
  drawdown: number
}

export interface MonthlyReturnPoint {
  month: string
  return_ratio: number
  pnl_amount: number
  trade_count: number
}

export interface ReviewRange {
  date_from: string
  date_to: string
  date_axis: 'sell'
}

export interface ReviewResponse {
  stats: ReviewStats
  trades: TradeRecord[]
  equity_curve: EquityPoint[]
  drawdown_curve: DrawdownPoint[]
  monthly_returns: MonthlyReturnPoint[]
  top_trades: TradeRecord[]
  bottom_trades: TradeRecord[]
  cost_snapshot: SimTradingConfig
  range: ReviewRange
}

export interface AIAnalysisRecord {
  provider: string
  symbol: string
  name: string
  fetched_at: string
  source_urls: string[]
  summary: string
  conclusion: string
  confidence: number
  breakout_date?: string
  trend_bull_type?: string
  theme_name?: string
  rise_reasons?: string[]
  error_code?: string
}

export interface DeleteAIRecordResponse {
  deleted: boolean
  remaining: number
}

export interface AIProviderConfig {
  id: string
  label: string
  base_url: string
  model: string
  api_key: string
  api_key_path: string
  enabled: boolean
}

export interface AISourceConfig {
  id: string
  name: string
  url: string
  enabled: boolean
}

export interface AIProviderTestRequest {
  provider: AIProviderConfig
  fallback_api_key: string
  fallback_api_key_path: string
  timeout_sec: number
}

export interface AIProviderTestResponse {
  ok: boolean
  provider_id: string
  latency_ms: number
  message: string
  error_code?: string
}

export interface AppConfig {
  tdx_data_path: string
  market_data_source: MarketDataSource
  akshare_cache_dir: string
  markets: Market[]
  return_window_days: number
  top_n: number
  turnover_threshold: number
  amount_threshold: number
  amplitude_threshold: number
  initial_capital: number
  ai_provider: string
  ai_timeout_sec: number
  ai_retry_count: number
  api_key: string
  api_key_path: string
  ai_providers: AIProviderConfig[]
  ai_sources: AISourceConfig[]
}

export interface SystemStorageStatus {
  app_state_path: string
  app_state_exists: boolean
  sim_state_path: string
  sim_state_exists: boolean
  akshare_cache_dir: string
  akshare_cache_dir_resolved: string
  akshare_cache_dir_exists: boolean
  akshare_cache_file_count: number
  akshare_cache_candidates: string[]
}

export interface MarketDataSyncRequest {
  provider: MarketSyncProvider
  mode: MarketSyncMode
  symbols: string
  all_market: boolean
  limit: number
  start_date: string
  end_date: string
  initial_days: number
  sleep_sec: number
  out_dir: string
}

export interface MarketDataSyncResponse {
  ok: boolean
  provider: MarketSyncProvider
  mode: MarketSyncMode
  message: string
  out_dir: string
  symbol_count: number
  ok_count: number
  fail_count: number
  skipped_count: number
  new_rows_total: number
  started_at: string
  finished_at: string
  duration_sec: number
  errors: string[]
}
