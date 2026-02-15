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
