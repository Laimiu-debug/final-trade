from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Market = Literal["sh", "sz", "bj"]
ScreenerMode = Literal["strict", "loose"]
TrendClass = Literal["A", "A_B", "B", "Unknown"]
ThemeStage = Literal["发酵中", "高潮", "退潮", "Unknown"]
SignalType = Literal["A", "B", "C"]
PriceSource = Literal["vwap", "approx"]
Stage = Literal["Early", "Mid", "Late"]


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


class SignalsResponse(BaseModel):
    items: list[SignalResult]


class SimTradeOrder(BaseModel):
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    signal_date: str
    submit_date: str
    status: Literal["pending", "filled", "cancelled", "rejected"]
    reject_reason: str | None = None


class SimTradeFill(BaseModel):
    order_id: str
    symbol: str
    fill_date: str
    fill_price: float
    price_source: PriceSource
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
    avg_cost: float
    current_price: float
    pnl_ratio: float
    holding_days: int


class PortfolioSnapshot(BaseModel):
    total_asset: float
    cash: float
    position_value: float
    positions: list[PortfolioPosition]


class ReviewStats(BaseModel):
    win_rate: float
    total_return: float
    max_drawdown: float
    avg_pnl_ratio: float


class TradeRecord(BaseModel):
    symbol: str
    buy_date: str
    buy_price: float
    sell_date: str
    sell_price: float
    holding_days: int
    pnl_amount: float
    pnl_ratio: float


class ReviewResponse(BaseModel):
    stats: ReviewStats
    trades: list[TradeRecord]


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
