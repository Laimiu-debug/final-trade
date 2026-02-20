from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    AIAnalysisRecord,
    AIProviderTestRequest,
    AIProviderTestResponse,
    AIRecordsResponse,
    BacktestResponse,
    BacktestRunRequest,
    BacktestTaskStartResponse,
    BacktestTaskStatusResponse,
    BoardFilter,
    Market,
    AnnotationUpdateResponse,
    ApiErrorPayload,
    AppConfig,
    CreateOrderRequest,
    CreateOrderResponse,
    DeleteAIRecordResponse,
    IntradayPayload,
    MarketDataSyncRequest,
    MarketDataSyncResponse,
    MarketNewsResponse,
    PortfolioSnapshot,
    DailyReviewListResponse,
    DailyReviewPayload,
    DailyReviewRecord,
    ReviewResponse,
    ReviewTag,
    ReviewTagCreateRequest,
    ReviewTagStatsResponse,
    ReviewTagsPayload,
    ReviewTagType,
    SimFillsResponse,
    SimOrdersResponse,
    SimResetResponse,
    SimSettleResponse,
    SimTradingConfig,
    SystemStorageStatus,
    SignalScanMode,
    TrendPoolStep,
    ScreenerParams,
    ScreenerRunDetail,
    ScreenerRunResponse,
    SignalsResponse,
    WyckoffEventStoreBackfillRequest,
    WyckoffEventStoreBackfillResponse,
    WyckoffEventStoreStatsResponse,
    StockAnalysisResponse,
    StockAnnotation,
    TradeFillTagAssignment,
    TradeFillTagUpdateRequest,
    WeeklyReviewListResponse,
    WeeklyReviewPayload,
    WeeklyReviewRecord,
)
from .sim_engine import SimEngineError
from .store import store

