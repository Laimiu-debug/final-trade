from __future__ import annotations

from typing import Any, Literal

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
StrategyId = str


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


class ScreenerStep1Config(BaseModel):
    top_n: int = Field(default=500, ge=100, le=2000)
    turnover_threshold: float = Field(default=0.05, ge=0.01, le=0.2)
    amount_threshold: float = Field(default=5e8, ge=5e7, le=5e9)
    amplitude_threshold: float = Field(default=0.03, ge=0.01, le=0.15)


class ScreenerStep2Config(BaseModel):
    retrace_min: float = Field(default=0.05, ge=0.0, le=0.8)
    retrace_max: float = Field(default=0.25, ge=0.0, le=0.8)
    max_pullback_days: int = Field(default=3, ge=0, le=30)
    min_ma10_above_ma20_days: int = Field(default=5, ge=0, le=40)
    min_ma5_above_ma10_days: int = Field(default=3, ge=0, le=40)
    max_price_vs_ma20: float = Field(default=0.08, ge=0.0, le=0.5)
    require_above_ma20: bool = True
    allow_b_trend: bool = False


class ScreenerStep3Config(BaseModel):
    min_vol_slope20: float = Field(default=0.05, ge=0.0, le=2.0)
    min_up_down_volume_ratio: float = Field(default=1.3, ge=0.0, le=20.0)
    max_pullback_volume_ratio: float = Field(default=0.9, ge=0.0, le=5.0)
    allow_blowoff_top: bool = False
    allow_divergence_5d: bool = False
    allow_upper_shadow_risk: bool = False
    allow_degraded: bool = False


class ScreenerStep4Config(BaseModel):
    final_top_n: int = Field(default=8, ge=1, le=500)
    min_ai_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    allowed_theme_stages: list[ThemeStage] = Field(default_factory=lambda: ["发酵中", "高潮"], min_length=1)
    allow_degraded: bool = True


class ScreenerStepConfigs(BaseModel):
    step1: ScreenerStep1Config = Field(default_factory=ScreenerStep1Config)
    step2: ScreenerStep2Config = Field(default_factory=ScreenerStep2Config)
    step3: ScreenerStep3Config = Field(default_factory=ScreenerStep3Config)
    step4: ScreenerStep4Config = Field(default_factory=ScreenerStep4Config)


class ScreenerParams(BaseModel):
    markets: list[Market] = Field(min_length=1)
    mode: ScreenerMode
    as_of_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    return_window_days: int = Field(ge=5, le=120)
    top_n: int = Field(ge=100, le=2000)
    turnover_threshold: float = Field(ge=0.01, le=0.2)
    amount_threshold: float = Field(ge=5e7, le=5e9)
    amplitude_threshold: float = Field(ge=0.01, le=0.15)
    step_configs: ScreenerStepConfigs | None = None


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
    step_configs: ScreenerStepConfigs = Field(default_factory=ScreenerStepConfigs)
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
    signal: 'SignalResult | None' = None


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
    signal_age_days: int = 0
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
    health_score: float = 0.0
    slope_stability: float = 0.0
    volatility_stability: float = 0.0
    pullback_quality: float = 0.0
    event_score: float = 0.0
    event_grade: Literal["A", "B", "C"] = "C"
    event_background_score: float = 0.0
    event_position_score: float = 0.0
    event_vol_price_score: float = 0.0
    event_confirmation_score: float = 0.0
    candle_quality_score: float = 0.0
    cost_center_shift_score: float = 0.0
    weekly_context_score: float = 0.0
    weekly_context_multiplier: float = 1.0
    event_recency_score: float = 0.0
    phase_context_score: float = 0.0
    risk_score: float = 0.0
    confirmation_status: Literal["confirmed", "partial", "unconfirmed", "risk_blocked"] = "unconfirmed"
    event_confirmation_map: dict[str, str] = Field(default_factory=dict)
    event_grade_map: dict[str, str] = Field(default_factory=dict)


class SignalsResponse(BaseModel):
    items: list[SignalResult]
    mode: SignalScanMode = "trend_pool"
    as_of_date: str | None = None
    generated_at: str = ""
    cache_hit: bool = False
    degraded: bool = False
    degraded_reason: str | None = None
    source_count: int = 0
    strategy_id: StrategyId = "wyckoff_trend_v1"
    strategy_version: str = "1.0.0"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    strategy_params_hash: str = ""
    notes: list[str] = Field(default_factory=list)


