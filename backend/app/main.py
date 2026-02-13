from __future__ import annotations

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .models import (
    AIAnalysisRecord,
    AIProviderTestRequest,
    AIProviderTestResponse,
    AIRecordsResponse,
    AnnotationUpdateResponse,
    ApiErrorPayload,
    AppConfig,
    CreateOrderRequest,
    CreateOrderResponse,
    DeleteAIRecordResponse,
    IntradayPayload,
    PortfolioSnapshot,
    ReviewResponse,
    ScreenerParams,
    ScreenerRunDetail,
    ScreenerRunResponse,
    SignalsResponse,
    StockAnalysisResponse,
    StockAnnotation,
)
from .store import store

app = FastAPI(title="TDX Trend Screener API", version="0.1.0")

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
def get_signals() -> SignalsResponse:
    return SignalsResponse(items=store.get_signals())


@app.post("/api/sim/orders", response_model=CreateOrderResponse)
def post_order(payload: CreateOrderRequest) -> CreateOrderResponse:
    return store.create_order(payload)


@app.get("/api/sim/portfolio", response_model=PortfolioSnapshot)
def get_portfolio() -> PortfolioSnapshot:
    return store.get_portfolio()


@app.get("/api/review/stats", response_model=ReviewResponse)
def get_review_stats() -> ReviewResponse:
    return store.get_review()


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