app = FastAPI(title="Final trade API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    degraded: bool | None = None,
    degraded_reason: str | None = None,
) -> JSONResponse:
    payload = ApiErrorPayload(
        code=code,
        message=message,
        degraded=degraded,
        degraded_reason=degraded_reason,
        trace_id=str(__import__("time").time_ns()),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = exc.errors()[0].get("msg") if exc.errors() else "请求参数不合法"
    return error_response(422, "VALIDATION_ERROR", str(detail))


@app.exception_handler(SimEngineError)
def handle_sim_error(_: Request, exc: SimEngineError) -> JSONResponse:
    status_code = 404 if exc.code == "SIM_ORDER_NOT_FOUND" else 400
    return error_response(status_code, exc.code, exc.message)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/screener/run", response_model=ScreenerRunResponse)
def run_screener(params: ScreenerParams) -> ScreenerRunResponse:
    detail = store.create_screener_run(params)
    return ScreenerRunResponse(run_id=detail.run_id)


@app.get("/api/screener/runs/{run_id}", response_model=ScreenerRunDetail)
def get_screener_run(run_id: str = Path(min_length=6)) -> ScreenerRunDetail | JSONResponse:
    run = store.get_screener_run(run_id)
    if run is None:
        return error_response(404, "RUN_NOT_FOUND", "筛选任务不存在")
    return run


@app.get("/api/screener/latest-run", response_model=ScreenerRunDetail)
def get_latest_screener_run() -> ScreenerRunDetail | JSONResponse:
    run = store.get_latest_screener_run()
    if run is None:
        return error_response(404, "RUN_NOT_FOUND", "暂无可用筛选任务，请先在选股池执行筛选")
    return run


@app.get("/api/stocks/{symbol}/candles")
def get_stock_candles(symbol: str) -> dict[str, object]:
    return store.get_candles_payload(symbol)


@app.get("/api/stocks/{symbol}/intraday", response_model=IntradayPayload)
def get_stock_intraday(
    symbol: str,
    date: str = Query(default="", description="YYYY-MM-DD"),
) -> IntradayPayload:
    return store.get_intraday_payload(symbol, date)


@app.get("/api/stocks/{symbol}/analysis", response_model=StockAnalysisResponse)
def get_stock_analysis(symbol: str) -> StockAnalysisResponse:
    return store.get_analysis(symbol)


@app.put("/api/stocks/{symbol}/annotations", response_model=AnnotationUpdateResponse)
def put_stock_annotation(symbol: str, payload: StockAnnotation) -> AnnotationUpdateResponse | JSONResponse:
    if payload.symbol != symbol:
        return error_response(400, "SYMBOL_MISMATCH", "symbol 与 URL 不一致")
    saved = store.save_annotation(payload)
    return AnnotationUpdateResponse(success=True, annotation=saved)


@app.get("/api/signals", response_model=SignalsResponse)
def get_signals(
    mode: SignalScanMode = Query(default="trend_pool"),
    run_id: str = Query(default="", min_length=0, max_length=64),
    trend_step: TrendPoolStep = Query(default="auto"),
    market_filters: list[Market] | None = Query(default=None),
    board_filters: list[BoardFilter] | None = Query(default=None),
    as_of_date: str | None = Query(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    refresh: bool = Query(default=False),
    window_days: int = Query(default=60, ge=20, le=240),
    min_score: float = Query(default=60, ge=0, le=100),
    require_sequence: bool = Query(default=False),
    min_event_count: int = Query(default=1, ge=0, le=12),
) -> SignalsResponse:
    return store.get_signals(
        mode=mode,
        run_id=run_id.strip() or None,
        trend_step=trend_step,
        market_filters=list(dict.fromkeys(market_filters or [])),
        board_filters=list(dict.fromkeys(board_filters or [])),
        as_of_date=as_of_date,
        refresh=refresh,
        window_days=window_days,
        min_score=min_score,
        require_sequence=require_sequence,
        min_event_count=min_event_count,
    )


@app.post("/api/backtest/run", response_model=BacktestResponse)
def post_backtest_run(payload: BacktestRunRequest) -> BacktestResponse | JSONResponse:
    try:
        return store.run_backtest(payload)
    except ValueError as exc:
        return error_response(400, "BACKTEST_INVALID", str(exc))


@app.post("/api/backtest/tasks", response_model=BacktestTaskStartResponse)
def post_backtest_task(payload: BacktestRunRequest) -> BacktestTaskStartResponse | JSONResponse:
    try:
        task_id = store.start_backtest_task(payload)
        return BacktestTaskStartResponse(task_id=task_id)
    except ValueError as exc:
        return error_response(400, "BACKTEST_INVALID", str(exc))


@app.get("/api/backtest/tasks/{task_id}", response_model=BacktestTaskStatusResponse)
def get_backtest_task(task_id: str = Path(min_length=8, max_length=64)) -> BacktestTaskStatusResponse | JSONResponse:
    task = store.get_backtest_task(task_id)
    if task is None:
        return error_response(404, "BACKTEST_TASK_NOT_FOUND", "回测任务不存在")
    return task


@app.post("/api/sim/orders", response_model=CreateOrderResponse)
def post_order(payload: CreateOrderRequest) -> CreateOrderResponse:
    return store.create_order(payload)


@app.get("/api/sim/orders", response_model=SimOrdersResponse)
def get_orders(
    status: Literal["pending", "filled", "cancelled", "rejected"] | None = Query(default=None),
    symbol: str | None = Query(default=None, min_length=2, max_length=16),
    side: Literal["buy", "sell"] | None = Query(default=None),
    date_from: str | None = Query(default=None, min_length=10, max_length=10),
    date_to: str | None = Query(default=None, min_length=10, max_length=10),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> SimOrdersResponse:
    return store.list_orders(
        status=status,
        symbol=symbol.strip().lower() if symbol else None,
        side=side,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@app.get("/api/sim/fills", response_model=SimFillsResponse)
def get_fills(
    symbol: str | None = Query(default=None, min_length=2, max_length=16),
    side: Literal["buy", "sell"] | None = Query(default=None),
    date_from: str | None = Query(default=None, min_length=10, max_length=10),
    date_to: str | None = Query(default=None, min_length=10, max_length=10),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> SimFillsResponse:
    return store.list_fills(
        symbol=symbol.strip().lower() if symbol else None,
        side=side,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@app.post("/api/sim/orders/{order_id}/cancel", response_model=CreateOrderResponse)
def post_cancel_order(order_id: str = Path(min_length=8, max_length=64)) -> CreateOrderResponse:
    return store.cancel_order(order_id)


@app.post("/api/sim/settle", response_model=SimSettleResponse)
def post_sim_settle() -> SimSettleResponse:
    return store.settle_sim()


@app.post("/api/sim/reset", response_model=SimResetResponse)
def post_sim_reset() -> SimResetResponse:
    return store.reset_sim()


@app.get("/api/sim/config", response_model=SimTradingConfig)
def get_sim_config() -> SimTradingConfig:
    return store.get_sim_config()


@app.put("/api/sim/config", response_model=SimTradingConfig)
def put_sim_config(payload: SimTradingConfig) -> SimTradingConfig:
    return store.set_sim_config(payload)


@app.get("/api/sim/portfolio", response_model=PortfolioSnapshot)
def get_portfolio() -> PortfolioSnapshot:
    return store.get_portfolio()


@app.get("/api/review/stats", response_model=ReviewResponse)
def get_review_stats(
    date_from: str | None = Query(default=None, min_length=10, max_length=10),
    date_to: str | None = Query(default=None, min_length=10, max_length=10),
    date_axis: Literal["sell", "buy"] = Query(default="sell"),
) -> ReviewResponse:
    return store.get_review(date_from=date_from, date_to=date_to, date_axis=date_axis)


@app.get("/api/market/news", response_model=MarketNewsResponse)
def get_market_news(
    query: str = Query(default="", min_length=0, max_length=120),
    symbol: str | None = Query(default=None, min_length=0, max_length=16),
    source_domains: str | None = Query(default=None, min_length=0, max_length=300),
    age_hours: int = Query(default=72, ge=1, le=240, description="支持 24/48/72，其他值会回退到 72"),
    refresh: bool = Query(default=False, description="true 时跳过短缓存，强制拉取最新资讯"),
    limit: int = Query(default=20, ge=1, le=50),
) -> MarketNewsResponse:
    domains: list[str] = []
    if source_domains:
        raw_tokens = source_domains.replace(";", ",").replace("|", ",")
        domains = [token.strip() for token in raw_tokens.split(",") if token.strip()]
    return store.get_market_news(
        query=query,
        symbol=symbol,
        source_domains=domains,
        age_hours=age_hours,
        refresh=refresh,
        limit=limit,
    )


@app.get("/api/review/daily", response_model=DailyReviewListResponse)
def get_daily_reviews(
    date_from: str | None = Query(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> DailyReviewListResponse:
    return store.list_daily_reviews(date_from=date_from, date_to=date_to)


@app.get("/api/review/daily/{date}", response_model=DailyReviewRecord)
def get_daily_review(date: str = Path(pattern=r"^\d{4}-\d{2}-\d{2}$")) -> DailyReviewRecord | JSONResponse:
    row = store.get_daily_review(date)
    if row is None:
        return error_response(404, "REVIEW_DAILY_NOT_FOUND", "日复盘不存在")
    return row


@app.put("/api/review/daily/{date}", response_model=DailyReviewRecord)
def put_daily_review(
    payload: DailyReviewPayload,
    date: str = Path(pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> DailyReviewRecord:
    return store.upsert_daily_review(date, payload)


@app.delete("/api/review/daily/{date}")
def delete_daily_review(date: str = Path(pattern=r"^\d{4}-\d{2}-\d{2}$")) -> dict[str, bool]:
    return {"deleted": store.delete_daily_review(date)}


@app.get("/api/review/weekly", response_model=WeeklyReviewListResponse)
def get_weekly_reviews(year: int | None = Query(default=None, ge=2000, le=2100)) -> WeeklyReviewListResponse:
    return store.list_weekly_reviews(year=year)


@app.get("/api/review/weekly/{week_label}", response_model=WeeklyReviewRecord)
def get_weekly_review(week_label: str = Path(pattern=r"^\d{4}-W\d{2}$")) -> WeeklyReviewRecord | JSONResponse:
    row = store.get_weekly_review(week_label)
    if row is None:
        return error_response(404, "REVIEW_WEEKLY_NOT_FOUND", "周复盘不存在")
    return row


@app.put("/api/review/weekly/{week_label}", response_model=WeeklyReviewRecord)
def put_weekly_review(
    payload: WeeklyReviewPayload,
    week_label: str = Path(pattern=r"^\d{4}-W\d{2}$"),
) -> WeeklyReviewRecord | JSONResponse:
    try:
        return store.upsert_weekly_review(week_label, payload)
    except ValueError as exc:
        return error_response(400, "REVIEW_WEEKLY_INVALID", str(exc))


@app.delete("/api/review/weekly/{week_label}")
def delete_weekly_review(week_label: str = Path(pattern=r"^\d{4}-W\d{2}$")) -> dict[str, bool]:
    return {"deleted": store.delete_weekly_review(week_label)}


@app.get("/api/review/tags", response_model=ReviewTagsPayload)
def get_review_tags() -> ReviewTagsPayload:
    return store.get_review_tags()


@app.post("/api/review/tags/{tag_type}", response_model=ReviewTag)
def post_review_tag(tag_type: ReviewTagType, payload: ReviewTagCreateRequest) -> ReviewTag | JSONResponse:
    try:
        return store.create_review_tag(tag_type, payload)
    except ValueError as exc:
        return error_response(400, "REVIEW_TAG_INVALID", str(exc))


@app.delete("/api/review/tags/{tag_type}/{tag_id}")
def delete_review_tag(
    tag_type: ReviewTagType,
    tag_id: str = Path(min_length=3, max_length=64),
) -> dict[str, bool]:
    return {"deleted": store.delete_review_tag(tag_type, tag_id)}


@app.get("/api/review/fill-tags", response_model=list[TradeFillTagAssignment])
def get_fill_tag_assignments() -> list[TradeFillTagAssignment]:
    return store.list_fill_tag_assignments()


@app.get("/api/review/fill-tags/{order_id}", response_model=TradeFillTagAssignment)
def get_fill_tag_assignment(order_id: str = Path(min_length=8, max_length=64)) -> TradeFillTagAssignment | JSONResponse:
    row = store.get_fill_tag_assignment(order_id)
    if row is None:
        return error_response(404, "REVIEW_FILL_TAG_NOT_FOUND", "成交标签不存在")
    return row


@app.put("/api/review/fill-tags/{order_id}", response_model=TradeFillTagAssignment)
def put_fill_tag_assignment(
    payload: TradeFillTagUpdateRequest,
    order_id: str = Path(min_length=8, max_length=64),
) -> TradeFillTagAssignment | JSONResponse:
    try:
        return store.set_fill_tag_assignment(order_id, payload)
    except ValueError as exc:
        return error_response(400, "REVIEW_FILL_TAG_INVALID", str(exc))


@app.get("/api/review/tag-stats", response_model=ReviewTagStatsResponse)
def get_review_tag_stats(
    date_from: str | None = Query(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, min_length=10, max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> ReviewTagStatsResponse:
    return store.get_review_tag_stats(date_from=date_from, date_to=date_to)


@app.get("/api/ai/records", response_model=AIRecordsResponse)
def get_ai_records() -> AIRecordsResponse:
    return AIRecordsResponse(items=store.get_ai_records())


@app.post("/api/stocks/{symbol}/ai-analyze", response_model=AIAnalysisRecord)
def post_stock_ai_analyze(symbol: str) -> AIAnalysisRecord:
    return store.analyze_stock_with_ai(symbol)


@app.get("/api/stocks/{symbol}/ai-prompt-preview")
def get_stock_ai_prompt_preview(symbol: str) -> dict[str, object]:
    return store.get_ai_prompt_preview(symbol)


@app.delete("/api/ai/records", response_model=DeleteAIRecordResponse)
def delete_ai_record(
    symbol: str = Query(min_length=2),
    fetched_at: str = Query(min_length=10),
    provider: str | None = Query(default=None),
) -> DeleteAIRecordResponse:
    deleted = store.delete_ai_record(symbol=symbol, fetched_at=fetched_at, provider=provider)
    return DeleteAIRecordResponse(deleted=deleted, remaining=len(store.get_ai_records()))


@app.post("/api/ai/providers/test", response_model=AIProviderTestResponse)
def post_ai_provider_test(payload: AIProviderTestRequest) -> AIProviderTestResponse:
    return store.test_ai_provider(
        payload.provider,
        fallback_api_key=payload.fallback_api_key,
        fallback_api_key_path=payload.fallback_api_key_path,
        timeout_sec=payload.timeout_sec,
    )


@app.get("/api/config", response_model=AppConfig)
def get_config() -> AppConfig:
    return store.get_config()


@app.put("/api/config", response_model=AppConfig)
def put_config(payload: AppConfig) -> AppConfig:
    return store.set_config(payload)


@app.get("/api/system/storage", response_model=SystemStorageStatus)
def get_system_storage() -> SystemStorageStatus:
    return store.get_system_storage_status()


@app.get("/api/system/wyckoff-event-store/stats", response_model=WyckoffEventStoreStatsResponse)
def get_wyckoff_event_store_stats() -> WyckoffEventStoreStatsResponse:
    return store.get_wyckoff_event_store_stats()


@app.post("/api/system/wyckoff-event-store/backfill", response_model=WyckoffEventStoreBackfillResponse)
def post_wyckoff_event_store_backfill(
    payload: WyckoffEventStoreBackfillRequest,
) -> WyckoffEventStoreBackfillResponse | JSONResponse:
    try:
        return store.backfill_wyckoff_event_store(payload)
    except ValueError as exc:
        return error_response(400, "WYCKOFF_BACKFILL_INVALID", str(exc))


@app.post("/api/system/sync-market-data", response_model=MarketDataSyncResponse)
def post_sync_market_data(payload: MarketDataSyncRequest) -> MarketDataSyncResponse:
    return store.sync_market_data(payload)