class SignalEtfBacktestConstituentInput(BaseModel):
    symbol: str = Field(min_length=4, max_length=16)
    name: str = Field(default="", max_length=64)
    signal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    signal_primary: str = Field(default="", max_length=16)
    signal_event: str = Field(default="", max_length=64)
    signal_reason: str = Field(default="", max_length=400)


class SignalEtfBacktestCreateRequest(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_name: str = Field(default="", max_length=128)
    signal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    name: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=1000)
    constituents: list[SignalEtfBacktestConstituentInput] = Field(min_length=1, max_length=2000)


class SignalEtfBacktestUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=1000)


class SignalEtfBacktestPerformance(BaseModel):
    return_pct: float = 0.0
    benchmark_return_pct: float = 0.0
    excess_return_pct: float = 0.0
    stock_win_rate: float = 0.0
    daily_win_rate: float = 0.0
    tradable_count: int = 0
    skipped_count: int = 0


class SignalEtfBacktestStrategyStats(BaseModel):
    strategy_id: str = ""
    total_records: int = 0
    win_rate_t1: float = 0.0
    win_rate_t2: float = 0.0


class SignalEtfBacktestSummary(BaseModel):
    t1: SignalEtfBacktestPerformance = Field(default_factory=SignalEtfBacktestPerformance)
    t2: SignalEtfBacktestPerformance = Field(default_factory=SignalEtfBacktestPerformance)
    strategy_stats: SignalEtfBacktestStrategyStats = Field(default_factory=SignalEtfBacktestStrategyStats)
    holding_period_days: int | None = None
    holding_target_date: str | None = None
    holding_return_pct: float | None = None


class SignalEtfBacktestRecord(BaseModel):
    record_id: str
    name: str
    notes: str = ""
    signal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    strategy_id: str
    strategy_name: str = ""
    benchmark_symbol: str = "sh000001"
    total_constituents: int = 0
    created_at: str
    updated_at: str
    summary: SignalEtfBacktestSummary = Field(default_factory=SignalEtfBacktestSummary)


class SignalEtfBacktestConstituentDetail(BaseModel):
    symbol: str
    name: str = ""
    signal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    signal_primary: str = ""
    signal_event: str = ""
    signal_reason: str = ""
    current_date: str | None = None
    current_price: float | None = None
    buy_date_t1: str | None = None
    buy_price_t1: float | None = None
    return_pct_t1: float | None = None
    status_t1: Literal["bought", "skipped"] = "skipped"
    buy_date_t2: str | None = None
    buy_price_t2: float | None = None
    return_pct_t2: float | None = None
    status_t2: Literal["bought", "skipped"] = "skipped"
    holding_period_days: int | None = None
    holding_target_date: str | None = None
    return_pct_holding: float | None = None


class SignalEtfBacktestCurvePoint(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    etf_return_t1: float | None = None
    etf_return_t2: float | None = None
    benchmark_return_t1: float | None = None
    benchmark_return_t2: float | None = None
    excess_return_t1: float | None = None
    excess_return_t2: float | None = None


class SignalEtfBacktestDetail(SignalEtfBacktestRecord):
    benchmark_available: bool = False
    constituents: list[SignalEtfBacktestConstituentDetail] = Field(default_factory=list)
    curve: list[SignalEtfBacktestCurvePoint] = Field(default_factory=list)


class SignalEtfBacktestListResponse(BaseModel):
    items: list[SignalEtfBacktestRecord] = Field(default_factory=list)


class SignalEtfBacktestDeleteResponse(BaseModel):
    deleted: bool
    record_id: str


class SignalEtfBacktestAutoCreateRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=64)
    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_name: str = Field(default="", max_length=128)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    trend_step: TrendPoolStep = "auto"
    board_filters: list[BoardFilter] = Field(default_factory=list, max_length=5)
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    window_days: int = Field(default=60, ge=20, le=240)
    min_score: float = Field(default=60.0, ge=0.0, le=100.0)
    require_sequence: bool = False
    min_event_count: int = Field(default=1, ge=0, le=12)
    signal_age_min: int = Field(default=0, ge=0, le=240)
    signal_age_max: int | None = Field(default=None, ge=0, le=240)
    name_prefix: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=1000)
    refresh_signals: bool = False


class SignalEtfBacktestAutoCreateItem(BaseModel):
    record_id: str
    name: str
    signal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    total_constituents: int = 0


class SignalEtfBacktestAutoCreateIssue(BaseModel):
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str


