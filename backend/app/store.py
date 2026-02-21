from __future__ import annotations

import math
import hashlib
import json
import os
import random
import re
import time
import html
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from itertools import product
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable, Literal
from urllib.parse import urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx
import numpy as np

from .models import (
    AIAnalysisRecord,
    AIProviderTestResponse,
    AISourceConfig,
    AIProviderConfig,
    AppConfig,
    CandlePoint,
    BacktestRunRequest,
    BacktestPlateauRunRequest,
    BacktestPlateauResponse,
    BacktestPlateauPoint,
    BacktestPlateauParams,
    BacktestPoolRollMode,
    BacktestResponse,
    BacktestTaskProgress,
    BacktestTaskStageTiming,
    BacktestTaskStatusResponse,
    BoardFilter,
    Market,
    CreateOrderRequest,
    CreateOrderResponse,
    IntradayPayload,
    IntradayPoint,
    MarketDataSyncRequest,
    MarketDataSyncResponse,
    MarketNewsItem,
    MarketNewsResponse,
    PortfolioPosition,
    PortfolioSnapshot,
    ReviewResponse,
    ReviewStats,
    ReviewTag,
    ReviewTagCreateRequest,
    ReviewTagStatItem,
    ReviewTagStatsResponse,
    ReviewTagsPayload,
    ReviewTagType,
    ScreenerMode,
    ScreenerParams,
    ScreenerResult,
    ScreenerRunDetail,
    ScreenerStepPools,
    ScreenerStepSummary,
    SignalScanMode,
    SignalResult,
    SignalsResponse,
    TrendPoolStep,
    SystemStorageStatus,
    SimFillsResponse,
    SimOrdersResponse,
    SimResetResponse,
    SimSettleResponse,
    SimTradeFill,
    SimTradeOrder,
    SimTradingConfig,
    Stage,
    DailyReviewListResponse,
    DailyReviewPayload,
    DailyReviewRecord,
    StockAnalysis,
    StockAnalysisResponse,
    StockAnnotation,
    TradeFillTagAssignment,
    TradeFillTagUpdateRequest,
    ThemeStage,
    TradeRecord,
    TrendClass,
    WeeklyReviewListResponse,
    WeeklyReviewPayload,
    WeeklyReviewRecord,
    WyckoffEventStoreBackfillRequest,
    WyckoffEventStoreBackfillResponse,
    WyckoffEventStoreStatsResponse,
)
from .market_data_sync import sync_baostock_daily
from .sim_engine import SimAccountEngine
from .tdx_loader import (
    load_candles_for_symbol,
    load_input_pool_from_tdx,
    load_intraday_for_symbol_date,
)

# Import refactored modules
from .utils.text_utils import TextProcessor, URLUtils
from .core.signal_analyzer import SignalAnalyzer, WYCKOFF_ACC_EVENTS, WYCKOFF_RISK_EVENTS, WYCKOFF_EVENT_ORDER
from .core.ai_analyzer import AIAnalyzer, create_ai_analyzer
from .core.backtest_engine import BacktestEngine
from .core.backtest_matrix_engine import BacktestMatrixEngine, MatrixBundle
from .core.backtest_signal_matrix import BacktestSignalMatrix, compute_backtest_signal_matrix
from .core.wyckoff_event_store import WyckoffEventStore, build_wyckoff_params_hash
from .core.screener import ScreenerEngine, create_screener_engine, THEME_STAGES
from .core.candle_analyzer import CandleAnalyzer, create_candle_analyzer
from .providers.web_provider import RSSWebEvidenceProvider, SearchWebEvidenceProvider
from .config import ConfigManager, create_config_manager, ConfigValidator
from .state_manager import StateManager, create_state_manager

STOCK_POOL: list[dict[str, str]] = [
    {"symbol": "sh600519", "name": "贵州茅台", "trend": "A", "stage": "Mid"},
    {"symbol": "sz300750", "name": "宁德时代", "trend": "A_B", "stage": "Early"},
    {"symbol": "sh601899", "name": "紫金矿业", "trend": "A", "stage": "Mid"},
    {"symbol": "sz002594", "name": "比亚迪", "trend": "A_B", "stage": "Mid"},
    {"symbol": "sh600030", "name": "中信证券", "trend": "A", "stage": "Early"},
    {"symbol": "sz000333", "name": "美的集团", "trend": "A", "stage": "Late"},
    {"symbol": "sh688041", "name": "海光信息", "trend": "B", "stage": "Late"},
    {"symbol": "sz002230", "name": "科大讯飞", "trend": "A_B", "stage": "Mid"},
]



class BacktestValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "BACKTEST_INVALID")


class BacktestTaskCancelledError(RuntimeError):
    pass


