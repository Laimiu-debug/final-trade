from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Market = Literal["sh", "sz", "bj"]
ScreenerMode = Literal["strict", "loose"]
TrendClass = Literal["A", "A_B", "B", "Unknown"]
ThemeStage = Literal["发酵中", "高潮", "退潮", "Unknown"]
SignalType = Literal["A", "B", "C"]
SignalScanMode = Literal["trend_pool", "full_market"]
TrendPoolStep = Literal["auto", "step1", "step2", "step3", "step4"]
PriceSource = Literal["vwap", "approx"]
Stage = Literal["Early", "Mid", "Late"]
MarketDataSource = Literal["tdx_only", "tdx_then_akshare", "akshare_only"]
MarketSyncProvider = Literal["baostock"]
MarketSyncMode = Literal["incremental", "full"]
ReviewTagType = Literal["emotion", "reason"]
BacktestPriorityMode = Literal["phase_first", "balanced", "momentum"]
BacktestPoolRollMode = Literal["daily", "weekly", "position"]
BoardFilter = Literal["main", "gem", "star", "beijing", "st"]


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    degraded: bool | None = None
    degraded_reason: str | None = None
    trace_id: str | None = None


class DataProviderStatus(BaseModel):
    source: Literal["primary", "secondary", "cache"]
    degraded: bool
    degraded_reason: str | None = None
    refreshed_at: str


class ScreenerParams(BaseModel):
    markets: list[Market] = Field(min_length=1)
    mode: ScreenerMode
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    return_window_days: int = Field(ge=5, le=120)
    top_n: int = Field(ge=100, le=2000)
    turnover_threshold: float = Field(ge=0.01, le=0.2)
    amount_threshold: float = Field(ge=5e7, le=5e9)
    amplitude_threshold: float = Field(ge=0.01, le=0.15)


class ScreenerResult(BaseModel):
    symbol: str
    name: str
    latest_price: float
    day_change: float
    day_change_pct: float
    score: int
    ret40: float
    turnover20: float
    amount20: float
    amplitude20: float
    retrace20: float
    pullback_days: int
    ma10_above_ma20_days: int
    ma5_above_ma10_days: int
    price_vs_ma20: float
    vol_slope20: float
    up_down_volume_ratio: float
    pullback_volume_ratio: float
    has_blowoff_top: bool
    has_divergence_5d: bool
    has_upper_shadow_risk: bool
    ai_confidence: float
    theme_stage: ThemeStage
    trend_class: TrendClass
    stage: Stage
    labels: list[str]
    reject_reasons: list[str]
    degraded: bool
    degraded_reason: str | None = None


class ScreenerStepSummary(BaseModel):
    input_count: int
    step1_count: int
    step2_count: int
    step3_count: int
    step4_count: int


class ScreenerStepPools(BaseModel):
    input: list[ScreenerResult]
    step1: list[ScreenerResult]
    step2: list[ScreenerResult]
    step3: list[ScreenerResult]
    step4: list[ScreenerResult]


class ScreenerRunResponse(BaseModel):
    run_id: str


class ScreenerRunDetail(BaseModel):
    run_id: str
    created_at: str
    as_of_date: str | None = None
    params: ScreenerParams
    step_summary: ScreenerStepSummary
    step_pools: ScreenerStepPools
    results: list[ScreenerResult]
    degraded: bool
    degraded_reason: str | None = None