class SignalEtfBacktestAutoCreateResponse(BaseModel):
    run_id: str
    strategy_id: str
    strategy_name: str = ""
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    processed_dates: int = 0
    created_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    created: list[SignalEtfBacktestAutoCreateItem] = Field(default_factory=list)
    skipped: list[SignalEtfBacktestAutoCreateIssue] = Field(default_factory=list)
    failed: list[SignalEtfBacktestAutoCreateIssue] = Field(default_factory=list)


class StrategyCapabilities(BaseModel):
    supports_matrix: bool = False
    supports_signal_age_filter: bool = True
    supports_entry_delay: bool = True


class StrategyDescriptor(BaseModel):
    strategy_id: StrategyId
    name: str
    version: str
    enabled: bool = True
    is_default: bool = False
    capabilities: StrategyCapabilities
    strategy_params_schema: dict[str, Any] = Field(default_factory=dict)
    strategy_params_defaults: dict[str, Any] = Field(default_factory=dict)


class StrategyCatalogResponse(BaseModel):
    items: list[StrategyDescriptor] = Field(default_factory=list)


class StrategyUpdateRequest(BaseModel):
    enabled: bool | None = None
    is_default: bool | None = None
    version: str | None = Field(default=None, min_length=1, max_length=64)


class EventJudgmentMetricOption(BaseModel):
    metric_key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=200)


class EventJudgmentRuleOption(BaseModel):
    rule_key: str = Field(min_length=1, max_length=96)
    label: str = Field(min_length=1, max_length=96)
    description: str = Field(default="", max_length=240)
    category: str = Field(default="", max_length=64)
    value_type: Literal["number", "integer", "boolean"] = "number"
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    recommended_min: float | None = None
    recommended_max: float | None = None
    risk_hint_low: str = Field(default="", max_length=240)
    risk_hint_high: str = Field(default="", max_length=240)
    default_value: bool | int | float


class EventJudgmentDimension(BaseModel):
    dimension_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    metric_key: str = Field(min_length=1, max_length=64)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    invert: bool = False
    enabled: bool = True


class EventJudgmentRuleValue(BaseModel):
    rule_key: str = Field(min_length=1, max_length=96)
    value: bool | int | float


class EventJudgmentProfile(BaseModel):
    profile_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=200)
    score_mode: Literal["legacy_formula", "dimension_weighted"] = "dimension_weighted"
    is_system: bool = False
    updated_at: str
    dimensions: list[EventJudgmentDimension] = Field(default_factory=list, max_length=24)
    rule_values: list[EventJudgmentRuleValue] = Field(default_factory=list, max_length=256)


class EventJudgmentCatalogResponse(BaseModel):
    active_profile_id: str = Field(min_length=1, max_length=64)
    metric_options: list[EventJudgmentMetricOption] = Field(default_factory=list)
    rule_options: list[EventJudgmentRuleOption] = Field(default_factory=list)
    profiles: list[EventJudgmentProfile] = Field(default_factory=list)


class EventJudgmentProfileUpsertRequest(BaseModel):
    profile_id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=200)
    dimensions: list[EventJudgmentDimension] = Field(min_length=1, max_length=24)
    rule_values: list[EventJudgmentRuleValue] | None = Field(default=None, max_length=256)
    make_active: bool = True


class EventJudgmentProfileApplyRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=64)


class EventJudgmentProfileDeleteResponse(BaseModel):
    success: Literal[True]
    profile_id: str


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
    strategy_id: StrategyId = "wyckoff_trend_v1"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
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
    trailing_stop_pct: float = Field(default=0.0, ge=0.0, le=0.5)
    max_hold_days: int = Field(default=60, ge=1, le=365)
    fee_bps: float = Field(default=10.0, ge=0.0, le=500.0)
    prioritize_signals: bool = True
    priority_mode: BacktestPriorityMode = "balanced"
    priority_topk_per_day: int = Field(default=0, ge=0, le=500)
    rank_weight_health: float = Field(default=0.45, ge=0.0, le=1.0)
    rank_weight_event: float = Field(default=0.55, ge=0.0, le=1.0)
    health_score_min: float = Field(default=0.0, ge=0.0, le=100.0)
    event_score_min: float = Field(default=0.0, ge=0.0, le=100.0)
    event_grade_min: Literal["A", "B", "C"] = "C"
    require_key_event_confirmation: bool = False
    execution_path_preference: Literal["auto", "matrix", "legacy"] = "auto"
    matrix_event_semantic_version: Literal["matrix_v1", "aligned_wyckoff_v2"] = "matrix_v1"
    enforce_t1: bool = True
    entry_delay_days: int = Field(default=1, ge=1, le=5)
    delay_invalidation_enabled: bool = True
    max_symbols: int = Field(default=120, ge=20, le=2000)
    pool_roll_mode: BacktestPoolRollMode = "daily"
    enable_advanced_analysis: bool = True