class InMemoryStore:
    _APP_STATE_SCHEMA_VERSION = 2
    _FULL_MARKET_SYSTEM_PROTECT_LIMIT = 6000
    _BACKTEST_INPUT_POOL_CACHE_VERSION = "input-pool-v1"
    _SCREENER_RESULT_CACHE_VERSION = "screener-run-v1"
    _SIGNALS_RESULT_CACHE_VERSION = "signals-v1"
    _BACKTEST_TREND_FILTER_CACHE_VERSION = "trend-filter-v1"
    _BACKTEST_RESULT_CACHE_VERSION = "backtest-result-v1"
    _BACKTEST_SIGNAL_MATRIX_CACHE_VERSION = "signal-matrix-v1"
    _BACKTEST_PRECHECK_CACHE_VERSION = "precheck-v1"
    _BACKTEST_MATRIX_TIMING_RE = re.compile(
        r"耗时\[建矩阵=(?P<matrix>[\d.]+)s,\s*算信号=(?P<signal>[\d.]+)s,\s*撮合=(?P<match>[\d.]+)s,\s*总计=(?P<total>[\d.]+)s\]"
    )

    def __init__(self, app_state_path: str | None = None, sim_state_path: str | None = None) -> None:
        self._lock = RLock()
        self._candles_map: dict[str, list[CandlePoint]] = {}
        self._run_store: dict[str, ScreenerRunDetail] = {}
        self._annotation_store: dict[str, StockAnnotation] = {}
        self._config: AppConfig = self._default_config()
        self._latest_rows: dict[str, ScreenerResult] = {}
        self._ai_record_store: list[AIAnalysisRecord] = self._default_ai_records()
        self._daily_review_store: dict[str, DailyReviewRecord] = {}
        self._weekly_review_store: dict[str, WeeklyReviewRecord] = {}
        self._review_tags: dict[ReviewTagType, list[ReviewTag]] = self._default_review_tags()
        self._fill_tag_store: dict[str, TradeFillTagAssignment] = {}
        self._web_evidence_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._market_news_last_success: tuple[float, list[dict[str, str]], dict[str, str]] | None = None
        self._quote_profile_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._signals_cache: dict[str, tuple[float, SignalsResponse]] = {}
        self._backtest_tasks: dict[str, BacktestTaskStatusResponse] = {}
        self._backtest_task_payloads: dict[str, BacktestRunRequest] = {}
        self._backtest_task_lock = RLock()
        self._backtest_running_worker_ids: set[str] = set()
        self._backtest_task_state_path = self._resolve_backtest_task_state_path()
        self._backtest_task_state_last_persist_at = 0.0
        self._backtest_matrix_engine = BacktestMatrixEngine()
        self._backtest_matrix_algo_version = os.getenv("TDX_TREND_BACKTEST_MATRIX_ALGO_VERSION", "").strip() or "matrix-v1"
        self._backtest_signal_matrix_runtime_cache: dict[str, tuple[float, BacktestSignalMatrix]] = {}
        self._backtest_signal_matrix_runtime_cache_lock = RLock()
        self._backtest_input_pool_runtime_cache: dict[str, tuple[float, list[ScreenerResult], str | None]] = {}
        self._backtest_input_pool_runtime_cache_lock = RLock()
        self._backtest_precheck_cache: dict[str, tuple[float, str | None, str | None]] = {}
        self._backtest_precheck_cache_lock = RLock()
        self._wyckoff_event_store_enabled = self._env_flag("TDX_TREND_WYCKOFF_STORE_ENABLED", True)
        self._wyckoff_event_store_read_only = self._env_flag("TDX_TREND_WYCKOFF_STORE_READ_ONLY", False)
        self._wyckoff_event_algo_version = os.getenv("TDX_TREND_WYCKOFF_ALGO_VERSION", "").strip() or "wyckoff-v1"
        self._wyckoff_event_data_version = os.getenv("TDX_TREND_WYCKOFF_DATA_VERSION", "").strip() or "default"
        self._wyckoff_event_store = WyckoffEventStore(
            self._resolve_wyckoff_event_store_path(),
            enabled=self._wyckoff_event_store_enabled,
            read_only=self._wyckoff_event_store_read_only,
        )
        self._wyckoff_metrics_lock = RLock()
        self._wyckoff_metrics: dict[str, object] = {
            "cache_hits": 0,
            "cache_misses": 0,
            "snapshot_reads": 0,
            "snapshot_read_ms_total": 0.0,
            "lazy_fill_writes": 0,
            "backfill_runs": 0,
            "backfill_writes": 0,
            "quality_empty_events": 0,
            "quality_score_outliers": 0,
            "quality_date_misaligned": 0,
            "last_backfill_started_at": None,
            "last_backfill_finished_at": None,
            "last_backfill_duration_sec": None,
            "last_backfill_scan_dates": 0,
            "last_backfill_symbols": 0,
            "last_backfill_quality_empty_events": 0,
            "last_backfill_quality_score_outliers": 0,
            "last_backfill_quality_date_misaligned": 0,
        }
        self._app_state_path = self._resolve_app_state_path(app_state_path)
        self._load_or_init_app_state()
        self._sim_engine = SimAccountEngine(
            get_candles=self._ensure_candles,
            resolve_symbol_name=self._resolve_symbol_name,
            now_date=self._now_date,
            now_datetime=self._now_datetime,
            state_path=sim_state_path or os.getenv("TDX_TREND_SIM_STATE_PATH", "").strip() or None,
        )
        self._load_backtest_task_state()
        self._resume_backtest_tasks_after_boot()

    @staticmethod
    def _resolve_user_path(value: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(str(value).strip()))
        return Path(expanded)

    @staticmethod
    def _env_flag(name: str, default: bool) -> bool:
        raw = os.getenv(name, "").strip().lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "y", "on"}:
            return True
        if raw in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @classmethod
    def _resolve_app_state_path(cls, app_state_path: str | None = None) -> Path:
        if app_state_path and str(app_state_path).strip():
            return cls._resolve_user_path(app_state_path)
        env_value = os.getenv("TDX_TREND_APP_STATE_PATH", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "app_state.json"

    @classmethod
    def _resolve_wyckoff_event_store_path(cls) -> Path:
        env_value = os.getenv("TDX_TREND_WYCKOFF_STORE_PATH", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "wyckoff_events.sqlite"

    @classmethod
    def _resolve_backtest_task_state_path(cls) -> Path:
        env_value = os.getenv("TDX_TREND_BACKTEST_TASK_STATE_PATH", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "backtest_tasks.json"

    @classmethod
    def _resolve_backtest_input_pool_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_BACKTEST_INPUT_POOL_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "backtest-input-cache"

    @classmethod
    def _resolve_screener_result_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_SCREENER_RESULT_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "screener-result-cache"

    @classmethod
    def _resolve_signals_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_SIGNALS_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "signals-cache"

    @classmethod
    def _resolve_backtest_trend_filter_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_BACKTEST_TREND_FILTER_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "backtest-trend-filter-cache"

    @classmethod
    def _resolve_backtest_result_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_BACKTEST_RESULT_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "backtest-result-cache"

    @classmethod
    def _resolve_backtest_signal_matrix_cache_dir(cls) -> Path:
        env_value = os.getenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_CACHE_DIR", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "backtest-signal-matrix-cache"

    def _build_app_state_payload(self) -> dict[str, object]:
        return {
            "schema_version": self._APP_STATE_SCHEMA_VERSION,
            "config": self._config.model_dump(),
            "ai_records": [item.model_dump() for item in self._ai_record_store],
            "annotations": {symbol: item.model_dump() for symbol, item in self._annotation_store.items()},
            "daily_reviews": {day: item.model_dump() for day, item in self._daily_review_store.items()},
            "weekly_reviews": {week: item.model_dump() for week, item in self._weekly_review_store.items()},
            "review_tags": {
                "emotion": [item.model_dump() for item in self._review_tags.get("emotion", [])],
                "reason": [item.model_dump() for item in self._review_tags.get("reason", [])],
            },
            "fill_tags": {order_id: item.model_dump() for order_id, item in self._fill_tag_store.items()},
            "audit": {
                "updated_at": self._now_datetime(),
            },
        }

    def _write_app_state_payload(self, payload: dict[str, object]) -> None:
        self._app_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._app_state_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._app_state_path)

    def _persist_app_state(self) -> None:
        try:
            self._write_app_state_payload(self._build_app_state_payload())
        except Exception:
            # Keep runtime available even if local persistence failed.
            pass

    def _load_or_init_app_state(self) -> None:
        if not self._app_state_path.exists():
            self._persist_app_state()
            return
        try:
            raw = json.loads(self._app_state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("invalid app state payload")
            default_config = self._default_config()
            config_raw = raw.get("config")
            if isinstance(config_raw, dict):
                merged = {**default_config.model_dump(), **config_raw}
                self._config = AppConfig(**merged)
            annotations_raw = raw.get("annotations")
            if isinstance(annotations_raw, dict):
                restored_annotations: dict[str, StockAnnotation] = {}
                for symbol, item in annotations_raw.items():
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored_annotations[str(symbol)] = StockAnnotation(**item)
                    except Exception:
                        continue
                self._annotation_store = restored_annotations
            ai_records_raw = raw.get("ai_records")
            if isinstance(ai_records_raw, list):
                restored_records: list[AIAnalysisRecord] = []
                for item in ai_records_raw:
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored_records.append(AIAnalysisRecord(**item))
                    except Exception:
                        continue
                self._ai_record_store = restored_records
            daily_reviews_raw = raw.get("daily_reviews")
            if isinstance(daily_reviews_raw, dict):
                restored_daily: dict[str, DailyReviewRecord] = {}
                for day, item in daily_reviews_raw.items():
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored_daily[str(day)] = DailyReviewRecord(**item)
                    except Exception:
                        continue
                self._daily_review_store = restored_daily
            weekly_reviews_raw = raw.get("weekly_reviews")
            if isinstance(weekly_reviews_raw, dict):
                restored_weekly: dict[str, WeeklyReviewRecord] = {}
                for week, item in weekly_reviews_raw.items():
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored_weekly[str(week)] = WeeklyReviewRecord(**item)
                    except Exception:
                        continue
                self._weekly_review_store = restored_weekly
            review_tags_raw = raw.get("review_tags")
            if isinstance(review_tags_raw, dict):
                merged_tags = self._default_review_tags()
                for tag_type in ("emotion", "reason"):
                    values = review_tags_raw.get(tag_type)
                    if not isinstance(values, list):
                        continue
                    restored_tags: list[ReviewTag] = []
                    for item in values:
                        if not isinstance(item, dict):
                            continue
                        try:
                            restored_tags.append(ReviewTag(**item))
                        except Exception:
                            continue
                    if restored_tags:
                        merged_tags[tag_type] = restored_tags
                self._review_tags = merged_tags
            fill_tags_raw = raw.get("fill_tags")
            if isinstance(fill_tags_raw, dict):
                restored_fill_tags: dict[str, TradeFillTagAssignment] = {}
                for order_id, item in fill_tags_raw.items():
                    if not isinstance(item, dict):
                        continue
                    try:
                        restored_fill_tags[str(order_id)] = TradeFillTagAssignment(**item)
                    except Exception:
                        continue
                self._fill_tag_store = restored_fill_tags
            self._persist_app_state()
        except Exception:
            self._persist_app_state()

    @staticmethod
    def _default_config() -> AppConfig:
        return AppConfig(
            tdx_data_path=r"D:\new_tdx\vipdoc",
            market_data_source="tdx_then_akshare",
            akshare_cache_dir=str(Path.home() / ".tdx-trend" / "akshare" / "daily"),
            markets=["sh", "sz"],
            return_window_days=40,
            candles_window_bars=120,
            top_n=500,
            turnover_threshold=0.05,
            amount_threshold=5e8,
            amplitude_threshold=0.03,
            initial_capital=1_000_000,
            ai_provider="openai",
            ai_timeout_sec=10,
            ai_retry_count=2,
            api_key="",
            api_key_path=r"%USERPROFILE%\.tdx-trend\app.config.json",
            ai_providers=[
                AIProviderConfig(
                    id="openai",
                    label="OpenAI",
                    base_url="https://api.openai.com/v1",
                    model="gpt-4o-mini",
                    api_key="",
                    api_key_path=r"%USERPROFILE%\.tdx-trend\openai.key",
                    enabled=True,
                ),
                AIProviderConfig(
                    id="qwen",
                    label="Qwen",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    model="qwen-plus",
                    api_key="",
                    api_key_path=r"%USERPROFILE%\.tdx-trend\qwen.key",
                    enabled=True,
                ),
                AIProviderConfig(
                    id="deepseek",
                    label="DeepSeek",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-chat",
                    api_key="",
                    api_key_path=r"%USERPROFILE%\.tdx-trend\deepseek.key",
                    enabled=True,
                ),
                AIProviderConfig(
                    id="ernie",
                    label="ERNIE",
                    base_url="https://qianfan.baidubce.com/v2",
                    model="ernie-4.0-turbo",
                    api_key="",
                    api_key_path=r"%USERPROFILE%\.tdx-trend\ernie.key",
                    enabled=False,
                ),
                AIProviderConfig(
                    id="custom-1",
                    label="自定义Provider",
                    base_url="https://your-provider.example.com/v1",
                    model="custom-model",
                    api_key="",
                    api_key_path=r"%USERPROFILE%\.tdx-trend\custom.key",
                    enabled=False,
                ),
            ],
            ai_sources=[
                AISourceConfig(
                    id="eastmoney",
                    name="东方财富新闻",
                    url="https://finance.eastmoney.com/",
                    enabled=True,
                ),
                AISourceConfig(
                    id="juchao",
                    name="巨潮资讯",
                    url="http://www.cninfo.com.cn/",
                    enabled=True,
                ),
                AISourceConfig(id="cls", name="财联社", url="https://www.cls.cn/", enabled=True),
                AISourceConfig(id="xueqiu", name="雪球", url="https://xueqiu.com/", enabled=False),
            ],
        )

    @staticmethod
    def _now_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _now_datetime() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _bump_wyckoff_metric(self, key: str, delta: int = 1) -> None:
        with self._wyckoff_metrics_lock:
            current = int(self._wyckoff_metrics.get(key, 0) or 0)
            self._wyckoff_metrics[key] = current + int(delta)

    def _set_wyckoff_metric(self, key: str, value: object) -> None:
        with self._wyckoff_metrics_lock:
            self._wyckoff_metrics[key] = value

    def _snapshot_wyckoff_metrics(self) -> dict[str, object]:
        with self._wyckoff_metrics_lock:
            return dict(self._wyckoff_metrics)

    def _record_wyckoff_snapshot_read_latency(self, duration_ms: float) -> None:
        if not math.isfinite(duration_ms):
            return
        with self._wyckoff_metrics_lock:
            current_reads = int(self._wyckoff_metrics.get("snapshot_reads", 0) or 0)
            current_total = float(self._wyckoff_metrics.get("snapshot_read_ms_total", 0.0) or 0.0)
            self._wyckoff_metrics["snapshot_reads"] = current_reads + 1
            self._wyckoff_metrics["snapshot_read_ms_total"] = current_total + max(0.0, float(duration_ms))

    @staticmethod
    def _is_snapshot_score_outlier(raw: object) -> bool:
        try:
            value = float(raw)
        except Exception:
            return True
        if not math.isfinite(value):
            return True
        return (value < 0.0) or (value > 100.0)

    def _inspect_wyckoff_snapshot_quality(
        self,
        snapshot: dict[str, object],
        *,
        trade_date: str,
    ) -> dict[str, int]:
        has_event_rows = False
        has_chain_rows = False
        date_misaligned = 0

        events = snapshot.get("events")
        if isinstance(events, list):
            for item in events:
                if str(item).strip():
                    has_event_rows = True
                    break

        risk_events = snapshot.get("risk_events")
        if isinstance(risk_events, list):
            for item in risk_events:
                if str(item).strip():
                    has_event_rows = True
                    break

        event_chain = snapshot.get("event_chain")
        if isinstance(event_chain, list):
            for row in event_chain:
                if not isinstance(row, dict):
                    continue
                code_text = str(row.get("event", "")).strip()
                date_text = str(row.get("date", "")).strip()
                if not code_text:
                    continue
                has_chain_rows = True
                if not date_text:
                    date_misaligned = 1
                    break
                parsed = self._parse_date(date_text)
                if parsed is None:
                    date_misaligned = 1
                    break
                if trade_date and date_text > trade_date:
                    date_misaligned = 1
                    break

        event_dates = snapshot.get("event_dates")
        if isinstance(event_dates, dict):
            for raw_date in event_dates.values():
                date_text = str(raw_date).strip()
                if not date_text:
                    continue
                parsed = self._parse_date(date_text)
                if parsed is None:
                    date_misaligned = 1
                    break
                if trade_date and date_text > trade_date:
                    date_misaligned = 1
                    break

        score_fields = (
            "entry_quality_score",
            "event_strength_score",
            "phase_score",
            "structure_score",
            "trend_score",
            "volatility_score",
        )
        score_outlier = 0
        for field in score_fields:
            if self._is_snapshot_score_outlier(snapshot.get(field, 0.0)):
                score_outlier = 1
                break

        return {
            "empty_events": 0 if (has_event_rows or has_chain_rows) else 1,
            "score_outliers": score_outlier,
            "date_misaligned": date_misaligned,
        }

    def _record_wyckoff_snapshot_quality(self, quality_flags: dict[str, int]) -> None:
        empty_events = int(max(0, quality_flags.get("empty_events", 0)))
        score_outliers = int(max(0, quality_flags.get("score_outliers", 0)))
        date_misaligned = int(max(0, quality_flags.get("date_misaligned", 0)))
        if empty_events > 0:
            self._bump_wyckoff_metric("quality_empty_events", empty_events)
        if score_outliers > 0:
            self._bump_wyckoff_metric("quality_score_outliers", score_outliers)
        if date_misaligned > 0:
            self._bump_wyckoff_metric("quality_date_misaligned", date_misaligned)

    @staticmethod
    def _days_ago(days: int) -> str:
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    @staticmethod
    def _default_review_tags() -> dict[ReviewTagType, list[ReviewTag]]:
        created_at = "2026-01-01 00:00:00"
        emotion_rows = [
            ("emotion-01", "冲动追高", "red"),
            ("emotion-02", "恐慌割肉", "volcano"),
            ("emotion-03", "理性建仓", "blue"),
            ("emotion-04", "波段操作", "purple"),
            ("emotion-05", "止盈离场", "green"),
            ("emotion-06", "止损离场", "orange"),
        ]
        reason_rows = [
            ("reason-01", "财报利好", "geekblue"),
            ("reason-02", "政策利好", "magenta"),
            ("reason-03", "技术突破", "cyan"),
            ("reason-04", "板块轮动", "gold"),
            ("reason-05", "资金需求", "lime"),
            ("reason-06", "止损", "volcano"),
            ("reason-07", "止盈", "green"),
        ]
        return {
            "emotion": [
                ReviewTag(id=tag_id, name=name, color=color, created_at=created_at)
                for tag_id, name, color in emotion_rows
            ],
            "reason": [
                ReviewTag(id=tag_id, name=name, color=color, created_at=created_at)
                for tag_id, name, color in reason_rows
            ],
        }

    @staticmethod
    def _resolve_week_range(week_label: str) -> tuple[str, str]:
        match = re.match(r"^(\d{4})-W(\d{2})$", week_label)
        if not match:
            raise ValueError("week_label must be YYYY-Www")
        year = int(match.group(1))
        week = int(match.group(2))
        start = datetime.fromisocalendar(year, week, 1).strftime("%Y-%m-%d")
        end = datetime.fromisocalendar(year, week, 7).strftime("%Y-%m-%d")
        return start, end

    @staticmethod
    def _unique_ordered(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            token = str(value).strip()
            if not token or token in seen:
                continue
            seen.add(token)
            result.append(token)
        return result

    def _find_review_tag(self, tag_type: ReviewTagType, tag_id: str) -> ReviewTag | None:
        for item in self._review_tags.get(tag_type, []):
            if item.id == tag_id:
                return item
        return None

    @staticmethod
    def _hash_seed(text: str) -> int:
        return sum(ord(c) for c in text)

    def _default_ai_records(self) -> list[AIAnalysisRecord]:
        return [
            AIAnalysisRecord(
                provider="openai",
                symbol="sz300750",
                name="宁德时代",
                fetched_at=self._now_datetime(),
                source_urls=["https://example.com/news/ev-1", "https://example.com/forum/battery"],
                summary="板块热度持续，头部与补涨梯队完整。",
                conclusion="发酵中",
                confidence=0.78,
                breakout_date=self._days_ago(17),
                trend_bull_type="A_B 慢牛加速",
                theme_name="固态电池",
                rise_reasons=[
                    "近20日量能斜率为正，资金持续流入",
                    "回调缩量且未破关键均线",
                    "题材热度维持在发酵区间",
                ],
            ),
            AIAnalysisRecord(
                provider="openai",
                symbol="sh600519",
                name="贵州茅台",
                fetched_at=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                source_urls=["https://example.com/news/consumption"],
                summary="消费主线维持，成交稳定。",
                conclusion="高潮",
                confidence=0.66,
                breakout_date=self._days_ago(26),
                trend_bull_type="A 阶梯慢牛",
                theme_name="高端消费",
                rise_reasons=[
                    "龙头股资金抱团明显",
                    "高位换手可控，回撤幅度有限",
                    "行业基本面预期稳定",
                ],
            ),
        ]

    def _enabled_ai_source_urls(self, limit: int = 5) -> list[str]:
        urls = [item.url for item in self._config.ai_sources if item.enabled and item.url.strip()]
        return urls[:limit]

    def _source_domains(self, source_urls: list[str]) -> set[str]:
        """Extract source domains from URLs using URLUtils."""
        return URLUtils.source_domains(source_urls)

    @staticmethod
    def _url_in_domains(url: str, domains: set[str]) -> bool:
        """Check if URL is in allowed domains using URLUtils."""
        return URLUtils.url_in_domains(url, domains)

    @staticmethod
    def _is_low_quality_source(source_name: str, source_url: str) -> bool:
        """Check if source is low quality using TextProcessor."""
        return TextProcessor.is_low_quality_source(source_name, source_url)

    @staticmethod
    def _is_low_signal_title(title: str) -> bool:
        """Check if title has low signal value using TextProcessor."""
        return TextProcessor.is_low_signal_title(title)

    @staticmethod
    def _clean_event_text(text: str) -> str:
        """Clean event text with media filtering."""
        cleaned = TextProcessor.clean_whitespace(text)
        cleaned = re.sub(r"^\[[^\]]+\]\s*", "", cleaned)
        cleaned = re.sub(r"^(新闻线索|信息源摘要|来源)[:：]\s*", "", cleaned)
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        media = (
            "东方财富|财联社|巨潮资讯|同花顺|新浪财经|新浪网|证券时报|每日经济新闻|雪球|股吧|"
            "凤凰网|凤凰财经|SOHU|sohu|腾讯网|网易财经|和讯网|金融界"
        )
        cleaned = re.sub(rf"({media})\s*[|｜]", "", cleaned)
        cleaned = re.sub(rf"[（(]({media})[^)）]*[)）]", "", cleaned)
        cleaned = TextProcessor.clean_whitespace(cleaned)
        cleaned = re.sub(rf"\s*[-|｜]\s*({media})\s*$", "", cleaned)
        cleaned = re.sub(rf"\s*({media})\s*$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|｜")
        return cleaned[:96]

    @staticmethod
    def _clean_text(text: str) -> str:
        """Simple text cleaning without media filtering."""
        return TextProcessor.clean_whitespace(TextProcessor.strip_html_tags(text))

    @staticmethod
    def _normalize_rise_reasons(reasons: list[str]) -> list[str]:
        """Normalize and deduplicate rise reasons with keyword prioritization."""
        cleaned: list[str] = []
        seen: set[str] = set()
        high_signal_keywords = (
            "收购",
            "并购",
            "重组",
            "增资",
            "注入",
            "标的",
            "订单",
            "中标",
            "合同",
            "签约",
            "业绩",
            "预增",
            "利润",
            "扭亏",
            "政策",
            "涨价",
            "新品",
            "合作",
            "回购",
            "激励",
            "投产",
            "扩产",
            "停牌",
            "核查",
            "问询",
            "监管",
            "警示",
            "入主",
            "景气",
            "需求",
            "供给",
            "回暖",
            "复苏",
            "资金",
        )
        for item in reasons:
            value = InMemoryStore._clean_event_text(item)
            if not value:
                continue
            lowered = value.lower()
            if value in seen:
                continue
            seen.add(value)
            cleaned.append(value)

        prioritized = [item for item in cleaned if any(keyword in item.lower() for keyword in high_signal_keywords)]
        if prioritized:
            return prioritized[:4]
        return cleaned[:4]

    @staticmethod
    def _extract_code_tokens(text: str) -> set[str]:
        """Extract stock code tokens from text."""
        return TextProcessor.extract_code_tokens(text)

    @staticmethod
    def _truncate_reason(text: str, max_len: int = 26) -> str:
        """Truncate text to max length, preserving word boundaries."""
        return TextProcessor.truncate_reason(text, max_len)

    @staticmethod
    def _extract_industry_label(industry_event_candidates: list[str] | None) -> str:
        for item in industry_event_candidates or []:
            text = InMemoryStore._clean_event_text(item)
            match = re.search(r"行业驱动[:：]?\s*([^\s，。；;]{2,12}?)(?:板块|行业)", text)
            if match:
                return match.group(1).strip()
            match = re.search(r"([^\s，。；;]{2,12}?)(?:板块|行业)", text)
            if match:
                return match.group(1).strip()
        return ""

    def _compact_reason_by_keywords(
        self,
        text: str,
        *,
        industry_mode: bool = False,
        industry_label: str = "",
    ) -> str | None:
        raw = self._clean_event_text(text)
        if not raw:
            return None

        # Remove long quoted headline fragments and trailing source-like tails.
        raw = re.sub(r"[“\"].{8,48}?[”\"]", "", raw)
        raw = re.sub(r"\s*[-|｜:：]\s*(财联社|东方财富|同花顺|新浪|证券时报|每日经济新闻).*$", "", raw)
        raw = TextProcessor.clean_whitespace(raw).strip("。；;，, ")
        if not raw:
            return None

        bucket = industry_label or "相关行业"

        if any(word in raw for word in ("收购", "并购", "重组", "拟购", "资产注入", "入主")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}并购重组预期升温"
            )
        if any(word in raw for word in ("订单", "中标", "合同", "签约")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}订单与项目预期改善"
            )
        if any(word in raw for word in ("业绩", "预增", "利润", "扭亏")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}业绩改善预期强化"
            )
        if any(word in raw for word in ("政策", "补贴", "规划", "支持", "国补", "降准", "降息")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}政策催化提升景气"
            )
        if any(word in raw for word in ("涨价", "提价")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}价格上行带动预期"
            )
        if any(word in raw for word in ("出海", "海外", "出口")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}海外需求扩张"
            )
        if any(word in raw for word in ("算力", "AI", "人工智能")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}AI需求拉动景气"
            )
        if any(word in raw for word in ("扩产", "投产", "产能")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}产能扩张预期增强"
            )
        if any(word in raw for word in ("景气", "需求", "回暖", "复苏", "供给")):
            return self._truncate_reason(
                f"{'行业驱动：' if industry_mode else ''}{bucket if industry_mode else ''}景气与需求回暖"
            )

        if industry_mode:
            return self._truncate_reason(f"行业驱动：{bucket}板块资金共振")
        if len(raw) < 8:
            return None
        return self._truncate_reason(raw)

    def _sanitize_ai_rise_reasons(
        self,
        reasons: list[str],
        *,
        symbol: str,
        core_event_candidates: list[str] | None = None,
        industry_event_candidates: list[str] | None = None,
        industry_hint: str = "",
    ) -> list[str]:
        symbol_code = symbol.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        industry_label = self._extract_industry_label(industry_event_candidates) or TextProcessor.clean_whitespace(industry_hint)
        combined: list[str] = []
        if core_event_candidates:
            combined.extend(core_event_candidates)
        if industry_event_candidates:
            combined.extend(industry_event_candidates)
        combined.extend(reasons)

        filtered: list[str] = []
        event_keywords = (
            "收购",
            "并购",
            "重组",
            "拟购",
            "增资",
            "注入",
            "标的",
            "订单",
            "中标",
            "合同",
            "签约",
            "业绩",
            "预增",
            "利润",
            "扭亏",
            "政策",
            "涨价",
            "新品",
            "合作",
            "回购",
            "激励",
            "投产",
            "扩产",
            "停牌",
            "核查",
            "问询",
            "监管",
            "警示",
            "入主",
            "景气",
            "需求",
            "供给",
            "回暖",
            "复苏",
            "资金",
        )
        banned_phrases = (
            "强势涨停",
            "果断上车",
            "上车",
            "主升浪",
            "牛股",
            "龙头",
            "看多",
            "建议关注",
            "跟随",
            "股价连涨",
            "恐难支撑",
            "压力位",
            "支撑位",
            "摇摇欲坠",
            "引爆股价",
        )

        if (not core_event_candidates) and industry_event_candidates:
            industry_normalized = self._normalize_rise_reasons(industry_event_candidates)
            industry_event_only = [item for item in industry_normalized if any(keyword in item for keyword in event_keywords)]
            if industry_event_only:
                tagged: list[str] = []
                for item in industry_event_only[:2]:
                    compact = self._compact_reason_by_keywords(
                        item,
                        industry_mode=True,
                        industry_label=industry_label,
                    )
                    if compact:
                        tagged.append(compact)
                if tagged:
                    return list(dict.fromkeys(tagged))

        for item in combined:
            for piece in re.split(r"[；;。]\s*", str(item)):
                text = self._clean_event_text(piece)
                if not text:
                    continue
                if self._is_low_signal_title(text):
                    continue
                if any(phrase in text for phrase in banned_phrases):
                    continue
                codes = self._extract_code_tokens(text)
                if codes and any(code != symbol_code for code in codes):
                    continue
                if len(text) < 6:
                    continue
                if text.count("、") >= 2 and not any(k in text for k in ("收购", "并购", "重组", "订单", "中标", "业绩", "预增")):
                    continue
                is_industry_text = text.startswith("行业驱动：") or any(
                    self._clean_event_text(candidate) in text or text in self._clean_event_text(candidate)
                    for candidate in (industry_event_candidates or [])
                )
                compact = self._compact_reason_by_keywords(
                    text,
                    industry_mode=is_industry_text,
                    industry_label=industry_label,
                )
                if compact:
                    filtered.append(compact)

        normalized = self._normalize_rise_reasons(filtered)
        event_only = [item for item in normalized if any(keyword in item for keyword in event_keywords)]
        if event_only:
            concise = [
                self._compact_reason_by_keywords(
                    item,
                    industry_mode=item.startswith("行业驱动："),
                    industry_label=industry_label,
                )
                for item in event_only[:4]
            ]
            return [item for item in concise if item]

        core_normalized = self._normalize_rise_reasons(core_event_candidates or [])
        core_event_only = [item for item in core_normalized if any(keyword in item for keyword in event_keywords)]
        if core_event_only:
            concise = [
                self._compact_reason_by_keywords(item, industry_mode=False, industry_label=industry_label)
                for item in core_event_only[:4]
            ]
            return [item for item in concise if item]

        industry_normalized = self._normalize_rise_reasons(industry_event_candidates or [])
        industry_event_only = [item for item in industry_normalized if any(keyword in item for keyword in event_keywords)]
        if industry_event_only:
            tagged: list[str] = []
            for item in industry_event_only[:2]:
                compact = self._compact_reason_by_keywords(
                    item,
                    industry_mode=True,
                    industry_label=industry_label,
                )
                if compact:
                    tagged.append(compact)
            if tagged:
                return list(dict.fromkeys(tagged))
        return []

    def _sanitize_theme_name(
        self,
        theme_name: str,
        *,
        evidence: list[dict[str, str]],
        inferred_sector: str,
    ) -> str:
        value = TextProcessor.clean_whitespace(theme_name)
        generic = {"", "Unknown", "未知题材", "潜在热点", "主线热点"}
        if value in generic:
            inferred_theme = self._infer_theme_from_web_evidence(evidence)
            if inferred_theme != "Unknown":
                return inferred_theme
            return inferred_sector if inferred_sector != "Unknown" else "Unknown"

        corpus = " ".join(
            f"{item.get('title', '')} {item.get('snippet', '')}" for item in evidence
        )
        if value not in corpus and inferred_sector != "Unknown":
            inferred_theme = self._infer_theme_from_web_evidence(evidence)
            if inferred_theme != "Unknown":
                return inferred_theme
            return inferred_sector
        return value

    def _build_compact_ai_summary(
        self,
        *,
        symbol: str,
        breakout_date: str | None,
        board_label: str,
        inferred_sector: str,
        rise_reasons: list[str],
        raw_summary: str,
        row: ScreenerResult | None = None,
    ) -> str:
        lead = rise_reasons[0].rstrip("。；; ") if rise_reasons else ""
        summary = self._clean_event_text(raw_summary)
        extras: list[str] = []
        if summary and lead and summary != lead:
            first = re.split(r"[。；;]", summary)[0].strip()
            if first and first != lead and len(first) >= 8 and (lead not in first and first not in lead) and "核心催化" not in first:
                extras.append(first[:36].rstrip("。；; "))
        head = f"{lead}。" if lead.startswith("行业驱动：") else (f"核心催化：{lead}。" if lead else "")
        sector_text = inferred_sector if inferred_sector and inferred_sector != "Unknown" else "待确认"
        body = f"板块={board_label}，行业={sector_text}。"
        tail = f"补充：{extras[0]}。" if extras else ""
        quant = ""
        candles = self._ensure_candles(symbol)
        if candles:
            aligned_breakout = self._align_date_to_candles(candles, breakout_date or candles[-1].time)
            index_by_date = {item.time: idx for idx, item in enumerate(candles)}
            start_idx = index_by_date.get(aligned_breakout, len(candles) - 1)
            start_idx = max(0, min(start_idx, len(candles) - 1))
            start_close = max(0.01, candles[start_idx].close)
            latest_close = candles[-1].close
            high_slice = [item.high for item in candles[start_idx:]]
            peak_rel = max(range(len(high_slice)), key=lambda i: high_slice[i]) if high_slice else 0
            peak_idx = start_idx + peak_rel
            peak_high = max(0.01, candles[peak_idx].high)
            peak_date = candles[peak_idx].time

            rise_to_peak = (peak_high - start_close) / start_close
            current_vs_breakout = (latest_close - start_close) / start_close
            pullback_from_peak = max(0.0, (peak_high - latest_close) / peak_high)
            in_pullback = peak_idx < len(candles) - 1 and pullback_from_peak >= 0.015

            quant = (
                f"量化：起爆{aligned_breakout}→高点{peak_date}涨幅{rise_to_peak * 100:.2f}%，"
                f"当前较起爆{current_vs_breakout * 100:.2f}%，"
                f"{'高点回撤' + format(pullback_from_peak * 100, '.2f') + '%。' if in_pullback else '尚未明显回撤。'}"
            )
            latest_date = candles[-1].time
            latest_idx = len(candles) - 1
            idx_5 = max(0, latest_idx - 5)
            idx_10 = max(0, latest_idx - 10)
            base_close_5 = max(0.01, candles[idx_5].close)
            base_close_10 = max(0.01, candles[idx_10].close)
            ret_5 = (latest_close - base_close_5) / base_close_5
            ret_10 = (latest_close - base_close_10) / base_close_10
            recent_high_20 = max(point.high for point in candles[max(0, latest_idx - 19): latest_idx + 1])
            recent_low_20 = min(point.low for point in candles[max(0, latest_idx - 19): latest_idx + 1])
            drawdown_20 = max(0.0, (recent_high_20 - latest_close) / max(recent_high_20, 0.01))
            ma20_latest = self._safe_mean([point.close for point in candles[max(0, latest_idx - 19): latest_idx + 1]])
            above_ma20 = latest_close >= ma20_latest
            if ret_5 >= 0.03 and drawdown_20 <= 0.05:
                near_status = "短线强势延续"
            elif ret_5 >= 0 and above_ma20:
                near_status = "高位震荡偏强"
            elif above_ma20:
                near_status = "回踩整理"
            elif drawdown_20 >= 0.12:
                near_status = "短线转弱"
            else:
                near_status = "震荡观察"
            quant += (
                f"近况：截至{latest_date}，近5日{ret_5 * 100:+.2f}%，"
                f"近10日{ret_10 * 100:+.2f}%，20日高低区间[{recent_low_20:.2f},{recent_high_20:.2f}]，"
                f"当前状态={near_status}。"
            )
        if row is not None:
            amount20_yi = row.amount20 / 1e8 if row.amount20 > 0 else 0.0
            liquidity = (
                f"流动性：20日平均换手{row.turnover20 * 100:.2f}%"
                f"{f'，20日平均成交额{amount20_yi:.2f}亿' if amount20_yi > 0 else ''}。"
            )
            quant = f"{quant}{liquidity}" if quant else liquidity
        return f"{head}{body}{tail}{quant}"

    @staticmethod
    def _extract_core_event_candidates(evidence: list[dict[str, str]]) -> list[str]:
        event_keywords = (
            "收购",
            "并购",
            "重组",
            "拟购",
            "增资",
            "中标",
            "订单",
            "合同",
            "签约",
            "业绩",
            "预增",
            "扭亏",
            "涨价",
        )
        candidates: list[str] = []
        seen: set[str] = set()
        for item in evidence[:10]:
            text = InMemoryStore._clean_event_text(str(item.get("title", "")))
            if not text:
                continue
            if not any(keyword in text for keyword in event_keywords):
                continue
            if text in seen:
                continue
            seen.add(text)
            candidates.append(text[:96])
            if len(candidates) >= 4:
                break
        return candidates

    def _extract_industry_event_candidates(
        self,
        industry: str,
        evidence: list[dict[str, str]],
    ) -> list[str]:
        industry_name = TextProcessor.clean_whitespace(industry)
        if not industry_name:
            return []
        event_keywords = (
            "政策",
            "补贴",
            "景气",
            "需求",
            "供给",
            "涨价",
            "扩产",
            "产能",
            "订单",
            "库存",
            "周期",
            "国产替代",
            "降息",
            "降准",
        )
        banned = ("个股", "股价", "涨停", "跌停", "龙头", "复盘", "早盘", "午评", "收评")
        candidates: list[str] = []
        seen: set[str] = set()
        for item in evidence[:12]:
            text = self._clean_event_text(
                f"{item.get('title', '')} {item.get('snippet', '')}"
            )
            if not text:
                continue
            if industry_name not in text:
                continue
            if any(
                token in text
                for token in ("基金", "份额", "净值", "产品资料概要", "发起式", "证券投资基金", "公告更新", "招募说明书")
            ):
                continue
            if any(word in text for word in banned):
                continue
            if any(code != "" for code in self._extract_code_tokens(text)):
                continue
            if "、" in text and not any(word in text for word in ("政策", "需求", "供给", "涨价", "景气", "订单", "产能")):
                continue
            if not any(word in text for word in event_keywords):
                continue
            if text in seen:
                continue
            seen.add(text)
            candidates.append(text[:60])
            if len(candidates) >= 3:
                break
        return candidates

    def _build_industry_fallback_reasons(
        self,
        industry: str,
        row: ScreenerResult | None,
    ) -> list[str]:
        industry_name = TextProcessor.clean_whitespace(industry)
        if not industry_name or industry_name == "Unknown":
            return []
        reasons: list[str] = [f"行业驱动：{industry_name}板块近期放量走强，行业资金共振带动个股补涨。"]
        if row is not None:
            if row.up_down_volume_ratio >= 1.1:
                reasons.append(f"行业驱动：{industry_name}上涨日量能占优，短线资金风险偏好回升。")
            elif row.retrace20 <= 0.12:
                reasons.append(f"行业驱动：{industry_name}板块回撤受控，行业资金维持轮动配置。")
            else:
                reasons.append(f"行业驱动：{industry_name}景气预期回暖，行业资金从核心向二线扩散。")
        return reasons[:2]

    @staticmethod
    def _parse_rss_pub_date(date_text: str) -> datetime | None:
        if not date_text.strip():
            return None
        try:
            parsed = parsedate_to_datetime(date_text.strip())
            if parsed.tzinfo is not None:
                return parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            return None

    @staticmethod
    def _market_board_label(symbol: str) -> str:
        code = symbol.lower().strip()
        if code.startswith("sz300") or code.startswith("sz301"):
            return "创业板"
        if code.startswith("sh688"):
            return "科创板"
        if code.startswith("bj"):
            return "北交所"
        return "主板"

    @staticmethod
    def _symbol_to_secid(symbol: str) -> str | None:
        raw = symbol.lower().strip()
        market = ""
        code = ""
        if raw.startswith("sz"):
            market, code = "0", raw[2:]
        elif raw.startswith("sh"):
            market, code = "1", raw[2:]
        elif raw.startswith("bj"):
            market, code = "0", raw[2:]
        elif re.fullmatch(r"\d{6}", raw):
            code = raw
            market = "1" if raw.startswith(("5", "6", "9")) else "0"
        if not code or not re.fullmatch(r"\d{6}", code):
            return None
        return f"{market}.{code}"

    def _fetch_quote_profile(self, symbol: str) -> dict[str, str]:
        cache_key = symbol.lower()
        now_ts = time.time()
        cached = self._quote_profile_cache.get(cache_key)
        if cached and now_ts - cached[0] <= 3600:
            return cached[1]

        secid = self._symbol_to_secid(symbol)
        if secid is None:
            profile = {"name": "", "industry": "", "region": ""}
            self._quote_profile_cache[cache_key] = (now_ts, profile)
            return profile

        profile = {"name": "", "industry": "", "region": ""}
        try:
            with httpx.Client(timeout=6.0, follow_redirects=True) as client:
                resp = client.get(
                    "https://push2.eastmoney.com/api/qt/stock/get",
                    params={"secid": secid, "fields": "f57,f58,f127,f128"},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                        )
                    },
                )
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            profile = {
                "name": str(data.get("f58", "")).strip(),
                "industry": str(data.get("f127", "")).strip(),
                "region": str(data.get("f128", "")).strip(),
            }
        except Exception:
            profile = {"name": "", "industry": "", "region": ""}

        self._quote_profile_cache[cache_key] = (now_ts, profile)
        return profile

    def _build_web_search_queries(
        self,
        symbol: str,
        stock_name: str,
        source_domains: set[str],
        focus_date: str | None = None,
    ) -> list[str]:
        base_queries = [
            f"{symbol} {stock_name} 收购 并购 重组",
            f"{symbol} {stock_name} 并购 标的 公告",
            f"{symbol} {stock_name} 上涨原因 题材 新闻",
            f"{symbol} {stock_name} 涨停 原因 公告",
            f"{symbol} {stock_name} 板块 热点",
            f"{symbol} {stock_name} 公告 业绩",
        ]
        parsed_focus = self._parse_date(focus_date or "")
        if parsed_focus is not None:
            month_key = parsed_focus.strftime("%Y-%m")
            base_queries.insert(0, f"{symbol} {stock_name} {month_key} 公告 热点")
            base_queries.insert(1, f"{symbol} {stock_name} {month_key} 板块 题材")
        queries: list[str] = []
        for domain in list(source_domains)[:4]:
            queries.append(f"{symbol} {stock_name} 上涨原因 site:{domain}")
            queries.append(f"{symbol} {stock_name} 题材 site:{domain}")
        queries.extend(base_queries)
        return queries

    def _build_industry_search_queries(
        self,
        industry: str,
        source_domains: set[str],
        focus_date: str | None = None,
    ) -> list[str]:
        base_queries = [
            f"{industry} 板块 大涨 原因",
            f"{industry} 行业 景气 政策",
            f"{industry} 需求 供给 价格",
            f"{industry} 产业链 催化",
        ]
        parsed_focus = self._parse_date(focus_date or "")
        if parsed_focus is not None:
            month_key = parsed_focus.strftime("%Y-%m")
            base_queries.insert(0, f"{industry} {month_key} 板块 大涨 原因")
            base_queries.insert(1, f"{industry} {month_key} 政策 催化")
        queries: list[str] = []
        for domain in list(source_domains)[:4]:
            queries.append(f"{industry} 大涨 原因 site:{domain}")
            queries.append(f"{industry} 行业 催化 site:{domain}")
        queries.extend(base_queries)
        return queries

    def _collect_web_evidence(
        self,
        symbol: str,
        stock_name: str,
        source_urls: list[str],
        *,
        focus_date: str | None = None,
        max_items: int = 8,
    ) -> list[dict[str, str]]:
        cache_key = f"{symbol}:{focus_date or ''}:{','.join(source_urls)}"
        now_ts = time.time()
        cached = self._web_evidence_cache.get(cache_key)
        if cached and now_ts - cached[0] <= 600:
            return cached[1]

        allowed_domains = self._source_domains(source_urls)
        queries = self._build_web_search_queries(symbol, stock_name, allowed_domains, focus_date)
        timeout = max(5.0, min(float(self._config.ai_timeout_sec), 12.0))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

        results: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        def parse_rss(xml_text: str, domain_filter: set[str]) -> list[dict[str, str]]:
            parsed_items: list[dict[str, str]] = []
            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError:
                return parsed_items
            for item in root.findall("./channel/item"):
                link = (item.findtext("link") or "").strip()
                source_node = item.find("source")
                source_name = ""
                source_url = ""
                if source_node is not None:
                    source_name = (source_node.text or "").strip()
                    source_url = (source_node.attrib.get("url") or "").strip()
                if self._is_low_quality_source(source_name, source_url):
                    continue
                filter_url = source_url or link
                display_url = source_url or link
                if display_url in seen_urls and link and link not in seen_urls:
                    display_url = link
                dedupe_key = display_url
                if not display_url or dedupe_key in seen_urls:
                    continue
                if not self._url_in_domains(filter_url, domain_filter):
                    continue
                title_raw = html.unescape((item.findtext("title") or "").strip())
                desc_raw = html.unescape((item.findtext("description") or "").strip())
                title = self._clean_text(title_raw)
                snippet = self._clean_text(desc_raw)
                if self._is_low_signal_title(title):
                    continue
                if stock_name and stock_name not in f"{title} {snippet}" and symbol.lower() not in f"{title} {snippet}".lower():
                    continue
                if not title and not snippet:
                    continue
                parsed_items.append(
                    {
                        "title": title[:120] if title else "无标题",
                        "url": display_url,
                        "snippet": (f"{source_name} | {snippet}" if source_name else snippet)[:260] if snippet else "无摘要",
                        "pub_date": (item.findtext("pubDate") or "").strip()[:40],
                        "source_name": source_name[:40],
                    }
                )
                seen_urls.add(dedupe_key)
                if len(results) + len(parsed_items) >= max_items:
                    break
            return parsed_items

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                for query in queries:
                    if len(results) >= max_items:
                        break
                    response = client.get(
                        "https://news.google.com/rss/search",
                        params={
                            "q": query,
                            "hl": "zh-CN",
                            "gl": "CN",
                            "ceid": "CN:zh-Hans",
                        },
                    )
                    response.raise_for_status()

                    parsed_items = parse_rss(response.text, allowed_domains)
                    if not parsed_items and allowed_domains:
                        parsed_items = parse_rss(response.text, set())
                    results.extend(parsed_items)
                    if len(results) >= max_items:
                        break
        except Exception:
            results = []

        results = results[:max_items]
        self._web_evidence_cache[cache_key] = (now_ts, results)
        return results

    def _collect_industry_evidence(
        self,
        industry: str,
        source_urls: list[str],
        *,
        focus_date: str | None = None,
        max_items: int = 8,
    ) -> list[dict[str, str]]:
        industry_name = TextProcessor.clean_whitespace(industry)
        if not industry_name or industry_name == "Unknown":
            return []
        cache_key = f"industry:{industry_name}:{focus_date or ''}:{','.join(source_urls)}"
        now_ts = time.time()
        cached = self._web_evidence_cache.get(cache_key)
        if cached and now_ts - cached[0] <= 600:
            return cached[1]

        allowed_domains = self._source_domains(source_urls)
        queries = self._build_industry_search_queries(industry_name, allowed_domains, focus_date)
        timeout = max(5.0, min(float(self._config.ai_timeout_sec), 12.0))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

        results: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        def parse_rss(xml_text: str, domain_filter: set[str]) -> list[dict[str, str]]:
            parsed_items: list[dict[str, str]] = []
            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError:
                return parsed_items
            for item in root.findall("./channel/item"):
                link = (item.findtext("link") or "").strip()
                source_node = item.find("source")
                source_name = ""
                source_url = ""
                if source_node is not None:
                    source_name = (source_node.text or "").strip()
                    source_url = (source_node.attrib.get("url") or "").strip()
                if self._is_low_quality_source(source_name, source_url):
                    continue
                filter_url = source_url or link
                display_url = source_url or link
                if display_url in seen_urls and link and link not in seen_urls:
                    display_url = link
                if not display_url or display_url in seen_urls:
                    continue
                if not self._url_in_domains(filter_url, domain_filter):
                    continue
                title_raw = html.unescape((item.findtext("title") or "").strip())
                desc_raw = html.unescape((item.findtext("description") or "").strip())
                title = self._clean_text(title_raw)
                snippet = self._clean_text(desc_raw)
                if self._is_low_signal_title(title):
                    continue
                if industry_name not in f"{title} {snippet}":
                    continue
                if not title and not snippet:
                    continue
                parsed_items.append(
                    {
                        "title": title[:120] if title else "无标题",
                        "url": display_url,
                        "snippet": (f"{source_name} | {snippet}" if source_name else snippet)[:260] if snippet else "无摘要",
                        "pub_date": (item.findtext("pubDate") or "").strip()[:40],
                        "source_name": source_name[:40],
                    }
                )
                seen_urls.add(display_url)
                if len(results) + len(parsed_items) >= max_items:
                    break
            return parsed_items

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                for query in queries:
                    if len(results) >= max_items:
                        break
                    response = client.get(
                        "https://news.google.com/rss/search",
                        params={
                            "q": query,
                            "hl": "zh-CN",
                            "gl": "CN",
                            "ceid": "CN:zh-Hans",
                        },
                    )
                    response.raise_for_status()

                    parsed_items = parse_rss(response.text, allowed_domains)
                    if not parsed_items and allowed_domains:
                        parsed_items = parse_rss(response.text, set())
                    results.extend(parsed_items)
                    if len(results) >= max_items:
                        break
        except Exception:
            results = []

        results = results[:max_items]
        self._web_evidence_cache[cache_key] = (now_ts, results)
        return results

    def _active_ai_provider(self) -> AIProviderConfig | None:
        for provider in self._config.ai_providers:
            if provider.id == self._config.ai_provider and provider.enabled:
                return provider
        return None

    @staticmethod
    def _read_api_key_file(path_text: str) -> str:
        if not path_text.strip():
            return ""
        full = os.path.expandvars(path_text.strip())
        full = os.path.expanduser(full)
        try:
            with open(full, "r", encoding="utf-8") as fp:
                return fp.read().strip()
        except OSError:
            return ""

    def _resolve_provider_api_key(
        self,
        provider: AIProviderConfig | None,
        *,
        fallback_api_key: str = "",
        fallback_api_key_path: str = "",
    ) -> str:
        if provider and provider.api_key.strip():
            return provider.api_key.strip()
        if self._config.api_key.strip():
            return self._config.api_key.strip()
        if fallback_api_key.strip():
            return fallback_api_key.strip()
        if provider and provider.api_key_path.strip():
            key = self._read_api_key_file(provider.api_key_path)
            if key:
                return key
        if self._config.api_key_path.strip():
            key = self._read_api_key_file(self._config.api_key_path)
            if key:
                return key
        if fallback_api_key_path.strip():
            key = self._read_api_key_file(fallback_api_key_path)
            if key:
                return key
        return ""

    @staticmethod
    def _trend_bull_type_label(trend: TrendClass) -> str:
        if trend == "A":
            return "A 阶梯慢牛"
        if trend == "A_B":
            return "A_B 慢牛加速"
        if trend == "B":
            return "B 脉冲涨停牛"
        return "Unknown"

    def _resolve_symbol_name(self, symbol: str, row: ScreenerResult | None = None) -> str:
        def _valid_name(name: str | None) -> str | None:
            if not name:
                return None
            value = name.strip()
            if not value:
                return None
            if value.upper() == symbol.upper():
                return None
            return value

        if row:
            resolved = _valid_name(row.name)
            if resolved:
                return resolved

        cached = self._latest_rows.get(symbol)
        if cached:
            resolved = _valid_name(cached.name)
            if resolved:
                return resolved

        for run in reversed(list(self._run_store.values())):
            for pool in (
                run.step_pools.step4,
                run.step_pools.step3,
                run.step_pools.step2,
                run.step_pools.step1,
                run.step_pools.input,
            ):
                found = next((item for item in pool if item.symbol == symbol), None)
                if not found:
                    continue
                resolved = _valid_name(found.name)
                if resolved:
                    return resolved

        profile = self._fetch_quote_profile(symbol)
        resolved = _valid_name(profile.get("name"))
        if resolved:
            return resolved

        base = next((item for item in STOCK_POOL if item["symbol"] == symbol), None)
        if base and base.get("name"):
            return str(base["name"])
        return symbol.upper()

    @staticmethod
    def _safe_mean(values: list[float] | list[int]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    @staticmethod
    def _parse_date(date_text: str) -> datetime | None:
        try:
            return datetime.strptime(date_text, "%Y-%m-%d")
        except ValueError:
            return None

    def _align_date_to_candles(self, candles: list[CandlePoint], date_text: str) -> str:
        if not candles:
            return date_text
        parsed_target = self._parse_date(date_text)
        if parsed_target is None:
            return candles[-1].time
        for candle in reversed(candles):
            parsed_candle = self._parse_date(candle.time)
            if parsed_candle and parsed_candle <= parsed_target:
                return candle.time
        return candles[0].time

    def _slice_candles_as_of(
        self,
        candles: list[CandlePoint],
        as_of_date: str | None,
    ) -> tuple[list[CandlePoint], str | None]:
        if not candles:
            return [], None
        if not as_of_date:
            return candles, candles[-1].time
        aligned = self._align_date_to_candles(candles, as_of_date)
        for idx, point in enumerate(candles):
            if point.time == aligned:
                return candles[: idx + 1], aligned
        return candles, candles[-1].time

    def _infer_recent_rebreakout_index(self, candles: list[CandlePoint]) -> int | None:
        if len(candles) < 70:
            return None
        closes = [point.close for point in candles]
        highs = [point.high for point in candles]
        lows = [point.low for point in candles]
        volumes = [max(0, int(point.volume)) for point in candles]

        # Focus on the recent 45 bars to avoid returning an old rally ignition.
        start = max(45, len(candles) - 45)
        end = len(candles) - 2
        for idx in range(start, end + 1):
            prior_window_start = idx - 20
            if prior_window_start < 20:
                continue
            prior_high20 = max(highs[prior_window_start:idx])
            prior_low20 = min(lows[prior_window_start:idx])
            if prior_low20 <= 0:
                continue

            breakout = closes[idx] >= prior_high20 * 1.01
            avg_vol20 = self._safe_mean(volumes[prior_window_start:idx])
            volume_confirmed = volumes[idx] >= avg_vol20 * 1.15 if avg_vol20 > 0 else False

            consolidation_range = (prior_high20 - prior_low20) / max(prior_low20, 0.01)
            ma20_curr = self._safe_mean(closes[idx - 19 : idx + 1])
            ma20_prev = self._safe_mean(closes[idx - 29 : idx - 9])
            ma20_flat = abs(ma20_curr - ma20_prev) / max(ma20_prev, 0.01) <= 0.05

            pre_peak_start = max(0, idx - 60)
            pre_peak_end = max(pre_peak_start + 1, idx - 20)
            pre_peak = max(highs[pre_peak_start:pre_peak_end])
            prior_run_existed = pre_peak >= prior_high20 * 1.08

            ignition = (
                closes[idx] >= ma20_curr * 1.005
                and closes[idx] >= closes[idx - 1] * 1.015
                and volume_confirmed
            )
            if not (ma20_flat and consolidation_range <= 0.24 and prior_run_existed and (breakout or ignition)):
                continue

            forward_end = min(len(candles), idx + 11)
            if forward_end <= idx + 1:
                continue
            forward_high = max(highs[idx + 1 : forward_end])
            forward_ret = (forward_high - closes[idx]) / max(closes[idx], 0.01)
            if forward_ret >= 0.05:
                return idx
        return None

    def _collect_volume_price_breakout_candidates(
        self,
        candles: list[CandlePoint],
        *,
        lookback: int = 55,
        max_items: int = 4,
    ) -> list[tuple[int, float, float, bool, bool]]:
        if len(candles) < 35:
            return []

        closes = [point.close for point in candles]
        highs = [point.high for point in candles]
        lows = [point.low for point in candles]
        volumes = [max(0, int(point.volume)) for point in candles]
        start = max(20, len(candles) - lookback)
        end = len(candles) - 2
        if end <= start:
            return []

        scored: list[tuple[float, int, float, float, bool, bool, int]] = []
        for idx in range(start, end + 1):
            prev_close = closes[idx - 1]
            if prev_close <= 0:
                continue
            day_ret = (closes[idx] - prev_close) / prev_close
            avg_vol10 = self._safe_mean(volumes[max(0, idx - 10) : idx])
            if avg_vol10 <= 0:
                continue
            vol_ratio10 = volumes[idx] / avg_vol10
            prior_high20 = max(highs[idx - 20 : idx])
            is_breakout = closes[idx] >= prior_high20 * 1.005

            pre_start = max(0, idx - 15)
            pre_low = min(lows[pre_start:idx]) if idx > pre_start else lows[idx]
            pre_high = max(highs[pre_start:idx]) if idx > pre_start else highs[idx]
            pre_range = (pre_high - pre_low) / max(pre_low, 0.01)
            is_consolidation_end = pre_range <= 0.26 and closes[idx] >= pre_high * 0.995
            ma10_curr = self._safe_mean(closes[max(0, idx - 9) : idx + 1])
            ma20_curr = self._safe_mean(closes[max(0, idx - 19) : idx + 1])
            ma20_prev = self._safe_mean(closes[max(0, idx - 20) : idx]) if idx >= 20 else ma20_curr
            is_ma_ignition = (
                closes[idx] >= ma10_curr * 1.005
                and closes[idx] >= ma20_curr * 1.02
                and ma20_curr >= ma20_prev * 0.997
            )
            is_washout_reversal = False
            anchor_idx = idx
            if idx >= 6:
                prev5_high = max(closes[idx - 5 : idx])
                prev_drop_ratio = (closes[idx - 1] - prev5_high) / max(prev5_high, 0.01)
                intraday_rebound = (closes[idx] - lows[idx]) / max(lows[idx], 0.01)
                is_washout_reversal = (
                    day_ret >= 0.08
                    and vol_ratio10 >= 1.45
                    and prev_drop_ratio <= -0.10
                    and intraday_rebound >= 0.08
                )
                if is_washout_reversal:
                    low_start = max(0, idx - 4)
                    low_end = idx
                    if low_end > low_start:
                        anchor_idx = min(range(low_start, low_end), key=lambda i: closes[i])

            forward_end = min(len(candles), idx + 8)
            if forward_end <= idx + 1:
                continue
            forward_high = max(highs[idx + 1 : forward_end])
            forward_ret = (forward_high - closes[idx]) / max(closes[idx], 0.01)

            if day_ret < 0.04:
                continue
            if vol_ratio10 < 1.45:
                continue
            if not (is_breakout or is_consolidation_end or is_ma_ignition or is_washout_reversal):
                continue
            if forward_ret < 0.04:
                continue

            recency = (idx - start) / max(1, (end - start))
            score = (
                day_ret * 100
                + vol_ratio10 * 5.0
                + (3.0 if is_breakout else 0.0)
                + (2.0 if is_consolidation_end else 0.0)
                + (1.5 if is_ma_ignition else 0.0)
                + (2.5 if is_washout_reversal else 0.0)
                + forward_ret * 30
                + recency * 4.0
            )
            scored.append((score, anchor_idx, day_ret, vol_ratio10, is_breakout, is_washout_reversal, idx))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[int, float, float, bool, bool]] = []
        for _, idx, day_ret, vol_ratio10, is_breakout, is_washout_reversal, _ in scored:
            if any(abs(idx - picked_idx) <= 2 for picked_idx, _, _, _, _ in selected):
                continue
            selected.append((idx, day_ret, vol_ratio10, is_breakout, is_washout_reversal))
            if len(selected) >= max_items:
                break
        return selected

    def _build_recent_price_volume_snapshot(
        self,
        candles: list[CandlePoint],
        *,
        lookback: int = 16,
    ) -> str:
        if len(candles) < 2:
            return "insufficient_recent_kline"
        closes = [point.close for point in candles]
        highs = [point.high for point in candles]
        volumes = [max(0, int(point.volume)) for point in candles]
        start = max(1, len(candles) - lookback)
        lines: list[str] = []
        for idx in range(start, len(candles)):
            prev_close = closes[idx - 1]
            day_ret = (closes[idx] - prev_close) / max(prev_close, 0.01)
            avg_vol10 = self._safe_mean(volumes[max(0, idx - 10) : idx])
            vol_ratio10 = volumes[idx] / max(avg_vol10, 1.0)
            prior_high20 = max(highs[max(0, idx - 20) : idx]) if idx > 0 else highs[idx]
            break20 = closes[idx] >= prior_high20 * 1.005 if idx >= 20 else False
            lines.append(
                (
                    f"{candles[idx].time}"
                    f"|close={closes[idx]:.2f}"
                    f"|pct={day_ret * 100:.2f}%"
                    f"|vol10x={vol_ratio10:.2f}"
                    f"|break20={1 if break20 else 0}"
                )
            )
        return "\n".join(lines)

    def _adjust_to_cluster_lead_index(self, candles: list[CandlePoint], index: int) -> int:
        if index <= 0 or len(candles) < 25:
            return index
        closes = [point.close for point in candles]
        highs = [point.high for point in candles]
        volumes = [max(0, int(point.volume)) for point in candles]
        start = max(1, index - 3)
        lead = index
        for idx in range(index, start - 1, -1):
            prev_close = closes[idx - 1]
            day_ret = (closes[idx] - prev_close) / max(prev_close, 0.01)
            avg_vol10 = self._safe_mean(volumes[max(0, idx - 10) : idx])
            vol_ratio10 = volumes[idx] / max(avg_vol10, 1.0)
            prior_high20 = max(highs[max(0, idx - 20) : idx]) if idx > 0 else highs[idx]
            breakout_like = closes[idx] >= prior_high20 * 0.995
            ma10_curr = self._safe_mean(closes[max(0, idx - 9) : idx + 1])
            ma20_curr = self._safe_mean(closes[max(0, idx - 19) : idx + 1])
            ma20_prev = self._safe_mean(closes[max(0, idx - 20) : idx]) if idx >= 20 else ma20_curr
            ma_ignition = (
                closes[idx] >= ma10_curr * 1.005
                and closes[idx] >= ma20_curr * 1.02
                and ma20_curr >= ma20_prev * 0.997
            )
            if day_ret >= 0.025 and vol_ratio10 >= 1.3 and (breakout_like or ma_ignition):
                lead = idx
        return lead

    def _infer_breakout_index_from_candles(self, candles: list[CandlePoint]) -> int | None:
        if len(candles) < 40:
            return None

        # First priority: recent volume-price ignition (放量+长阳+突破/结束盘整).
        volume_price_candidates = self._collect_volume_price_breakout_candidates(candles, lookback=55, max_items=3)
        if volume_price_candidates:
            candidate_idx, _, _, _, is_washout_reversal = volume_price_candidates[0]
            if is_washout_reversal:
                return candidate_idx
            return self._adjust_to_cluster_lead_index(candles, candidate_idx)

        # Prefer "二次启动" when a clear consolidation followed by a fresh breakout exists.
        recent_rebreakout = self._infer_recent_rebreakout_index(candles)
        if recent_rebreakout is not None:
            return recent_rebreakout

        closes = [point.close for point in candles]
        highs = [point.high for point in candles]
        volumes = [max(0, int(point.volume)) for point in candles]
        start = max(20, len(candles) - 110)
        end = len(candles) - 8
        if end <= start:
            return None

        # Primary rule: first confirmed breakout + trend alignment + volume expansion.
        for idx in range(start, end):
            prior_high20 = max(highs[idx - 20 : idx])
            if prior_high20 <= 0:
                continue
            ma20 = self._safe_mean(closes[idx - 19 : idx + 1])
            ma10 = self._safe_mean(closes[idx - 9 : idx + 1])
            ma5 = self._safe_mean(closes[idx - 4 : idx + 1])
            avg_vol20 = self._safe_mean(volumes[idx - 20 : idx])
            if avg_vol20 <= 0:
                continue

            breakout = closes[idx] >= prior_high20 * 1.01
            trend_aligned = ma5 > ma10 > ma20 and closes[idx] >= ma20 * 1.005
            volume_confirmed = volumes[idx] >= avg_vol20 * 1.2
            forward_high = max(highs[idx + 1 : idx + 9])
            forward_ret = (forward_high - closes[idx]) / max(closes[idx], 0.01)
            if breakout and trend_aligned and volume_confirmed and forward_ret >= 0.10:
                return idx

        # Secondary rule: MA20上穿并在短期内有延续。
        for idx in range(start + 1, end):
            ma20_prev = self._safe_mean(closes[idx - 20 : idx])
            ma20_curr = self._safe_mean(closes[idx - 19 : idx + 1])
            if closes[idx - 1] <= ma20_prev and closes[idx] > ma20_curr and ma20_curr >= ma20_prev * 0.997:
                forward_high = max(highs[idx + 1 : idx + 9])
                forward_ret = (forward_high - closes[idx]) / max(closes[idx], 0.01)
                if forward_ret >= 0.08:
                    return idx

        # Final fallback: lowest point in recent trend window before acceleration.
        recent_start = max(0, len(candles) - 45)
        recent_end = max(recent_start + 1, len(candles) - 5)
        if recent_end > recent_start:
            return min(range(recent_start, recent_end), key=lambda i: closes[i])
        return None

    def _sanitize_breakout_date(self, symbol: str, raw_date: str, baseline_date: str) -> str:
        candles = self._ensure_candles(symbol)
        if not candles:
            return baseline_date
        baseline_aligned = self._align_date_to_candles(candles, baseline_date)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            return baseline_aligned

        raw_aligned = self._align_date_to_candles(candles, raw_date)
        date_to_index = {point.time: idx for idx, point in enumerate(candles)}
        raw_index = date_to_index.get(raw_aligned)
        baseline_index = date_to_index.get(baseline_aligned)
        if raw_index is None:
            return baseline_aligned
        if baseline_index is None:
            return raw_aligned

        # Clamp AI hallucination: breakout day should not drift too far from K-line baseline.
        if abs(raw_index - baseline_index) > 18:
            return baseline_aligned
        # Too close to current end usually means "latest acceleration", not "起爆".
        if raw_index >= len(candles) - 3:
            return baseline_aligned
        return raw_aligned

    def _build_row_from_candles(self, symbol: str, as_of_date: str | None = None) -> ScreenerResult | None:
        candles, _ = self._slice_candles_as_of(self._ensure_candles(symbol), as_of_date)
        if len(candles) < 30:
            return None

        closes = [item.close for item in candles]
        highs = [item.high for item in candles]
        lows = [item.low for item in candles]
        opens = [item.open for item in candles]
        volumes = [max(0, int(item.volume)) for item in candles]
        amounts = [max(0.0, float(item.amount)) for item in candles]

        latest = closes[-1]
        prev = closes[-2]
        look20 = min(20, len(closes))
        look40 = min(40, len(closes) - 1)
        if look40 < 5:
            return None

        start20 = len(closes) - look20
        start40 = len(closes) - look40
        start40_close = closes[start40]
        ret40 = (latest - start40_close) / max(start40_close, 0.01)

        high20 = max(highs[start20:])
        retrace20 = max(0.0, (high20 - latest) / max(high20, 0.01))
        amount20 = self._safe_mean(amounts[start20:])
        amplitude20 = self._safe_mean(
            [
                (highs[idx] - lows[idx]) / max(closes[idx], 0.01)
                for idx in range(start20, len(closes))
            ]
        )

        avg_vol10 = self._safe_mean(volumes[-10:])
        avg_vol_prev10 = self._safe_mean(volumes[-20:-10]) if len(volumes) >= 20 else avg_vol10
        vol_slope20 = (avg_vol10 - avg_vol_prev10) / max(avg_vol_prev10, 1.0)

        up_volumes: list[int] = []
        down_volumes: list[int] = []
        for idx in range(1, len(closes)):
            if closes[idx] >= closes[idx - 1]:
                up_volumes.append(volumes[idx])
            else:
                down_volumes.append(volumes[idx])
        up_down_volume_ratio = self._safe_mean(up_volumes) / max(self._safe_mean(down_volumes), 1.0)

        pullback_days = 0
        for idx in range(len(closes) - 1, 0, -1):
            if closes[idx] <= closes[idx - 1]:
                pullback_days += 1
            else:
                break
        recent_pullback_volume = volumes[-pullback_days:] if pullback_days > 0 else []
        pullback_volume_ratio = (
            self._safe_mean(recent_pullback_volume) / max(self._safe_mean(volumes[-5:]), 1.0)
            if recent_pullback_volume
            else 0.85
        )

        ma20 = self._safe_mean(closes[-20:])
        ma10 = self._safe_mean(closes[-10:])
        ma5 = self._safe_mean(closes[-5:])
        price_vs_ma20 = (latest - ma20) / max(ma20, 0.01)

        ma10_above_ma20_days = 0
        ma5_above_ma10_days = 0
        for idx in range(len(closes) - 1, max(len(closes) - 20, 1), -1):
            ma10_i = self._safe_mean(closes[max(0, idx - 9) : idx + 1])
            ma20_i = self._safe_mean(closes[max(0, idx - 19) : idx + 1])
            ma5_i = self._safe_mean(closes[max(0, idx - 4) : idx + 1])
            if ma10_i >= ma20_i:
                ma10_above_ma20_days += 1
            if ma5_i >= ma10_i:
                ma5_above_ma10_days += 1

        if ret40 >= 0.8 or (latest - prev) / max(prev, 0.01) >= 0.08:
            trend_class: TrendClass = "B"
        elif ret40 >= 0.3 and vol_slope20 > 0:
            trend_class = "A_B"
        elif ret40 >= 0.12:
            trend_class = "A"
        else:
            trend_class = "Unknown"

        if ret40 < 0.3:
            stage: Stage = "Early"
        elif ret40 <= 0.8:
            stage = "Mid"
        else:
            stage = "Late"

        if ret40 >= 0.8:
            theme_stage: ThemeStage = "高潮"
        elif vol_slope20 > 0 and up_down_volume_ratio >= 1.1:
            theme_stage = "发酵中"
        elif ret40 <= 0.05 and retrace20 > 0.15:
            theme_stage = "退潮"
        else:
            theme_stage = "Unknown"

        has_blowoff_top = False
        for idx in range(max(0, len(closes) - 20), len(closes)):
            if volumes[idx] > max(avg_vol10, 1.0) * 2.5 and closes[idx] <= opens[idx]:
                has_blowoff_top = True
                break

        has_divergence_5d = False
        if len(closes) >= 10:
            price_rise = closes[-1] > closes[-6]
            avg_v5 = self._safe_mean(volumes[-5:])
            avg_prev5 = self._safe_mean(volumes[-10:-5])
            has_divergence_5d = price_rise and avg_v5 < avg_prev5 * 0.9

        has_upper_shadow_risk = False
        for idx in range(max(0, len(closes) - 5), len(closes)):
            bar_range = highs[idx] - lows[idx]
            if bar_range <= 0:
                continue
            body_high = max(opens[idx], closes[idx])
            upper_shadow = highs[idx] - body_high
            if upper_shadow / bar_range > 0.5 and closes[idx] <= opens[idx]:
                has_upper_shadow_risk = True
                break

        pseudo_float_shares = 2_000_000_000.0 + (self._hash_seed(symbol) % 500) * 10_000_000.0
        turnover20 = self._safe_mean(
            [max(0.0, float(vol)) / pseudo_float_shares for vol in volumes[start20:]]
        )

        score_raw = (
            45
            + ret40 * 95
            + up_down_volume_ratio * 8
            - pullback_volume_ratio * 14
            + max(0.0, (0.08 - abs(price_vs_ma20)) * 180)
        )
        score = int(round(max(0.0, min(100.0, score_raw))))
        ai_confidence = max(
            0.35,
            min(
                0.95,
                0.50
                + ret40 * 0.30
                + (up_down_volume_ratio - 1.0) * 0.10
                - max(0.0, pullback_volume_ratio - 0.8) * 0.20,
            ),
        )
        has_approx = any(point.price_source == "approx" for point in candles)

        return ScreenerResult(
            symbol=symbol,
            name=self._resolve_symbol_name(symbol),
            latest_price=round(latest, 2),
            day_change=round(latest - prev, 2),
            day_change_pct=round((latest - prev) / max(prev, 0.01), 4),
            score=score,
            ret40=round(ret40, 4),
            turnover20=round(turnover20, 4),
            amount20=float(amount20),
            amplitude20=round(amplitude20, 4),
            retrace20=round(retrace20, 4),
            pullback_days=pullback_days,
            ma10_above_ma20_days=ma10_above_ma20_days,
            ma5_above_ma10_days=ma5_above_ma10_days,
            price_vs_ma20=round(price_vs_ma20, 4),
            vol_slope20=round(vol_slope20, 4),
            up_down_volume_ratio=round(up_down_volume_ratio, 4),
            pullback_volume_ratio=round(pullback_volume_ratio, 4),
            has_blowoff_top=has_blowoff_top,
            has_divergence_5d=has_divergence_5d,
            has_upper_shadow_risk=has_upper_shadow_risk,
            ai_confidence=round(ai_confidence, 2),
            theme_stage=theme_stage,
            trend_class=trend_class,
            stage=stage,
            labels=["K线上下文补全"],
            reject_reasons=[],
            degraded=has_approx,
            degraded_reason="MINUTE_DATA_MISSING_PARTIAL" if has_approx else None,
        )

    def _build_ai_context_text(self, symbol: str, row: ScreenerResult | None) -> str:
        candles = self._ensure_candles(symbol)
        if not candles:
            return "kline=unavailable"

        closes = [item.close for item in candles]
        latest = closes[-1]
        look20 = min(20, len(closes) - 1)
        ret20 = 0.0
        if look20 > 0:
            start_price = closes[-look20]
            ret20 = (latest - start_price) / max(start_price, 0.01)
        ma20 = self._safe_mean(closes[-20:])
        annotation = self._annotation_store.get(symbol)
        annotation_text = "manual=none"
        if annotation:
            annotation_text = (
                f"manual_start={annotation.start_date}, manual_stage={annotation.stage}, "
                f"manual_trend={annotation.trend_class}, decision={annotation.decision}"
            )
        row_text = "row=none"
        if row:
            row_text = (
                f"row_ret40={row.ret40:.4f}, row_stage={row.stage}, row_trend={row.trend_class}, "
                f"row_theme={row.theme_stage}, row_score={row.score}"
            )
        return (
            f"latest={latest:.2f}, ret20={ret20:.4f}, price_vs_ma20={(latest - ma20) / max(ma20, 0.01):.4f}, "
            f"{row_text}, {annotation_text}"
        )

    def _guess_theme_name(self, symbol: str, row: ScreenerResult | None) -> str:
        if row and row.theme_stage == "高潮":
            return "主线热点"
        if row and row.theme_stage == "发酵中":
            return "潜在热点"
        return "Unknown"

    def _infer_theme_from_web_evidence(self, evidence: list[dict[str, str]]) -> str:
        if not evidence:
            return "Unknown"
        corpus = " ".join(
            f"{item.get('title', '')} {item.get('snippet', '')}" for item in evidence
        ).lower()
        theme_keywords: list[tuple[str, tuple[str, ...]]] = [
            ("创新药", ("创新药", "医药", "制药", "生物")),
            ("机器人", ("机器人", "自动化", "工业母机")),
            ("半导体", ("芯片", "半导体", "算力")),
            ("新能源", ("锂电", "电池", "光伏", "储能", "新能源")),
            ("军工", ("军工", "航天", "航空", "卫星")),
            ("高端消费", ("消费", "白酒", "食品饮料")),
            ("化工", ("化工", "材料", "涨价")),
        ]
        best_label = "Unknown"
        best_score = 0
        for label, words in theme_keywords:
            score = sum(corpus.count(word.lower()) for word in words)
            if score > best_score:
                best_score = score
                best_label = label
        return best_label if best_score > 0 else "Unknown"

    def _infer_sector_from_context(
        self,
        symbol: str,
        stock_name: str,
        evidence: list[dict[str, str]],
    ) -> str:
        profile = self._fetch_quote_profile(symbol)
        profile_industry = TextProcessor.clean_whitespace(profile.get("industry", ""))
        if profile_industry:
            return profile_industry
        corpus = " ".join(
            [stock_name, symbol, *[f"{item.get('title', '')} {item.get('snippet', '')}" for item in evidence]]
        ).lower()
        rules: list[tuple[str, tuple[str, ...]]] = [
            ("通信设备", ("通信", "运营商", "算力", "光模块", "网络", "信息")),
            ("创新药", ("创新药", "医药", "制药", "生物")),
            ("机器人", ("机器人", "工业自动化", "机器视觉", "工业母机")),
            ("半导体", ("芯片", "半导体", "算力", "封装", "光刻")),
            ("新能源", ("锂电", "电池", "光伏", "储能", "风电", "新能源")),
            ("军工", ("军工", "航天", "航空", "卫星", "雷达")),
            ("消费", ("消费", "食品饮料", "白酒", "家电")),
            ("化工", ("化工", "材料", "涨价", "聚酯", "化纤")),
        ]
        best_label = "Unknown"
        best_score = 0
        for label, words in rules:
            score = sum(corpus.count(word.lower()) for word in words)
            if score > best_score:
                best_score = score
                best_label = label
        return best_label if best_score > 0 else "Unknown"

    def _pick_breakout_hotspot_titles(
        self,
        evidence: list[dict[str, str]],
        breakout_date: str | None,
        *,
        max_items: int = 2,
    ) -> list[str]:
        if not evidence:
            return []
        parsed_breakout = self._parse_date(breakout_date or "")
        with_parsed: list[tuple[dict[str, str], datetime | None]] = [
            (item, self._parse_rss_pub_date(str(item.get("pub_date", ""))))
            for item in evidence
        ]
        selected: list[dict[str, str]] = []
        if parsed_breakout is not None:
            start = parsed_breakout - timedelta(days=5)
            end = parsed_breakout + timedelta(days=10)
            for item, parsed in with_parsed:
                if parsed is None:
                    continue
                if start <= parsed <= end:
                    selected.append(item)
                if len(selected) >= max_items:
                    break
        if parsed_breakout is None and not selected:
            selected = [item for item, _ in with_parsed[:max_items]]
        if parsed_breakout is not None and not selected:
            return []

        titles: list[str] = []
        for item in selected[:max_items]:
            title = self._clean_event_text(str(item.get("title", "")))
            if not title:
                continue
            titles.append(title)
        return titles

    @staticmethod
    def _infer_rise_reasons_from_web_evidence(evidence: list[dict[str, str]]) -> list[str]:
        reasons: list[str] = []
        seen_titles: set[str] = set()
        for item in evidence[:6]:
            title = InMemoryStore._clean_event_text(item.get("title", ""))
            if title and title not in seen_titles:
                seen_titles.add(title)
                reasons.append(title)
            if len(reasons) >= 4:
                break
        return InMemoryStore._normalize_rise_reasons(reasons)

    def _infer_breakout_date(self, symbol: str, row: ScreenerResult | None) -> str:
        candles = self._ensure_candles(symbol)
        breakout_index = self._infer_breakout_index_from_candles(candles)
        if breakout_index is not None:
            return candles[breakout_index].time

        if row is None:
            fallback = self._days_ago(18 + self._hash_seed(symbol) % 18)
            return self._align_date_to_candles(candles, fallback)

        offset = 12 + int(max(0.0, min(50.0, row.retrace20 * 150)))
        if row.trend_class in ("A", "A_B"):
            offset += 8
        elif row.trend_class == "B":
            offset = max(6, offset - 4)
        fallback = self._days_ago(offset)
        return self._align_date_to_candles(candles, fallback)

    def _infer_rise_reasons(self, row: ScreenerResult | None) -> list[str]:
        if row is None:
            return ["缺少可用日线数据，需先补齐行情后再评估"]
        reasons: list[str] = []
        if row.vol_slope20 > 0:
            reasons.append("20日量能斜率为正，成交活跃度提升")
        if row.up_down_volume_ratio >= 1.2:
            reasons.append("上涨日量能显著大于下跌日，资金承接较强")
        if row.pullback_volume_ratio <= 0.75:
            reasons.append("回调阶段缩量，抛压释放相对充分")
        if row.price_vs_ma20 >= 0:
            reasons.append("价格站上MA20，趋势结构保持多头")
        if row.theme_stage in ("发酵中", "高潮"):
            reasons.append(f"题材阶段处于{row.theme_stage}，具备跟踪价值")
        if not reasons:
            reasons.append("量价结构中性，建议结合分时确认是否介入")
        return reasons[:4]

    def _heuristic_ai_analysis(
        self,
        symbol: str,
        row: ScreenerResult | None,
        source_urls: list[str],
    ) -> AIAnalysisRecord:
        provider = self._config.ai_provider
        stock_name = self._resolve_symbol_name(symbol, row)
        breakout_date = self._infer_breakout_date(symbol, row)
        trend_bull_type = self._trend_bull_type_label(row.trend_class) if row else "Unknown"
        board_label = self._market_board_label(symbol)
        sector_label = self._infer_sector_from_context(symbol, stock_name, [])
        theme_name = self._guess_theme_name(symbol, row)
        if theme_name == "Unknown" and sector_label != "Unknown":
            theme_name = sector_label
        rise_reasons = self._infer_rise_reasons(row)
        if row is None:
            return AIAnalysisRecord(
                provider=provider,
                symbol=symbol,
                name=stock_name,
                fetched_at=self._now_datetime(),
                source_urls=source_urls,
                summary="已尝试补全上下文但可用行情不足，建议先确认近20日量价结构再决定是否介入。",
                conclusion="Unknown",
                confidence=0.5,
                breakout_date=breakout_date,
                trend_bull_type=trend_bull_type,
                theme_name=theme_name,
                rise_reasons=rise_reasons,
                error_code="AI_KLINE_CONTEXT_MISSING",
            )

        ret_text = f"{row.ret40 * 100:.2f}%"
        retrace_text = f"{row.retrace20 * 100:.2f}%"
        turnover_text = f"{row.turnover20 * 100:.2f}%"
        if row.trend_class == "B" and row.retrace20 > 0.12:
            conclusion = "退潮"
        elif row.ai_confidence >= 0.72 and row.up_down_volume_ratio >= 1.2:
            conclusion = "发酵中"
        else:
            conclusion = "高潮" if row.theme_stage == "高潮" else "发酵中"

        summary = (
            f"所属板块 {board_label}，趋势类型 {row.trend_class}，阶段 {row.stage}，窗口涨幅 {ret_text}，"
            f"回撤 {retrace_text}，20日平均换手 {turnover_text}。"
            "建议结合分时承接与板块联动确认节奏。"
        )
        confidence = max(0.45, min(0.95, row.ai_confidence))
        return AIAnalysisRecord(
            provider=provider,
            symbol=symbol,
            name=stock_name,
            fetched_at=self._now_datetime(),
            source_urls=source_urls,
            summary=summary,
            conclusion=conclusion,
            confidence=round(confidence, 2),
            breakout_date=breakout_date,
            trend_bull_type=trend_bull_type,
            theme_name=theme_name,
            rise_reasons=rise_reasons,
            error_code=None,
        )

    def _extract_conclusion_from_text(self, text: str) -> str:
        if "退潮" in text:
            return "退潮"
        if "高潮" in text:
            return "高潮"
        if "发酵" in text:
            return "发酵中"
        return "Unknown"

    def _extract_confidence_from_text(self, text: str, fallback: float) -> float:
        match = re.search(r"(\d{1,3}(?:\.\d+)?%)|(0?\.\d+)", text)
        if not match:
            return fallback
        token = match.group(0)
        if token.endswith("%"):
            value = float(token[:-1]) / 100.0
        else:
            value = float(token)
        return max(0.0, min(1.0, value))

    def _compose_ai_prompt_context(
        self,
        symbol: str,
        row: ScreenerResult | None,
        source_urls: list[str],
    ) -> dict[str, object]:
        baseline = self._heuristic_ai_analysis(symbol, row, source_urls)
        row_text = "no_recent_context"
        if row:
            row_text = (
                f"trend={row.trend_class}, stage={row.stage}, ret={row.ret40:.4f}, "
                f"turnover20={row.turnover20:.4f}, retrace20={row.retrace20:.4f}, "
                f"vol_ratio={row.up_down_volume_ratio:.4f}, theme={row.theme_stage}"
            )
        context_text = self._build_ai_context_text(symbol, row)
        stock_name = self._resolve_symbol_name(symbol, row)
        board_label = self._market_board_label(symbol)
        web_evidence = self._collect_web_evidence(
            symbol,
            stock_name,
            source_urls,
            focus_date=baseline.breakout_date,
        )
        evidence_urls = [item["url"] for item in web_evidence if item.get("url")]
        inferred_sector = self._infer_sector_from_context(symbol, stock_name, web_evidence)
        industry_evidence = self._collect_industry_evidence(
            inferred_sector,
            source_urls,
            focus_date=baseline.breakout_date,
        )
        industry_event_candidates = self._extract_industry_event_candidates(
            inferred_sector,
            industry_evidence,
        )
        if not industry_event_candidates:
            industry_event_candidates = self._build_industry_fallback_reasons(inferred_sector, row)
        evidence_urls.extend([item["url"] for item in industry_evidence if item.get("url")])
        hotspot_titles = self._pick_breakout_hotspot_titles(web_evidence, baseline.breakout_date, max_items=2)
        core_event_candidates = self._extract_core_event_candidates(web_evidence)
        evidence_text = "\n".join(
            [
                (
                    f"- [{idx + 1}] title={self._clean_event_text(str(item.get('title', '')))}; "
                    f"date={item.get('pub_date', '')}; "
                    f"source={item.get('source_name', '')}; "
                    f"url={item.get('url', '')}"
                )
                for idx, item in enumerate(web_evidence)
            ]
        )
        if not evidence_text:
            evidence_text = "no_high_signal_web_evidence"
        industry_evidence_text = "\n".join(
            [
                (
                    f"- [{idx + 1}] title={self._clean_event_text(str(item.get('title', '')))}; "
                    f"date={item.get('pub_date', '')}; "
                    f"source={item.get('source_name', '')}; "
                    f"url={item.get('url', '')}"
                )
                for idx, item in enumerate(industry_evidence)
            ]
        )
        if not industry_evidence_text:
            industry_evidence_text = "no_industry_evidence"
        candles = self._ensure_candles(symbol)
        trading_dates_tail = ",".join([point.time for point in candles[-45:]]) if candles else ""
        baseline_breakout = baseline.breakout_date or self._now_date()
        today = self._now_date()
        recent_kline = self._build_recent_price_volume_snapshot(candles, lookback=16)
        breakout_candidate_details = self._collect_volume_price_breakout_candidates(candles, lookback=55, max_items=4)
        breakout_candidates: list[str] = []
        breakout_candidates_text_parts: list[str] = []
        for idx, day_ret, vol_ratio10, is_breakout, is_washout_reversal in breakout_candidate_details:
            day = candles[idx].time
            breakout_candidates.append(day)
            breakout_candidates_text_parts.append(
                (
                    f"{day}"
                    f"(pct={day_ret * 100:.2f}%,vol10x={vol_ratio10:.2f},"
                    f"break20={1 if is_breakout else 0},washout={1 if is_washout_reversal else 0})"
                )
            )
        if not breakout_candidates:
            breakout_candidates = [baseline_breakout]
            breakout_candidates_text_parts = [f"{baseline_breakout}(baseline)"]
        breakout_candidates_text = ", ".join(breakout_candidates_text_parts)

        prompt = (
            "你是A股短线量价分析助手。只输出 JSON，不要任何解释。\n"
            "JSON keys 固定为: conclusion, confidence, summary, breakout_date, rise_reasons, trend_bull_type, theme_name。\n"
            "任务只做两件事：\n"
            "A) 从候选交易日中选出“当前这一轮”的起爆日 breakout_date。\n"
            "B) 给出 1~2 条上涨原因 rise_reasons（优先公司事件，缺失时给行业驱动）。\n"
            "硬约束：\n"
            "1) breakout_date 必须从 breakout_candidates 中选择。\n"
            "2) 起爆日优先满足量价共振：当日涨幅>=4%、当日成交量>=前10日均量1.5倍，且突破近20日高点或结束盘整。\n"
            "3) 若历史有上一轮炒作且中间有明显盘整，必须选择新一轮起爆日，不得回到旧周期。\n"
            "4) rise_reasons 每条<=26字，禁止媒体名/网址/其他股票代码。\n"
            "5) 若个股无明确利好，rise_reasons 第一条必须写“行业驱动：...”。\n"
            "6) summary 仅一句话，<=40字。\n"
            f"symbol={symbol}\n"
            f"name={stock_name}\n"
            f"board={board_label}\n"
            f"inferred_sector={inferred_sector}\n"
            f"today={today}\n"
            f"features={row_text}\n"
            f"context={context_text}\n"
            f"baseline_breakout={baseline_breakout}\n"
            f"breakout_candidates={breakout_candidates_text}\n"
            f"recent_kline=\n{recent_kline}\n"
            f"core_event_candidates={core_event_candidates}\n"
            f"industry_event_candidates={industry_event_candidates}\n"
            f"breakout_hotspot_titles={hotspot_titles}\n"
            f"configured_sources={source_urls}\n"
            f"trading_dates_tail={trading_dates_tail}\n"
            f"web_evidence_count={len(web_evidence)}\n"
            f"web_evidence=\n{evidence_text}\n"
            f"industry_evidence_count={len(industry_evidence)}\n"
            f"industry_evidence=\n{industry_evidence_text}"
        )
        evidence_urls = list(dict.fromkeys([url for url in evidence_urls if url]))
        return {
            "prompt": prompt,
            "baseline": baseline,
            "web_evidence": web_evidence,
            "evidence_urls": evidence_urls,
            "inferred_sector": inferred_sector,
            "board_label": board_label,
            "hotspot_titles": hotspot_titles,
            "core_event_candidates": core_event_candidates,
            "industry_event_candidates": industry_event_candidates,
            "breakout_candidates": breakout_candidates,
            "industry_evidence": industry_evidence,
        }

    def _call_provider_for_stock(
        self,
        symbol: str,
        row: ScreenerResult | None,
        source_urls: list[str],
    ) -> AIAnalysisRecord | None:
        provider = self._active_ai_provider()
        api_key = self._resolve_provider_api_key(provider)
        if provider is None or not provider.base_url.strip() or not provider.model.strip():
            return None
        if not api_key:
            return None

        prompt_ctx = self._compose_ai_prompt_context(symbol, row, source_urls)
        baseline = prompt_ctx["baseline"]  # type: ignore[assignment]
        web_evidence = prompt_ctx["web_evidence"]  # type: ignore[assignment]
        evidence_urls = prompt_ctx["evidence_urls"]  # type: ignore[assignment]
        industry_evidence = (
            prompt_ctx.get("industry_evidence")
            if isinstance(prompt_ctx.get("industry_evidence"), list)
            else []
        )
        inferred_sector = str(prompt_ctx.get("inferred_sector", "")).strip() or "Unknown"
        board_label = str(prompt_ctx.get("board_label", "")).strip() or self._market_board_label(symbol)
        core_event_candidates = (
            prompt_ctx.get("core_event_candidates")
            if isinstance(prompt_ctx.get("core_event_candidates"), list)
            else []
        )
        industry_event_candidates = (
            prompt_ctx.get("industry_event_candidates")
            if isinstance(prompt_ctx.get("industry_event_candidates"), list)
            else []
        )
        breakout_candidates = (
            prompt_ctx.get("breakout_candidates")
            if isinstance(prompt_ctx.get("breakout_candidates"), list)
            else []
        )
        prompt = str(prompt_ctx["prompt"])
        if not isinstance(baseline, AIAnalysisRecord):
            baseline = self._heuristic_ai_analysis(symbol, row, source_urls)
        if not isinstance(web_evidence, list):
            web_evidence = []
        if not isinstance(evidence_urls, list):
            evidence_urls = []
        if not isinstance(industry_evidence, list):
            industry_evidence = []
        combined_evidence: list[dict[str, str]] = []
        combined_evidence.extend(web_evidence)
        combined_evidence.extend(industry_evidence)
        stock_name = self._resolve_symbol_name(symbol, row)
        body = {
            "model": provider.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": "You are an A-share short-term trend analyst. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
        }

        try:
            with httpx.Client(timeout=float(self._config.ai_timeout_sec)) as client:
                response = client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
            response.raise_for_status()
            payload = response.json()
            content = (
                payload.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                raise ValueError("AI_EMPTY_CONTENT")

            fallback_confidence = row.ai_confidence if row else 0.6
            parsed: dict[str, object] | None = None
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                json_match = re.search(r"\{[\s\S]+\}", content)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        parsed = None

            conclusion = (
                str(parsed.get("conclusion", "")).strip()
                if parsed
                else self._extract_conclusion_from_text(content)
            ) or self._extract_conclusion_from_text(content)
            confidence = (
                float(parsed.get("confidence", fallback_confidence))
                if parsed
                else self._extract_confidence_from_text(content, fallback_confidence)
            )
            confidence = max(0.0, min(1.0, float(confidence)))
            summary = (
                str(parsed.get("summary", "")).strip() if parsed else content.replace("\n", " ").strip()
            )
            if not summary:
                summary = baseline.summary
            if len(summary) > 120:
                summary = f"{summary[:120]}..."

            breakout_raw = str(parsed.get("breakout_date", "")).strip() if parsed else ""
            breakout_date = self._sanitize_breakout_date(
                symbol,
                breakout_raw,
                baseline.breakout_date or self._now_date(),
            )
            if breakout_candidates:
                candles = self._ensure_candles(symbol)
                normalized_candidates = {
                    self._align_date_to_candles(candles, str(item))
                    for item in breakout_candidates
                    if str(item).strip()
                }
                normalized_candidates.discard("")
                if normalized_candidates and breakout_date not in normalized_candidates:
                    breakout_date = sorted(normalized_candidates)[0]

            trend_bull_type = str(parsed.get("trend_bull_type", "")).strip() if parsed else ""
            if not trend_bull_type:
                trend_bull_type = baseline.trend_bull_type or "Unknown"

            theme_name = str(parsed.get("theme_name", "")).strip() if parsed else ""
            if not theme_name:
                theme_name = baseline.theme_name or "未知题材"

            rise_reasons: list[str] = []
            if parsed and isinstance(parsed.get("rise_reasons"), list):
                rise_reasons = [str(item).strip() for item in parsed["rise_reasons"] if str(item).strip()]
            if not rise_reasons:
                rise_reasons = baseline.rise_reasons
            rise_reasons = self._sanitize_ai_rise_reasons(
                rise_reasons,
                symbol=symbol,
                core_event_candidates=core_event_candidates,
                industry_event_candidates=industry_event_candidates,
                industry_hint=inferred_sector,
            )

            theme_name = self._sanitize_theme_name(
                theme_name,
                evidence=combined_evidence,
                inferred_sector=inferred_sector,
            )
            if rise_reasons and rise_reasons[0].startswith("行业驱动：") and inferred_sector != "Unknown":
                theme_name = inferred_sector
            summary = self._build_compact_ai_summary(
                symbol=symbol,
                breakout_date=breakout_date,
                board_label=board_label,
                inferred_sector=inferred_sector,
                rise_reasons=rise_reasons,
                raw_summary=summary,
                row=row,
            )

            return AIAnalysisRecord(
                provider=provider.id,
                symbol=symbol,
                name=stock_name,
                fetched_at=self._now_datetime(),
                source_urls=evidence_urls[:8] or source_urls,
                summary=summary,
                conclusion=conclusion,
                confidence=round(confidence, 2),
                breakout_date=breakout_date,
                trend_bull_type=trend_bull_type,
                theme_name=theme_name,
                rise_reasons=rise_reasons[:2],
                error_code=None,
            )
        except httpx.TimeoutException:
            return baseline.model_copy(
                update={
                    "provider": provider.id,
                    "source_urls": evidence_urls[:8] or source_urls,
                    "summary": "AI请求超时，已回退本地规则分析。",
                    "error_code": "AI_TIMEOUT",
                }
            )
        except Exception:
            return baseline.model_copy(
                update={
                    "provider": provider.id,
                    "source_urls": evidence_urls[:8] or source_urls,
                    "summary": "AI请求失败，已回退本地规则分析。",
                    "error_code": "AI_PROVIDER_ERROR",
                }
            )

    def test_ai_provider(
        self,
        provider: AIProviderConfig,
        *,
        fallback_api_key: str = "",
        fallback_api_key_path: str = "",
        timeout_sec: int = 10,
    ) -> AIProviderTestResponse:
        if not provider.base_url.strip() or not provider.model.strip():
            return AIProviderTestResponse(
                ok=False,
                provider_id=provider.id,
                latency_ms=0,
                message="缺少 base_url 或 model",
                error_code="INVALID_PROVIDER_CONFIG",
            )

        api_key = self._resolve_provider_api_key(
            provider,
            fallback_api_key=fallback_api_key,
            fallback_api_key_path=fallback_api_key_path,
        )
        if not api_key:
            return AIProviderTestResponse(
                ok=False,
                provider_id=provider.id,
                latency_ms=0,
                message="缺少 API 凭证，请填写 api_key 或 api_key_path",
                error_code="AI_KEY_MISSING",
            )

        body = {
            "model": provider.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": "You are a connectivity probe."},
                {"role": "user", "content": "Reply only OK"},
            ],
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=float(timeout_sec)) as client:
                resp = client.post(
                    f"{provider.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=body,
                )
            latency_ms = int((time.perf_counter() - started) * 1000)
            resp.raise_for_status()
            payload = resp.json()
            content = (
                payload.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                return AIProviderTestResponse(
                    ok=False,
                    provider_id=provider.id,
                    latency_ms=latency_ms,
                    message="返回为空，Provider 可能不可用",
                    error_code="AI_EMPTY_CONTENT",
                )
            return AIProviderTestResponse(
                ok=True,
                provider_id=provider.id,
                latency_ms=latency_ms,
                message=f"连接成功，耗时 {latency_ms}ms",
                error_code=None,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AIProviderTestResponse(
                ok=False,
                provider_id=provider.id,
                latency_ms=latency_ms,
                message=f"请求超时（{timeout_sec}s）",
                error_code="AI_TIMEOUT",
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return AIProviderTestResponse(
                ok=False,
                provider_id=provider.id,
                latency_ms=latency_ms,
                message=f"请求失败: {type(exc).__name__}",
                error_code="AI_PROVIDER_ERROR",
            )

    def get_ai_prompt_preview(self, symbol: str) -> dict[str, object]:
        row = self._latest_rows.get(symbol) or self._build_row_from_candles(symbol)
        if row and symbol not in self._latest_rows:
            self._latest_rows[symbol] = row
        source_urls = self._enabled_ai_source_urls()
        prompt_ctx = self._compose_ai_prompt_context(symbol, row, source_urls)
        baseline = prompt_ctx.get("baseline")
        return {
            "symbol": symbol,
            "name": self._resolve_symbol_name(symbol, row),
            "provider": self._config.ai_provider,
            "prompt": str(prompt_ctx.get("prompt", "")),
            "web_evidence_count": len(prompt_ctx.get("web_evidence", []))
            if isinstance(prompt_ctx.get("web_evidence"), list)
            else 0,
            "inferred_sector": str(prompt_ctx.get("inferred_sector", "")),
            "baseline_breakout": baseline.breakout_date if isinstance(baseline, AIAnalysisRecord) else None,
        }

    def _gen_candles(self, seed: int, start_price: float = 40.0) -> list[CandlePoint]:
        points: list[CandlePoint] = []
        close = start_price
        for i in range(119, -1, -1):
            date = self._days_ago(i)
            drift = math.sin((i + seed) / 9.0) * 0.9 + (0.2 if seed % 3 == 0 else 0.35)
            open_price = max(5.0, close + drift * 0.35)
            high = open_price + abs(drift) * 1.8 + 0.6
            low = max(1.0, open_price - abs(drift) * 1.4 - 0.5)
            close = round(low + (high - low) * 0.68, 2)
            points.append(
                CandlePoint(
                    time=date,
                    open=round(open_price, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=close,
                    volume=int(2_000_000 + (math.cos((i + seed) / 7.0) + 1.4) * 1_700_000),
                    amount=float(int(close * 100_000_000)),
                    price_source="approx" if seed % 4 == 0 else "vwap",
                )
            )
        return points

    def _ensure_candles(self, symbol: str) -> list[CandlePoint]:
        if symbol not in self._candles_map:
            window_bars = max(120, int(self._config.candles_window_bars))
            real_candles = load_candles_for_symbol(
                self._config.tdx_data_path,
                symbol,
                window=window_bars,
                market_data_source=self._config.market_data_source,
                akshare_cache_dir=self._config.akshare_cache_dir,
            )
            if real_candles:
                self._candles_map[symbol] = real_candles
            else:
                seed = self._hash_seed(symbol)
                self._candles_map[symbol] = self._gen_candles(seed, 20.0 + (seed % 70))
        return self._candles_map[symbol]

    @staticmethod
    def _intraday_axis() -> list[str]:
        morning = []
        for i in range(120):
            total = 9 * 60 + 30 + i
            hh = total // 60
            mm = total % 60
            morning.append(f"{hh:02d}:{mm:02d}")
        afternoon = []
        for i in range(120):
            total = 13 * 60 + i
            hh = total // 60
            mm = total % 60
            afternoon.append(f"{hh:02d}:{mm:02d}")
        return morning + afternoon

    def _gen_intraday_points(self, symbol: str, date: str, base_price: float) -> list[IntradayPoint]:
        times = self._intraday_axis()
        seed = self._hash_seed(f"{symbol}-{date}")

        points: list[IntradayPoint] = []
        price = base_price
        turnover = 0.0
        total_volume = 0

        for index, time in enumerate(times):
            wave = math.sin((index + seed) / 10.0) * 0.22
            drift = (index / len(times) - 0.5) * (0.5 if seed % 3 == 0 else 0.28)
            micro = math.cos((index + seed) / 5.0) * 0.06
            price = max(1.0, price + wave * 0.05 + drift * 0.03 + micro)
            rounded_price = round(price, 2)

            volume = max(1200, int(4000 + math.sin((index + seed) / 8.0) * 1300 + (seed % 7) * 180))
            total_volume += volume
            turnover += rounded_price * volume
            avg_price = round(turnover / total_volume, 2)

            points.append(
                IntradayPoint(
                    time=time,
                    price=rounded_price,
                    avg_price=avg_price,
                    volume=volume,
                    price_source="approx" if index % 79 == 0 else "vwap",
                )
            )

        return points

    @staticmethod
    def _mock_symbol(index: int) -> str:
        market = "sh" if index % 2 == 0 else "sz"
        code = str(100000 + index).zfill(6)[-6:]
        return f"{market}{code}"

    @staticmethod
    def _mock_name(index: int) -> str:
        sectors = ["科技", "医药", "消费", "金融", "能源", "制造", "材料", "军工"]
        return f"{sectors[index % len(sectors)]}样本{index + 1}"

    def _pool_record(
        self,
        index: int,
        mode: ScreenerMode,
        stage: Literal["input", "step1", "step2", "step3", "step4"],
    ) -> ScreenerResult:
        strict_offset = 0.0 if mode == "strict" else 0.015
        base_ret = 0.06 + ((index % 200) / 1000.0) + strict_offset
        trend: TrendClass = "B" if index % 17 == 0 else "A_B" if index % 5 == 0 else "A"
        stage_label: Stage = "Early" if index % 3 == 0 else "Mid" if index % 3 == 1 else "Late"
        degraded = stage != "input" and index % 211 == 0
        theme_stage = THEME_STAGES[index % len(THEME_STAGES)]

        return ScreenerResult(
            symbol=self._mock_symbol(index),
            name=self._mock_name(index),
            latest_price=round(8.0 + (index % 220) * 0.9, 2),
            day_change=round(-2.1 + (index % 11) * 0.42, 2),
            day_change_pct=round(-0.03 + (index % 15) * 0.0045, 4),
            score=max(20, 92 - (index % 70)),
            ret40=base_ret,
            turnover20=0.035 + (index % 25) * 0.002,
            amount20=220_000_000 + (index % 150) * 18_000_000,
            amplitude20=0.025 + (index % 12) * 0.002,
            retrace20=0.03 + (index % 22) * 0.01,
            pullback_days=1 + (index % 6),
            ma10_above_ma20_days=4 + (index % 11),
            ma5_above_ma10_days=2 + (index % 9),
            price_vs_ma20=-0.03 + (index % 13) * 0.008,
            vol_slope20=-0.2 + (index % 20) * 0.07,
            up_down_volume_ratio=0.9 + (index % 18) * 0.06,
            pullback_volume_ratio=0.45 + (index % 11) * 0.08,
            has_blowoff_top=stage != "input" and index % 31 == 0,
            has_divergence_5d=stage != "input" and index % 17 == 0,
            has_upper_shadow_risk=stage != "input" and index % 19 == 0,
            ai_confidence=0.4 + (index % 11) * 0.05,
            theme_stage=theme_stage,
            trend_class=trend,
            stage=stage_label,
            labels=["全市场候选"] if stage == "input" else ["活跃", "趋势延续"],
            reject_reasons=[],
            degraded=degraded,
            degraded_reason="PARTIAL_CACHE_FALLBACK" if degraded else None,
        )

    @staticmethod
    def _build_result(item: dict[str, str], index: int, mode: ScreenerMode) -> ScreenerResult:
        mode_offset = 0 if mode == "strict" else 4
        score = 86 - index * 4 + mode_offset
        degraded = item["symbol"] == "sz002230"
        theme_stage = THEME_STAGES[index % len(THEME_STAGES)]

        trend_class: TrendClass = item["trend"]  # type: ignore[assignment]
        stage: Stage = item["stage"]  # type: ignore[assignment]

        return ScreenerResult(
            symbol=item["symbol"],
            name=item["name"],
            latest_price=round(42 + index * 3.6, 2),
            day_change=round(-1.2 + (index % 5) * 0.8, 2),
            day_change_pct=round(-0.018 + (index % 6) * 0.009, 4),
            score=score,
            ret40=0.22 + index * 0.031,
            turnover20=0.053 + index * 0.008,
            amount20=580_000_000 + index * 80_000_000,
            amplitude20=0.032 + index * 0.003,
            retrace20=0.06 + index * 0.02,
            pullback_days=1 + (index % 4),
            ma10_above_ma20_days=8 + (index % 7),
            ma5_above_ma10_days=6 + (index % 5),
            price_vs_ma20=0.008 + (index % 6) * 0.005,
            vol_slope20=0.14 + (index % 8) * 0.05,
            up_down_volume_ratio=1.26 + (index % 6) * 0.1,
            pullback_volume_ratio=0.5 + (index % 5) * 0.07,
            has_blowoff_top=index % 21 == 0,
            has_divergence_5d=index % 13 == 0,
            has_upper_shadow_risk=index % 17 == 0,
            ai_confidence=0.63 + (index % 4) * 0.08,
            theme_stage=theme_stage,
            trend_class=trend_class,
            stage=stage,
            labels=["活跃", "高波动" if trend_class == "B" else "趋势延续"],
            reject_reasons=[],
            degraded=degraded,
            degraded_reason="FLOAT_SHARES_CACHE_USED" if degraded else None,
        )

    def _pool_range(
        self,
        start: int,
        count: int,
        mode: ScreenerMode,
        stage: Literal["input", "step1", "step2", "step3"],
    ) -> list[ScreenerResult]:
        return [self._pool_record(start + i, mode, stage) for i in range(count)]

    @staticmethod
    def _build_screener_run_id() -> str:
        return f"{int(datetime.now().timestamp() * 1000)}-{uuid4().hex[:6]}"

    def _store_screener_run_detail(self, detail: ScreenerRunDetail) -> ScreenerRunDetail:
        latest_rows: dict[str, ScreenerResult] = {}
        for row in detail.step_pools.input:
            latest_rows[row.symbol] = row
        for row in detail.step_pools.step1:
            latest_rows[row.symbol] = row
        for row in detail.step_pools.step2:
            latest_rows[row.symbol] = row
        for row in detail.step_pools.step3:
            latest_rows[row.symbol] = row
        for row in detail.step_pools.step4:
            latest_rows[row.symbol] = row
        self._latest_rows = latest_rows
        self._run_store[detail.run_id] = detail
        return detail

    def _is_screener_result_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_SCREENER_RESULT_CACHE", True)

    @staticmethod
    def _screener_input_pool_load_timeout_sec() -> float | None:
        raw = os.getenv("TDX_TREND_SCREENER_INPUT_POOL_LOAD_TIMEOUT_SEC", "").strip()
        if not raw:
            return 120.0
        try:
            parsed = float(raw)
        except Exception:
            return 120.0
        if parsed <= 0:
            return None
        return parsed

    @staticmethod
    def _screener_result_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_SCREENER_RESULT_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 24 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 24 * 3600.0

    @staticmethod
    def _is_screener_result_cache_eligible(params: ScreenerParams) -> bool:
        _ = params
        return True

    def _build_screener_result_cache_key(self, params: ScreenerParams) -> str:
        normalized_as_of_date = str(params.as_of_date or "").strip() or "__latest__"
        params_raw = params.model_dump(exclude_none=True)
        params_raw["as_of_date"] = normalized_as_of_date
        payload = {
            "version": self._SCREENER_RESULT_CACHE_VERSION,
            "params": params_raw,
            "config": {
                "tdx_root": str(self._resolve_user_path(self._config.tdx_data_path)),
                "market_data_source": str(self._config.market_data_source).strip(),
                "candles_window_bars": int(self._config.candles_window_bars),
            },
            "algo": {
                "wyckoff_algo_version": str(self._wyckoff_event_algo_version).strip(),
                "wyckoff_data_version": str(self._wyckoff_event_data_version).strip(),
            },
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _screener_result_cache_file(self, params: ScreenerParams) -> Path:
        cache_key = self._build_screener_result_cache_key(params)
        return self._resolve_screener_result_cache_dir() / f"{cache_key}.json"

    def _load_screener_result_cache(self, params: ScreenerParams) -> ScreenerRunDetail | None:
        if not self._is_screener_result_cache_enabled():
            return None
        if not self._is_screener_result_cache_eligible(params):
            return None
        path = self._screener_result_cache_file(params)
        if not path.exists():
            return None
        ttl_sec = self._screener_result_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            detail_raw = raw.get("detail")
            if not isinstance(detail_raw, dict):
                return None
            return ScreenerRunDetail(**detail_raw)
        except Exception:
            return None

    def _save_screener_result_cache(self, params: ScreenerParams, detail: ScreenerRunDetail) -> bool:
        if not self._is_screener_result_cache_enabled():
            return False
        if not self._is_screener_result_cache_eligible(params):
            return False
        path = self._screener_result_cache_file(params)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "created_at": self._now_datetime(),
                "detail": detail.model_dump(exclude_none=True),
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    def _clone_screener_detail_for_new_run(
        self,
        cached_detail: ScreenerRunDetail,
        *,
        run_id: str,
        params: ScreenerParams,
    ) -> ScreenerRunDetail:
        return cached_detail.model_copy(
            update={
                "run_id": run_id,
                "created_at": self._now_datetime(),
                "as_of_date": params.as_of_date,
                "params": params,
            }
        )

    def create_screener_run(self, params: ScreenerParams) -> ScreenerRunDetail:
        run_id = self._build_screener_run_id()
        cached_detail = self._load_screener_result_cache(params)
        if cached_detail is not None:
            detail = self._clone_screener_detail_for_new_run(
                cached_detail,
                run_id=run_id,
                params=params,
            )
            return self._store_screener_run_detail(detail)

        real_input_pool, real_error, _cache_hit = self._load_input_pool_rows(
            markets=params.markets,
            return_window_days=params.return_window_days,
            as_of_date=params.as_of_date,
        )
        if real_input_pool:
            step1_pool = (
                sorted(
                    (
                        row
                        for row in real_input_pool
                        if row.turnover20 >= params.turnover_threshold
                        and row.amount20 >= params.amount_threshold
                        and row.amplitude20 >= params.amplitude_threshold
                    ),
                    key=lambda row: row.ret40,
                    reverse=True,
                )[: params.top_n]
            )
            if len(step1_pool) > 400:
                step1_pool = step1_pool[:400]

            loose_padding = 0.02 if params.mode == "loose" else 0.0
            loose_days = 1 if params.mode == "loose" else 0
            retrace_min = max(0.0, 0.05 - loose_padding)
            retrace_max = min(0.8, 0.25 + loose_padding)
            max_pullback_days = 3 + loose_days
            min_ma10_days = max(0, 5 - loose_days)
            min_ma5_days = max(0, 3 - loose_days)

            step2_pool = [
                row
                for row in step1_pool
                if row.retrace20 >= retrace_min
                and row.retrace20 <= retrace_max
                and row.pullback_days <= max_pullback_days
                and row.ma10_above_ma20_days >= min_ma10_days
                and row.ma5_above_ma10_days >= min_ma5_days
                and abs(row.price_vs_ma20) <= 0.08
                and row.price_vs_ma20 >= 0
                and row.trend_class != "B"
            ]

            step3_pool = [
                row
                for row in step2_pool
                if row.vol_slope20 >= 0.05
                and row.up_down_volume_ratio >= 1.3
                and row.pullback_volume_ratio <= 0.9
                and not row.has_blowoff_top
                and not row.has_divergence_5d
                and not row.has_upper_shadow_risk
                and not row.degraded
            ]

            step4_source = [
                row
                for row in step3_pool
                if row.ai_confidence >= 0.55 and row.theme_stage in ("发酵中", "高潮")
            ]
            step4_pool = [
                row.model_copy(update={"labels": list({*row.labels, "待买观察"})})
                for row in sorted(
                    step4_source,
                    key=lambda row: row.score + row.ai_confidence * 20,
                    reverse=True,
                )[:8]
            ]
            has_degraded_rows = any(row.degraded for row in real_input_pool)

            detail = ScreenerRunDetail(
                run_id=run_id,
                created_at=self._now_datetime(),
                as_of_date=params.as_of_date,
                params=params,
                step_summary=ScreenerStepSummary(
                    input_count=len(real_input_pool),
                    step1_count=len(step1_pool),
                    step2_count=len(step2_pool),
                    step3_count=len(step3_pool),
                    step4_count=len(step4_pool),
                ),
                step_pools=ScreenerStepPools(
                    input=real_input_pool,
                    step1=step1_pool,
                    step2=step2_pool,
                    step3=step3_pool,
                    step4=step4_pool,
                ),
                results=step4_pool,
                degraded=bool(has_degraded_rows or real_error),
                degraded_reason=real_error,
            )
            self._save_screener_result_cache(params, detail)
            return self._store_screener_run_detail(detail)

        mode = params.mode

        input_count = 5100
        step1_count = 400
        step2_count = 68 if mode == "strict" else 92
        step3_count = 26 if mode == "strict" else 37

        input_pool = self._pool_range(0, input_count, mode, "input")
        step1_pool = [
            row.model_copy(update={"score": 78 - (index % 30), "labels": ["活跃强势池"]})
            for index, row in enumerate(input_pool[:step1_count])
        ]
        step2_pool = [
            row.model_copy(update={"score": 82 - (index % 28), "labels": ["图形待确认"]})
            for index, row in enumerate(step1_pool[:step2_count])
        ]
        step3_pool = [
            row.model_copy(update={"score": 86 - (index % 20), "labels": ["量能健康"]})
            for index, row in enumerate(step2_pool[:step3_count])
        ]

        final_base = STOCK_POOL[:5] if mode == "strict" else STOCK_POOL
        step4_pool: list[ScreenerResult] = []
        for index, item in enumerate(final_base):
            base_result = self._build_result(item, index, mode)
            if index < len(step3_pool):
                base_result = base_result.model_copy(
                    update={
                        "symbol": step3_pool[index].symbol,
                        "name": step3_pool[index].name,
                    }
                )
            step4_pool.append(base_result.model_copy(update={"labels": ["题材发酵", "待买观察"]}))

        detail = ScreenerRunDetail(
            run_id=run_id,
            created_at=self._now_datetime(),
            as_of_date=params.as_of_date,
            params=params,
            step_summary=ScreenerStepSummary(
                input_count=input_count,
                step1_count=step1_count,
                step2_count=step2_count,
                step3_count=step3_count,
                step4_count=len(step4_pool),
            ),
            step_pools=ScreenerStepPools(
                input=input_pool,
                step1=step1_pool,
                step2=step2_pool,
                step3=step3_pool,
                step4=step4_pool,
            ),
            results=step4_pool,
            degraded=any(item.degraded for item in step4_pool),
            degraded_reason=real_error or "PARTIAL_FLOAT_SHARES_FROM_CACHE"
            if any(item.degraded for item in step4_pool)
            else None,
        )
        return self._store_screener_run_detail(detail)

    def get_screener_run(self, run_id: str) -> ScreenerRunDetail | None:
        return self._run_store.get(run_id)

    def get_latest_screener_run(self) -> ScreenerRunDetail | None:
        if not self._run_store:
            return None
        return max(self._run_store.values(), key=lambda run: run.created_at)

    def get_candles_payload(self, symbol: str) -> dict[str, object]:
        candles = self._ensure_candles(symbol)
        degraded = any(point.price_source == "approx" for point in candles)
        return {
            "symbol": symbol,
            "candles": candles,
            "degraded": degraded,
            "degraded_reason": "MINUTE_DATA_MISSING_PARTIAL" if degraded else None,
        }

    def get_intraday_payload(self, symbol: str, date: str) -> IntradayPayload:
        real_points, real_date = load_intraday_for_symbol_date(
            tdx_root=self._config.tdx_data_path,
            symbol=symbol,
            target_date=date,
        )
        if real_points:
            return IntradayPayload(
                symbol=symbol,
                date=real_date or date or self._now_date(),
                points=real_points,
                degraded=False,
                degraded_reason=None,
            )

        candles = self._ensure_candles(symbol)
        fallback_date = candles[-1].time if candles else self._now_date()
        matched = next((item for item in candles if item.time == date), None)
        target_date = date if matched else fallback_date
        base_price = matched.close if matched else (candles[-1].close if candles else 20.0)
        points = self._gen_intraday_points(symbol, target_date, base_price)
        degraded = True

        return IntradayPayload(
            symbol=symbol,
            date=target_date,
            points=points,
            degraded=degraded,
            degraded_reason="LC1_DATA_NOT_FOUND_FALLBACK_APPROX",
        )

    def get_analysis(self, symbol: str) -> StockAnalysisResponse:
        cached = self._latest_rows.get(symbol)
        if cached:
            analysis = StockAnalysis(
                symbol=symbol,
                suggest_start_date=self._days_ago(53),
                suggest_stage=cached.stage,
                suggest_trend_class=cached.trend_class,
                confidence=max(0.5, min(0.95, cached.ai_confidence)),
                reason=f"基于近端K线与量能自动识别，综合分 {cached.score}。",
                theme_stage=cached.theme_stage,
                degraded=cached.degraded,
                degraded_reason=cached.degraded_reason,
            )
            return StockAnalysisResponse(analysis=analysis, annotation=self._annotation_store.get(symbol))

        base = next((stock for stock in STOCK_POOL if stock["symbol"] == symbol), None)
        analysis = StockAnalysis(
            symbol=symbol,
            suggest_start_date=self._days_ago(53),
            suggest_stage=(base["stage"] if base else "Mid"),  # type: ignore[arg-type]
            suggest_trend_class=(base["trend"] if base else "Unknown"),  # type: ignore[arg-type]
            confidence=0.74,
            reason="均线结构稳定，回调量能可控，板块热度仍在发酵。",
            theme_stage="发酵中",
            degraded=symbol == "sz002230",
            degraded_reason="AI_TIMEOUT_CACHE_FALLBACK" if symbol == "sz002230" else None,
        )
        return StockAnalysisResponse(analysis=analysis, annotation=self._annotation_store.get(symbol))

    def save_annotation(self, annotation: StockAnnotation) -> StockAnnotation:
        self._annotation_store[annotation.symbol] = annotation
        self._persist_app_state()
        return annotation

    @staticmethod
    def _resolve_signal_priority(signals: list[str]) -> tuple[str, list[str]]:
        order = {"B": 3, "A": 2, "C": 1}
        unique = [s for s in ["B", "A", "C"] if s in signals]
        if not unique:
            return "C", []
        primary = unique[0]
        secondary = [s for s in unique[1:] if order[s] < order[primary]]
        return primary, secondary

    @staticmethod
    def _phase_hint(phase: str) -> str:
        mapping = {
            "吸筹A": "疑似筹码吸收初期，重点观察抛压衰减。",
            "吸筹B": "震荡测试阶段，关注ST/TSO后的承接力度。",
            "吸筹C": "Spring 触发区，需确认假跌破后的快速收复。",
            "吸筹D": "SOS/JOC 强势确认，等待回踩与量能配合。",
            "吸筹E": "LPS 附近，偏向趋势延续但需防止高位背离。",
            "派发A": "出现派发迹象，建议降低仓位并谨慎追高。",
            "派发B": "派发风险增强，优先规避或仅做观察。",
            "派发C": "派发链路较完整，建议回避买入信号。",
            "派发D": "中后段弱势结构，关注反弹失败风险。",
            "派发E": "弱势延续概率高，等待新结构形成后再评估。",
        }
        return mapping.get(phase, "阶段未明，建议结合结构与量能进一步确认。")


    def _latest_run_id(self) -> str | None:
        if not self._run_store:
            return None
        latest = max(self._run_store.values(), key=lambda run: run.created_at)
        return latest.run_id

    def _resolve_signal_candidates(
        self,
        *,
        mode: SignalScanMode,
        run_id: str | None,
        trend_step: TrendPoolStep = "auto",
        as_of_date: str | None = None,
    ) -> tuple[list[ScreenerResult], str | None, str | None, str | None]:
        if mode == "trend_pool":
            resolved_run_id = run_id or self._latest_run_id()
            if not resolved_run_id:
                return [], "TREND_POOL_RUN_NOT_FOUND", None, as_of_date
            run = self._run_store.get(resolved_run_id)
            if run is None:
                return [], "TREND_POOL_RUN_NOT_FOUND", resolved_run_id, as_of_date
            if trend_step == "step4":
                source = run.step_pools.step4
            elif trend_step == "step3":
                source = run.step_pools.step3
            elif trend_step == "step2":
                source = run.step_pools.step2
            elif trend_step == "step1":
                source = run.step_pools.step1
            else:
                source = run.step_pools.step4 or run.step_pools.step3
            if not source:
                if trend_step == "auto":
                    reason = "TREND_POOL_EMPTY"
                else:
                    reason = f"TREND_POOL_{trend_step.upper()}_EMPTY"
                return [], reason, resolved_run_id, (as_of_date or run.as_of_date)
            return source, run.degraded_reason if run.degraded else None, resolved_run_id, (as_of_date or run.as_of_date)

        source, error, cache_hit = self._load_input_pool_rows(
            markets=self._config.markets,
            return_window_days=self._config.return_window_days,
            as_of_date=as_of_date,
        )
        if not source:
            fallback_rows: list[ScreenerResult] = []
            for stock in STOCK_POOL:
                row = self._build_row_from_candles(stock["symbol"], as_of_date=as_of_date)
                if row:
                    fallback_rows.append(row)
            if fallback_rows:
                return fallback_rows, error or "FULL_MARKET_TDX_UNAVAILABLE_FALLBACK_CANDLES", None, as_of_date
            return [], error or "FULL_MARKET_SCAN_EMPTY", None, as_of_date

        ordered_rows = sorted(source, key=lambda row: str(row.symbol).strip().lower())
        deduped_rows: list[ScreenerResult] = []
        seen_symbols: set[str] = set()
        for row in ordered_rows:
            symbol = str(row.symbol).strip().lower()
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            deduped_rows.append(row)

        protect_limit = max(1000, int(self._FULL_MARKET_SYSTEM_PROTECT_LIMIT))
        protect_hit = len(deduped_rows) > protect_limit
        if protect_hit:
            deduped_rows = deduped_rows[:protect_limit]

        reasons: list[str] = []
        if error:
            reasons.append(str(error))
        if cache_hit:
            reasons.append("INPUT_POOL_CACHE_HIT")
        if protect_hit:
            reasons.append("FULL_MARKET_SYSTEM_LIMIT_HIT")
        degraded_reason = ";".join(reasons) if reasons else None
        return deduped_rows, degraded_reason, None, as_of_date

    def _calc_wyckoff_snapshot(
        self,
        row: ScreenerResult,
        window_days: int,
        *,
        as_of_date: str | None = None,
    ) -> dict[str, object]:
        """Calculate Wyckoff snapshot with lazy persisted daily event cache."""
        candles, resolved_as_of_date = self._slice_candles_as_of(
            self._ensure_candles(row.symbol), as_of_date
        )
        symbol = str(row.symbol).strip().lower()
        trade_date = str(resolved_as_of_date or "").strip()
        data_source = str(self._config.market_data_source).strip() or "unknown"
        params_hash = build_wyckoff_params_hash(window_days)

        if symbol and trade_date:
            read_started = time.perf_counter()
            cached = self._wyckoff_event_store.get_snapshot(
                symbol=symbol,
                trade_date=trade_date,
                window_days=window_days,
                algo_version=self._wyckoff_event_algo_version,
                data_source=data_source,
                data_version=self._wyckoff_event_data_version,
                params_hash=params_hash,
            )
            read_duration_ms = (time.perf_counter() - read_started) * 1000.0
            self._record_wyckoff_snapshot_read_latency(read_duration_ms)
            if cached is not None:
                self._bump_wyckoff_metric("cache_hits", 1)
                return cached

        self._bump_wyckoff_metric("cache_misses", 1)
        snapshot = SignalAnalyzer.calculate_wyckoff_snapshot(row, candles, window_days)
        quality_flags = self._inspect_wyckoff_snapshot_quality(snapshot, trade_date=trade_date)
        self._record_wyckoff_snapshot_quality(quality_flags)
        if symbol and trade_date:
            write_ok = self._wyckoff_event_store.upsert_snapshot(
                symbol=symbol,
                trade_date=trade_date,
                window_days=window_days,
                algo_version=self._wyckoff_event_algo_version,
                data_source=data_source,
                data_version=self._wyckoff_event_data_version,
                params_hash=params_hash,
                snapshot=snapshot,
            )
            if write_ok:
                self._bump_wyckoff_metric("lazy_fill_writes", 1)
        return snapshot

    def _is_signals_disk_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_SIGNALS_DISK_CACHE", True)

    @staticmethod
    def _signals_disk_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_SIGNALS_DISK_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 6 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 6 * 3600.0

    def _build_signals_disk_cache_key(self, core_cache_key: str) -> str:
        payload = {
            "version": self._SIGNALS_RESULT_CACHE_VERSION,
            "core_key": str(core_cache_key).strip(),
            "market_data_source": str(self._config.market_data_source).strip(),
            "candles_window_bars": int(self._config.candles_window_bars),
            "wyckoff_algo_version": str(self._wyckoff_event_algo_version).strip(),
            "wyckoff_data_version": str(self._wyckoff_event_data_version).strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _signals_disk_cache_file(self, core_cache_key: str) -> Path:
        cache_key = self._build_signals_disk_cache_key(core_cache_key)
        return self._resolve_signals_cache_dir() / f"{cache_key}.json"

    def _load_signals_disk_cache(self, core_cache_key: str) -> SignalsResponse | None:
        path = self._signals_disk_cache_file(core_cache_key)
        if not path.exists():
            return None
        ttl_sec = self._signals_disk_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        try:
            payload_raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload_raw, dict):
                return None
            body = payload_raw.get("payload")
            if not isinstance(body, dict):
                return None
            return SignalsResponse(**body)
        except Exception:
            return None

    def _save_signals_disk_cache(self, core_cache_key: str, payload: SignalsResponse) -> bool:
        path = self._signals_disk_cache_file(core_cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "schema_version": 1,
                "created_at": self._now_datetime(),
                "payload": payload.model_dump(exclude_none=True),
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    def _signals_cache_key(
        self,
        *,
        mode: SignalScanMode,
        run_id: str | None,
        trend_step: TrendPoolStep,
        market_filters: list[Market],
        board_filters: list[BoardFilter],
        as_of_date: str | None,
        window_days: int,
        min_score: float,
        require_sequence: bool,
        min_event_count: int,
    ) -> str:
        payload = {
            "mode": mode,
            "run_id": run_id or "",
            "trend_step": trend_step,
            "market_filters": market_filters,
            "board_filters": board_filters,
            "as_of_date": as_of_date or "",
            "window_days": window_days,
            "min_score": round(min_score, 3),
            "require_sequence": require_sequence,
            "min_event_count": min_event_count,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=True)

    def get_signals(
        self,
        *,
        mode: SignalScanMode = "trend_pool",
        run_id: str | None = None,
        trend_step: TrendPoolStep = "auto",
        market_filters: list[Market] | None = None,
        board_filters: list[BoardFilter] | None = None,
        as_of_date: str | None = None,
        refresh: bool = False,
        window_days: int = 60,
        min_score: float = 60,
        require_sequence: bool = False,
        min_event_count: int = 1,
    ) -> SignalsResponse:
        candidates, degraded_reason, resolved_run_id, resolved_as_of_date = self._resolve_signal_candidates(
            mode=mode,
            run_id=run_id,
            trend_step=trend_step,
            as_of_date=as_of_date,
        )
        allowed_markets = {"sh", "sz", "bj"}
        normalized_market_filters = list(dict.fromkeys(item for item in (market_filters or []) if item in allowed_markets))
        if normalized_market_filters:
            candidates = [row for row in candidates if self._row_matches_market_filters(row, normalized_market_filters)]
        allowed_board_filters = {"main", "gem", "star", "beijing", "st"}
        normalized_board_filters = list(
            dict.fromkeys(item for item in (board_filters or []) if item in allowed_board_filters)
        )
        if normalized_board_filters:
            candidates = [row for row in candidates if self._row_matches_board_filters(row, normalized_board_filters)]
        source_count = len(candidates)
        cache_key = self._signals_cache_key(
            mode=mode,
            run_id=resolved_run_id if mode == "trend_pool" else run_id,
            trend_step=trend_step if mode == "trend_pool" else "auto",
            market_filters=normalized_market_filters,
            board_filters=normalized_board_filters,
            as_of_date=resolved_as_of_date,
            window_days=window_days,
            min_score=min_score,
            require_sequence=require_sequence,
            min_event_count=min_event_count,
        )
        now_ts = time.time()
        cache_ttl_sec = 180
        cached = self._signals_cache.get(cache_key)
        if not refresh and cached and now_ts - cached[0] <= cache_ttl_sec:
            cached_payload = cached[1]
            return cached_payload.model_copy(
                update={
                    "cache_hit": True,
                    "as_of_date": resolved_as_of_date or cached_payload.as_of_date,
                    "degraded": cached_payload.degraded or bool(degraded_reason),
                    "degraded_reason": degraded_reason or cached_payload.degraded_reason,
                    "source_count": source_count or cached_payload.source_count,
                }
            )

        if (not refresh) and self._is_signals_disk_cache_enabled():
            cached_disk_payload = self._load_signals_disk_cache(cache_key)
            if cached_disk_payload is not None:
                self._signals_cache[cache_key] = (now_ts, cached_disk_payload)
                return cached_disk_payload.model_copy(
                    update={
                        "cache_hit": True,
                        "as_of_date": resolved_as_of_date or cached_disk_payload.as_of_date,
                        "degraded": cached_disk_payload.degraded or bool(degraded_reason),
                        "degraded_reason": degraded_reason or cached_disk_payload.degraded_reason,
                        "source_count": source_count or cached_disk_payload.source_count,
                    }
                )

        items: list[SignalResult] = []
        seen_symbols: set[str] = set()

        for row in candidates:
            if row.symbol in seen_symbols:
                continue
            snapshot = self._calc_wyckoff_snapshot(row, window_days=window_days, as_of_date=resolved_as_of_date)
            events = snapshot["events"] if isinstance(snapshot["events"], list) else []
            risk_events = snapshot["risk_events"] if isinstance(snapshot["risk_events"], list) else []
            raw_event_dates = snapshot.get("event_dates")
            event_dates: dict[str, str] = {}
            if isinstance(raw_event_dates, dict):
                for event_code, event_date in raw_event_dates.items():
                    code_text = str(event_code).strip()
                    date_text = str(event_date).strip()
                    if code_text and date_text:
                        event_dates[code_text] = date_text
            raw_event_chain = snapshot.get("event_chain")
            event_chain: list[dict[str, str]] = []
            if isinstance(raw_event_chain, list):
                for node in raw_event_chain:
                    if not isinstance(node, dict):
                        continue
                    code_text = str(node.get("event", "")).strip()
                    date_text = str(node.get("date", "")).strip()
                    category_text = str(node.get("category", "")).strip()
                    if code_text and date_text:
                        event_chain.append({
                            "event": code_text,
                            "date": date_text,
                            "category": category_text or "other",
                        })
            if not event_chain and event_dates:
                risk_event_set = {str(event).strip() for event in risk_events}
                for code_text, date_text in sorted(event_dates.items(), key=lambda item: (item[1], item[0])):
                    event_chain.append({
                        "event": code_text,
                        "date": date_text,
                        "category": "distributionRisk" if code_text in risk_event_set else "accumulation",
                    })
            sequence_ok = bool(snapshot["sequence_ok"])
            entry_quality_score = float(snapshot["entry_quality_score"])
            total_event_count = len(event_chain) if event_chain else len(events) + len(risk_events)

            if total_event_count < min_event_count:
                continue
            if require_sequence and not sequence_ok:
                continue
            if entry_quality_score < min_score:
                continue

            signal_tags: list[str] = []
            if entry_quality_score >= 82:
                signal_tags.append("B")
            elif entry_quality_score >= 68:
                signal_tags.append("A")
            else:
                signal_tags.append("C")
            if risk_events:
                signal_tags.append("C")
            if str(snapshot["phase"]).startswith("吸筹D") or str(snapshot["phase"]).startswith("吸筹E"):
                signal_tags.append("B")

            primary, secondary = self._resolve_signal_priority(signal_tags)
            trigger_date = str(snapshot["trigger_date"])
            try:
                trigger_dt = datetime.strptime(trigger_date, "%Y-%m-%d")
            except ValueError:
                trigger_dt = datetime.now()
                trigger_date = trigger_dt.strftime("%Y-%m-%d")
            expire_dt = trigger_dt + timedelta(days=2)
            expire_date = expire_dt.strftime("%Y-%m-%d")
            wyckoff_signal = str(snapshot["signal"])
            phase = str(snapshot["phase"])
            phase_hint = str(snapshot["phase_hint"])
            reason = f"{phase_hint} 关键事件={wyckoff_signal or '无'}"
            if risk_events:
                reason = f"{reason} 风险={','.join(risk_events)}"

            items.append(
                SignalResult(
                    symbol=row.symbol,
                    name=row.name,
                    primary_signal=primary,  # type: ignore[arg-type]
                    secondary_signals=secondary,  # type: ignore[arg-type]
                    trigger_date=trigger_date,
                    expire_date=expire_date,
                    trigger_reason=reason,
                    priority=3 if primary == "B" else 2 if primary == "A" else 1,
                    wyckoff_phase=phase,
                    wyckoff_signal=wyckoff_signal,
                    structure_hhh=str(snapshot["structure_hhh"]),
                    wy_event_count=total_event_count,
                    wy_sequence_ok=sequence_ok,
                    entry_quality_score=entry_quality_score,
                    wy_events=[str(event) for event in events],
                    wy_risk_events=[str(event) for event in risk_events],
                    wy_event_dates=event_dates,
                    wy_event_chain=event_chain,
                    phase_hint=phase_hint,
                    scan_mode=mode,
                    event_strength_score=float(snapshot["event_strength_score"]),
                    phase_score=float(snapshot["phase_score"]),
                    structure_score=float(snapshot["structure_score"]),
                    trend_score=float(snapshot["trend_score"]),
                    volatility_score=float(snapshot["volatility_score"]),
                )
            )
            seen_symbols.add(row.symbol)

        items.sort(
            key=lambda item: (
                item.entry_quality_score,
                item.priority,
                item.wy_event_count,
                item.trigger_date,
            ),
            reverse=True,
        )

        degraded = bool(degraded_reason) or any(row.degraded for row in candidates)
        payload = SignalsResponse(
            items=items,
            mode=mode,
            as_of_date=resolved_as_of_date,
            generated_at=self._now_datetime(),
            cache_hit=False,
            degraded=degraded,
            degraded_reason=degraded_reason,
            source_count=source_count,
        )
        self._signals_cache[cache_key] = (now_ts, payload)
        if self._is_signals_disk_cache_enabled():
            self._save_signals_disk_cache(cache_key, payload)
        return payload

    @staticmethod
    def _detect_primary_board_from_symbol(symbol: str) -> str | None:
        normalized = str(symbol).strip().lower()
        if len(normalized) < 8:
            return None
        market = normalized[:2]
        code = normalized[2:]
        if market == "bj":
            return "beijing"
        if market == "sh":
            if code.startswith("688") or code.startswith("689"):
                return "star"
            return "main"
        if market == "sz":
            if code.startswith("300") or code.startswith("301"):
                return "gem"
            return "main"
        return None

    @staticmethod
    def _is_st_stock(name: str) -> bool:
        normalized_name = re.sub(r"\s+", "", str(name).upper())
        return "ST" in normalized_name

    @staticmethod
    def _row_matches_market_filters(
        row: ScreenerResult,
        market_filters: list[Market],
    ) -> bool:
        if not market_filters:
            return True
        symbol = str(row.symbol).strip().lower()
        if len(symbol) < 2:
            return False
        return symbol[:2] in set(market_filters)

    @classmethod
    def _row_matches_board_filters(
        cls,
        row: ScreenerResult,
        board_filters: list[BoardFilter],
    ) -> bool:
        if not board_filters:
            return True
        selected = set(board_filters)
        is_st = cls._is_st_stock(row.name)
        if is_st and "st" not in selected:
            return False

        selected_boards = [item for item in board_filters if item != "st"]
        if not selected_boards:
            return is_st

        board = cls._detect_primary_board_from_symbol(row.symbol)
        if board is None:
            return False
        return board in selected_boards

    @staticmethod
    def _select_step_source_for_backtest(
        *,
        trend_step: TrendPoolStep,
        step1_pool: list[ScreenerResult],
        step2_pool: list[ScreenerResult],
        step3_pool: list[ScreenerResult],
        step4_pool: list[ScreenerResult],
    ) -> list[ScreenerResult]:
        if trend_step == "step4":
            return step4_pool
        if trend_step == "step3":
            return step3_pool
        if trend_step == "step2":
            return step2_pool
        if trend_step == "step1":
            return step1_pool
        return step4_pool or step3_pool

    @staticmethod
    def _run_screener_filters_for_backtest(
        rows: list[ScreenerResult],
        params: ScreenerParams,
    ) -> tuple[list[ScreenerResult], list[ScreenerResult], list[ScreenerResult], list[ScreenerResult]]:
        step1_pool = (
            sorted(
                (
                    row
                    for row in rows
                    if row.turnover20 >= params.turnover_threshold
                    and row.amount20 >= params.amount_threshold
                    and row.amplitude20 >= params.amplitude_threshold
                ),
                key=lambda row: row.ret40,
                reverse=True,
            )[: params.top_n]
        )
        if len(step1_pool) > 400:
            step1_pool = step1_pool[:400]

        loose_padding = 0.02 if params.mode == "loose" else 0.0
        loose_days = 1 if params.mode == "loose" else 0
        retrace_min = max(0.0, 0.05 - loose_padding)
        retrace_max = min(0.8, 0.25 + loose_padding)
        max_pullback_days = 3 + loose_days
        min_ma10_days = max(0, 5 - loose_days)
        min_ma5_days = max(0, 3 - loose_days)

        step2_pool = [
            row
            for row in step1_pool
            if row.retrace20 >= retrace_min
            and row.retrace20 <= retrace_max
            and row.pullback_days <= max_pullback_days
            and row.ma10_above_ma20_days >= min_ma10_days
            and row.ma5_above_ma10_days >= min_ma5_days
            and abs(row.price_vs_ma20) <= 0.08
            and row.price_vs_ma20 >= 0
            and row.trend_class != "B"
        ]

        step3_pool = [
            row
            for row in step2_pool
            if row.vol_slope20 >= 0.05
            and row.up_down_volume_ratio >= 1.3
            and row.pullback_volume_ratio <= 0.9
            and not row.has_blowoff_top
            and not row.has_divergence_5d
            and not row.has_upper_shadow_risk
            and not row.degraded
        ]

        step4_source = [
            row
            for row in step3_pool
            if row.ai_confidence >= 0.55 and row.theme_stage in ("发酵中", "高潮")
        ]
        step4_pool = sorted(
            step4_source,
            key=lambda row: row.score + row.ai_confidence * 20,
            reverse=True,
        )[:8]

        return step1_pool, step2_pool, step3_pool, step4_pool

    def _build_backtest_scan_dates(self, date_from: str, date_to: str) -> list[str]:
        start_dt = self._parse_date(date_from)
        end_dt = self._parse_date(date_to)
        if start_dt is None or end_dt is None:
            return []
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
        out: list[str] = []
        cursor = start_dt
        while cursor <= end_dt:
            if cursor.weekday() < 5:
                out.append(cursor.strftime("%Y-%m-%d"))
            cursor += timedelta(days=1)
        return out

    def _build_weekly_refresh_dates(self, scan_dates: list[str]) -> list[str]:
        out: list[str] = []
        last_key: tuple[int, int] | None = None
        for day in scan_dates:
            parsed = self._parse_date(day)
            if parsed is None:
                continue
            year, week_no, _ = parsed.isocalendar()
            key = (year, week_no)
            if key != last_key:
                out.append(day)
                last_key = key
        if not out and scan_dates:
            out.append(scan_dates[0])
        return out

    @staticmethod
    def _next_scan_date(scan_dates: list[str], current_date: str) -> str | None:
        for day in scan_dates:
            if day > current_date:
                return day
        return None

    def _resolve_backtest_refresh_dates(
        self,
        *,
        scan_dates: list[str],
        pool_roll_mode: BacktestPoolRollMode,
        refresh_dates: list[str] | None = None,
    ) -> list[str]:
        if not scan_dates:
            return []
        if refresh_dates is None:
            if pool_roll_mode == "weekly":
                refresh_dates_used = self._build_weekly_refresh_dates(scan_dates)
            elif pool_roll_mode == "position":
                refresh_dates_used = [scan_dates[0]]
            else:
                refresh_dates_used = list(scan_dates)
            return refresh_dates_used or [scan_dates[0]]

        scan_date_set = set(scan_dates)
        refresh_dates_used = [day for day in refresh_dates if day in scan_date_set]
        return refresh_dates_used or [scan_dates[0]]

    def _is_backtest_input_pool_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_INPUT_POOL_CACHE", True)

    @staticmethod
    def _backtest_input_pool_preload_workers() -> int:
        raw = os.getenv("TDX_TREND_BACKTEST_INPUT_POOL_WORKERS", "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except Exception:
                pass
        cpu_count = os.cpu_count() or 4
        return max(1, min(8, cpu_count))

    @staticmethod
    def _backtest_input_pool_runtime_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_INPUT_POOL_RUNTIME_TTL_SEC", "").strip()
        if not raw:
            return 15 * 60.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 15 * 60.0

    @staticmethod
    def _backtest_input_pool_runtime_max_items() -> int:
        raw = os.getenv("TDX_TREND_BACKTEST_INPUT_POOL_RUNTIME_MAX_ITEMS", "").strip()
        if not raw:
            return 512
        try:
            return max(32, int(raw))
        except Exception:
            return 512

    def _load_backtest_input_pool_runtime_cache(
        self,
        cache_key: str,
    ) -> tuple[list[ScreenerResult], str | None] | None:
        ttl_sec = self._backtest_input_pool_runtime_ttl_sec()
        with self._backtest_input_pool_runtime_cache_lock:
            cached = self._backtest_input_pool_runtime_cache.get(cache_key)
            if cached is None:
                return None
            created_at, rows, load_error = cached
            if ttl_sec > 0 and (time.time() - created_at) > ttl_sec:
                self._backtest_input_pool_runtime_cache.pop(cache_key, None)
                return None
            return list(rows), load_error

    def _save_backtest_input_pool_runtime_cache(
        self,
        cache_key: str,
        rows: list[ScreenerResult],
        load_error: str | None,
    ) -> None:
        if not rows and (not load_error):
            return
        now_ts = time.time()
        with self._backtest_input_pool_runtime_cache_lock:
            self._backtest_input_pool_runtime_cache[cache_key] = (now_ts, list(rows), load_error)
            max_items = self._backtest_input_pool_runtime_max_items()
            if len(self._backtest_input_pool_runtime_cache) > max_items:
                stale_keys = sorted(
                    self._backtest_input_pool_runtime_cache.items(),
                    key=lambda item: float(item[1][0]),
                )
                overflow = len(self._backtest_input_pool_runtime_cache) - max_items
                for key, _value in stale_keys[:overflow]:
                    self._backtest_input_pool_runtime_cache.pop(key, None)

    def _clear_backtest_input_pool_runtime_cache(self) -> None:
        with self._backtest_input_pool_runtime_cache_lock:
            self._backtest_input_pool_runtime_cache.clear()

    @staticmethod
    def _backtest_input_pool_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_INPUT_POOL_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 12 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 12 * 3600.0

    def _build_backtest_input_pool_cache_key(
        self,
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        as_of_date: str,
    ) -> str:
        payload = {
            "version": self._BACKTEST_INPUT_POOL_CACHE_VERSION,
            "tdx_root": str(self._resolve_user_path(tdx_root)),
            "markets": sorted({str(item).strip().lower() for item in markets if str(item).strip()}),
            "return_window_days": int(return_window_days),
            "as_of_date": str(as_of_date).strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _backtest_input_pool_cache_file(self, cache_key: str) -> Path:
        cache_dir = self._resolve_backtest_input_pool_cache_dir()
        return cache_dir / f"{cache_key}.json"

    def _load_backtest_input_pool_cache(
        self,
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        as_of_date: str,
    ) -> tuple[list[ScreenerResult], str | None] | None:
        cache_key = self._build_backtest_input_pool_cache_key(
            tdx_root=tdx_root,
            markets=markets,
            return_window_days=return_window_days,
            as_of_date=as_of_date,
        )
        path = self._backtest_input_pool_cache_file(cache_key)
        if not path.exists():
            return None
        ttl_sec = self._backtest_input_pool_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            rows_raw = payload.get("rows")
            if not isinstance(rows_raw, list):
                return None
            rows: list[ScreenerResult] = []
            for item in rows_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    rows.append(ScreenerResult(**item))
                except Exception:
                    continue
            load_error_raw = payload.get("load_error")
            load_error = str(load_error_raw).strip() if isinstance(load_error_raw, str) and load_error_raw.strip() else None
            return rows, load_error
        except Exception:
            return None

    def _save_backtest_input_pool_cache(
        self,
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        as_of_date: str,
        rows: list[ScreenerResult],
        load_error: str | None,
    ) -> bool:
        if not rows:
            return False
        cache_key = self._build_backtest_input_pool_cache_key(
            tdx_root=tdx_root,
            markets=markets,
            return_window_days=return_window_days,
            as_of_date=as_of_date,
        )
        path = self._backtest_input_pool_cache_file(cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "schema_version": 1,
                "created_at": self._now_datetime(),
                "as_of_date": str(as_of_date).strip(),
                "load_error": (str(load_error).strip() if (load_error and str(load_error).strip()) else None),
                "rows": [row.model_dump(exclude_none=True) for row in rows],
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    @staticmethod
    def _normalize_input_pool_cache_as_of_date(as_of_date: str | None) -> str:
        text = str(as_of_date or "").strip()
        if text:
            return text
        return "__latest__"

    def _load_input_pool_rows(
        self,
        *,
        markets: list[str],
        return_window_days: int,
        as_of_date: str | None,
    ) -> tuple[list[ScreenerResult], str | None, bool]:
        tdx_root = self._config.tdx_data_path
        cache_enabled = self._is_backtest_input_pool_cache_enabled()
        cache_as_of_date = self._normalize_input_pool_cache_as_of_date(as_of_date)
        cache_key = self._build_backtest_input_pool_cache_key(
            tdx_root=tdx_root,
            markets=markets,
            return_window_days=return_window_days,
            as_of_date=cache_as_of_date,
        )
        if cache_enabled:
            cached_runtime = self._load_backtest_input_pool_runtime_cache(cache_key)
            if cached_runtime is not None:
                rows_cached, load_error_cached = cached_runtime
                return list(rows_cached), load_error_cached, True

            cached = self._load_backtest_input_pool_cache(
                tdx_root=tdx_root,
                markets=markets,
                return_window_days=return_window_days,
                as_of_date=cache_as_of_date,
            )
            if cached is not None:
                rows_cached, load_error_cached = cached
                self._save_backtest_input_pool_runtime_cache(cache_key, list(rows_cached), load_error_cached)
                return list(rows_cached), load_error_cached, True

        rows, load_error = load_input_pool_from_tdx(
            tdx_root=tdx_root,
            markets=markets,
            return_window_days=return_window_days,
            as_of_date=as_of_date,
            load_timeout_sec=self._screener_input_pool_load_timeout_sec(),
        )
        typed_rows = [row for row in rows if isinstance(row, ScreenerResult)]
        if cache_enabled:
            self._save_backtest_input_pool_runtime_cache(cache_key, typed_rows, load_error)
        if cache_enabled and typed_rows:
            self._save_backtest_input_pool_cache(
                tdx_root=tdx_root,
                markets=markets,
                return_window_days=return_window_days,
                as_of_date=cache_as_of_date,
                rows=typed_rows,
                load_error=load_error,
            )
        return rows, load_error, False

    def _is_backtest_trend_filter_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_TREND_FILTER_CACHE", True)

    @staticmethod
    def _backtest_trend_filter_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_TREND_FILTER_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 24 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 24 * 3600.0

    def _build_backtest_trend_filter_cache_key(
        self,
        *,
        as_of_date: str,
        trend_step: TrendPoolStep,
        board_filters: list[BoardFilter],
        max_symbols: int,
        screener_params: ScreenerParams,
    ) -> str:
        payload = {
            "version": self._BACKTEST_TREND_FILTER_CACHE_VERSION,
            "as_of_date": str(as_of_date).strip(),
            "trend_step": str(trend_step).strip(),
            "board_filters": sorted({str(item).strip().lower() for item in board_filters if str(item).strip()}),
            "max_symbols": int(max_symbols),
            "tdx_root": str(self._resolve_user_path(self._config.tdx_data_path)),
            "markets": sorted({str(item).strip().lower() for item in screener_params.markets if str(item).strip()}),
            "mode": str(screener_params.mode).strip(),
            "return_window_days": int(screener_params.return_window_days),
            "top_n": int(screener_params.top_n),
            "turnover_threshold": round(float(screener_params.turnover_threshold), 8),
            "amount_threshold": round(float(screener_params.amount_threshold), 4),
            "amplitude_threshold": round(float(screener_params.amplitude_threshold), 8),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _backtest_trend_filter_cache_file(self, cache_key: str) -> Path:
        cache_dir = self._resolve_backtest_trend_filter_cache_dir()
        return cache_dir / f"{cache_key}.json"

    def _load_backtest_trend_filter_cache(
        self,
        *,
        as_of_date: str,
        trend_step: TrendPoolStep,
        board_filters: list[BoardFilter],
        max_symbols: int,
        screener_params: ScreenerParams,
    ) -> list[str] | None:
        cache_key = self._build_backtest_trend_filter_cache_key(
            as_of_date=as_of_date,
            trend_step=trend_step,
            board_filters=board_filters,
            max_symbols=max_symbols,
            screener_params=screener_params,
        )
        path = self._backtest_trend_filter_cache_file(cache_key)
        if not path.exists():
            return None
        ttl_sec = self._backtest_trend_filter_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            symbols_raw = payload.get("symbols")
            if not isinstance(symbols_raw, list):
                return None
            out: list[str] = []
            seen: set[str] = set()
            for item in symbols_raw:
                symbol = str(item).strip().lower()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                out.append(symbol)
            return out
        except Exception:
            return None

    def _save_backtest_trend_filter_cache(
        self,
        *,
        as_of_date: str,
        trend_step: TrendPoolStep,
        board_filters: list[BoardFilter],
        max_symbols: int,
        screener_params: ScreenerParams,
        symbols: list[str],
    ) -> bool:
        if not symbols:
            return False
        cache_key = self._build_backtest_trend_filter_cache_key(
            as_of_date=as_of_date,
            trend_step=trend_step,
            board_filters=board_filters,
            max_symbols=max_symbols,
            screener_params=screener_params,
        )
        path = self._backtest_trend_filter_cache_file(cache_key)
        try:
            deduped_symbols = list(dict.fromkeys(str(item).strip().lower() for item in symbols if str(item).strip()))
            if not deduped_symbols:
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "created_at": self._now_datetime(),
                "as_of_date": str(as_of_date).strip(),
                "symbols": deduped_symbols,
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    def _load_backtest_input_rows_by_dates(
        self,
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        refresh_dates: list[str],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> tuple[dict[str, tuple[list[object], str | None]], dict[str, int]]:
        refresh_unique = list(dict.fromkeys(str(day).strip() for day in refresh_dates if str(day).strip()))
        if not refresh_unique:
            return {}, {"cache_hit_days": 0, "cache_miss_days": 0, "cache_write_days": 0}

        cache_enabled = self._is_backtest_input_pool_cache_enabled()
        out: dict[str, tuple[list[object], str | None]] = {}
        cache_hit_days = 0
        cache_write_days = 0
        pending_days: list[str] = []
        total_days = len(refresh_unique)
        done_days_progress = 0

        def _emit_progress(day: str, done: int, total: int, message: str) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(day, done, total, message)
            except Exception:
                return

        if cache_enabled:
            for day in refresh_unique:
                cache_key = self._build_backtest_input_pool_cache_key(
                    tdx_root=tdx_root,
                    markets=markets,
                    return_window_days=return_window_days,
                    as_of_date=day,
                )
                cached_runtime = self._load_backtest_input_pool_runtime_cache(cache_key)
                if cached_runtime is not None:
                    rows_cached_runtime, load_error_cached_runtime = cached_runtime
                    out[day] = (list(rows_cached_runtime), load_error_cached_runtime)
                    cache_hit_days += 1
                    continue
                cached = self._load_backtest_input_pool_cache(
                    tdx_root=tdx_root,
                    markets=markets,
                    return_window_days=return_window_days,
                    as_of_date=day,
                )
                if cached is None:
                    pending_days.append(day)
                    continue
                rows_cached, load_error_cached = cached
                out[day] = (list(rows_cached), load_error_cached)
                self._save_backtest_input_pool_runtime_cache(cache_key, list(rows_cached), load_error_cached)
                cache_hit_days += 1
            done_days_progress = cache_hit_days
            if cache_hit_days > 0:
                _emit_progress(
                    refresh_unique[min(len(refresh_unique) - 1, cache_hit_days - 1)],
                    done_days_progress,
                    total_days,
                    f"滚动筛选准备：输入池预加载 {done_days_progress}/{total_days}（cache hit）",
                )
        else:
            pending_days = list(refresh_unique)

        def _load_for_day(as_of_date: str) -> tuple[str, list[object], str | None]:
            rows, load_error = load_input_pool_from_tdx(
                tdx_root=tdx_root,
                markets=markets,
                return_window_days=return_window_days,
                as_of_date=as_of_date,
            )
            return as_of_date, list(rows), load_error

        if len(pending_days) <= 1:
            for day in pending_days:
                as_of_date, rows, load_error = _load_for_day(day)
                out[as_of_date] = (rows, load_error)
                if cache_enabled:
                    cache_key = self._build_backtest_input_pool_cache_key(
                        tdx_root=tdx_root,
                        markets=markets,
                        return_window_days=return_window_days,
                        as_of_date=as_of_date,
                    )
                    typed_rows = [row for row in rows if isinstance(row, ScreenerResult)]
                    self._save_backtest_input_pool_runtime_cache(cache_key, typed_rows, load_error)
                    if self._save_backtest_input_pool_cache(
                        tdx_root=tdx_root,
                        markets=markets,
                        return_window_days=return_window_days,
                        as_of_date=as_of_date,
                        rows=typed_rows,
                        load_error=load_error,
                    ):
                        cache_write_days += 1
                done_days_progress += 1
                _emit_progress(
                    as_of_date,
                    done_days_progress,
                    total_days,
                    f"滚动筛选准备：输入池预加载 {done_days_progress}/{total_days}",
                )
            return out, {
                "cache_hit_days": int(cache_hit_days if cache_enabled else 0),
                "cache_miss_days": int(len(pending_days)),
                "cache_write_days": int(cache_write_days),
            }

        workers = max(1, min(self._backtest_input_pool_preload_workers(), len(pending_days)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_load_for_day, day): day
                for day in pending_days
            }
            for future in as_completed(future_map):
                day = future_map[future]
                try:
                    as_of_date, rows, load_error = future.result()
                    out[as_of_date] = (rows, load_error)
                    if cache_enabled:
                        cache_key = self._build_backtest_input_pool_cache_key(
                            tdx_root=tdx_root,
                            markets=markets,
                            return_window_days=return_window_days,
                            as_of_date=as_of_date,
                        )
                        typed_rows = [row for row in rows if isinstance(row, ScreenerResult)]
                        self._save_backtest_input_pool_runtime_cache(cache_key, typed_rows, load_error)
                        if self._save_backtest_input_pool_cache(
                            tdx_root=tdx_root,
                            markets=markets,
                            return_window_days=return_window_days,
                            as_of_date=as_of_date,
                            rows=typed_rows,
                            load_error=load_error,
                        ):
                            cache_write_days += 1
                except Exception as exc:  # noqa: BLE001
                    out[day] = ([], f"LOADER_EXCEPTION:{type(exc).__name__}")
                    as_of_date = day
                done_days_progress += 1
                _emit_progress(
                    as_of_date,
                    done_days_progress,
                    total_days,
                    f"滚动筛选准备：输入池预加载 {done_days_progress}/{total_days}",
                )
        return out, {
            "cache_hit_days": int(cache_hit_days if cache_enabled else 0),
            "cache_miss_days": int(len(pending_days)),
            "cache_write_days": int(cache_write_days),
        }

    @staticmethod
    def _build_allowed_symbols_by_date(
        *,
        scan_dates: list[str],
        pool_by_refresh_date: dict[str, set[str]],
    ) -> tuple[dict[str, set[str]], set[str], int]:
        allowed_symbols_by_date: dict[str, set[str]] = {}
        symbols_union: set[str] = set()
        empty_days = 0
        active_pool: set[str] = set()
        for day in scan_dates:
            if day in pool_by_refresh_date:
                active_pool = set(pool_by_refresh_date.get(day, set()))
            allowed_today = set(active_pool)
            allowed_symbols_by_date[day] = allowed_today
            if allowed_today:
                symbols_union.update(allowed_today)
            else:
                empty_days += 1
        return allowed_symbols_by_date, symbols_union, empty_days

    def _build_backtest_screener_params_from_config(self) -> ScreenerParams:
        markets = [item for item in self._config.markets if item in {"sh", "sz", "bj"}]
        if not markets:
            markets = ["sh", "sz"]
        return ScreenerParams(
            markets=markets,
            mode="strict",
            as_of_date=None,
            return_window_days=max(5, min(120, int(self._config.return_window_days))),
            top_n=max(100, min(2000, int(self._config.top_n))),
            turnover_threshold=max(0.01, min(0.2, float(self._config.turnover_threshold))),
            amount_threshold=max(5e7, min(5e9, float(self._config.amount_threshold))),
            amplitude_threshold=max(0.01, min(0.15, float(self._config.amplitude_threshold))),
        )

    @staticmethod
    def _build_backtest_param_snapshot_note(
        payload: BacktestRunRequest,
        *,
        resolved_run_id: str | None,
        board_filters: list[BoardFilter],
    ) -> str:
        snapshot_payload = {
            "mode": payload.mode,
            "run_id": (resolved_run_id or payload.run_id or "").strip(),
            "trend_step": payload.trend_step,
            "pool_roll_mode": payload.pool_roll_mode,
            "board_filters": sorted(board_filters),
            "date_from": payload.date_from,
            "date_to": payload.date_to,
            "window_days": int(payload.window_days),
            "min_score": round(float(payload.min_score), 3),
            "require_sequence": bool(payload.require_sequence),
            "min_event_count": int(payload.min_event_count),
            "entry_events": list(payload.entry_events),
            "exit_events": list(payload.exit_events),
            "max_symbols": int(payload.max_symbols),
            "max_positions": int(payload.max_positions),
            "priority_mode": payload.priority_mode,
            "priority_topk_per_day": int(payload.priority_topk_per_day),
            "enforce_t1": bool(payload.enforce_t1),
        }
        raw = json.dumps(snapshot_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return (
            f"参数快照摘要: {digest} "
            f"(mode={payload.mode}, roll={payload.pool_roll_mode}, window={payload.window_days}, "
            f"min_score={payload.min_score}, min_event_count={payload.min_event_count}, "
            f"max_symbols={payload.max_symbols}, run_id={(resolved_run_id or payload.run_id or 'none')})"
        )

    def _resolve_backtest_trend_pool_params(
        self,
        requested_run_id: str | None,
    ) -> tuple[ScreenerParams, str | None, str | None, str | None]:
        run_id = (requested_run_id or "").strip() or None
        if run_id:
            run = self._run_store.get(run_id)
            if run is not None:
                degraded_reason = run.degraded_reason if run.degraded else None
                return run.params, run.run_id, degraded_reason, None
            fallback_note = f"筛选任务 {run_id} 不存在，已改用系统筛选参数重建滚动池。"
            return self._build_backtest_screener_params_from_config(), None, "TREND_POOL_RUN_NOT_FOUND", fallback_note

        latest_run_id = self._latest_run_id()
        if latest_run_id:
            latest_run = self._run_store.get(latest_run_id)
            if latest_run is not None:
                degraded_reason = latest_run.degraded_reason if latest_run.degraded else None
                return latest_run.params, latest_run.run_id, degraded_reason, None

        fallback_note = "未找到可用筛选任务，已改用系统筛选参数重建滚动池。"
        return self._build_backtest_screener_params_from_config(), None, "TREND_POOL_RUN_NOT_FOUND", fallback_note

    def _build_trend_pool_rolling_universe(
        self,
        *,
        payload: BacktestRunRequest,
        screener_params: ScreenerParams,
        board_filters: list[BoardFilter],
        refresh_dates: list[str] | None = None,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> tuple[list[str], dict[str, set[str]], list[str], list[str], list[str]]:
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            return [], {}, ["回测区间内无可扫描交易日。"], [], []

        refresh_dates_used = self._resolve_backtest_refresh_dates(
            scan_dates=scan_dates,
            pool_roll_mode=payload.pool_roll_mode,
            refresh_dates=refresh_dates,
        )
        total_refresh = max(1, len(refresh_dates_used))
        preload_progress_cap = max(1, total_refresh // 4)

        def _preload_progress(day: str, done: int, total: int, message: str) -> None:
            if progress_callback is None:
                return
            total_safe = max(1, int(total))
            cap = min(total_safe, preload_progress_cap)
            done_safe = max(0, min(int(done), total_safe))
            processed = min(cap, int(round((done_safe / total_safe) * cap)))
            progress_callback(day, processed, total_safe, message)

        pool_by_refresh_date: dict[str, set[str]] = {}
        empty_refresh_days = 0
        loader_error_counter: dict[str, int] = {}
        source_rows_total = 0
        trend_cache_enabled = self._is_backtest_trend_filter_cache_enabled()
        trend_cache_hit_days = 0
        trend_cache_miss_days = 0
        trend_cache_write_days = 0
        pending_refresh_dates: list[str] = []
        if trend_cache_enabled:
            for as_of_date in refresh_dates_used:
                cached_symbols = self._load_backtest_trend_filter_cache(
                    as_of_date=as_of_date,
                    trend_step=payload.trend_step,
                    board_filters=board_filters,
                    max_symbols=payload.max_symbols,
                    screener_params=screener_params,
                )
                if cached_symbols is None:
                    pending_refresh_dates.append(as_of_date)
                    trend_cache_miss_days += 1
                    continue
                pool_by_refresh_date[as_of_date] = set(cached_symbols)
                trend_cache_hit_days += 1
        else:
            pending_refresh_dates = list(refresh_dates_used)

        loaded_rows_by_date: dict[str, tuple[list[object], str | None]] = {}
        loader_cache_stats = {"cache_hit_days": 0, "cache_miss_days": 0, "cache_write_days": 0}
        if pending_refresh_dates:
            loaded_rows_by_date, loader_cache_stats = self._load_backtest_input_rows_by_dates(
                tdx_root=self._config.tdx_data_path,
                markets=screener_params.markets,
                return_window_days=screener_params.return_window_days,
                refresh_dates=pending_refresh_dates,
                progress_callback=_preload_progress,
            )
        for idx, as_of_date in enumerate(refresh_dates_used, start=1):
            if as_of_date in pool_by_refresh_date:
                if progress_callback is not None:
                    progress_callback(
                        as_of_date,
                        idx,
                        len(refresh_dates_used),
                        f"滚动筛选进度 {idx}/{len(refresh_dates_used)}（趋势快照 cache hit）",
                    )
                continue
            input_rows, load_error = loaded_rows_by_date.get(as_of_date, ([], "LOADER_MISS"))
            if load_error:
                loader_error_counter[load_error] = loader_error_counter.get(load_error, 0) + 1
            source_rows_total += len(input_rows)

            if not input_rows:
                pool_by_refresh_date[as_of_date] = set()
                empty_refresh_days += 1
                if progress_callback is not None:
                    progress_callback(
                        as_of_date,
                        idx,
                        len(refresh_dates_used),
                        f"滚动筛选进度 {idx}/{len(refresh_dates_used)}（当日数据为空）",
                    )
                continue

            step1_pool, step2_pool, step3_pool, step4_pool = self._run_screener_filters_for_backtest(
                input_rows,
                screener_params,
            )
            source = self._select_step_source_for_backtest(
                trend_step=payload.trend_step,
                step1_pool=step1_pool,
                step2_pool=step2_pool,
                step3_pool=step3_pool,
                step4_pool=step4_pool,
            )
            if board_filters:
                source = [row for row in source if self._row_matches_board_filters(row, board_filters)]

            day_symbols: list[str] = []
            seen_symbols: set[str] = set()
            for row in source:
                symbol = str(row.symbol).strip().lower()
                if not symbol or symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                day_symbols.append(symbol)
                if len(day_symbols) >= payload.max_symbols:
                    break

            pool_by_refresh_date[as_of_date] = set(day_symbols)
            if trend_cache_enabled and day_symbols:
                if self._save_backtest_trend_filter_cache(
                    as_of_date=as_of_date,
                    trend_step=payload.trend_step,
                    board_filters=board_filters,
                    max_symbols=payload.max_symbols,
                    screener_params=screener_params,
                    symbols=day_symbols,
                ):
                    trend_cache_write_days += 1
            if progress_callback is not None:
                progress_callback(
                    as_of_date,
                    idx,
                    len(refresh_dates_used),
                    f"滚动筛选进度 {idx}/{len(refresh_dates_used)}",
                )

        allowed_symbols_by_date, symbols_union, empty_days = self._build_allowed_symbols_by_date(
            scan_dates=scan_dates,
            pool_by_refresh_date=pool_by_refresh_date,
        )

        mode_label_map = {
            "daily": "每日滚动",
            "weekly": "每周滚动",
            "position": "持仓触发滚动",
        }
        mode_label = mode_label_map.get(payload.pool_roll_mode, "每日滚动")
        avg_source_rows = int(round(source_rows_total / max(1, len(refresh_dates_used))))
        notes = [
            (
                f"候选池构建: {mode_label}（扫描 {len(scan_dates)} 日，刷新 {len(refresh_dates_used)} 次，"
                f"每次刷新平均加载 {avg_source_rows} 只标的）。"
            ),
            f"滚动股票池并集数量: {len(symbols_union)}，单日上限: {payload.max_symbols}。",
        ]
        if empty_refresh_days > 0:
            notes.append(f"有 {empty_refresh_days} 个刷新日当日数据为空。")
        if loader_error_counter:
            parts = [f"{reason} x{count}" for reason, count in sorted(loader_error_counter.items())]
            notes.append(f"刷新日数据加载提示: {'; '.join(parts)}")
        if empty_days > 0:
            notes.append(f"有 {empty_days} 个交易日筛选为空，当日不会产生候选信号。")
        cache_hit_days = int(loader_cache_stats.get("cache_hit_days", 0))
        cache_miss_days = int(loader_cache_stats.get("cache_miss_days", 0))
        cache_write_days = int(loader_cache_stats.get("cache_write_days", 0))
        if (cache_hit_days + cache_miss_days) > 0:
            notes.append(
                f"刷新日输入池缓存: hit {cache_hit_days} / miss {cache_miss_days} / write {cache_write_days}。"
            )
        if trend_cache_enabled and (trend_cache_hit_days + trend_cache_miss_days) > 0:
            notes.append(
                f"趋势快照缓存: hit {trend_cache_hit_days} / miss {trend_cache_miss_days} / write {trend_cache_write_days}。"
            )
        return sorted(symbols_union), allowed_symbols_by_date, notes, scan_dates, refresh_dates_used

    def _build_full_market_rolling_universe(
        self,
        *,
        payload: BacktestRunRequest,
        board_filters: list[BoardFilter],
        refresh_dates: list[str] | None = None,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> tuple[list[str], dict[str, set[str]], list[str], list[str], list[str]]:
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            return [], {}, ["回测区间内无可扫描交易日。"], [], []

        refresh_dates_used = self._resolve_backtest_refresh_dates(
            scan_dates=scan_dates,
            pool_roll_mode=payload.pool_roll_mode,
            refresh_dates=refresh_dates,
        )
        total_refresh = max(1, len(refresh_dates_used))
        preload_progress_cap = max(1, total_refresh // 4)

        def _preload_progress(day: str, done: int, total: int, message: str) -> None:
            if progress_callback is None:
                return
            total_safe = max(1, int(total))
            cap = min(total_safe, preload_progress_cap)
            done_safe = max(0, min(int(done), total_safe))
            processed = min(cap, int(round((done_safe / total_safe) * cap)))
            progress_callback(day, processed, total_safe, message)

        markets = [item for item in self._config.markets if item in {"sh", "sz", "bj"}]
        if not markets:
            markets = ["sh", "sz"]

        pool_by_refresh_date: dict[str, set[str]] = {}
        empty_refresh_days = 0
        loader_error_counter: dict[str, int] = {}
        source_rows_total = 0
        protect_limit = max(1000, int(self._FULL_MARKET_SYSTEM_PROTECT_LIMIT))
        system_limit_hit_days = 0
        loaded_rows_by_date, loader_cache_stats = self._load_backtest_input_rows_by_dates(
            tdx_root=self._config.tdx_data_path,
            markets=markets,
            return_window_days=max(5, min(120, int(self._config.return_window_days))),
            refresh_dates=refresh_dates_used,
            progress_callback=_preload_progress,
        )

        for idx, as_of_date in enumerate(refresh_dates_used, start=1):
            input_rows, load_error = loaded_rows_by_date.get(as_of_date, ([], "LOADER_MISS"))
            if load_error:
                loader_error_counter[load_error] = loader_error_counter.get(load_error, 0) + 1
            source_rows_total += len(input_rows)

            source = input_rows
            if board_filters:
                source = [row for row in source if self._row_matches_board_filters(row, board_filters)]

            day_symbols: list[str] = []
            seen_symbols: set[str] = set()
            for row in source:
                symbol = str(row.symbol).strip().lower()
                if not symbol or symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                day_symbols.append(symbol)

            day_symbols.sort()
            if len(day_symbols) > protect_limit:
                day_symbols = day_symbols[:protect_limit]
                system_limit_hit_days += 1
            if len(day_symbols) > payload.max_symbols:
                day_symbols = day_symbols[: payload.max_symbols]

            pool_by_refresh_date[as_of_date] = set(day_symbols)
            if not day_symbols:
                empty_refresh_days += 1

            if progress_callback is not None:
                progress_text = f"滚动筛选进度 {idx}/{len(refresh_dates_used)}"
                if not day_symbols:
                    progress_text = f"{progress_text}（当日候选为空）"
                progress_callback(
                    as_of_date,
                    idx,
                    len(refresh_dates_used),
                    progress_text,
                )

        allowed_symbols_by_date, symbols_union, empty_days = self._build_allowed_symbols_by_date(
            scan_dates=scan_dates,
            pool_by_refresh_date=pool_by_refresh_date,
        )

        mode_label_map = {
            "daily": "每日滚动",
            "weekly": "每周滚动",
            "position": "持仓触发滚动",
        }
        mode_label = mode_label_map.get(payload.pool_roll_mode, "每日滚动")
        avg_source_rows = int(round(source_rows_total / max(1, len(refresh_dates_used))))
        notes = [
            (
                f"全市场候选池构建: {mode_label}（扫描 {len(scan_dates)} 日，刷新 {len(refresh_dates_used)} 次，"
                f"每次刷新平均加载 {avg_source_rows} 只标的）。"
            ),
            f"滚动股票池并集数量: {len(symbols_union)}，单日上限: {payload.max_symbols}。",
        ]
        if system_limit_hit_days > 0:
            notes.append(
                f"触发系统保护上限: {protect_limit}（共 {system_limit_hit_days} 个刷新日被截断，仅用于资源保护）。"
            )
        if empty_refresh_days > 0:
            notes.append(f"有 {empty_refresh_days} 个刷新日当日候选为空。")
        if loader_error_counter:
            parts = [f"{reason} x{count}" for reason, count in sorted(loader_error_counter.items())]
            notes.append(f"刷新日数据加载提示: {'; '.join(parts)}")
        if empty_days > 0:
            notes.append(f"有 {empty_days} 个交易日筛选为空，当日不会产生候选信号。")
        cache_hit_days = int(loader_cache_stats.get("cache_hit_days", 0))
        cache_miss_days = int(loader_cache_stats.get("cache_miss_days", 0))
        cache_write_days = int(loader_cache_stats.get("cache_write_days", 0))
        if (cache_hit_days + cache_miss_days) > 0:
            notes.append(
                f"刷新日输入池缓存: hit {cache_hit_days} / miss {cache_miss_days} / write {cache_write_days}。"
            )
        return sorted(symbols_union), allowed_symbols_by_date, notes, scan_dates, refresh_dates_used

    def _is_backtest_matrix_engine_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_MATRIX_ENGINE", False)

    @staticmethod
    def _build_backtest_matrix_windows(payload: BacktestRunRequest) -> tuple[int, ...]:
        return tuple(sorted(set([10, 20, 40, 60, max(20, int(payload.window_days))])))

    def _is_backtest_signal_matrix_runtime_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_SIGNAL_MATRIX_RUNTIME_CACHE", True)

    @staticmethod
    def _backtest_signal_matrix_runtime_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_RUNTIME_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 15 * 60.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 15 * 60.0

    @staticmethod
    def _backtest_signal_matrix_runtime_max_items() -> int:
        raw = os.getenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_RUNTIME_CACHE_MAX_ITEMS", "").strip()
        if not raw:
            return 32
        try:
            return max(1, int(raw))
        except Exception:
            return 32

    @staticmethod
    def _build_backtest_signal_matrix_runtime_cache_key(*, matrix_cache_key: str, top_n: int) -> str:
        return f"{matrix_cache_key}|top_n={int(top_n)}"

    def _load_backtest_signal_matrix_runtime_cache(self, cache_key: str) -> BacktestSignalMatrix | None:
        if not self._is_backtest_signal_matrix_runtime_cache_enabled():
            return None
        ttl_sec = self._backtest_signal_matrix_runtime_ttl_sec()
        with self._backtest_signal_matrix_runtime_cache_lock:
            cached = self._backtest_signal_matrix_runtime_cache.get(cache_key)
            if cached is None:
                return None
            created_at, matrix = cached
            if ttl_sec > 0 and (time.time() - created_at) > ttl_sec:
                self._backtest_signal_matrix_runtime_cache.pop(cache_key, None)
                return None
            return matrix

    def _save_backtest_signal_matrix_runtime_cache(self, cache_key: str, matrix: BacktestSignalMatrix) -> None:
        if not self._is_backtest_signal_matrix_runtime_cache_enabled():
            return
        now_ts = time.time()
        with self._backtest_signal_matrix_runtime_cache_lock:
            self._backtest_signal_matrix_runtime_cache[cache_key] = (now_ts, matrix)
            max_items = self._backtest_signal_matrix_runtime_max_items()
            if len(self._backtest_signal_matrix_runtime_cache) > max_items:
                stale_items = sorted(
                    self._backtest_signal_matrix_runtime_cache.items(),
                    key=lambda item: float(item[1][0]),
                )
                overflow = len(self._backtest_signal_matrix_runtime_cache) - max_items
                for key, _value in stale_items[:overflow]:
                    self._backtest_signal_matrix_runtime_cache.pop(key, None)

    def _clear_backtest_signal_matrix_runtime_cache(self) -> None:
        with self._backtest_signal_matrix_runtime_cache_lock:
            self._backtest_signal_matrix_runtime_cache.clear()

    def _is_backtest_signal_matrix_disk_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_SIGNAL_MATRIX_DISK_CACHE", True)

    @staticmethod
    def _backtest_signal_matrix_disk_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 48 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 48 * 3600.0

    def _build_backtest_signal_matrix_disk_cache_key(self, *, matrix_cache_key: str, top_n: int) -> str:
        payload = {
            "version": self._BACKTEST_SIGNAL_MATRIX_CACHE_VERSION,
            "matrix_cache_key": str(matrix_cache_key).strip(),
            "top_n": int(top_n),
            "algo": str(self._backtest_matrix_algo_version).strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _backtest_signal_matrix_disk_cache_file(self, cache_key: str) -> Path:
        return self._resolve_backtest_signal_matrix_cache_dir() / f"{cache_key}.npz"

    def _load_backtest_signal_matrix_disk_cache(
        self,
        *,
        cache_key: str,
        expected_shape: tuple[int, int],
    ) -> BacktestSignalMatrix | None:
        if not self._is_backtest_signal_matrix_disk_cache_enabled():
            return None
        path = self._backtest_signal_matrix_disk_cache_file(cache_key)
        if not path.exists():
            return None
        ttl_sec = self._backtest_signal_matrix_disk_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        bool_fields = (
            "s1",
            "s2",
            "s3",
            "s4",
            "s5",
            "s6",
            "s7",
            "s8",
            "s9",
            "in_pool",
            "buy_signal",
            "sell_signal",
        )
        try:
            with np.load(path, allow_pickle=False) as data:
                out_bool: dict[str, np.ndarray] = {}
                for field in bool_fields:
                    if field not in data:
                        return None
                    arr = np.array(data[field], dtype=bool, copy=True)
                    if arr.shape != expected_shape:
                        return None
                    out_bool[field] = arr
                if "score" not in data:
                    return None
                score = np.array(data["score"], dtype=np.float64, copy=True)
                if score.shape != expected_shape:
                    return None
            return BacktestSignalMatrix(
                s1=out_bool["s1"],
                s2=out_bool["s2"],
                s3=out_bool["s3"],
                s4=out_bool["s4"],
                s5=out_bool["s5"],
                s6=out_bool["s6"],
                s7=out_bool["s7"],
                s8=out_bool["s8"],
                s9=out_bool["s9"],
                in_pool=out_bool["in_pool"],
                buy_signal=out_bool["buy_signal"],
                sell_signal=out_bool["sell_signal"],
                score=score,
            )
        except Exception:
            return None

    def _save_backtest_signal_matrix_disk_cache(
        self,
        *,
        cache_key: str,
        matrix: BacktestSignalMatrix,
    ) -> bool:
        if not self._is_backtest_signal_matrix_disk_cache_enabled():
            return False
        path = self._backtest_signal_matrix_disk_cache_file(cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp.npz")
            np.savez_compressed(
                tmp_path,
                s1=matrix.s1.astype(np.uint8),
                s2=matrix.s2.astype(np.uint8),
                s3=matrix.s3.astype(np.uint8),
                s4=matrix.s4.astype(np.uint8),
                s5=matrix.s5.astype(np.uint8),
                s6=matrix.s6.astype(np.uint8),
                s7=matrix.s7.astype(np.uint8),
                s8=matrix.s8.astype(np.uint8),
                s9=matrix.s9.astype(np.uint8),
                in_pool=matrix.in_pool.astype(np.uint8),
                buy_signal=matrix.buy_signal.astype(np.uint8),
                sell_signal=matrix.sell_signal.astype(np.uint8),
                score=matrix.score.astype(np.float64),
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    def _build_backtest_engine(self) -> BacktestEngine:
        return BacktestEngine(
            get_candles=self._ensure_candles,
            build_row=self._build_row_from_candles,
            calc_snapshot=lambda row, window_days, as_of_date: self._calc_wyckoff_snapshot(
                row,
                window_days=window_days,
                as_of_date=as_of_date,
            ),
            resolve_symbol_name=self._resolve_symbol_name,
        )

    def _run_matrix_execution(
        self,
        *,
        payload: BacktestRunRequest,
        symbols: list[str],
        allowed_symbols_by_date: dict[str, set[str]] | None,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        progress_total_dates: int | None = None,
        control_callback: Callable[[], None] | None = None,
    ) -> tuple[BacktestResponse, str]:
        if control_callback is not None:
            control_callback()
        total_start_ts = time.perf_counter()

        matrix_windows = self._build_backtest_matrix_windows(payload)
        data_version = (
            f"{self._config.market_data_source}|bars={int(self._config.candles_window_bars)}|"
            f"wy={self._wyckoff_event_data_version}|mode={payload.mode}|roll={payload.pool_roll_mode}"
        )
        cache_key = self._backtest_matrix_engine.build_cache_key(
            symbols=symbols,
            date_from=payload.date_from,
            date_to=payload.date_to,
            data_version=data_version,
            window_set=matrix_windows,
            algo_version=self._backtest_matrix_algo_version,
        )
        bundle_start_ts = time.perf_counter()
        bundle, cache_hit = self._backtest_matrix_engine.build_bundle(
            symbols=symbols,
            get_candles=self._ensure_candles,
            date_from=payload.date_from,
            date_to=payload.date_to,
            max_lookback_days=max(matrix_windows),
            cache_key=cache_key,
            use_cache=True,
        )
        bundle_elapsed = time.perf_counter() - bundle_start_ts
        if control_callback is not None:
            control_callback()
        if not bundle.dates or not bundle.symbols:
            raise ValueError("矩阵引擎未构建出有效数据，请检查K线覆盖范围。")
        self._validate_backtest_data_coverage_with_matrix_bundle(
            payload,
            symbols,
            bundle,
            scope_label="滚动池并集",
        )

        signal_start_ts = time.perf_counter()
        signal_top_n = max(50, min(2000, int(self._config.top_n)))
        signal_runtime_cache_key = self._build_backtest_signal_matrix_runtime_cache_key(
            matrix_cache_key=cache_key,
            top_n=signal_top_n,
        )
        signal_disk_cache_key = self._build_backtest_signal_matrix_disk_cache_key(
            matrix_cache_key=cache_key,
            top_n=signal_top_n,
        )
        signal_cache_source = "miss"
        signal_matrix = self._load_backtest_signal_matrix_runtime_cache(signal_runtime_cache_key)
        if signal_matrix is not None:
            signal_cache_source = "runtime"
        else:
            signal_matrix = self._load_backtest_signal_matrix_disk_cache(
                cache_key=signal_disk_cache_key,
                expected_shape=bundle.shape(),
            )
            if signal_matrix is not None:
                signal_cache_source = "disk"
                self._save_backtest_signal_matrix_runtime_cache(signal_runtime_cache_key, signal_matrix)
            else:
                signal_matrix = compute_backtest_signal_matrix(
                    bundle,
                    top_n=signal_top_n,
                )
                self._save_backtest_signal_matrix_runtime_cache(signal_runtime_cache_key, signal_matrix)
                self._save_backtest_signal_matrix_disk_cache(
                    cache_key=signal_disk_cache_key,
                    matrix=signal_matrix,
                )
        signal_elapsed = time.perf_counter() - signal_start_ts
        if control_callback is not None:
            control_callback()
        if progress_callback is not None and progress_total_dates is not None:
            total_safe = max(1, int(progress_total_dates))
            progress_callback(
                payload.date_to,
                total_safe,
                total_safe,
                "矩阵信号计算完成，开始执行回测撮合...",
            )

        engine = self._build_backtest_engine()
        execute_start_ts = time.perf_counter()
        result = engine.run(
            payload=payload,
            symbols=symbols,
            allowed_symbols_by_date=allowed_symbols_by_date,
            matrix_bundle=bundle,
            matrix_signals=signal_matrix,
            control_callback=control_callback,
        )
        execute_elapsed = time.perf_counter() - execute_start_ts
        total_elapsed = time.perf_counter() - total_start_ts

        shape_t, shape_n = bundle.shape()
        matrix_note = (
            "矩阵引擎已启用："
            f"shape={shape_t}x{shape_n}，windows={list(matrix_windows)}，"
            f"cache={'hit' if cache_hit else 'miss'}，signal_cache={signal_cache_source}，"
            f"key={cache_key[:12]}...；"
            f"耗时[建矩阵={bundle_elapsed:.2f}s, 算信号={signal_elapsed:.2f}s, 撮合={execute_elapsed:.2f}s, 总计={total_elapsed:.2f}s]"
        )
        return result, matrix_note

    def _resolve_matrix_rolling_universe(
        self,
        *,
        payload: BacktestRunRequest,
        board_filters: list[BoardFilter],
        trend_pool_params: ScreenerParams | None,
        progress_callback: Callable[[str, int, int, str], None] | None,
        control_callback: Callable[[], None] | None,
    ) -> tuple[list[str], dict[str, set[str]], list[str], list[str]]:
        if control_callback is not None:
            control_callback()
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            raise ValueError("回测区间内无可扫描交易日。")

        if payload.mode == "trend_pool":
            if trend_pool_params is None:
                raise ValueError("趋势池筛选参数不可用。")

            def _build(
                refresh_dates: list[str] | None,
                cb: Callable[[str, int, int, str], None] | None,
            ) -> tuple[list[str], dict[str, set[str]], list[str], list[str], list[str]]:
                return self._build_trend_pool_rolling_universe(
                    payload=payload,
                    screener_params=trend_pool_params,
                    board_filters=board_filters,
                    refresh_dates=refresh_dates,
                    progress_callback=cb,
                )

        elif payload.mode == "full_market":

            def _build(
                refresh_dates: list[str] | None,
                cb: Callable[[str, int, int, str], None] | None,
            ) -> tuple[list[str], dict[str, set[str]], list[str], list[str], list[str]]:
                return self._build_full_market_rolling_universe(
                    payload=payload,
                    board_filters=board_filters,
                    refresh_dates=refresh_dates,
                    progress_callback=cb,
                )

        else:
            raise ValueError(f"不支持的回测模式: {payload.mode}")

        if payload.pool_roll_mode == "position":
            seed_refresh_dates = [scan_dates[0]]
            seed_symbols, seed_allowed_by_date, _, _, _ = _build(seed_refresh_dates, None)
            if not seed_symbols:
                raise ValueError("回测股票池为空：持仓触发滚动初始池为空。")
            probe_result, probe_matrix_note = self._run_matrix_execution(
                payload=payload,
                symbols=seed_symbols,
                allowed_symbols_by_date=seed_allowed_by_date,
                progress_callback=None,
                progress_total_dates=None,
                control_callback=control_callback,
            )
            refresh_date_set: set[str] = {scan_dates[0]}
            for trade in probe_result.trades:
                next_day = self._next_scan_date(scan_dates, trade.exit_date)
                if next_day:
                    refresh_date_set.add(next_day)
            if progress_callback is not None:
                progress_callback(
                    scan_dates[0],
                    0,
                    max(1, len(refresh_date_set)),
                    "持仓触发滚动：正在根据卖出日生成刷新计划...",
                )
            rolling_symbols, rolling_allowed_by_date, notes, _, refresh_dates_used = _build(
                sorted(refresh_date_set),
                progress_callback,
            )
            merged_notes = [
                *notes,
                f"持仓触发滚动：首日+卖出后下一交易日刷新，共 {len(refresh_dates_used)} 次。",
                f"持仓触发滚动预演: {probe_matrix_note}",
            ]
            return rolling_symbols, rolling_allowed_by_date, merged_notes, scan_dates

        rolling_symbols, rolling_allowed_by_date, notes, _, _ = _build(None, progress_callback)
        return rolling_symbols, rolling_allowed_by_date, list(notes), scan_dates

    def _run_backtest_matrix(
        self,
        *,
        payload: BacktestRunRequest,
        board_filters: list[BoardFilter],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        control_callback: Callable[[], None] | None = None,
    ) -> BacktestResponse:
        degraded_reason: str | None = None
        resolved_run_id: str | None = None
        trend_pool_params: ScreenerParams | None = None
        trend_pool_fallback_note: str | None = None
        if payload.mode == "trend_pool":
            (
                trend_pool_params,
                resolved_run_id,
                degraded_reason,
                trend_pool_fallback_note,
            ) = self._resolve_backtest_trend_pool_params(payload.run_id)

        pool_notes: list[str] = []
        if trend_pool_fallback_note:
            pool_notes.append(trend_pool_fallback_note)

        rolling_symbols, rolling_allowed_by_date, rolling_notes, scan_dates = self._resolve_matrix_rolling_universe(
            payload=payload,
            board_filters=board_filters,
            trend_pool_params=trend_pool_params,
            progress_callback=progress_callback,
            control_callback=control_callback,
        )
        pool_notes = [*pool_notes, *rolling_notes]
        if not rolling_symbols:
            reason_text = "；".join(pool_notes) if pool_notes else "滚动筛选结果为空。"
            raise ValueError(f"回测股票池为空：{reason_text}")

        result, matrix_note = self._run_matrix_execution(
            payload=payload,
            symbols=rolling_symbols,
            allowed_symbols_by_date=rolling_allowed_by_date,
            progress_callback=progress_callback,
            progress_total_dates=max(1, len(scan_dates)),
            control_callback=control_callback,
        )

        notes = [matrix_note, *pool_notes, *list(result.notes)]
        if board_filters:
            roll_mode_label = {
                "daily": "每日滚动",
                "weekly": "每周滚动",
                "position": "持仓触发滚动",
            }.get(payload.pool_roll_mode, "每日滚动")
            notes.insert(0, f"候选池板块过滤: {','.join(board_filters)}（{roll_mode_label}生效）")
        if payload.mode == "trend_pool" and resolved_run_id:
            notes.insert(0, f"使用筛选任务: {resolved_run_id}")
        notes.insert(
            0,
            self._build_backtest_param_snapshot_note(
                payload,
                resolved_run_id=resolved_run_id,
                board_filters=board_filters,
            ),
        )
        if degraded_reason:
            notes.append(f"候选池降级原因: {degraded_reason}")
        if notes != result.notes:
            result = result.model_copy(update={"notes": notes})
        return result

    def _summarize_backtest_candle_coverage(
        self,
        *,
        symbols: list[str],
        date_from: str,
        date_to: str,
    ) -> tuple[str | None, str | None, int, int, int]:
        effective_start: str | None = None
        effective_end: str | None = None
        covered_from_count = 0
        covered_to_count = 0
        checked_count = 0

        for raw_symbol in symbols:
            symbol = str(raw_symbol).strip().lower()
            if not symbol:
                continue
            candles = self._ensure_candles(symbol)
            if not candles:
                continue
            first_date = str(candles[0].time).strip()
            last_date = str(candles[-1].time).strip()
            if not first_date or not last_date:
                continue
            checked_count += 1
            if effective_start is None or first_date < effective_start:
                effective_start = first_date
            if effective_end is None or last_date > effective_end:
                effective_end = last_date
            if first_date <= date_from <= last_date:
                covered_from_count += 1
            if first_date <= date_to <= last_date:
                covered_to_count += 1

        return effective_start, effective_end, covered_from_count, covered_to_count, checked_count

    @staticmethod
    def _summarize_backtest_candle_coverage_from_matrix_bundle(
        *,
        symbols: list[str],
        date_from: str,
        date_to: str,
        matrix_bundle: MatrixBundle,
    ) -> tuple[str | None, str | None, int, int, int]:
        dates = list(matrix_bundle.dates)
        valid_mask = matrix_bundle.valid_mask
        if not dates or valid_mask.size <= 0:
            return None, None, 0, 0, 0
        if valid_mask.ndim != 2 or valid_mask.shape[0] != len(dates):
            return None, None, 0, 0, 0

        has_data = np.any(valid_mask, axis=0)
        if not bool(np.any(has_data)):
            return None, None, 0, 0, 0
        first_indexes = np.argmax(valid_mask, axis=0)
        last_indexes = (valid_mask.shape[0] - 1) - np.argmax(valid_mask[::-1, :], axis=0)

        symbol_to_col = matrix_bundle.symbol_to_index()
        effective_start: str | None = None
        effective_end: str | None = None
        covered_from_count = 0
        covered_to_count = 0
        checked_count = 0

        for raw_symbol in symbols:
            symbol = str(raw_symbol).strip().lower()
            if not symbol:
                continue
            col = symbol_to_col.get(symbol)
            if col is None or (not bool(has_data[col])):
                continue
            first_date = str(dates[int(first_indexes[col])]).strip()
            last_date = str(dates[int(last_indexes[col])]).strip()
            if not first_date or not last_date:
                continue
            checked_count += 1
            if effective_start is None or first_date < effective_start:
                effective_start = first_date
            if effective_end is None or last_date > effective_end:
                effective_end = last_date
            if first_date <= date_from <= last_date:
                covered_from_count += 1
            if first_date <= date_to <= last_date:
                covered_to_count += 1

        return effective_start, effective_end, covered_from_count, covered_to_count, checked_count

    def _validate_backtest_data_coverage_by_summary(
        self,
        payload: BacktestRunRequest,
        *,
        summary: tuple[str | None, str | None, int, int, int],
        scope_label: str,
    ) -> None:
        (
            effective_start,
            effective_end,
            covered_from_count,
            covered_to_count,
            checked_count,
        ) = summary
        if checked_count <= 0:
            raise BacktestValidationError(
                "BACKTEST_DATA_COVERAGE_INSUFFICIENT",
                (
                    "回测K线覆盖不足：候选池未读取到可用K线。"
                    "请检查行情源与数据路径。"
                ),
            )

        covered_from_ratio = covered_from_count / checked_count
        covered_to_ratio = covered_to_count / checked_count
        min_coverage_ratio = self._backtest_precheck_min_symbol_coverage_ratio()
        coverage_insufficient = (
            effective_start is None
            or effective_end is None
            or covered_from_count <= 0
            or covered_to_count <= 0
            or covered_from_ratio < min_coverage_ratio
            or covered_to_ratio < min_coverage_ratio
            or effective_start > payload.date_from
            or effective_end < payload.date_to
        )
        if not coverage_insufficient:
            return

        raise BacktestValidationError(
            "BACKTEST_DATA_COVERAGE_INSUFFICIENT",
            (
                f"回测K线覆盖不足：请求区间 {payload.date_from} ~ {payload.date_to}，"
                f"{scope_label}在当前K线窗口(candles_window_bars={int(self._config.candles_window_bars)})下"
                f"有效覆盖约 {effective_start or 'N/A'} ~ {effective_end or 'N/A'}；"
                f"可覆盖起始日标的 {covered_from_count}/{checked_count}，"
                f"可覆盖结束日标的 {covered_to_count}/{checked_count}。"
                f"覆盖比例(起始/结束)={covered_from_ratio:.1%}/{covered_to_ratio:.1%}，"
                f"最低要求={min_coverage_ratio:.1%}。"
                "请增大K线窗口或缩短回测区间。"
            ),
        )

    def _validate_backtest_data_coverage_with_matrix_bundle(
        self,
        payload: BacktestRunRequest,
        symbols: list[str],
        matrix_bundle: MatrixBundle,
        *,
        scope_label: str,
    ) -> None:
        summary = self._summarize_backtest_candle_coverage_from_matrix_bundle(
            symbols=symbols,
            date_from=payload.date_from,
            date_to=payload.date_to,
            matrix_bundle=matrix_bundle,
        )
        self._validate_backtest_data_coverage_by_summary(
            payload,
            summary=summary,
            scope_label=scope_label,
        )

    def _validate_backtest_data_coverage(
        self,
        payload: BacktestRunRequest,
        symbols: list[str],
        *,
        scope_label: str,
    ) -> None:
        summary = self._summarize_backtest_candle_coverage(
            symbols=symbols,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
        self._validate_backtest_data_coverage_by_summary(
            payload,
            summary=summary,
            scope_label=scope_label,
        )

    def _precheck_backtest_data_coverage_before_task(self, payload: BacktestRunRequest) -> None:
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            raise BacktestValidationError("BACKTEST_INVALID", "回测区间内无可扫描交易日。")
        required_bars = max(1, len(scan_dates)) + max(20, int(payload.window_days)) + 5
        configured_bars = int(self._config.candles_window_bars or 0)
        if configured_bars > 0 and configured_bars < required_bars:
            raise BacktestValidationError(
                "BACKTEST_CANDLES_WINDOW_TOO_SHORT",
                (
                    f"回测K线窗口不足：请求区间 {payload.date_from} ~ {payload.date_to} "
                    f"共 {len(scan_dates)} 个交易日，signal_window={int(payload.window_days)}；"
                    f"估算至少需要 {required_bars} 根K线，当前 candles_window_bars={configured_bars}。"
                    "请在设置中提高K线数后重试。"
                ),
            )
        first_refresh_date = [scan_dates[0]]
        board_filters = [item for item in payload.board_filters if item in {"main", "gem", "star", "beijing", "st"}]

        if payload.mode == "trend_pool":
            trend_pool_params, _, _, _ = self._resolve_backtest_trend_pool_params(payload.run_id)
            seed_symbols, _, _, _, _ = self._build_trend_pool_rolling_universe(
                payload=payload,
                screener_params=trend_pool_params,
                board_filters=board_filters,
                refresh_dates=first_refresh_date,
                progress_callback=None,
            )
        elif payload.mode == "full_market":
            seed_symbols, _, _, _, _ = self._build_full_market_rolling_universe(
                payload=payload,
                board_filters=board_filters,
                refresh_dates=first_refresh_date,
                progress_callback=None,
            )
        else:
            raise BacktestValidationError("BACKTEST_INVALID", f"不支持的回测模式: {payload.mode}")

        if not seed_symbols:
            return
        self._validate_backtest_data_coverage(
            payload,
            seed_symbols,
            scope_label="首个刷新日候选池",
        )

    def _is_backtest_task_precheck_async_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_TASK_PRECHECK_ASYNC", False)

    @staticmethod
    def _backtest_precheck_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_PRECHECK_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 10 * 60.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 10 * 60.0

    @staticmethod
    def _backtest_precheck_min_symbol_coverage_ratio() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_PRECHECK_MIN_SYMBOL_COVERAGE", "").strip()
        if not raw:
            return 0.08
        try:
            parsed = float(raw)
        except Exception:
            return 0.08
        return max(0.0, min(1.0, parsed))

    @staticmethod
    def _build_backtest_task_stage_timing(
        stage_key: str,
        label: str,
        elapsed_sec: float,
    ) -> BacktestTaskStageTiming:
        elapsed_ms = max(0, int(round(float(max(0.0, elapsed_sec)) * 1000.0)))
        return BacktestTaskStageTiming(
            stage_key=str(stage_key or "").strip() or "unknown",
            label=str(label or "").strip() or "未命名阶段",
            elapsed_ms=elapsed_ms,
        )

    def _extract_backtest_stage_timings(
        self,
        result: BacktestResponse,
        *,
        run_elapsed_sec: float,
    ) -> list[BacktestTaskStageTiming]:
        notes = list(result.notes)
        matrix_match: re.Match[str] | None = None
        for note in notes:
            if not note:
                continue
            matrix_match = self._BACKTEST_MATRIX_TIMING_RE.search(str(note))
            if matrix_match:
                break

        if matrix_match is None:
            return [
                self._build_backtest_task_stage_timing(
                    "run_total",
                    "回测执行",
                    run_elapsed_sec,
                )
            ]

        try:
            matrix_build = float(matrix_match.group("matrix"))
            signal_compute = float(matrix_match.group("signal"))
            execute_match = float(matrix_match.group("match"))
            matrix_total = float(matrix_match.group("total"))
        except Exception:
            return [
                self._build_backtest_task_stage_timing(
                    "run_total",
                    "回测执行",
                    run_elapsed_sec,
                )
            ]

        stage_rows: list[BacktestTaskStageTiming] = []
        pool_overhead = max(0.0, float(run_elapsed_sec) - float(matrix_total))
        if pool_overhead >= 0.02:
            stage_rows.append(
                self._build_backtest_task_stage_timing(
                    "rolling_universe",
                    "候选池构建",
                    pool_overhead,
                )
            )
        stage_rows.extend(
            [
                self._build_backtest_task_stage_timing("matrix_build", "矩阵构建", matrix_build),
                self._build_backtest_task_stage_timing("signal_compute", "信号计算", signal_compute),
                self._build_backtest_task_stage_timing("execution_match", "撮合执行", execute_match),
                self._build_backtest_task_stage_timing("run_total", "回测总耗时", max(run_elapsed_sec, matrix_total)),
            ]
        )
        return stage_rows

    def _build_backtest_precheck_cache_key(self, payload: BacktestRunRequest) -> str:
        payload_raw = payload.model_dump(exclude_none=True)
        board_filters = payload_raw.get("board_filters")
        if isinstance(board_filters, list):
            payload_raw["board_filters"] = sorted(
                {str(item).strip().lower() for item in board_filters if str(item).strip()}
            )
        cache_payload = {
            "version": self._BACKTEST_PRECHECK_CACHE_VERSION,
            "payload": payload_raw,
            "config": {
                "tdx_root": str(self._resolve_user_path(self._config.tdx_data_path)),
                "market_data_source": str(self._config.market_data_source).strip(),
                "candles_window_bars": int(self._config.candles_window_bars),
                "markets": sorted({str(item).strip().lower() for item in self._config.markets if str(item).strip()}),
                "return_window_days": int(self._config.return_window_days),
                "top_n": int(self._config.top_n),
            },
            "algo": {
                "matrix_algo_version": str(self._backtest_matrix_algo_version).strip(),
                "wyckoff_algo_version": str(self._wyckoff_event_algo_version).strip(),
                "wyckoff_data_version": str(self._wyckoff_event_data_version).strip(),
            },
        }
        raw = json.dumps(cache_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _load_backtest_precheck_cache(
        self,
        cache_key: str,
    ) -> tuple[str | None, str | None] | None:
        ttl_sec = self._backtest_precheck_cache_ttl_sec()
        with self._backtest_precheck_cache_lock:
            cached = self._backtest_precheck_cache.get(cache_key)
            if cached is None:
                return None
            created_at, error_code, error_message = cached
            if ttl_sec > 0 and (time.time() - created_at) > ttl_sec:
                self._backtest_precheck_cache.pop(cache_key, None)
                return None
            return error_code, error_message

    def _save_backtest_precheck_cache(
        self,
        cache_key: str,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        now_ts = time.time()
        with self._backtest_precheck_cache_lock:
            self._backtest_precheck_cache[cache_key] = (now_ts, error_code, error_message)
            if len(self._backtest_precheck_cache) > 256:
                stale_items = sorted(
                    self._backtest_precheck_cache.items(),
                    key=lambda item: float(item[1][0]),
                )
                overflow = len(self._backtest_precheck_cache) - 256
                for key, _value in stale_items[:overflow]:
                    self._backtest_precheck_cache.pop(key, None)

    def _clear_backtest_precheck_cache(self) -> None:
        with self._backtest_precheck_cache_lock:
            self._backtest_precheck_cache.clear()

    def _run_backtest_precheck_with_cache(self, payload: BacktestRunRequest) -> None:
        cache_key = self._build_backtest_precheck_cache_key(payload)
        cached = self._load_backtest_precheck_cache(cache_key)
        if cached is not None:
            cached_error_code, cached_error_message = cached
            if cached_error_code and cached_error_message:
                raise BacktestValidationError(cached_error_code, cached_error_message)
            return
        try:
            self._precheck_backtest_data_coverage_before_task(payload)
        except BacktestValidationError as exc:
            self._save_backtest_precheck_cache(
                cache_key,
                error_code=exc.code,
                error_message=str(exc),
            )
            raise
        self._save_backtest_precheck_cache(cache_key, error_code=None, error_message=None)

    def _is_backtest_result_cache_enabled(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_RESULT_CACHE", True)

    @staticmethod
    def _backtest_result_cache_ttl_sec() -> float:
        raw = os.getenv("TDX_TREND_BACKTEST_RESULT_CACHE_TTL_SEC", "").strip()
        if not raw:
            return 48 * 3600.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 48 * 3600.0

    @staticmethod
    def _is_backtest_result_cache_eligible(payload: BacktestRunRequest) -> bool:
        if payload.mode == "trend_pool" and not str(payload.run_id or "").strip():
            # 没有显式 run_id 时会回落到 latest_run，结果来源不稳定，不做持久缓存。
            return False
        return True

    def _build_backtest_result_cache_key(self, payload: BacktestRunRequest) -> str:
        payload_raw = payload.model_dump(exclude_none=True)
        board_filters = payload_raw.get("board_filters")
        if isinstance(board_filters, list):
            payload_raw["board_filters"] = sorted(
                {str(item).strip().lower() for item in board_filters if str(item).strip()}
            )
        payload_meta = {
            "version": self._BACKTEST_RESULT_CACHE_VERSION,
            "payload": payload_raw,
            "config": {
                "tdx_root": str(self._resolve_user_path(self._config.tdx_data_path)),
                "market_data_source": str(self._config.market_data_source).strip(),
                "candles_window_bars": int(self._config.candles_window_bars),
                "return_window_days": int(self._config.return_window_days),
                "top_n": int(self._config.top_n),
            },
            "algo": {
                "matrix_algo_version": str(self._backtest_matrix_algo_version).strip(),
                "wyckoff_algo_version": str(self._wyckoff_event_algo_version).strip(),
                "wyckoff_data_version": str(self._wyckoff_event_data_version).strip(),
                "matrix_enabled": bool(self._is_backtest_matrix_engine_enabled()),
            },
        }
        raw = json.dumps(payload_meta, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _backtest_result_cache_file(self, cache_key: str) -> Path:
        return self._resolve_backtest_result_cache_dir() / f"{cache_key}.json"

    def _load_backtest_result_cache(self, payload: BacktestRunRequest) -> BacktestResponse | None:
        if not self._is_backtest_result_cache_enabled():
            return None
        if not self._is_backtest_result_cache_eligible(payload):
            return None
        cache_key = self._build_backtest_result_cache_key(payload)
        path = self._backtest_result_cache_file(cache_key)
        if not path.exists():
            return None
        ttl_sec = self._backtest_result_cache_ttl_sec()
        if ttl_sec > 0:
            try:
                age_sec = max(0.0, time.time() - path.stat().st_mtime)
                if age_sec > ttl_sec:
                    return None
            except Exception:
                return None
        try:
            payload_raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload_raw, dict):
                return None
            result_raw = payload_raw.get("result")
            if not isinstance(result_raw, dict):
                return None
            return BacktestResponse(**result_raw)
        except Exception:
            return None

    def _save_backtest_result_cache(self, payload: BacktestRunRequest, result: BacktestResponse) -> bool:
        if not self._is_backtest_result_cache_enabled():
            return False
        if not self._is_backtest_result_cache_eligible(payload):
            return False
        cache_key = self._build_backtest_result_cache_key(payload)
        path = self._backtest_result_cache_file(cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "schema_version": 1,
                "created_at": self._now_datetime(),
                "cache_key": cache_key,
                "result": result.model_dump(exclude_none=True),
            }
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(path)
            return True
        except Exception:
            return False

    @staticmethod
    def _normalize_plateau_axis_int(
        values: list[int],
        *,
        base: int,
        lower: int,
        upper: int,
    ) -> list[int]:
        source = values if values else [int(base)]
        out: list[int] = []
        seen: set[int] = set()
        for raw in source:
            value = int(raw)
            value = max(lower, min(upper, value))
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        if not out:
            out.append(max(lower, min(upper, int(base))))
        return out

    @staticmethod
    def _normalize_plateau_axis_float(
        values: list[float],
        *,
        base: float,
        lower: float,
        upper: float,
        precision: int = 6,
    ) -> list[float]:
        source = values if values else [float(base)]
        out: list[float] = []
        seen: set[float] = set()
        for raw in source:
            value = float(raw)
            value = max(lower, min(upper, value))
            value = round(value, precision)
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        if not out:
            out.append(round(max(lower, min(upper, float(base))), precision))
        return out

    @staticmethod
    def _backtest_plateau_score(result: BacktestResponse) -> float:
        total_return = float(result.stats.total_return)
        max_drawdown = abs(min(0.0, float(result.stats.max_drawdown)))
        win_rate = max(0.0, min(1.0, float(result.stats.win_rate)))
        profit_factor = float(result.stats.profit_factor)
        if not math.isfinite(profit_factor):
            profit_factor = 5.0
        profit_factor = max(0.0, min(profit_factor, 5.0))
        return round(total_return - max_drawdown * 0.6 + win_rate * 0.1 + profit_factor * 0.02, 6)

    @staticmethod
    def _resolve_plateau_sample_points(payload: BacktestPlateauRunRequest) -> int:
        if payload.sample_points is not None:
            return max(1, int(payload.sample_points))
        return max(1, int(payload.max_points))

    @staticmethod
    def _lhs_unit_matrix(point_count: int, dim_count: int, rng: random.Random) -> list[list[float]]:
        if point_count <= 0:
            return []
        matrix: list[list[float]] = [[0.0 for _ in range(dim_count)] for _ in range(point_count)]
        for dim in range(dim_count):
            bins = list(range(point_count))
            rng.shuffle(bins)
            for row in range(point_count):
                matrix[row][dim] = (float(bins[row]) + rng.random()) / float(point_count)
        return matrix

    @staticmethod
    def _map_plateau_int_from_unit(
        unit_value: float,
        *,
        lower: int,
        upper: int,
    ) -> int:
        if upper <= lower:
            return int(lower)
        mapped = int(round(float(lower) + float(unit_value) * float(upper - lower)))
        return max(int(lower), min(int(upper), mapped))

    @staticmethod
    def _map_plateau_float_from_unit(
        unit_value: float,
        *,
        lower: float,
        upper: float,
        precision: int,
    ) -> float:
        if upper <= lower:
            return round(float(lower), int(precision))
        mapped = float(lower) + float(unit_value) * float(upper - lower)
        mapped = max(float(lower), min(float(upper), mapped))
        return round(mapped, int(precision))

    def _build_plateau_lhs_params(
        self,
        *,
        point_count: int,
        random_seed: int | None,
        window_axis: list[int],
        min_score_axis: list[float],
        stop_loss_axis: list[float],
        take_profit_axis: list[float],
        max_positions_axis: list[int],
        position_pct_axis: list[float],
        max_symbols_axis: list[int],
        priority_topk_axis: list[int],
    ) -> list[BacktestPlateauParams]:
        if point_count <= 0:
            return []

        rng = random.Random(int(random_seed)) if random_seed is not None else random.Random()
        window_bounds = (min(window_axis), max(window_axis))
        min_score_bounds = (min(min_score_axis), max(min_score_axis))
        stop_loss_bounds = (min(stop_loss_axis), max(stop_loss_axis))
        take_profit_bounds = (min(take_profit_axis), max(take_profit_axis))
        max_positions_bounds = (min(max_positions_axis), max(max_positions_axis))
        position_pct_bounds = (min(position_pct_axis), max(position_pct_axis))
        max_symbols_bounds = (min(max_symbols_axis), max(max_symbols_axis))
        priority_topk_bounds = (min(priority_topk_axis), max(priority_topk_axis))

        seen: set[tuple[object, ...]] = set()
        params: list[BacktestPlateauParams] = []

        def _try_append(unit_values: list[float]) -> None:
            candidate = BacktestPlateauParams(
                window_days=self._map_plateau_int_from_unit(
                    unit_values[0],
                    lower=int(window_bounds[0]),
                    upper=int(window_bounds[1]),
                ),
                min_score=self._map_plateau_float_from_unit(
                    unit_values[1],
                    lower=float(min_score_bounds[0]),
                    upper=float(min_score_bounds[1]),
                    precision=4,
                ),
                stop_loss=self._map_plateau_float_from_unit(
                    unit_values[2],
                    lower=float(stop_loss_bounds[0]),
                    upper=float(stop_loss_bounds[1]),
                    precision=6,
                ),
                take_profit=self._map_plateau_float_from_unit(
                    unit_values[3],
                    lower=float(take_profit_bounds[0]),
                    upper=float(take_profit_bounds[1]),
                    precision=6,
                ),
                max_positions=self._map_plateau_int_from_unit(
                    unit_values[4],
                    lower=int(max_positions_bounds[0]),
                    upper=int(max_positions_bounds[1]),
                ),
                position_pct=self._map_plateau_float_from_unit(
                    unit_values[5],
                    lower=float(position_pct_bounds[0]),
                    upper=float(position_pct_bounds[1]),
                    precision=6,
                ),
                max_symbols=self._map_plateau_int_from_unit(
                    unit_values[6],
                    lower=int(max_symbols_bounds[0]),
                    upper=int(max_symbols_bounds[1]),
                ),
                priority_topk_per_day=self._map_plateau_int_from_unit(
                    unit_values[7],
                    lower=int(priority_topk_bounds[0]),
                    upper=int(priority_topk_bounds[1]),
                ),
            )
            key = (
                int(candidate.window_days),
                float(candidate.min_score),
                float(candidate.stop_loss),
                float(candidate.take_profit),
                int(candidate.max_positions),
                float(candidate.position_pct),
                int(candidate.max_symbols),
                int(candidate.priority_topk_per_day),
            )
            if key in seen:
                return
            seen.add(key)
            params.append(candidate)

        lhs_units = self._lhs_unit_matrix(point_count, 8, rng)
        for row in lhs_units:
            _try_append(row)
            if len(params) >= point_count:
                return params

        max_attempts = max(512, point_count * 64)
        attempts = 0
        while len(params) < point_count and attempts < max_attempts:
            attempts += 1
            _try_append([rng.random() for _ in range(8)])

        return params[:point_count]

    def run_backtest_plateau(self, payload: BacktestPlateauRunRequest) -> BacktestPlateauResponse:
        base = payload.base_payload.model_copy(deep=True)
        window_axis = self._normalize_plateau_axis_int(
            payload.window_days_list,
            base=int(base.window_days),
            lower=20,
            upper=240,
        )
        min_score_axis = self._normalize_plateau_axis_float(
            payload.min_score_list,
            base=float(base.min_score),
            lower=0.0,
            upper=100.0,
            precision=4,
        )
        stop_loss_axis = self._normalize_plateau_axis_float(
            payload.stop_loss_list,
            base=float(base.stop_loss),
            lower=0.0,
            upper=0.5,
            precision=6,
        )
        take_profit_axis = self._normalize_plateau_axis_float(
            payload.take_profit_list,
            base=float(base.take_profit),
            lower=0.0,
            upper=1.5,
            precision=6,
        )
        max_positions_axis = self._normalize_plateau_axis_int(
            payload.max_positions_list,
            base=int(base.max_positions),
            lower=1,
            upper=100,
        )
        position_pct_axis = self._normalize_plateau_axis_float(
            payload.position_pct_list,
            base=float(base.position_pct),
            lower=0.0001,
            upper=1.0,
            precision=6,
        )
        max_symbols_axis = self._normalize_plateau_axis_int(
            payload.max_symbols_list,
            base=int(base.max_symbols),
            lower=20,
            upper=2000,
        )
        priority_topk_axis = self._normalize_plateau_axis_int(
            payload.priority_topk_per_day_list,
            base=int(base.priority_topk_per_day),
            lower=0,
            upper=500,
        )

        axis_lengths = [
            len(window_axis),
            len(min_score_axis),
            len(stop_loss_axis),
            len(take_profit_axis),
            len(max_positions_axis),
            len(position_pct_axis),
            len(max_symbols_axis),
            len(priority_topk_axis),
        ]
        grid_total_combinations = 1
        for size in axis_lengths:
            grid_total_combinations *= max(1, int(size))

        points: list[BacktestPlateauPoint] = []
        failure_count = 0
        evaluated = 0
        sampling_mode = payload.sampling_mode
        sample_points = self._resolve_plateau_sample_points(payload)

        params_to_evaluate: list[BacktestPlateauParams] = []
        total_combinations = int(grid_total_combinations)
        if sampling_mode == "lhs":
            total_combinations = int(sample_points)
            params_to_evaluate = self._build_plateau_lhs_params(
                point_count=sample_points,
                random_seed=payload.random_seed,
                window_axis=window_axis,
                min_score_axis=min_score_axis,
                stop_loss_axis=stop_loss_axis,
                take_profit_axis=take_profit_axis,
                max_positions_axis=max_positions_axis,
                position_pct_axis=position_pct_axis,
                max_symbols_axis=max_symbols_axis,
                priority_topk_axis=priority_topk_axis,
            )
        else:
            for combo in product(
                window_axis,
                min_score_axis,
                stop_loss_axis,
                take_profit_axis,
                max_positions_axis,
                position_pct_axis,
                max_symbols_axis,
                priority_topk_axis,
            ):
                if len(params_to_evaluate) >= sample_points:
                    break
                (
                    window_days,
                    min_score,
                    stop_loss,
                    take_profit,
                    max_positions,
                    position_pct,
                    max_symbols,
                    priority_topk_per_day,
                ) = combo
                params_to_evaluate.append(
                    BacktestPlateauParams(
                        window_days=int(window_days),
                        min_score=float(min_score),
                        stop_loss=float(stop_loss),
                        take_profit=float(take_profit),
                        max_positions=int(max_positions),
                        position_pct=float(position_pct),
                        max_symbols=int(max_symbols),
                        priority_topk_per_day=int(priority_topk_per_day),
                    )
                )

        for params in params_to_evaluate:
            run_payload = base.model_copy(
                update={
                    "window_days": params.window_days,
                    "min_score": params.min_score,
                    "stop_loss": params.stop_loss,
                    "take_profit": params.take_profit,
                    "max_positions": params.max_positions,
                    "position_pct": params.position_pct,
                    "max_symbols": params.max_symbols,
                    "priority_topk_per_day": params.priority_topk_per_day,
                },
                deep=True,
            )
            evaluated += 1
            try:
                result = self.run_backtest(run_payload)
                cache_hit = any("回测结果缓存命中" in str(note) for note in result.notes)
                point = BacktestPlateauPoint(
                    params=params,
                    stats=result.stats,
                    candidate_count=int(result.candidate_count),
                    skipped_count=int(result.skipped_count),
                    fill_rate=float(result.fill_rate),
                    max_concurrent_positions=int(result.max_concurrent_positions),
                    score=self._backtest_plateau_score(result),
                    cache_hit=cache_hit,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                failure_count += 1
                point = BacktestPlateauPoint(
                    params=params,
                    stats=ReviewStats(
                        win_rate=0.0,
                        total_return=0.0,
                        max_drawdown=0.0,
                        avg_pnl_ratio=0.0,
                        trade_count=0,
                        win_count=0,
                        loss_count=0,
                        profit_factor=0.0,
                    ),
                    candidate_count=0,
                    skipped_count=0,
                    fill_rate=0.0,
                    max_concurrent_positions=0,
                    score=-9999.0,
                    cache_hit=False,
                    error=str(exc),
                )
            points.append(point)

        points.sort(
            key=lambda row: (
                row.error is None,
                row.score,
                row.stats.total_return,
                row.stats.win_rate,
            ),
            reverse=True,
        )
        best_point = next((row for row in points if row.error is None), None)
        notes: list[str] = []
        if sampling_mode == "grid" and grid_total_combinations > sample_points:
            notes.append(
                f"参数组合总数 {grid_total_combinations} 超过上限，已截断评估前 {sample_points} 组。"
            )
        if sampling_mode == "lhs":
            notes.append(f"参数采样模式: lhs，目标采样 {sample_points} 组。")
            if payload.random_seed is not None:
                notes.append(f"LHS 随机种子: {payload.random_seed}。")
            if len(params_to_evaluate) < sample_points:
                notes.append(
                    f"LHS 去重后仅生成 {len(params_to_evaluate)} 组有效参数（目标 {sample_points} 组）。"
                )
            notes.append(f"参考网格组合规模（按列表离散值估算）: {grid_total_combinations}。")
        if failure_count > 0:
            notes.append(f"有 {failure_count} 组参数评估失败，详情见 points.error。")
        notes.append(
            f"收益平原评估完成：总组合 {total_combinations}，实际评估 {evaluated}。"
        )
        return BacktestPlateauResponse(
            base_payload=base,
            total_combinations=int(total_combinations),
            evaluated_combinations=int(evaluated),
            points=points,
            best_point=best_point,
            generated_at=self._now_datetime(),
            notes=notes,
        )

    def run_backtest(
        self,
        payload: BacktestRunRequest,
        *,
        progress_callback: Callable[[str, int, int, str], None] | None = None,
        control_callback: Callable[[], None] | None = None,
    ) -> BacktestResponse:
        board_filters = [item for item in payload.board_filters if item in {"main", "gem", "star", "beijing", "st"}]
        if control_callback is not None:
            control_callback()
        effective_progress_callback = progress_callback
        if control_callback is not None:

            def _progress_with_control(current_date: str, processed_dates: int, total: int, message: str) -> None:
                control_callback()
                if progress_callback is not None:
                    progress_callback(current_date, processed_dates, total, message)

            effective_progress_callback = _progress_with_control

        cached_result = self._load_backtest_result_cache(payload)
        if cached_result is not None:
            if effective_progress_callback is not None:
                effective_progress_callback(
                    payload.date_to,
                    1,
                    1,
                    "回测结果缓存命中，直接返回。",
                )
            cached_notes = list(cached_result.notes)
            cache_note = "回测结果缓存命中：复用本地持久化结果。"
            if cache_note not in cached_notes:
                cached_notes.insert(0, cache_note)
            if cached_notes != cached_result.notes:
                return cached_result.model_copy(update={"notes": cached_notes})
            return cached_result

        matrix_fallback_note: str | None = None
        matrix_supported = (
            payload.mode in {"full_market", "trend_pool"}
            and payload.pool_roll_mode in {"daily", "weekly", "position"}
        )
        if self._is_backtest_matrix_engine_enabled() and matrix_supported:
            try:
                matrix_result = self._run_backtest_matrix(
                    payload=payload,
                    board_filters=board_filters,
                    progress_callback=effective_progress_callback,
                    control_callback=control_callback,
                )
                self._save_backtest_result_cache(payload, matrix_result)
                return matrix_result
            except BacktestTaskCancelledError:
                raise
            except Exception as exc:
                matrix_fallback_note = f"矩阵引擎执行失败，已回退旧路径：{exc}"

        degraded_reason: str | None = None
        resolved_run_id: str | None = None
        trend_pool_params: ScreenerParams | None = None
        trend_pool_fallback_note: str | None = None
        if payload.mode == "trend_pool":
            (
                trend_pool_params,
                resolved_run_id,
                degraded_reason,
                trend_pool_fallback_note,
            ) = self._resolve_backtest_trend_pool_params(payload.run_id)

        pool_notes: list[str] = []
        if matrix_fallback_note:
            pool_notes.append(matrix_fallback_note)
        if trend_pool_fallback_note:
            pool_notes.append(trend_pool_fallback_note)

        symbols: list[str] = []
        allowed_symbols_by_date: dict[str, set[str]] | None = None
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)

        engine = BacktestEngine(
            get_candles=self._ensure_candles,
            build_row=self._build_row_from_candles,
            calc_snapshot=lambda row, window_days, as_of_date: self._calc_wyckoff_snapshot(
                row,
                window_days=window_days,
                as_of_date=as_of_date,
            ),
            resolve_symbol_name=self._resolve_symbol_name,
        )

        if payload.mode == "trend_pool":
            if trend_pool_params is None:
                raise ValueError("趋势池筛选参数不可用。")
            if payload.pool_roll_mode == "position":
                if not scan_dates:
                    raise ValueError("回测区间内无可扫描交易日。")
                seed_refresh_dates = [scan_dates[0]]
                seed_symbols, seed_allowed_by_date, _, _, _ = self._build_trend_pool_rolling_universe(
                    payload=payload,
                    screener_params=trend_pool_params,
                    board_filters=board_filters,
                    refresh_dates=seed_refresh_dates,
                    progress_callback=None,
                )
                if not seed_symbols:
                    raise ValueError("回测股票池为空：持仓触发滚动初始池为空。")
                probe_result = engine.run(
                    payload=payload,
                    symbols=seed_symbols,
                    allowed_symbols_by_date=seed_allowed_by_date,
                    control_callback=control_callback,
                )
                refresh_date_set: set[str] = {scan_dates[0]}
                for trade in probe_result.trades:
                    next_day = self._next_scan_date(scan_dates, trade.exit_date)
                    if next_day:
                        refresh_date_set.add(next_day)
                if effective_progress_callback is not None:
                    effective_progress_callback(
                        scan_dates[0],
                        0,
                        max(1, len(refresh_date_set)),
                        "持仓触发滚动：正在根据卖出日生成刷新计划...",
                    )
                rolling_symbols, rolling_allowed_by_date, notes, _, refresh_dates_used = (
                    self._build_trend_pool_rolling_universe(
                        payload=payload,
                        screener_params=trend_pool_params,
                        board_filters=board_filters,
                        refresh_dates=sorted(refresh_date_set),
                        progress_callback=effective_progress_callback,
                    )
                )
                pool_notes = [
                    *pool_notes,
                    *notes,
                    f"持仓触发滚动：首日+卖出后下一交易日刷新，共 {len(refresh_dates_used)} 次。",
                ]
            else:
                rolling_symbols, rolling_allowed_by_date, notes, _, _ = self._build_trend_pool_rolling_universe(
                    payload=payload,
                    screener_params=trend_pool_params,
                    board_filters=board_filters,
                    refresh_dates=None,
                    progress_callback=effective_progress_callback,
                )
                pool_notes = [*pool_notes, *notes]
            if not rolling_symbols:
                reason_text = "；".join(pool_notes) if pool_notes else "滚动筛选结果为空。"
                raise ValueError(f"回测股票池为空：{reason_text}")
            symbols = rolling_symbols
            allowed_symbols_by_date = rolling_allowed_by_date
        elif payload.mode == "full_market":
            if payload.pool_roll_mode == "position":
                if not scan_dates:
                    raise ValueError("回测区间内无可扫描交易日。")
                seed_refresh_dates = [scan_dates[0]]
                seed_symbols, seed_allowed_by_date, _, _, _ = self._build_full_market_rolling_universe(
                    payload=payload,
                    board_filters=board_filters,
                    refresh_dates=seed_refresh_dates,
                    progress_callback=None,
                )
                if not seed_symbols:
                    raise ValueError("回测股票池为空：持仓触发滚动初始池为空。")
                probe_result = engine.run(
                    payload=payload,
                    symbols=seed_symbols,
                    allowed_symbols_by_date=seed_allowed_by_date,
                    control_callback=control_callback,
                )
                refresh_date_set: set[str] = {scan_dates[0]}
                for trade in probe_result.trades:
                    next_day = self._next_scan_date(scan_dates, trade.exit_date)
                    if next_day:
                        refresh_date_set.add(next_day)
                if effective_progress_callback is not None:
                    effective_progress_callback(
                        scan_dates[0],
                        0,
                        max(1, len(refresh_date_set)),
                        "持仓触发滚动：正在根据卖出日生成刷新计划...",
                    )
                rolling_symbols, rolling_allowed_by_date, notes, _, refresh_dates_used = (
                    self._build_full_market_rolling_universe(
                        payload=payload,
                        board_filters=board_filters,
                        refresh_dates=sorted(refresh_date_set),
                        progress_callback=effective_progress_callback,
                    )
                )
                pool_notes = [
                    *pool_notes,
                    *notes,
                    f"持仓触发滚动：首日+卖出后下一交易日刷新，共 {len(refresh_dates_used)} 次。",
                ]
            else:
                rolling_symbols, rolling_allowed_by_date, notes, _, _ = self._build_full_market_rolling_universe(
                    payload=payload,
                    board_filters=board_filters,
                    refresh_dates=None,
                    progress_callback=effective_progress_callback,
                )
                pool_notes = [*pool_notes, *notes]
            if not rolling_symbols:
                reason_text = "；".join(pool_notes) if pool_notes else "滚动筛选结果为空。"
                raise ValueError(f"回测股票池为空：{reason_text}")
            symbols = rolling_symbols
            allowed_symbols_by_date = rolling_allowed_by_date
        else:
            raise ValueError(f"不支持的回测模式: {payload.mode}")

        if not symbols:
            raise ValueError("回测股票池为空，请先执行筛选或调整回测模式")

        self._validate_backtest_data_coverage(
            payload,
            symbols,
            scope_label="滚动池并集",
        )

        result = engine.run(
            payload=payload,
            symbols=symbols,
            allowed_symbols_by_date=allowed_symbols_by_date,
            control_callback=control_callback,
        )

        notes = list(result.notes)
        if pool_notes:
            notes = [*pool_notes, *notes]
        if board_filters:
            roll_mode_label = {
                "daily": "每日滚动",
                "weekly": "每周滚动",
                "position": "持仓触发滚动",
            }.get(payload.pool_roll_mode, "每日滚动")
            notes.insert(0, f"候选池板块过滤: {','.join(board_filters)}（{roll_mode_label}生效）")
        if payload.mode == "trend_pool" and resolved_run_id:
            notes.insert(0, f"使用筛选任务: {resolved_run_id}")
        notes.insert(
            0,
            self._build_backtest_param_snapshot_note(
                payload,
                resolved_run_id=resolved_run_id,
                board_filters=board_filters,
            ),
        )
        if degraded_reason:
            notes.append(f"候选池降级原因: {degraded_reason}")
        if notes != result.notes:
            result = result.model_copy(update={"notes": notes})
        self._save_backtest_result_cache(payload, result)
        return result

    def _estimate_backtest_progress_total_dates(self, payload: BacktestRunRequest) -> int:
        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            return 1
        if payload.pool_roll_mode == "weekly":
            return max(1, len(self._build_weekly_refresh_dates(scan_dates)))
        if payload.pool_roll_mode == "position":
            return max(1, len(scan_dates))
        return max(1, len(scan_dates))

    def _build_backtest_task_state_payload(self) -> dict[str, object]:
        with self._backtest_task_lock:
            tasks = []
            for task_id, task in self._backtest_tasks.items():
                payload = self._backtest_task_payloads.get(task_id)
                task_payload = task.model_dump(exclude_none=True, exclude={"result"})
                tasks.append(
                    {
                        "task": task_payload,
                        "payload": payload.model_dump(exclude_none=True) if payload is not None else None,
                    }
                )
            return {
                "schema_version": 1,
                "updated_at": self._now_datetime(),
                "tasks": tasks,
            }

    def _write_backtest_task_state_payload(self, payload: dict[str, object]) -> None:
        self._backtest_task_state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._backtest_task_state_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._backtest_task_state_path)

    def _persist_backtest_task_state(self, *, force: bool = False) -> None:
        now_ts = time.time()
        if (not force) and (now_ts - self._backtest_task_state_last_persist_at < 1.5):
            return
        try:
            payload = self._build_backtest_task_state_payload()
            self._write_backtest_task_state_payload(payload)
            self._backtest_task_state_last_persist_at = now_ts
        except Exception:
            pass

    def _load_backtest_task_state(self) -> None:
        if not self._backtest_task_state_path.exists():
            return
        try:
            raw = json.loads(self._backtest_task_state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            items = raw.get("tasks")
            if not isinstance(items, list):
                return
            restored_tasks: dict[str, BacktestTaskStatusResponse] = {}
            restored_payloads: dict[str, BacktestRunRequest] = {}
            for row in items:
                if not isinstance(row, dict):
                    continue
                task_raw = row.get("task")
                if not isinstance(task_raw, dict):
                    continue
                try:
                    task = BacktestTaskStatusResponse(**task_raw)
                except Exception:
                    continue
                restored_tasks[task.task_id] = task
                payload_raw = row.get("payload")
                if isinstance(payload_raw, dict):
                    try:
                        restored_payloads[task.task_id] = BacktestRunRequest(**payload_raw)
                    except Exception:
                        pass
            with self._backtest_task_lock:
                self._backtest_tasks = restored_tasks
                self._backtest_task_payloads = restored_payloads
        except Exception:
            return

    def _should_auto_resume_backtest_tasks(self) -> bool:
        return self._env_flag("TDX_TREND_BACKTEST_TASK_AUTO_RESUME", False)

    def _resume_backtest_tasks_after_boot(self) -> None:
        resumable: list[tuple[str, BacktestRunRequest]] = []
        unrecoverable_task_ids: list[str] = []
        auto_resume = self._should_auto_resume_backtest_tasks()
        with self._backtest_task_lock:
            for task_id, task in list(self._backtest_tasks.items()):
                if task.status not in {"pending", "running"}:
                    continue
                payload = self._backtest_task_payloads.get(task_id)
                if payload is None:
                    unrecoverable_task_ids.append(task_id)
                    continue
                resumable.append((task_id, payload))

        now_text = self._now_datetime()
        for task_id in unrecoverable_task_ids:
            task = self.get_backtest_task(task_id)
            if task is None:
                continue
            failed_progress = task.progress.model_copy(
                update={
                    "message": "服务重启后无法恢复：缺少任务参数。",
                    "updated_at": now_text,
                }
            )
            self._upsert_backtest_task(
                task.model_copy(
                    update={
                        "status": "failed",
                        "progress": failed_progress,
                        "error": "服务重启后无法恢复任务：缺少任务参数。",
                        "error_code": "BACKTEST_TASK_RESUME_PAYLOAD_MISSING",
                    }
                )
            )

        for task_id, payload in resumable:
            task = self.get_backtest_task(task_id)
            if task is None:
                continue
            if not auto_resume:
                paused_progress = task.progress.model_copy(
                    update={
                        "message": "检测到服务重启，任务已自动暂停，请手动继续。",
                        "updated_at": now_text,
                    }
                )
                self._upsert_backtest_task(
                    task.model_copy(
                        update={
                            "status": "paused",
                            "progress": paused_progress,
                            "error": None,
                            "error_code": None,
                        }
                    )
                )
                continue
            pending_progress = task.progress.model_copy(
                update={
                    "message": "检测到服务重启，任务已自动续跑。",
                    "updated_at": now_text,
                }
            )
            self._upsert_backtest_task(
                task.model_copy(
                    update={
                        "status": "pending",
                        "progress": pending_progress,
                        "error": None,
                        "error_code": None,
                    }
                )
            )
            self._start_backtest_task_worker(task_id, payload, resumed=True)

    def _upsert_backtest_task(self, task: BacktestTaskStatusResponse) -> None:
        force_persist = task.status in {"paused", "succeeded", "failed", "cancelled"}
        with self._backtest_task_lock:
            self._backtest_tasks[task.task_id] = task
            if len(self._backtest_tasks) > 80:
                sorted_items = sorted(
                    self._backtest_tasks.items(),
                    key=lambda item: item[1].progress.updated_at,
                )
                for old_task_id, _ in sorted_items[: max(0, len(sorted_items) - 80)]:
                    self._backtest_tasks.pop(old_task_id, None)
                    self._backtest_task_payloads.pop(old_task_id, None)
        self._persist_backtest_task_state(force=force_persist)

    def get_backtest_task(self, task_id: str) -> BacktestTaskStatusResponse | None:
        with self._backtest_task_lock:
            task = self._backtest_tasks.get(task_id)
            if task is None:
                return None
            return task.model_copy(deep=True)

    def _await_backtest_task_runnable(self, task_id: str) -> None:
        while True:
            task = self.get_backtest_task(task_id)
            if task is None:
                raise BacktestTaskCancelledError("任务不存在，无法继续执行。")
            if task.status == "cancelled":
                raise BacktestTaskCancelledError("任务已停止。")
            if task.status in {"succeeded", "failed"}:
                raise BacktestTaskCancelledError(f"任务状态已结束：{task.status}")
            if task.status == "paused":
                time.sleep(0.25)
                continue
            if task.status in {"pending", "running"}:
                return
            time.sleep(0.25)

    def _control_backtest_task(
        self,
        task_id: str,
        action: Literal["pause", "resume", "cancel"],
    ) -> BacktestTaskStatusResponse:
        payload_for_resume: BacktestRunRequest | None = None
        now_text = self._now_datetime()
        with self._backtest_task_lock:
            task = self._backtest_tasks.get(task_id)
            if task is None:
                raise BacktestValidationError("BACKTEST_TASK_NOT_FOUND", "回测任务不存在")
            if action == "pause":
                if task.status in {"succeeded", "failed", "cancelled"}:
                    raise BacktestValidationError(
                        "BACKTEST_TASK_CONTROL_INVALID",
                        f"任务当前状态为 {task.status}，无法暂停。",
                    )
                if task.status != "paused":
                    task = task.model_copy(
                        update={
                            "status": "paused",
                            "progress": task.progress.model_copy(
                                update={
                                    "message": "任务已暂停。",
                                    "updated_at": now_text,
                                }
                            ),
                            "error": None,
                            "error_code": None,
                        }
                    )
                    self._backtest_tasks[task_id] = task
            elif action == "resume":
                if task.status in {"succeeded", "failed", "cancelled"}:
                    raise BacktestValidationError(
                        "BACKTEST_TASK_CONTROL_INVALID",
                        f"任务当前状态为 {task.status}，无法继续执行。",
                    )
                if task.status == "paused":
                    payload_for_resume = self._backtest_task_payloads.get(task_id)
                    if payload_for_resume is None:
                        raise BacktestValidationError(
                            "BACKTEST_TASK_RESUME_PAYLOAD_MISSING",
                            "任务参数缺失，无法继续执行。",
                        )
                    task = task.model_copy(
                        update={
                            "status": "pending",
                            "progress": task.progress.model_copy(
                                update={
                                    "message": "任务已恢复，等待继续执行。",
                                    "updated_at": now_text,
                                }
                            ),
                            "error": None,
                            "error_code": None,
                        }
                    )
                    self._backtest_tasks[task_id] = task
            else:
                if task.status not in {"succeeded", "failed", "cancelled"}:
                    task = task.model_copy(
                        update={
                            "status": "cancelled",
                            "progress": task.progress.model_copy(
                                update={
                                    "message": "任务已停止。",
                                    "updated_at": now_text,
                                }
                            ),
                            "error": None,
                            "error_code": None,
                        }
                    )
                    self._backtest_tasks[task_id] = task

        current = self.get_backtest_task(task_id)
        if current is None:
            raise BacktestValidationError("BACKTEST_TASK_NOT_FOUND", "回测任务不存在")
        self._persist_backtest_task_state(force=current.status in {"paused", "cancelled"})
        if action == "resume" and payload_for_resume is not None:
            self._start_backtest_task_worker(task_id, payload_for_resume, resumed=True)
        return current

    def pause_backtest_task(self, task_id: str) -> BacktestTaskStatusResponse:
        return self._control_backtest_task(task_id, "pause")

    def resume_backtest_task(self, task_id: str) -> BacktestTaskStatusResponse:
        return self._control_backtest_task(task_id, "resume")

    def cancel_backtest_task(self, task_id: str) -> BacktestTaskStatusResponse:
        return self._control_backtest_task(task_id, "cancel")

    def _start_backtest_task_worker(
        self,
        task_id: str,
        payload: BacktestRunRequest,
        *,
        resumed: bool = False,
        run_precheck: bool = False,
    ) -> None:
        with self._backtest_task_lock:
            if task_id in self._backtest_running_worker_ids:
                return
            self._backtest_running_worker_ids.add(task_id)

        def _worker() -> None:
            try:
                task = self.get_backtest_task(task_id)
                if task is None:
                    return
                task_stage_timings: list[BacktestTaskStageTiming] = list(task.progress.stage_timings)

                def _upsert_stage_timing(stage_timing: BacktestTaskStageTiming) -> None:
                    nonlocal task_stage_timings
                    stage_key = str(stage_timing.stage_key or "").strip()
                    if not stage_key:
                        return
                    updated = False
                    next_rows: list[BacktestTaskStageTiming] = []
                    for row in task_stage_timings:
                        if str(row.stage_key) == stage_key:
                            next_rows.append(stage_timing)
                            updated = True
                        else:
                            next_rows.append(row)
                    if not updated:
                        next_rows.append(stage_timing)
                    task_stage_timings = next_rows
                    current_task = self.get_backtest_task(task_id)
                    if current_task is None:
                        return
                    next_progress = current_task.progress.model_copy(
                        update={
                            "stage_timings": list(task_stage_timings),
                            "updated_at": self._now_datetime(),
                        }
                    )
                    self._upsert_backtest_task(current_task.model_copy(update={"progress": next_progress}))

                self._await_backtest_task_runnable(task_id)
                task = self.get_backtest_task(task_id)
                if task is None:
                    return
                running_message = "任务执行中..." if not resumed else "服务重启后自动续跑中..."
                running_progress = task.progress.model_copy(
                    update={
                        "message": running_message,
                        "stage_timings": list(task_stage_timings),
                        "updated_at": self._now_datetime(),
                    }
                )
                self._upsert_backtest_task(
                    task.model_copy(
                        update={
                            "status": "running",
                            "progress": running_progress,
                            "error": None,
                            "error_code": None,
                        }
                    )
                )

                if run_precheck:
                    self._await_backtest_task_runnable(task_id)
                    precheck_task = self.get_backtest_task(task_id)
                    if precheck_task is not None:
                        precheck_progress = precheck_task.progress.model_copy(
                            update={
                                "message": "任务预检中：检查K线覆盖...",
                                "updated_at": self._now_datetime(),
                            }
                        )
                        self._upsert_backtest_task(
                            precheck_task.model_copy(
                                update={
                                    "status": "running",
                                    "progress": precheck_progress,
                                }
                            )
                        )
                    precheck_start_ts = time.perf_counter()
                    self._run_backtest_precheck_with_cache(payload)
                    precheck_elapsed = time.perf_counter() - precheck_start_ts
                    _upsert_stage_timing(
                        self._build_backtest_task_stage_timing(
                            "precheck",
                            "前置校验",
                            precheck_elapsed,
                        )
                    )
                    post_precheck_task = self.get_backtest_task(task_id)
                    if post_precheck_task is not None:
                        post_precheck_progress = post_precheck_task.progress.model_copy(
                            update={
                                "message": "任务预检完成，开始回测...",
                                "stage_timings": list(task_stage_timings),
                                "updated_at": self._now_datetime(),
                            }
                        )
                        self._upsert_backtest_task(
                            post_precheck_task.model_copy(
                                update={
                                    "status": "running",
                                    "progress": post_precheck_progress,
                                }
                            )
                        )

                def _progress(current_date: str, processed_dates: int, total: int, message: str) -> None:
                    self._await_backtest_task_runnable(task_id)
                    current_task = self.get_backtest_task(task_id)
                    if current_task is None:
                        return
                    total_safe = max(1, int(total), int(current_task.progress.total_dates or 0))
                    processed_safe = max(0, min(int(processed_dates), total_safe))
                    processed_safe = max(int(current_task.progress.processed_dates or 0), processed_safe)
                    percent = round((processed_safe / total_safe) * 100.0, 2)
                    next_progress = current_task.progress.model_copy(
                        update={
                            "current_date": current_date,
                            "processed_dates": processed_safe,
                            "total_dates": total_safe,
                            "percent": percent,
                            "message": message,
                            "stage_timings": list(task_stage_timings),
                            "updated_at": self._now_datetime(),
                        }
                    )
                    self._upsert_backtest_task(
                        current_task.model_copy(update={"status": "running", "progress": next_progress})
                    )

                run_start_ts = time.perf_counter()
                result = self.run_backtest(
                    payload,
                    progress_callback=_progress,
                    control_callback=lambda: self._await_backtest_task_runnable(task_id),
                )
                run_elapsed = time.perf_counter() - run_start_ts
                for stage_timing in self._extract_backtest_stage_timings(result, run_elapsed_sec=run_elapsed):
                    _upsert_stage_timing(stage_timing)
                finished_task = self.get_backtest_task(task_id)
                if finished_task is None:
                    return
                done_progress = finished_task.progress.model_copy(
                    update={
                        "percent": 100.0,
                        "processed_dates": max(finished_task.progress.processed_dates, finished_task.progress.total_dates),
                        "message": "回测完成。",
                        "stage_timings": list(task_stage_timings),
                        "updated_at": self._now_datetime(),
                    }
                )
                self._upsert_backtest_task(
                    finished_task.model_copy(
                        update={
                            "status": "succeeded",
                            "progress": done_progress,
                            "result": result,
                            "error": None,
                            "error_code": None,
                        }
                    )
                )
            except BacktestTaskCancelledError:
                cancelled_task = self.get_backtest_task(task_id)
                if cancelled_task is None:
                    return
                if cancelled_task.status == "cancelled":
                    return
                cancelled_progress = cancelled_task.progress.model_copy(
                    update={
                        "message": "任务已停止。",
                        "stage_timings": list(task_stage_timings),
                        "updated_at": self._now_datetime(),
                    }
                )
                self._upsert_backtest_task(
                    cancelled_task.model_copy(
                        update={
                            "status": "cancelled",
                            "progress": cancelled_progress,
                            "error": None,
                            "error_code": None,
                        }
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed_task = self.get_backtest_task(task_id)
                if failed_task is None:
                    return
                failed_progress = failed_task.progress.model_copy(
                    update={
                        "message": "回测失败。",
                        "stage_timings": list(task_stage_timings),
                        "updated_at": self._now_datetime(),
                    }
                )
                error_code = "BACKTEST_TASK_FAILED"
                if isinstance(exc, BacktestValidationError):
                    error_code = exc.code
                self._upsert_backtest_task(
                    failed_task.model_copy(
                        update={
                            "status": "failed",
                            "progress": failed_progress,
                            "error": str(exc),
                            "error_code": error_code,
                        }
                    )
                )
            finally:
                with self._backtest_task_lock:
                    self._backtest_running_worker_ids.discard(task_id)
                self._persist_backtest_task_state(force=True)

        Thread(target=_worker, daemon=True).start()

    def start_backtest_task(self, payload: BacktestRunRequest) -> str:
        async_precheck = self._is_backtest_task_precheck_async_enabled()
        sync_precheck_stage: BacktestTaskStageTiming | None = None
        if not async_precheck:
            precheck_start_ts = time.perf_counter()
            self._run_backtest_precheck_with_cache(payload)
            sync_precheck_stage = self._build_backtest_task_stage_timing(
                "precheck",
                "前置校验",
                time.perf_counter() - precheck_start_ts,
            )

        task_id = f"bt_{uuid4().hex[:16]}"
        now_text = self._now_datetime()
        total_dates = self._estimate_backtest_progress_total_dates(payload)
        warning: str | None = None
        if payload.pool_roll_mode in {"daily", "weekly"} and total_dates >= 45:
            warning = "滚动回测日期较长，耗时可能较久，请耐心等待。"

        initial_progress = BacktestTaskProgress(
            mode=payload.pool_roll_mode,
            current_date=None,
            processed_dates=0,
            total_dates=total_dates,
            percent=0.0,
            message=("任务已创建，等待预检。" if async_precheck else "任务已创建，等待执行。"),
            warning=warning,
            stage_timings=([sync_precheck_stage] if sync_precheck_stage is not None else []),
            started_at=now_text,
            updated_at=now_text,
        )
        with self._backtest_task_lock:
            self._backtest_task_payloads[task_id] = payload.model_copy(deep=True)
        self._upsert_backtest_task(
            BacktestTaskStatusResponse(
                task_id=task_id,
                status="pending",
                progress=initial_progress,
                result=None,
                error=None,
                error_code=None,
            )
        )
        self._start_backtest_task_worker(
            task_id,
            payload,
            resumed=False,
            run_precheck=async_precheck,
        )
        return task_id

    def create_order(self, payload: CreateOrderRequest) -> CreateOrderResponse:
        return self._sim_engine.create_order(payload)

    def list_orders(
        self,
        *,
        status: Literal["pending", "filled", "cancelled", "rejected"] | None,
        symbol: str | None,
        side: Literal["buy", "sell"] | None,
        date_from: str | None,
        date_to: str | None,
        page: int,
        page_size: int,
    ) -> SimOrdersResponse:
        return self._sim_engine.list_orders(
            status=status,
            symbol=symbol,
            side=side,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )

    def list_fills(
        self,
        *,
        symbol: str | None,
        side: Literal["buy", "sell"] | None,
        date_from: str | None,
        date_to: str | None,
        page: int,
        page_size: int,
    ) -> SimFillsResponse:
        return self._sim_engine.list_fills(
            symbol=symbol,
            side=side,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )

    def cancel_order(self, order_id: str) -> CreateOrderResponse:
        return self._sim_engine.cancel_order(order_id)

    def settle_sim(self) -> SimSettleResponse:
        return self._sim_engine.settle()

    def reset_sim(self) -> SimResetResponse:
        return self._sim_engine.reset()

    def get_sim_config(self) -> SimTradingConfig:
        return self._sim_engine.get_config()

    def set_sim_config(self, payload: SimTradingConfig) -> SimTradingConfig:
        return self._sim_engine.set_config(payload)

    def get_portfolio(self) -> PortfolioSnapshot:
        return self._sim_engine.get_portfolio()

    def get_review(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        date_axis: Literal["sell", "buy"] = "sell",
    ) -> ReviewResponse:
        return self._sim_engine.get_review(
            date_from=date_from,
            date_to=date_to,
            date_axis=date_axis,
        )

    def get_daily_review(self, date: str) -> DailyReviewRecord | None:
        return self._daily_review_store.get(date)

    def list_daily_reviews(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> DailyReviewListResponse:
        rows = list(self._daily_review_store.values())
        if date_from:
            rows = [row for row in rows if row.date >= date_from]
        if date_to:
            rows = [row for row in rows if row.date <= date_to]
        rows.sort(key=lambda row: row.date, reverse=True)
        return DailyReviewListResponse(items=rows)

    def upsert_daily_review(self, date: str, payload: DailyReviewPayload) -> DailyReviewRecord:
        body = payload.model_dump()
        body["tags"] = self._unique_ordered([str(item) for item in body.get("tags", [])])
        record = DailyReviewRecord(
            date=date,
            updated_at=self._now_datetime(),
            **body,
        )
        self._daily_review_store[date] = record
        self._persist_app_state()
        return record

    def delete_daily_review(self, date: str) -> bool:
        if date not in self._daily_review_store:
            return False
        self._daily_review_store.pop(date, None)
        self._persist_app_state()
        return True

    def get_weekly_review(self, week_label: str) -> WeeklyReviewRecord | None:
        return self._weekly_review_store.get(week_label)

    def list_weekly_reviews(self, *, year: int | None = None) -> WeeklyReviewListResponse:
        rows = list(self._weekly_review_store.values())
        if year is not None:
            prefix = f"{year:04d}-W"
            rows = [row for row in rows if row.week_label.startswith(prefix)]
        rows.sort(key=lambda row: row.week_label, reverse=True)
        return WeeklyReviewListResponse(items=rows)

    def upsert_weekly_review(self, week_label: str, payload: WeeklyReviewPayload) -> WeeklyReviewRecord:
        body = payload.model_dump()
        start_date = str(body.get("start_date", "")).strip()
        end_date = str(body.get("end_date", "")).strip()
        if not start_date or not end_date:
            start_date, end_date = self._resolve_week_range(week_label)
        body["start_date"] = start_date
        body["end_date"] = end_date
        body["tags"] = self._unique_ordered([str(item) for item in body.get("tags", [])])
        record = WeeklyReviewRecord(
            week_label=week_label,
            updated_at=self._now_datetime(),
            **body,
        )
        self._weekly_review_store[week_label] = record
        self._persist_app_state()
        return record

    def delete_weekly_review(self, week_label: str) -> bool:
        if week_label not in self._weekly_review_store:
            return False
        self._weekly_review_store.pop(week_label, None)
        self._persist_app_state()
        return True

    def get_market_news(
        self,
        *,
        query: str = "",
        limit: int = 20,
        symbol: str | None = None,
        source_domains: list[str] | None = None,
        age_hours: int = 72,
        refresh: bool = False,
    ) -> MarketNewsResponse:
        max_items = max(1, min(int(limit), 50))
        max_age_hours = age_hours if age_hours in (24, 48, 72) else 72
        now_dt = datetime.now()
        cutoff_dt = now_dt - timedelta(hours=max_age_hours)

        symbol_text = TextProcessor.clean_whitespace(str(symbol or "")).lower()
        symbol_name = ""
        if symbol_text:
            profile = self._fetch_quote_profile(symbol_text)
            symbol_name = TextProcessor.clean_whitespace(profile.get("name", ""))
            if not query.strip():
                query = f"{symbol_text} {symbol_name} 新闻".strip()

        query_text = TextProcessor.clean_whitespace(query) or "A股 热点"
        default_domains = self._source_domains(self._enabled_ai_source_urls(limit=8))

        selected_domains: set[str] = set()
        for raw_domain in source_domains or []:
            token = TextProcessor.clean_whitespace(str(raw_domain))
            if not token:
                continue
            normalized = token
            if "://" in token:
                normalized = TextProcessor.extract_domain(token)
            normalized = normalized.lower().strip()
            if normalized.startswith("www."):
                normalized = normalized[4:]
            normalized = normalized.strip("/")
            if not normalized:
                continue
            selected_domains.add(normalized)
            root = TextProcessor.registrable_domain(normalized)
            if root:
                selected_domains.add(root)

        allowed_domains = selected_domains
        response_domains = sorted(selected_domains or default_domains)
        domain_key = ",".join(sorted(allowed_domains)) if allowed_domains else "*"
        cache_key = f"market_news:v3:{query_text}:{symbol_text}:{max_items}:{max_age_hours}:{domain_key}"
        now_ts = time.time()

        def parse_news_datetime(value: str) -> datetime | None:
            raw = TextProcessor.clean_whitespace(value)
            if not raw:
                return None
            parsed = self._parse_rss_pub_date(raw)
            if parsed is not None:
                return parsed

            candidate = raw
            candidate = candidate.replace("年", "-").replace("月", "-").replace("日", "")
            candidate = candidate.replace("/", "-").replace("T", " ")
            candidate = re.sub(r"\s+", " ", candidate).strip()

            patterns = [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%m-%d %H:%M:%S",
                "%m-%d %H:%M",
                "%H:%M:%S",
                "%H:%M",
            ]
            for pattern in patterns:
                try:
                    parsed_dt = datetime.strptime(candidate, pattern)
                    if pattern.startswith("%m"):
                        parsed_dt = parsed_dt.replace(year=now_dt.year)
                    elif pattern.startswith("%H"):
                        parsed_dt = now_dt.replace(
                            hour=parsed_dt.hour,
                            minute=parsed_dt.minute,
                            second=parsed_dt.second,
                            microsecond=0,
                        )
                        if parsed_dt > now_dt + timedelta(minutes=5):
                            parsed_dt = parsed_dt - timedelta(days=1)
                    if parsed_dt > now_dt + timedelta(days=2):
                        parsed_dt = parsed_dt.replace(year=parsed_dt.year - 1)
                    return parsed_dt
                except Exception:
                    continue
            return None

        def to_pub_date(parsed_dt: datetime | None, raw_text: str) -> str:
            if parsed_dt is not None:
                return parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
            return TextProcessor.clean_whitespace(raw_text)[:40]

        def is_recent(parsed_dt: datetime | None) -> bool:
            return parsed_dt is not None and parsed_dt >= cutoff_dt

        def filter_recent_items(rows: list[dict[str, str]]) -> list[dict[str, str]]:
            filtered: list[dict[str, str]] = []
            for item in rows:
                parsed_dt = parse_news_datetime(str(item.get("pub_date", "")))
                if not is_recent(parsed_dt):
                    continue
                filtered.append(item)
            filtered.sort(
                key=lambda item: parse_news_datetime(str(item.get("pub_date", ""))) or datetime.min,
                reverse=True,
            )
            return filtered[:max_items]

        def filter_relaxed_items(rows: list[dict[str, str]]) -> list[dict[str, str]]:
            filtered: list[dict[str, str]] = []
            for item in rows:
                parsed_dt = parse_news_datetime(str(item.get("pub_date", "")))
                if parsed_dt is None:
                    continue
                filtered.append(item)
            filtered.sort(
                key=lambda item: parse_news_datetime(str(item.get("pub_date", ""))) or datetime.min,
                reverse=True,
            )
            return filtered[:max_items]

        symbol_code = re.sub(r"^(sh|sz|bj)", "", symbol_text)
        default_query_tokens = {"a股", "热点", "a股热点", "a股 热点"}
        token_filters = [token.lower() for token in re.split(r"\s+", query_text) if token]
        if query_text.replace(" ", "").lower() in default_query_tokens:
            token_filters = []
        if symbol_text:
            token_filters.extend([symbol_text.lower(), symbol_code.lower()])
            if symbol_name:
                token_filters.append(symbol_name.lower())
        token_filters = [token for token in token_filters if token]

        cached = self._web_evidence_cache.get(cache_key)
        if (not refresh) and cached and now_ts - cached[0] <= 180:
            cached_items = filter_recent_items(cached[1])
            if not cached_items:
                cached_relaxed = filter_relaxed_items(cached[1])
                if cached_relaxed:
                    return MarketNewsResponse(
                        query=query_text,
                        age_hours=max_age_hours,
                        symbol=symbol_text or None,
                        symbol_name=symbol_name or None,
                        source_domains=response_domains,
                        items=[MarketNewsItem(**item) for item in cached_relaxed],
                        fetched_at=self._now_datetime(),
                        cache_hit=True,
                        fallback_used=True,
                        degraded=True,
                        degraded_reason="NEWS_OUT_OF_WINDOW",
                    )
            return MarketNewsResponse(
                query=query_text,
                age_hours=max_age_hours,
                symbol=symbol_text or None,
                symbol_name=symbol_name or None,
                source_domains=response_domains,
                items=[MarketNewsItem(**item) for item in cached_items],
                fetched_at=self._now_datetime(),
                cache_hit=True,
                fallback_used=False,
                degraded=len(cached_items) == 0,
                degraded_reason="NEWS_EMPTY" if len(cached_items) == 0 else None,
            )

        timeout = max(5.0, min(float(self._config.ai_timeout_sec), 12.0))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }

        def fetch_eastmoney_fast_news(client: httpx.Client) -> list[dict[str, str]]:
            timestamp = int(time.time() * 1000)
            response = client.get(
                "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
                params={
                    "client": "web",
                    "biz": "web_724",
                    "fastColumn": "102",
                    "sortEnd": "",
                    "pageSize": max(50, max_items * 3),
                    "req_trace": str(timestamp),
                    "_": str(timestamp),
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

            data = payload.get("data") if isinstance(payload, dict) else None
            source_rows: list[dict[str, object]] = []
            if isinstance(data, list):
                source_rows = [item for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                news_list = data.get("newsList")
                if isinstance(news_list, list):
                    source_rows = [item for item in news_list if isinstance(item, dict)]
                if not source_rows:
                    for value in data.values():
                        if isinstance(value, list) and value and isinstance(value[0], dict):
                            source_rows = [item for item in value if isinstance(item, dict)]
                            break

            results: list[dict[str, str]] = []
            seen_urls: set[str] = set()
            for idx, item in enumerate(source_rows):
                title = self._clean_text(html.unescape(str(item.get("title", "")).strip()))
                snippet = self._clean_text(
                    html.unescape(
                        str(
                            item.get("summary")
                            or item.get("digest")
                            or item.get("content")
                            or item.get("ltext")
                            or ""
                        ).strip()
                    )
                )
                if self._is_low_signal_title(title):
                    continue
                raw_time = str(
                    item.get("showTime")
                    or item.get("displayTime")
                    or item.get("publishTime")
                    or item.get("time")
                    or ""
                )
                parsed_dt = parse_news_datetime(raw_time)
                pub_date = to_pub_date(parsed_dt, raw_time)

                raw_unique_id = TextProcessor.clean_whitespace(
                    str(item.get("id") or item.get("newsid") or item.get("code") or "")
                )
                link = TextProcessor.clean_whitespace(str(item.get("url") or ""))
                if not link:
                    # Eastmoney fast news often has no URL and uses `code` as unique id.
                    link = f"https://kuaixun.eastmoney.com/news/{raw_unique_id}" if raw_unique_id else "https://kuaixun.eastmoney.com/"
                if link.startswith("//"):
                    link = f"https:{link}"
                elif link and not link.startswith("http"):
                    link = f"https://{link.lstrip('/')}"
                if not self._url_in_domains(link, allowed_domains):
                    continue

                source_name = self._clean_text(
                    str(item.get("source") or item.get("mediaName") or item.get("media") or item.get("infoSource") or "东方财富快讯")
                )[:40]
                corpus = f"{title} {snippet} {source_name}".lower()
                if token_filters and not any(token in corpus for token in token_filters):
                    continue
                if not title and not snippet:
                    continue

                dedupe_key = raw_unique_id or link or f"{title}:{pub_date}:{idx}"
                if dedupe_key in seen_urls:
                    continue
                seen_urls.add(dedupe_key)
                results.append(
                    {
                        "title": title[:120] if title else "无标题",
                        "url": link,
                        "snippet": (f"{source_name} | {snippet}" if source_name and snippet else (snippet or "无摘要"))[:260],
                        "pub_date": pub_date,
                        "source_name": source_name or "东方财富快讯",
                    }
                )
                if len(results) >= max_items:
                    break

            results.sort(
                key=lambda row: parse_news_datetime(str(row.get("pub_date", ""))) or datetime.min,
                reverse=True,
            )
            return results[:max_items]

        def fetch_google_rss(client: httpx.Client) -> tuple[list[dict[str, str]], str | None]:
            if symbol_text:
                query_candidates = [
                    f"{symbol_text} {symbol_name} {query_text}".strip(),
                    f"{symbol_code} {symbol_name} 新闻 公告".strip(),
                    f"{symbol_name} 板块 热点".strip(),
                    query_text,
                ]
            else:
                query_candidates = [query_text, f"{query_text} 财经", f"{query_text} A股"]

            queries: list[str] = []
            for candidate in query_candidates:
                cleaned = TextProcessor.clean_whitespace(candidate)
                if cleaned and cleaned not in queries:
                    queries.append(cleaned)

            seen_urls: set[str] = set()
            results: list[dict[str, str]] = []

            def parse_rss(xml_text: str, domain_filter: set[str]) -> list[dict[str, str]]:
                parsed_items: list[dict[str, str]] = []
                try:
                    root = ET.fromstring(xml_text)
                except ET.ParseError:
                    return parsed_items
                for item in root.findall("./channel/item"):
                    link = TextProcessor.clean_whitespace(item.findtext("link") or "")
                    source_node = item.find("source")
                    source_name = ""
                    source_url = ""
                    if source_node is not None:
                        source_name = TextProcessor.clean_whitespace(source_node.text or "")
                        source_url = TextProcessor.clean_whitespace(source_node.attrib.get("url") or "")
                    if self._is_low_quality_source(source_name, source_url):
                        continue
                    filter_url = source_url or link
                    # Prefer article link so the title can jump to the exact news page.
                    display_url = link or source_url
                    if not display_url:
                        continue
                    if display_url in seen_urls and source_url and source_url not in seen_urls:
                        display_url = source_url
                    if display_url in seen_urls:
                        continue
                    if not self._url_in_domains(filter_url, domain_filter):
                        continue
                    title_raw = html.unescape(TextProcessor.clean_whitespace(item.findtext("title") or ""))
                    desc_raw = html.unescape(TextProcessor.clean_whitespace(item.findtext("description") or ""))
                    title = self._clean_text(title_raw)
                    snippet = self._clean_text(desc_raw)
                    if self._is_low_signal_title(title):
                        continue
                    parsed_dt = parse_news_datetime(str(item.findtext("pubDate") or ""))
                    pub_date = to_pub_date(parsed_dt, str(item.findtext("pubDate") or ""))
                    corpus = f"{title} {snippet} {source_name}".lower()
                    if token_filters and not any(token in corpus for token in token_filters):
                        continue
                    if not title and not snippet:
                        continue
                    parsed_items.append(
                        {
                            "title": title[:120] if title else "无标题",
                            "url": display_url,
                            "snippet": (f"{source_name} | {snippet}" if source_name else snippet)[:260] if snippet else "无摘要",
                            "pub_date": pub_date,
                            "source_name": source_name[:40],
                        }
                    )
                    seen_urls.add(display_url)
                    if len(results) + len(parsed_items) >= max_items:
                        break
                return parsed_items

            fetch_error: str | None = None
            try:
                for item_query in queries:
                    if len(results) >= max_items:
                        break
                    response = client.get(
                        "https://news.google.com/rss/search",
                        params={
                            "q": item_query,
                            "hl": "zh-CN",
                            "gl": "CN",
                            "ceid": "CN:zh-Hans",
                        },
                    )
                    response.raise_for_status()
                    parsed_items = parse_rss(response.text, allowed_domains)
                    if not parsed_items and allowed_domains:
                        parsed_items = parse_rss(response.text, set())
                    results.extend(parsed_items)
                    if len(results) >= max_items:
                        break
            except Exception as exc:
                fetch_error = str(exc)[:160]
                results = []

            results.sort(
                key=lambda row: parse_news_datetime(str(row.get("pub_date", ""))) or datetime.min,
                reverse=True,
            )
            return results[:max_items], fetch_error

        fresh_items_raw: list[dict[str, str]] = []
        fetch_error: str | None = None
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                fresh_items_raw = fetch_eastmoney_fast_news(client)
                if not fresh_items_raw:
                    fresh_items_raw, fetch_error = fetch_google_rss(client)
        except Exception as exc:
            fetch_error = str(exc)[:160]
            fresh_items_raw = []

        fresh_items = filter_recent_items(fresh_items_raw)
        if fresh_items:
            self._web_evidence_cache[cache_key] = (now_ts, fresh_items)
            self._market_news_last_success = (
                now_ts,
                fresh_items,
                {"query": query_text, "symbol": symbol_text, "source_domains": domain_key},
            )
            return MarketNewsResponse(
                query=query_text,
                age_hours=max_age_hours,
                symbol=symbol_text or None,
                symbol_name=symbol_name or None,
                source_domains=response_domains,
                items=[MarketNewsItem(**item) for item in fresh_items],
                fetched_at=self._now_datetime(),
                cache_hit=False,
                fallback_used=False,
                degraded=False,
                degraded_reason=None,
            )

        fresh_relaxed_items = filter_relaxed_items(fresh_items_raw)
        if fresh_relaxed_items:
            self._web_evidence_cache[cache_key] = (now_ts, fresh_relaxed_items)
            self._market_news_last_success = (
                now_ts,
                fresh_relaxed_items,
                {"query": query_text, "symbol": symbol_text, "source_domains": domain_key},
            )
            return MarketNewsResponse(
                query=query_text,
                age_hours=max_age_hours,
                symbol=symbol_text or None,
                symbol_name=symbol_name or None,
                source_domains=response_domains,
                items=[MarketNewsItem(**item) for item in fresh_relaxed_items],
                fetched_at=self._now_datetime(),
                cache_hit=False,
                fallback_used=True,
                degraded=True,
                degraded_reason="NEWS_OUT_OF_WINDOW",
            )

        fallback_items: list[dict[str, str]] = []
        fallback_reason: str | None = None
        if cached and cached[1]:
            fallback_items = filter_recent_items(cached[1])
            if fallback_items:
                fallback_reason = "NEWS_FALLBACK_STALE_CACHE"
            else:
                fallback_items = filter_relaxed_items(cached[1])
                if fallback_items:
                    fallback_reason = "NEWS_FALLBACK_STALE_CACHE_OUT_OF_WINDOW"
        if not fallback_items and self._market_news_last_success and self._market_news_last_success[1]:
            _, last_rows, last_meta = self._market_news_last_success
            last_symbol = TextProcessor.clean_whitespace(str(last_meta.get("symbol", ""))).lower()
            if (symbol_text and last_symbol == symbol_text) or (not symbol_text):
                fallback_items = filter_recent_items(last_rows)
                if fallback_items:
                    fallback_reason = "NEWS_FALLBACK_LAST_SUCCESS"
                else:
                    fallback_items = filter_relaxed_items(last_rows)
                    if fallback_items:
                        fallback_reason = "NEWS_FALLBACK_LAST_SUCCESS_OUT_OF_WINDOW"

        if fallback_items:
            return MarketNewsResponse(
                query=query_text,
                age_hours=max_age_hours,
                symbol=symbol_text or None,
                symbol_name=symbol_name or None,
                source_domains=response_domains,
                items=[MarketNewsItem(**item) for item in fallback_items],
                fetched_at=self._now_datetime(),
                cache_hit=False,
                fallback_used=True,
                degraded=True,
                degraded_reason=f"{fallback_reason}:{fetch_error or 'NEWS_EMPTY'}",
            )

        self._web_evidence_cache[cache_key] = (now_ts, [])
        return MarketNewsResponse(
            query=query_text,
            age_hours=max_age_hours,
            symbol=symbol_text or None,
            symbol_name=symbol_name or None,
            source_domains=response_domains,
            items=[],
            fetched_at=self._now_datetime(),
            cache_hit=False,
            fallback_used=False,
            degraded=True,
            degraded_reason=fetch_error or "NEWS_EMPTY",
        )

    def get_review_tags(self) -> ReviewTagsPayload:
        return ReviewTagsPayload(
            emotion=[item.model_copy() for item in self._review_tags.get("emotion", [])],
            reason=[item.model_copy() for item in self._review_tags.get("reason", [])],
        )

    def create_review_tag(self, tag_type: ReviewTagType, payload: ReviewTagCreateRequest) -> ReviewTag:
        name = payload.name.strip()
        if not name:
            raise ValueError("tag name cannot be empty")
        for item in self._review_tags[tag_type]:
            if item.name.strip() == name:
                return item
        colors = ["blue", "cyan", "green", "gold", "orange", "red", "magenta", "purple", "geekblue", "lime"]
        color = colors[len(self._review_tags[tag_type]) % len(colors)]
        created = ReviewTag(
            id=f"{tag_type}-{uuid4().hex[:8]}",
            name=name,
            color=color,
            created_at=self._now_datetime(),
        )
        self._review_tags[tag_type].append(created)
        self._persist_app_state()
        return created

    def delete_review_tag(self, tag_type: ReviewTagType, tag_id: str) -> bool:
        original_count = len(self._review_tags[tag_type])
        self._review_tags[tag_type] = [item for item in self._review_tags[tag_type] if item.id != tag_id]
        if len(self._review_tags[tag_type]) == original_count:
            return False

        updated_at = self._now_datetime()
        for order_id in list(self._fill_tag_store.keys()):
            row = self._fill_tag_store[order_id]
            next_emotion = row.emotion_tag_id
            next_reasons = list(row.reason_tag_ids)
            changed = False
            if tag_type == "emotion" and row.emotion_tag_id == tag_id:
                next_emotion = None
                changed = True
            if tag_type == "reason" and tag_id in row.reason_tag_ids:
                next_reasons = [item for item in row.reason_tag_ids if item != tag_id]
                changed = True
            if not changed:
                continue
            if not next_emotion and not next_reasons:
                self._fill_tag_store.pop(order_id, None)
                continue
            self._fill_tag_store[order_id] = TradeFillTagAssignment(
                order_id=order_id,
                emotion_tag_id=next_emotion,
                reason_tag_ids=next_reasons,
                updated_at=updated_at,
            )
        self._persist_app_state()
        return True

    def get_fill_tag_assignment(self, order_id: str) -> TradeFillTagAssignment | None:
        return self._fill_tag_store.get(order_id)

    def list_fill_tag_assignments(self) -> list[TradeFillTagAssignment]:
        rows = list(self._fill_tag_store.values())
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows

    def set_fill_tag_assignment(self, order_id: str, payload: TradeFillTagUpdateRequest) -> TradeFillTagAssignment:
        fill_resp = self._sim_engine.list_fills(
            symbol=None,
            side=None,
            date_from=None,
            date_to=None,
            page=1,
            page_size=200_000,
        )
        if not any(item.order_id == order_id for item in fill_resp.items):
            raise ValueError("order_id not found in fill records")

        emotion_tag_id = (payload.emotion_tag_id or "").strip() or None
        if emotion_tag_id and self._find_review_tag("emotion", emotion_tag_id) is None:
            raise ValueError(f"emotion tag not found: {emotion_tag_id}")

        reason_ids = self._unique_ordered([str(item) for item in payload.reason_tag_ids])
        for item in reason_ids:
            if self._find_review_tag("reason", item) is None:
                raise ValueError(f"reason tag not found: {item}")

        if emotion_tag_id is None and not reason_ids:
            self._fill_tag_store.pop(order_id, None)
            self._persist_app_state()
            return TradeFillTagAssignment(
                order_id=order_id,
                emotion_tag_id=None,
                reason_tag_ids=[],
                updated_at=self._now_datetime(),
            )

        record = TradeFillTagAssignment(
            order_id=order_id,
            emotion_tag_id=emotion_tag_id,
            reason_tag_ids=reason_ids,
            updated_at=self._now_datetime(),
        )
        self._fill_tag_store[order_id] = record
        self._persist_app_state()
        return record

    def get_review_tag_stats(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> ReviewTagStatsResponse:
        fills = self._sim_engine.list_fills(
            symbol=None,
            side=None,
            date_from=date_from,
            date_to=date_to,
            page=1,
            page_size=200_000,
        ).items

        emotion_acc: dict[str, dict[str, float | int | str]] = {}
        reason_acc: dict[str, dict[str, float | int | str]] = {}
        for tag in self._review_tags.get("emotion", []):
            emotion_acc[tag.id] = {
                "tag_id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "count": 0,
                "gross_amount": 0.0,
                "net_amount": 0.0,
            }
        for tag in self._review_tags.get("reason", []):
            reason_acc[tag.id] = {
                "tag_id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "count": 0,
                "gross_amount": 0.0,
                "net_amount": 0.0,
            }

        for fill in fills:
            assignment = self._fill_tag_store.get(fill.order_id)
            if assignment is None:
                continue

            if assignment.emotion_tag_id and assignment.emotion_tag_id in emotion_acc:
                item = emotion_acc[assignment.emotion_tag_id]
                item["count"] = int(item["count"]) + 1
                item["gross_amount"] = float(item["gross_amount"]) + float(fill.gross_amount)
                item["net_amount"] = float(item["net_amount"]) + float(fill.net_amount)

            for tag_id in assignment.reason_tag_ids:
                if tag_id not in reason_acc:
                    continue
                item = reason_acc[tag_id]
                item["count"] = int(item["count"]) + 1
                item["gross_amount"] = float(item["gross_amount"]) + float(fill.gross_amount)
                item["net_amount"] = float(item["net_amount"]) + float(fill.net_amount)

        emotion_rows = [
            ReviewTagStatItem(
                tag_id=str(item["tag_id"]),
                name=str(item["name"]),
                color=str(item["color"]),
                count=int(item["count"]),
                gross_amount=float(item["gross_amount"]),
                net_amount=float(item["net_amount"]),
            )
            for item in emotion_acc.values()
            if int(item["count"]) > 0
        ]
        reason_rows = [
            ReviewTagStatItem(
                tag_id=str(item["tag_id"]),
                name=str(item["name"]),
                color=str(item["color"]),
                count=int(item["count"]),
                gross_amount=float(item["gross_amount"]),
                net_amount=float(item["net_amount"]),
            )
            for item in reason_acc.values()
            if int(item["count"]) > 0
        ]
        emotion_rows.sort(key=lambda row: (row.count, row.net_amount), reverse=True)
        reason_rows.sort(key=lambda row: (row.count, row.net_amount), reverse=True)

        return ReviewTagStatsResponse(
            date_from=date_from,
            date_to=date_to,
            emotion=emotion_rows,
            reason=reason_rows,
        )

    def analyze_stock_with_ai(self, symbol: str) -> AIAnalysisRecord:
        row = self._latest_rows.get(symbol) or self._build_row_from_candles(symbol)
        if row and symbol not in self._latest_rows:
            self._latest_rows[symbol] = row
        source_urls = self._enabled_ai_source_urls()
        stock_name = self._resolve_symbol_name(symbol, row)
        board_label = self._market_board_label(symbol)
        fallback = self._heuristic_ai_analysis(symbol, row, source_urls)
        web_evidence = self._collect_web_evidence(
            symbol,
            stock_name,
            source_urls,
            focus_date=fallback.breakout_date,
        )
        evidence_urls = [item["url"] for item in web_evidence if item.get("url")]
        fallback = fallback.model_copy(update={"source_urls": evidence_urls[:8] or source_urls})
        inferred_sector = self._infer_sector_from_context(symbol, stock_name, web_evidence)
        industry_evidence = self._collect_industry_evidence(
            inferred_sector,
            source_urls,
            focus_date=fallback.breakout_date,
        )
        industry_event_candidates = self._extract_industry_event_candidates(
            inferred_sector,
            industry_evidence,
        )
        if not industry_event_candidates:
            industry_event_candidates = self._build_industry_fallback_reasons(inferred_sector, row)
        combined_evidence: list[dict[str, str]] = []
        combined_evidence.extend(web_evidence)
        combined_evidence.extend(industry_evidence)
        core_event_candidates = self._extract_core_event_candidates(web_evidence)
        hotspot_titles = self._pick_breakout_hotspot_titles(web_evidence, fallback.breakout_date, max_items=2)
        if web_evidence:
            inferred_theme = self._infer_theme_from_web_evidence(web_evidence)
            inferred_reasons = self._infer_rise_reasons_from_web_evidence(web_evidence)
            enriched_reasons = [*core_event_candidates, *inferred_reasons, *hotspot_titles, *industry_event_candidates]
            if not enriched_reasons:
                enriched_reasons = fallback.rise_reasons
            sanitized_fallback_reasons = self._sanitize_ai_rise_reasons(
                enriched_reasons,
                symbol=symbol,
                core_event_candidates=core_event_candidates,
                industry_event_candidates=industry_event_candidates,
                industry_hint=inferred_sector,
            )
            fallback = fallback.model_copy(
                update={
                    "source_urls": evidence_urls[:8] or source_urls,
                    "theme_name": self._sanitize_theme_name(
                        inferred_theme if inferred_theme != "Unknown" else (fallback.theme_name or ""),
                        evidence=combined_evidence,
                        inferred_sector=inferred_sector,
                    ),
                    "rise_reasons": sanitized_fallback_reasons[:2],
                    "summary": self._build_compact_ai_summary(
                        symbol=symbol,
                        breakout_date=fallback.breakout_date,
                        board_label=board_label,
                        inferred_sector=inferred_sector,
                        rise_reasons=sanitized_fallback_reasons,
                        raw_summary=fallback.summary,
                        row=row,
                    ),
                }
            )
        else:
            sanitized_fallback_reasons = self._sanitize_ai_rise_reasons(
                [*fallback.rise_reasons, *industry_event_candidates],
                symbol=symbol,
                core_event_candidates=core_event_candidates,
                industry_event_candidates=industry_event_candidates,
                industry_hint=inferred_sector,
            )
            fallback = fallback.model_copy(
                update={
                    "theme_name": self._sanitize_theme_name(
                        fallback.theme_name or "",
                        evidence=combined_evidence,
                        inferred_sector=inferred_sector,
                    ),
                    "rise_reasons": sanitized_fallback_reasons[:2],
                    "summary": self._build_compact_ai_summary(
                        symbol=symbol,
                        breakout_date=fallback.breakout_date,
                        board_label=board_label,
                        inferred_sector=inferred_sector,
                        rise_reasons=sanitized_fallback_reasons,
                        raw_summary=fallback.summary,
                        row=row,
                    ),
                }
            )

        provider_result = self._call_provider_for_stock(symbol, row, source_urls)
        record = provider_result or fallback
        if provider_result and provider_result.error_code:
            record = fallback.model_copy(
                update={
                    "provider": provider_result.provider,
                    "summary": provider_result.summary,
                    "error_code": provider_result.error_code,
                }
            )

        final_reasons_source = [
            *(core_event_candidates or []),
            *(industry_event_candidates or []),
            *(record.rise_reasons or []),
            *hotspot_titles,
        ]
        final_reasons = self._sanitize_ai_rise_reasons(
            final_reasons_source,
            symbol=symbol,
            core_event_candidates=core_event_candidates,
            industry_event_candidates=industry_event_candidates,
            industry_hint=inferred_sector,
        )
        final_theme = self._sanitize_theme_name(
            record.theme_name or "",
            evidence=combined_evidence,
            inferred_sector=inferred_sector,
        )
        if final_reasons and final_reasons[0].startswith("行业驱动：") and inferred_sector != "Unknown":
            final_theme = inferred_sector
        final_summary = self._build_compact_ai_summary(
            symbol=symbol,
            breakout_date=record.breakout_date,
            board_label=board_label,
            inferred_sector=inferred_sector,
            rise_reasons=final_reasons,
            raw_summary=record.summary,
            row=row,
        )
        record = record.model_copy(
            update={
                "theme_name": final_theme,
                "rise_reasons": final_reasons[:2],
                "summary": final_summary,
                "source_urls": evidence_urls[:8] or source_urls,
            }
        )

        self._ai_record_store.insert(0, record)
        if len(self._ai_record_store) > 200:
            self._ai_record_store = self._ai_record_store[:200]
        self._persist_app_state()
        return record

    def get_ai_records(self) -> list[AIAnalysisRecord]:
        return self._ai_record_store

    def delete_ai_record(self, symbol: str, fetched_at: str, provider: str | None = None) -> bool:
        for index, item in enumerate(self._ai_record_store):
            if item.symbol != symbol:
                continue
            if item.fetched_at != fetched_at:
                continue
            if provider is not None and item.provider != provider:
                continue
            del self._ai_record_store[index]
            self._persist_app_state()
            return True
        return False

    def get_config(self) -> AppConfig:
        return self._config

    def set_config(self, payload: AppConfig) -> AppConfig:
        self._config = payload
        self._candles_map = {}
        self._latest_rows = {}
        self._signals_cache = {}
        self._backtest_matrix_engine.clear_runtime_cache()
        self._clear_backtest_signal_matrix_runtime_cache()
        self._clear_backtest_input_pool_runtime_cache()
        self._clear_backtest_precheck_cache()
        self._persist_app_state()
        return self._config

    def get_wyckoff_event_store_stats(self) -> WyckoffEventStoreStatsResponse:
        metrics = self._snapshot_wyckoff_metrics()
        cache_hits = int(metrics.get("cache_hits", 0) or 0)
        cache_misses = int(metrics.get("cache_misses", 0) or 0)
        cache_total = cache_hits + cache_misses
        cache_hit_rate = round(cache_hits / cache_total, 6) if cache_total > 0 else 0.0
        cache_miss_rate = round(cache_misses / cache_total, 6) if cache_total > 0 else 0.0
        snapshot_reads = int(metrics.get("snapshot_reads", 0) or 0)
        snapshot_read_ms_total = float(metrics.get("snapshot_read_ms_total", 0.0) or 0.0)
        avg_snapshot_read_ms = round(snapshot_read_ms_total / snapshot_reads, 6) if snapshot_reads > 0 else 0.0
        return WyckoffEventStoreStatsResponse(
            enabled=self._wyckoff_event_store.enabled,
            read_only=self._wyckoff_event_store.read_only,
            db_path=str(self._wyckoff_event_store.db_path),
            db_exists=self._wyckoff_event_store.db_path.exists(),
            db_record_count=self._wyckoff_event_store.count_records(),
            runtime_cache_size=self._wyckoff_event_store.runtime_cache_size,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            cache_hit_rate=cache_hit_rate,
            cache_miss_rate=cache_miss_rate,
            snapshot_reads=snapshot_reads,
            avg_snapshot_read_ms=avg_snapshot_read_ms,
            lazy_fill_writes=int(metrics.get("lazy_fill_writes", 0) or 0),
            backfill_runs=int(metrics.get("backfill_runs", 0) or 0),
            backfill_writes=int(metrics.get("backfill_writes", 0) or 0),
            quality_empty_events=int(metrics.get("quality_empty_events", 0) or 0),
            quality_score_outliers=int(metrics.get("quality_score_outliers", 0) or 0),
            quality_date_misaligned=int(metrics.get("quality_date_misaligned", 0) or 0),
            last_backfill_started_at=(
                str(metrics.get("last_backfill_started_at"))
                if metrics.get("last_backfill_started_at") is not None
                else None
            ),
            last_backfill_finished_at=(
                str(metrics.get("last_backfill_finished_at"))
                if metrics.get("last_backfill_finished_at") is not None
                else None
            ),
            last_backfill_duration_sec=(
                float(metrics.get("last_backfill_duration_sec"))
                if metrics.get("last_backfill_duration_sec") is not None
                else None
            ),
            last_backfill_scan_dates=int(metrics.get("last_backfill_scan_dates", 0) or 0),
            last_backfill_symbols=int(metrics.get("last_backfill_symbols", 0) or 0),
            last_backfill_quality_empty_events=int(metrics.get("last_backfill_quality_empty_events", 0) or 0),
            last_backfill_quality_score_outliers=int(
                metrics.get("last_backfill_quality_score_outliers", 0) or 0
            ),
            last_backfill_quality_date_misaligned=int(
                metrics.get("last_backfill_quality_date_misaligned", 0) or 0
            ),
        )

    def backfill_wyckoff_event_store(
        self,
        payload: WyckoffEventStoreBackfillRequest,
    ) -> WyckoffEventStoreBackfillResponse:
        if not self._wyckoff_event_store.enabled:
            raise ValueError("威科夫事件库未启用，请先开启 TDX_TREND_WYCKOFF_STORE_ENABLED。")
        if self._wyckoff_event_store.read_only:
            raise ValueError("威科夫事件库当前为只读模式，无法执行回填。")

        scan_dates = self._build_backtest_scan_dates(payload.date_from, payload.date_to)
        if not scan_dates:
            raise ValueError("回填区间内无可扫描交易日。")

        valid_markets = [item for item in payload.markets if item in {"sh", "sz", "bj"}]
        if not valid_markets:
            valid_markets = [item for item in self._config.markets if item in {"sh", "sz", "bj"}]
        if not valid_markets:
            valid_markets = ["sh", "sz"]
        markets = list(dict.fromkeys(valid_markets))

        raw_windows = [int(item) for item in payload.window_days_list]
        window_days_list = sorted(
            list(
                dict.fromkeys(
                    item for item in raw_windows if 20 <= item <= 240
                )
            )
        )
        if not window_days_list:
            raise ValueError("window_days_list 必须至少包含一个 [20,240] 内的窗口。")

        started_at = self._now_datetime()
        started_ts = time.perf_counter()
        self._bump_wyckoff_metric("backfill_runs", 1)
        self._set_wyckoff_metric("last_backfill_started_at", started_at)

        loaded_rows_total = 0
        symbols_scanned = 0
        cache_hits = 0
        cache_misses = 0
        computed_count = 0
        write_count = 0
        quality_empty_events = 0
        quality_score_outliers = 0
        quality_date_misaligned = 0
        loader_error_counter: dict[str, int] = {}

        for as_of_date in scan_dates:
            input_rows, load_error = load_input_pool_from_tdx(
                tdx_root=self._config.tdx_data_path,
                markets=markets,
                return_window_days=max(5, min(120, int(self._config.return_window_days))),
                as_of_date=as_of_date,
            )
            if load_error:
                loader_error_counter[load_error] = loader_error_counter.get(load_error, 0) + 1
            loaded_rows_total += len(input_rows)

            unique_rows: list[ScreenerResult] = []
            seen_symbols: set[str] = set()
            for row in input_rows:
                symbol = str(row.symbol).strip().lower()
                if not symbol or symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                unique_rows.append(row)
                if len(unique_rows) >= payload.max_symbols_per_day:
                    break

            for row in unique_rows:
                symbol = str(row.symbol).strip().lower()
                if not symbol:
                    continue
                symbols_scanned += 1
                data_source = str(self._config.market_data_source).strip() or "unknown"
                for window_days in window_days_list:
                    params_hash = build_wyckoff_params_hash(window_days)
                    if not payload.force_rebuild:
                        read_started = time.perf_counter()
                        cached = self._wyckoff_event_store.get_snapshot(
                            symbol=symbol,
                            trade_date=as_of_date,
                            window_days=window_days,
                            algo_version=self._wyckoff_event_algo_version,
                            data_source=data_source,
                            data_version=self._wyckoff_event_data_version,
                            params_hash=params_hash,
                        )
                        read_duration_ms = (time.perf_counter() - read_started) * 1000.0
                        self._record_wyckoff_snapshot_read_latency(read_duration_ms)
                        if cached is not None:
                            cache_hits += 1
                            self._bump_wyckoff_metric("cache_hits", 1)
                            continue

                    cache_misses += 1
                    self._bump_wyckoff_metric("cache_misses", 1)
                    candles, resolved_as_of_date = self._slice_candles_as_of(
                        self._ensure_candles(symbol),
                        as_of_date,
                    )
                    if not candles or not resolved_as_of_date:
                        continue
                    snapshot = SignalAnalyzer.calculate_wyckoff_snapshot(row, candles, window_days)
                    quality_flags = self._inspect_wyckoff_snapshot_quality(
                        snapshot,
                        trade_date=resolved_as_of_date,
                    )
                    self._record_wyckoff_snapshot_quality(quality_flags)
                    quality_empty_events += int(max(0, quality_flags.get("empty_events", 0)))
                    quality_score_outliers += int(max(0, quality_flags.get("score_outliers", 0)))
                    quality_date_misaligned += int(max(0, quality_flags.get("date_misaligned", 0)))
                    computed_count += 1
                    write_ok = self._wyckoff_event_store.upsert_snapshot(
                        symbol=symbol,
                        trade_date=resolved_as_of_date,
                        window_days=window_days,
                        algo_version=self._wyckoff_event_algo_version,
                        data_source=data_source,
                        data_version=self._wyckoff_event_data_version,
                        params_hash=params_hash,
                        snapshot=snapshot,
                    )
                    if write_ok:
                        write_count += 1
                        self._bump_wyckoff_metric("backfill_writes", 1)

        finished_at = self._now_datetime()
        duration_sec = round(max(0.0, time.perf_counter() - started_ts), 4)
        self._set_wyckoff_metric("last_backfill_finished_at", finished_at)
        self._set_wyckoff_metric("last_backfill_duration_sec", duration_sec)
        self._set_wyckoff_metric("last_backfill_scan_dates", len(scan_dates))
        self._set_wyckoff_metric("last_backfill_symbols", symbols_scanned)
        self._set_wyckoff_metric("last_backfill_quality_empty_events", quality_empty_events)
        self._set_wyckoff_metric("last_backfill_quality_score_outliers", quality_score_outliers)
        self._set_wyckoff_metric("last_backfill_quality_date_misaligned", quality_date_misaligned)

        warnings: list[str] = []
        if loader_error_counter:
            for reason, count in sorted(loader_error_counter.items()):
                warnings.append(f"{reason} x{count}")
        if payload.force_rebuild:
            warnings.append("已开启 force_rebuild：命中记录也会重算并覆盖写入。")
        if quality_empty_events > 0:
            warnings.append(f"检测到空事件快照 {quality_empty_events} 条。")
        if quality_score_outliers > 0:
            warnings.append(f"检测到异常分值快照 {quality_score_outliers} 条。")
        if quality_date_misaligned > 0:
            warnings.append(f"检测到事件日期错位快照 {quality_date_misaligned} 条。")

        message = (
            f"事件库回填完成：扫描 {len(scan_dates)} 日，标的 {symbols_scanned}，"
            f"命中 {cache_hits}，重算 {computed_count}，写入 {write_count}。"
        )
        return WyckoffEventStoreBackfillResponse(
            ok=True,
            message=message,
            date_from=scan_dates[0],
            date_to=scan_dates[-1],
            markets=markets,
            window_days_list=window_days_list,
            scan_dates=len(scan_dates),
            loaded_rows_total=loaded_rows_total,
            symbols_scanned=symbols_scanned,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            computed_count=computed_count,
            write_count=write_count,
            quality_empty_events=quality_empty_events,
            quality_score_outliers=quality_score_outliers,
            quality_date_misaligned=quality_date_misaligned,
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=duration_sec,
            warnings=warnings,
        )

    def get_system_storage_status(self) -> SystemStorageStatus:
        configured = (self._config.akshare_cache_dir or "").strip()
        if configured:
            resolved_cache_dir = self._resolve_user_path(configured)
        else:
            resolved_cache_dir = Path.home() / ".tdx-trend" / "akshare" / "daily"
        cache_exists = resolved_cache_dir.exists() and resolved_cache_dir.is_dir()
        cache_file_count = len(list(resolved_cache_dir.glob("*.csv"))) if cache_exists else 0

        candidates: set[str] = set()
        candidates.add(str(resolved_cache_dir))
        default_cache_dir = Path.home() / ".tdx-trend" / "akshare" / "daily"
        candidates.add(str(default_cache_dir))
        env_cache_dir = os.getenv("AKSHARE_CACHE_DIR", "").strip()
        if env_cache_dir:
            candidates.add(str(self._resolve_user_path(env_cache_dir)))
        home_cache_root = Path.home() / ".tdx-trend" / "akshare"
        if home_cache_root.exists() and home_cache_root.is_dir():
            for path in home_cache_root.glob("**"):
                if not path.is_dir():
                    continue
                if any(path.glob("*.csv")):
                    candidates.add(str(path))
        ordered_candidates = sorted(path for path in candidates if path.strip())

        sim_state_env = os.getenv("TDX_TREND_SIM_STATE_PATH", "").strip()
        sim_state_path = self._resolve_user_path(sim_state_env) if sim_state_env else Path.home() / ".tdx-trend" / "sim_state.json"
        return SystemStorageStatus(
            app_state_path=str(self._app_state_path),
            app_state_exists=self._app_state_path.exists(),
            sim_state_path=str(sim_state_path),
            sim_state_exists=sim_state_path.exists(),
            akshare_cache_dir=configured,
            akshare_cache_dir_resolved=str(resolved_cache_dir),
            akshare_cache_dir_exists=cache_exists,
            akshare_cache_file_count=cache_file_count,
            akshare_cache_candidates=ordered_candidates,
            wyckoff_event_store_path=str(self._wyckoff_event_store.db_path),
            wyckoff_event_store_exists=self._wyckoff_event_store.db_path.exists(),
            wyckoff_event_store_read_only=self._wyckoff_event_store.read_only,
        )

    def sync_market_data(self, payload: MarketDataSyncRequest) -> MarketDataSyncResponse:
        out_dir = (payload.out_dir or "").strip() or (self._config.akshare_cache_dir or "").strip()
        if not out_dir:
            out_dir = str(Path.home() / ".tdx-trend" / "akshare" / "daily")

        started = self._now_datetime()
        try:
            summary = sync_baostock_daily(
                symbols_text=payload.symbols,
                all_market=payload.all_market,
                limit=payload.limit,
                mode=payload.mode,
                start_date=payload.start_date,
                end_date=payload.end_date,
                initial_days=payload.initial_days,
                sleep_sec=payload.sleep_sec,
                out_dir=out_dir,
            )
            if int(summary.get("ok_count", 0)) > 0:
                # Ensure subsequent APIs reload latest local files after sync.
                self._candles_map = {}
                self._latest_rows = {}
                self._signals_cache = {}
                self._backtest_matrix_engine.clear_runtime_cache()
                self._clear_backtest_signal_matrix_runtime_cache()
                self._clear_backtest_input_pool_runtime_cache()
                self._clear_backtest_precheck_cache()
            errors = [str(item) for item in summary.get("errors", []) if str(item).strip()]
            failed = int(summary.get("fail_count", 0))
            ok = failed == 0
            message = (
                f"Baostock 同步完成: 成功 {summary.get('ok_count', 0)} / "
                f"失败 {failed} / 跳过 {summary.get('skipped_count', 0)} / "
                f"新增 {summary.get('new_rows_total', 0)} 行"
            )
            if not ok and errors:
                message = f"{message}（首个错误: {errors[0]}）"
            return MarketDataSyncResponse(
                ok=ok,
                provider="baostock",
                mode="full" if payload.mode == "full" else "incremental",
                message=message,
                out_dir=str(summary.get("out_dir", out_dir)),
                symbol_count=int(summary.get("symbol_count", 0)),
                ok_count=int(summary.get("ok_count", 0)),
                fail_count=failed,
                skipped_count=int(summary.get("skipped_count", 0)),
                new_rows_total=int(summary.get("new_rows_total", 0)),
                started_at=str(summary.get("started_at", started)),
                finished_at=str(summary.get("finished_at", self._now_datetime())),
                duration_sec=float(summary.get("duration_sec", 0.0)),
                errors=errors[:50],
            )
        except Exception as exc:
            return MarketDataSyncResponse(
                ok=False,
                provider="baostock",
                mode="full" if payload.mode == "full" else "incremental",
                message=f"Baostock 同步失败: {type(exc).__name__}: {exc}",
                out_dir=out_dir,
                started_at=started,
                finished_at=self._now_datetime(),
                duration_sec=0.0,
                errors=[str(exc)],
            )


store = InMemoryStore()