class CandlePoint(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    price_source: PriceSource | None = None


class IntradayPoint(BaseModel):
    time: str
    price: float
    avg_price: float
    volume: int
    price_source: PriceSource | None = None


class IntradayPayload(BaseModel):
    symbol: str
    date: str
    points: list[IntradayPoint]
    degraded: bool
    degraded_reason: str | None = None


class StockAnalysis(BaseModel):
    symbol: str
    suggest_start_date: str
    suggest_stage: Stage
    suggest_trend_class: TrendClass
    confidence: float
    reason: str
    theme_stage: ThemeStage
    degraded: bool
    degraded_reason: str | None = None


class StockAnnotation(BaseModel):
    symbol: str
    start_date: str
    stage: Stage
    trend_class: TrendClass
    decision: Literal["保留", "排除"]
    notes: str
    updated_by: Literal["manual", "auto"]


class StockAnalysisResponse(BaseModel):
    analysis: StockAnalysis
    annotation: StockAnnotation | None = None


class AnnotationUpdateResponse(BaseModel):
    success: Literal[True]
    annotation: StockAnnotation


class SignalResult(BaseModel):
    symbol: str
    name: str
    primary_signal: SignalType
    secondary_signals: list[SignalType]
    trigger_date: str
    expire_date: str
    trigger_reason: str
    priority: int
    wyckoff_phase: str = "阶段未明"
    wyckoff_signal: str = ""
    structure_hhh: str = "-"
    wy_event_count: int = 0
    wy_sequence_ok: bool = False
    entry_quality_score: float = 0.0
    wy_events: list[str] = Field(default_factory=list)
    wy_risk_events: list[str] = Field(default_factory=list)
    wy_event_dates: dict[str, str] = Field(default_factory=dict)
    wy_event_chain: list[dict[str, str]] = Field(default_factory=list)
    phase_hint: str = ""
    scan_mode: SignalScanMode = "trend_pool"
    event_strength_score: float = 0.0
    phase_score: float = 0.0
    structure_score: float = 0.0
    trend_score: float = 0.0
    volatility_score: float = 0.0


class SignalsResponse(BaseModel):
    items: list[SignalResult]
    mode: SignalScanMode = "trend_pool"
    as_of_date: str | None = None
    generated_at: str = ""
    cache_hit: bool = False
    degraded: bool = False
    degraded_reason: str | None = None
    source_count: int = 0


class SimTradingConfig(BaseModel):
    initial_capital: float = Field(default=1_000_000, gt=0)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.01)
    min_commission: float = Field(default=5.0, ge=0)
    stamp_tax_rate: float = Field(default=0.001, ge=0, le=0.01)
    transfer_fee_rate: float = Field(default=0.00001, ge=0, le=0.01)
    slippage_rate: float = Field(default=0.0, ge=0, le=0.05)


class SimTradeOrder(BaseModel):
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    signal_date: str
    submit_date: str
    status: Literal["pending", "filled", "cancelled", "rejected"]
    expected_fill_date: str | None = None
    filled_date: str | None = None
    estimated_price: float | None = None
    cash_impact: float | None = None
    status_reason: str | None = None
    reject_reason: str | None = None


class SimTradeFill(BaseModel):
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    fill_date: str
    fill_price: float
    price_source: PriceSource
    gross_amount: float
    net_amount: float
    fee_commission: float
    fee_stamp_tax: float
    fee_transfer: float
    warning: str | None = None


class CreateOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    signal_date: str
    submit_date: str


class CreateOrderResponse(BaseModel):
    order: SimTradeOrder
    fill: SimTradeFill | None = None


class PortfolioPosition(BaseModel):
    symbol: str
    name: str
    quantity: int
    available_quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    pnl_amount: float
    pnl_ratio: float
    holding_days: int


class PortfolioSnapshot(BaseModel):
    as_of_date: str
    total_asset: float
    cash: float
    position_value: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    pending_order_count: int = 0
    positions: list[PortfolioPosition]


class ReviewStats(BaseModel):
    win_rate: float
    total_return: float
    max_drawdown: float
    avg_pnl_ratio: float
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    profit_factor: float = 0.0


class TradeRecord(BaseModel):
    symbol: str
    buy_date: str
    buy_price: float
    sell_date: str
    sell_price: float
    quantity: int = 0
    holding_days: int
    pnl_amount: float
    pnl_ratio: float


class EquityPoint(BaseModel):
    date: str
    equity: float
    realized_pnl: float


class DrawdownPoint(BaseModel):
    date: str
    drawdown: float


class MonthlyReturnPoint(BaseModel):
    month: str
    return_ratio: float
    pnl_amount: float
    trade_count: int


class ReviewRange(BaseModel):
    date_from: str
    date_to: str
    date_axis: Literal["sell", "buy"] = "sell"


class ReviewResponse(BaseModel):
    stats: ReviewStats
    trades: list[TradeRecord]
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    drawdown_curve: list[DrawdownPoint] = Field(default_factory=list)
    monthly_returns: list[MonthlyReturnPoint] = Field(default_factory=list)
    top_trades: list[TradeRecord] = Field(default_factory=list)
    bottom_trades: list[TradeRecord] = Field(default_factory=list)
    cost_snapshot: SimTradingConfig = Field(default_factory=SimTradingConfig)
    range: ReviewRange