class BacktestTrade(BaseModel):
    symbol: str
    name: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_signal: str
    entry_phase: str = "阶段未明"
    entry_quality_score: float = 0.0
    candle_quality_score: float = 0.0
    cost_center_shift_score: float = 0.0
    weekly_context_score: float = 0.0
    weekly_context_multiplier: float = 1.0
    health_score: float = 0.0
    event_score: float = 0.0
    risk_score: float = 0.0
    confirmation_status: Literal["confirmed", "partial", "unconfirmed", "risk_blocked"] = "unconfirmed"
    event_grade: Literal["A", "B", "C"] = "C"
    phase_context_score: float = 0.0
    event_recency_score: float = 0.0
    exit_reason: str
    delay_entry_days: int = 1
    delay_window_days: int = 0
    quantity: int
    entry_price: float
    exit_price: float
    holding_days: int
    pnl_amount: float
    pnl_ratio: float


class BacktestRiskMetrics(BaseModel):
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    expectancy: float = 0.0
    avg_win_pnl_ratio: float = 0.0
    avg_loss_pnl_ratio: float = 0.0
    max_consecutive_losses: int = 0
    recovery_days: int = 0


class BacktestStabilityDiagnostics(BaseModel):
    stability_score: float = 0.0
    min_trade_count_threshold: int = 20
    trade_count_penalty: float = 0.0
    neighborhood_consistency: float = 0.0
    return_variance_penalty: float = 0.0
    monthly_return_std: float = 0.0
    notes: list[str] = Field(default_factory=list)


class BacktestRegimeBucket(BaseModel):
    regime: Literal["bull", "range", "bear"]
    label: str
    trade_count: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    avg_pnl_ratio: float = 0.0
    max_drawdown: float = 0.0


class BacktestMonteCarloSummary(BaseModel):
    simulations: int = 0
    seed: int = 0
    total_return_p5: float = 0.0
    total_return_p50: float = 0.0
    total_return_p95: float = 0.0
    max_drawdown_p5: float = 0.0
    max_drawdown_p50: float = 0.0
    max_drawdown_p95: float = 0.0
    ruin_probability: float = 0.0


class BacktestWalkForwardFold(BaseModel):
    fold_index: int
    train_date_from: str
    train_date_to: str
    test_date_from: str
    test_date_to: str
    selected_params: "BacktestPlateauParams"
    train_score: float = 0.0
    test_score: float = 0.0
    train_stats: ReviewStats
    test_stats: ReviewStats


class BacktestWalkForwardReport(BaseModel):
    fold_count: int = 0
    candidate_count: int = 0
    oos_pass_rate: float = 0.0
    avg_test_return: float = 0.0
    avg_test_win_rate: float = 0.0
    folds: list[BacktestWalkForwardFold] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


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
    risk_metrics: BacktestRiskMetrics | None = None
    stability_diagnostics: BacktestStabilityDiagnostics | None = None
    regime_breakdown: list[BacktestRegimeBucket] = Field(default_factory=list)
    monte_carlo: BacktestMonteCarloSummary | None = None
    walk_forward: BacktestWalkForwardReport | None = None
    execution_path: Literal["matrix", "legacy"] | None = None
    strategy_id: StrategyId = "wyckoff_trend_v1"
    strategy_version: str = "1.0.0"
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    strategy_params_hash: str = ""
    effective_run_request: BacktestRunRequest | None = None


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


class BacktestTaskListResponse(BaseModel):
    items: list[BacktestTaskStatusResponse] = Field(default_factory=list)


class BacktestPlateauRunRequest(BaseModel):
    base_payload: BacktestRunRequest
    sampling_mode: Literal["grid", "lhs"] = "lhs"
    window_days_list: list[int] = Field(default_factory=list, max_length=16)
    min_score_list: list[float] = Field(default_factory=list, max_length=16)
    stop_loss_list: list[float] = Field(default_factory=list, max_length=16)
    take_profit_list: list[float] = Field(default_factory=list, max_length=16)
    trailing_stop_pct_list: list[float] = Field(default_factory=list, max_length=16)
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
    trailing_stop_pct: float
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
    annual_trades: float = 0.0
    score: float = 0.0
    point_score: float = 0.0
    local_score: float = 0.0
    plateau_score: float = 0.0
    neighbor_pass_rate: float = 0.0
    neighbor_median_score: float = 0.0
    neighbor_p25_score: float = 0.0
    sensitivity_penalty: float = 0.0
    passes_hard_filters: bool = False
    hard_filter_failures: list[str] = Field(default_factory=list)
    region_id: str | None = None
    region_rank: int | None = None
    cache_hit: bool = False
    detail_key: str | None = None
    error: str | None = None