class BacktestRunRequest(BaseModel):
    mode: SignalScanMode = "trend_pool"
    run_id: str | None = None
    trend_step: TrendPoolStep = "auto"
    board_filters: list[BoardFilter] = Field(default_factory=list, max_length=5)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    window_days: int = Field(default=60, ge=20, le=240)
    min_score: float = Field(default=55.0, ge=0.0, le=100.0)
    require_sequence: bool = False
    min_event_count: int = Field(default=1, ge=0, le=12)
    entry_events: list[str] = Field(
        default_factory=lambda: ["Spring", "SOS", "JOC", "LPS"],
        min_length=1,
        max_length=12,
    )
    exit_events: list[str] = Field(
        default_factory=lambda: ["UTAD", "SOW", "LPSY"],
        min_length=1,
        max_length=12,
    )
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    position_pct: float = Field(default=0.2, gt=0, le=1)
    max_positions: int = Field(default=5, ge=1, le=100)
    stop_loss: float = Field(default=0.05, ge=0, le=0.5)
    take_profit: float = Field(default=0.15, ge=0, le=1.5)
    max_hold_days: int = Field(default=60, ge=1, le=365)
    fee_bps: float = Field(default=10.0, ge=0.0, le=500.0)
    prioritize_signals: bool = True
    priority_mode: BacktestPriorityMode = "balanced"
    priority_topk_per_day: int = Field(default=0, ge=0, le=500)
    enforce_t1: bool = True
    max_symbols: int = Field(default=120, ge=20, le=2000)
    pool_roll_mode: BacktestPoolRollMode = "daily"


class BacktestTrade(BaseModel):
    symbol: str
    name: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_signal: str
    entry_phase: str = "阶段未明"
    entry_quality_score: float = 0.0
    exit_reason: str
    quantity: int
    entry_price: float
    exit_price: float
    holding_days: int
    pnl_amount: float
    pnl_ratio: float


class BacktestResponse(BaseModel):
    stats: ReviewStats
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    drawdown_curve: list[DrawdownPoint] = Field(default_factory=list)
    monthly_returns: list[MonthlyReturnPoint] = Field(default_factory=list)
    top_trades: list[BacktestTrade] = Field(default_factory=list)
    bottom_trades: list[BacktestTrade] = Field(default_factory=list)
    cost_snapshot: SimTradingConfig = Field(default_factory=SimTradingConfig)
    range: ReviewRange
    notes: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    skipped_count: int = 0
    fill_rate: float = 0.0
    max_concurrent_positions: int = 0


class BacktestTaskStartResponse(BaseModel):
    task_id: str


class BacktestTaskStageTiming(BaseModel):
    stage_key: str
    label: str
    elapsed_ms: int = Field(default=0, ge=0)


class BacktestTaskProgress(BaseModel):
    mode: BacktestPoolRollMode = "daily"
    current_date: str | None = None
    processed_dates: int = 0
    total_dates: int = 0
    percent: float = 0.0
    message: str = ""
    warning: str | None = None
    stage_timings: list[BacktestTaskStageTiming] = Field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""


class BacktestTaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "paused", "succeeded", "failed", "cancelled"]
    progress: BacktestTaskProgress
    result: BacktestResponse | None = None
    error: str | None = None
    error_code: str | None = None


class BacktestPlateauRunRequest(BaseModel):
    base_payload: BacktestRunRequest
    sampling_mode: Literal["grid", "lhs"] = "lhs"
    window_days_list: list[int] = Field(default_factory=list, max_length=16)
    min_score_list: list[float] = Field(default_factory=list, max_length=16)
    stop_loss_list: list[float] = Field(default_factory=list, max_length=16)
    take_profit_list: list[float] = Field(default_factory=list, max_length=16)
    max_positions_list: list[int] = Field(default_factory=list, max_length=16)
    position_pct_list: list[float] = Field(default_factory=list, max_length=16)
    max_symbols_list: list[int] = Field(default_factory=list, max_length=16)
    priority_topk_per_day_list: list[int] = Field(default_factory=list, max_length=16)
    sample_points: int | None = Field(default=None, ge=1, le=2000)
    random_seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    max_points: int = Field(default=120, ge=1, le=2000)


class BacktestPlateauParams(BaseModel):
    window_days: int
    min_score: float
    stop_loss: float
    take_profit: float
    max_positions: int
    position_pct: float
    max_symbols: int
    priority_topk_per_day: int


class BacktestPlateauPoint(BaseModel):
    params: BacktestPlateauParams
    stats: ReviewStats
    candidate_count: int = 0
    skipped_count: int = 0
    fill_rate: float = 0.0
    max_concurrent_positions: int = 0
    score: float = 0.0
    cache_hit: bool = False
    error: str | None = None


class BacktestPlateauResponse(BaseModel):
    base_payload: BacktestRunRequest
    total_combinations: int
    evaluated_combinations: int
    points: list[BacktestPlateauPoint] = Field(default_factory=list)
    best_point: BacktestPlateauPoint | None = None
    generated_at: str
    notes: list[str] = Field(default_factory=list)


class BacktestPlateauTaskProgress(BaseModel):
    sampling_mode: Literal["grid", "lhs"] = "lhs"
    processed_points: int = 0
    total_points: int = 0
    percent: float = 0.0
    message: str = ""
    started_at: str = ""
    updated_at: str = ""


class BacktestPlateauTaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "paused", "succeeded", "failed", "cancelled"]
    progress: BacktestPlateauTaskProgress
    result: BacktestPlateauResponse | None = None
    error: str | None = None
    error_code: str | None = None


class ReviewTag(BaseModel):
    id: str
    name: str
    color: str
    created_at: str


class ReviewTagsPayload(BaseModel):
    emotion: list[ReviewTag] = Field(default_factory=list)
    reason: list[ReviewTag] = Field(default_factory=list)


class ReviewTagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class TradeFillTagUpdateRequest(BaseModel):
    emotion_tag_id: str | None = None
    reason_tag_ids: list[str] = Field(default_factory=list, max_length=16)


class TradeFillTagAssignment(BaseModel):
    order_id: str
    emotion_tag_id: str | None = None
    reason_tag_ids: list[str] = Field(default_factory=list)
    updated_at: str


class ReviewTagStatItem(BaseModel):
    tag_id: str
    name: str
    color: str
    count: int
    gross_amount: float
    net_amount: float


class ReviewTagStatsResponse(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    emotion: list[ReviewTagStatItem] = Field(default_factory=list)
    reason: list[ReviewTagStatItem] = Field(default_factory=list)


class DailyReviewPayload(BaseModel):
    title: str = ""
    market_summary: str = ""
    operations_summary: str = ""
    reflection: str = ""
    tomorrow_plan: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)


class DailyReviewRecord(DailyReviewPayload):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    updated_at: str


class DailyReviewListResponse(BaseModel):
    items: list[DailyReviewRecord] = Field(default_factory=list)


class WeeklyReviewPayload(BaseModel):
    start_date: str = ""
    end_date: str = ""
    core_goals: str = ""
    achievements: str = ""
    resource_analysis: str = ""
    market_rhythm: str = ""
    next_week_strategy: str = ""
    key_insight: str = ""
    tags: list[str] = Field(default_factory=list)


class WeeklyReviewRecord(WeeklyReviewPayload):
    week_label: str = Field(pattern=r"^\d{4}-W\d{2}$")
    updated_at: str


class WeeklyReviewListResponse(BaseModel):
    items: list[WeeklyReviewRecord] = Field(default_factory=list)


class MarketNewsItem(BaseModel):
    title: str
    url: str
    snippet: str = ""
    pub_date: str = ""
    source_name: str = ""


class MarketNewsResponse(BaseModel):
    query: str
    age_hours: int = 72
    symbol: str | None = None
    symbol_name: str | None = None
    source_domains: list[str] = Field(default_factory=list)
    items: list[MarketNewsItem] = Field(default_factory=list)
    fetched_at: str
    cache_hit: bool = False
    fallback_used: bool = False
    degraded: bool = False
    degraded_reason: str | None = None


class SimOrdersResponse(BaseModel):
    items: list[SimTradeOrder]
    total: int
    page: int
    page_size: int


class SimFillsResponse(BaseModel):
    items: list[SimTradeFill]
    total: int
    page: int
    page_size: int


class SimSettleResponse(BaseModel):
    settled_count: int
    filled_count: int
    pending_count: int
    as_of_date: str
    last_settle_at: str


class SimResetResponse(BaseModel):
    success: Literal[True]
    as_of_date: str
    cash: float


class AIAnalysisRecord(BaseModel):
    provider: str
    symbol: str
    name: str
    fetched_at: str
    source_urls: list[str]
    summary: str
    conclusion: str
    confidence: float
    breakout_date: str | None = None
    trend_bull_type: str | None = None
    theme_name: str | None = None
    rise_reasons: list[str] = Field(default_factory=list)
    error_code: str | None = None


class AIRecordsResponse(BaseModel):
    items: list[AIAnalysisRecord]


class DeleteAIRecordResponse(BaseModel):
    deleted: bool
    remaining: int