class BacktestPlateauRegionSummary(BaseModel):
    region_id: str
    region_rank: int = 0
    point_count: int = 0
    parameter_ranges: dict[str, str] = Field(default_factory=dict)
    center_point: BacktestPlateauPoint
    median_local_score: float = 0.0
    p25_local_score: float = 0.0
    median_point_score: float = 0.0
    median_total_return: float = 0.0
    best_total_return: float = 0.0
    center_margin_score: float = 0.0
    size_score: float = 0.0
    oos_pass_rate: float | None = None
    region_score: float = 0.0
    walk_forward: BacktestWalkForwardReport | None = None


class BacktestPlateauCorrelationRow(BaseModel):
    parameter: str
    parameter_label: str
    score_corr: float = 0.0
    total_return_corr: float = 0.0
    win_rate_corr: float = 0.0


class BacktestPlateauResponse(BaseModel):
    base_payload: BacktestRunRequest
    total_combinations: int
    evaluated_combinations: int
    points: list[BacktestPlateauPoint] = Field(default_factory=list)
    best_point: BacktestPlateauPoint | None = None
    recommended_point: BacktestPlateauPoint | None = None
    peak_point: BacktestPlateauPoint | None = None
    regions: list[BacktestPlateauRegionSummary] = Field(default_factory=list)
    correlations: list[BacktestPlateauCorrelationRow] = Field(default_factory=list)
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


class BacktestPlateauTaskListResponse(BaseModel):
    items: list[BacktestPlateauTaskStatusResponse] = Field(default_factory=list)


class BacktestPlateauTaskDeleteResponse(BaseModel):
    deleted: bool
    task_id: str


class BacktestPlateauPointDetailResponse(BaseModel):
    task_id: str
    detail_key: str
    saved_at: str
    params: BacktestPlateauParams
    run_request: BacktestRunRequest
    run_result: BacktestResponse


class BacktestReportManifestFile(BaseModel):
    path: str
    sha256: str
    bytes: int = Field(ge=0)


class BacktestReportManifestApp(BaseModel):
    name: str
    version: str


class BacktestReportManifest(BaseModel):
    schema_version: Literal["ftbt-1.0"] = "ftbt-1.0"
    package_type: Literal["backtest_report"] = "backtest_report"
    created_at: str
    report_id: str
    app: BacktestReportManifestApp
    files: list[BacktestReportManifestFile] = Field(default_factory=list)


class BacktestReportBuildRequest(BaseModel):
    run_request: BacktestRunRequest
    run_result: BacktestResponse
    report_html: str = Field(min_length=1)
    report_xlsx_base64: str = Field(min_length=1)
    plateau_result: BacktestPlateauResponse | None = None
    report_id: str | None = None
    app_name: str = "Final Trade"
    app_version: str = "unknown"


class BacktestReportBuildResponse(BaseModel):
    report_id: str
    file_name: str
    file_base64: str
    manifest: BacktestReportManifest


class BacktestReportSummary(BaseModel):
    report_id: str
    created_at: str
    first_imported_at: str
    last_imported_at: str
    source_file_name: str
    package_size_bytes: int = Field(ge=0)
    trade_count: int = 0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    date_from: str
    date_to: str
    has_plateau_result: bool = False


class BacktestReportListResponse(BaseModel):
    items: list[BacktestReportSummary] = Field(default_factory=list)


class BacktestReportDetail(BaseModel):
    summary: BacktestReportSummary
    manifest: BacktestReportManifest
    run_request: BacktestRunRequest
    run_result: BacktestResponse
    plateau_result: BacktestPlateauResponse | None = None


class BacktestReportImportResponse(BaseModel):
    summary: BacktestReportSummary


class BacktestReportDeleteResponse(BaseModel):
    deleted: bool
    report_id: str


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
    backtest_matrix_engine_enabled: bool = True
    backtest_plateau_workers: int = Field(default=4, ge=1, le=32)
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


BacktestWalkForwardFold.model_rebuild()
StockAnalysisResponse.model_rebuild()