class AIProviderConfig(BaseModel):
    id: str
    label: str
    base_url: str
    model: str
    api_key: str
    api_key_path: str
    enabled: bool


class AISourceConfig(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool


class AppConfig(BaseModel):
    tdx_data_path: str
    market_data_source: MarketDataSource = "tdx_then_akshare"
    akshare_cache_dir: str = ""
    markets: list[Market]
    return_window_days: int
    candles_window_bars: int = Field(default=120, ge=120, le=5000)
    top_n: int
    turnover_threshold: float
    amount_threshold: float
    amplitude_threshold: float
    initial_capital: float
    ai_provider: str
    ai_timeout_sec: int
    ai_retry_count: int
    api_key: str
    api_key_path: str
    ai_providers: list[AIProviderConfig]
    ai_sources: list[AISourceConfig]


class SystemStorageStatus(BaseModel):
    app_state_path: str
    app_state_exists: bool
    sim_state_path: str
    sim_state_exists: bool
    akshare_cache_dir: str
    akshare_cache_dir_resolved: str
    akshare_cache_dir_exists: bool
    akshare_cache_file_count: int
    akshare_cache_candidates: list[str] = Field(default_factory=list)
    wyckoff_event_store_path: str = ""
    wyckoff_event_store_exists: bool = False
    wyckoff_event_store_read_only: bool = False


class WyckoffEventStoreStatsResponse(BaseModel):
    enabled: bool
    read_only: bool
    db_path: str
    db_exists: bool
    db_record_count: int
    runtime_cache_size: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float = 0.0
    cache_miss_rate: float = 0.0
    snapshot_reads: int = 0
    avg_snapshot_read_ms: float = 0.0
    lazy_fill_writes: int
    backfill_runs: int
    backfill_writes: int
    quality_empty_events: int = 0
    quality_score_outliers: int = 0
    quality_date_misaligned: int = 0
    last_backfill_started_at: str | None = None
    last_backfill_finished_at: str | None = None
    last_backfill_duration_sec: float | None = None
    last_backfill_scan_dates: int = 0
    last_backfill_symbols: int = 0
    last_backfill_quality_empty_events: int = 0
    last_backfill_quality_score_outliers: int = 0
    last_backfill_quality_date_misaligned: int = 0


class WyckoffEventStoreBackfillRequest(BaseModel):
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    markets: list[Market] = Field(default_factory=list)
    window_days_list: list[int] = Field(default_factory=lambda: [60], min_length=1, max_length=6)
    max_symbols_per_day: int = Field(default=300, ge=20, le=6000)
    force_rebuild: bool = False


class WyckoffEventStoreBackfillResponse(BaseModel):
    ok: bool
    message: str
    date_from: str
    date_to: str
    markets: list[Market]
    window_days_list: list[int]
    scan_dates: int
    loaded_rows_total: int
    symbols_scanned: int
    cache_hits: int
    cache_misses: int
    computed_count: int
    write_count: int
    quality_empty_events: int = 0
    quality_score_outliers: int = 0
    quality_date_misaligned: int = 0
    started_at: str
    finished_at: str
    duration_sec: float
    warnings: list[str] = Field(default_factory=list)


class MarketDataSyncRequest(BaseModel):
    provider: MarketSyncProvider = "baostock"
    mode: MarketSyncMode = "incremental"
    symbols: str = ""
    all_market: bool = True
    limit: int = Field(default=300, ge=1, le=5000)
    start_date: str = ""
    end_date: str = ""
    initial_days: int = Field(default=420, ge=1, le=3000)
    sleep_sec: float = Field(default=0.01, ge=0.0, le=1.0)
    out_dir: str = ""


class MarketDataSyncResponse(BaseModel):
    ok: bool
    provider: MarketSyncProvider = "baostock"
    mode: MarketSyncMode = "incremental"
    message: str
    out_dir: str
    symbol_count: int = 0
    ok_count: int = 0
    fail_count: int = 0
    skipped_count: int = 0
    new_rows_total: int = 0
    started_at: str
    finished_at: str
    duration_sec: float = 0.0
    errors: list[str] = Field(default_factory=list)


class AIProviderTestRequest(BaseModel):
    provider: AIProviderConfig
    fallback_api_key: str = ""
    fallback_api_key_path: str = ""
    timeout_sec: int = Field(ge=3, le=60, default=10)


class AIProviderTestResponse(BaseModel):
    ok: bool
    provider_id: str
    latency_ms: int
    message: str
    error_code: str | None = None
