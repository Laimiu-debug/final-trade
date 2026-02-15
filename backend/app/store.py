from __future__ import annotations

import math
import json
import os
import random
import re
import time
import html
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx

from .models import (
    AIAnalysisRecord,
    AIProviderTestResponse,
    AISourceConfig,
    AIProviderConfig,
    AppConfig,
    CandlePoint,
    CreateOrderRequest,
    CreateOrderResponse,
    IntradayPayload,
    IntradayPoint,
    MarketDataSyncRequest,
    MarketDataSyncResponse,
    PortfolioPosition,
    PortfolioSnapshot,
    ReviewResponse,
    ReviewStats,
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
    StockAnalysis,
    StockAnalysisResponse,
    StockAnnotation,
    ThemeStage,
    TradeRecord,
    TrendClass,
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



class InMemoryStore:
    _APP_STATE_SCHEMA_VERSION = 1

    def __init__(self, app_state_path: str | None = None, sim_state_path: str | None = None) -> None:
        self._lock = RLock()
        self._candles_map: dict[str, list[CandlePoint]] = {}
        self._run_store: dict[str, ScreenerRunDetail] = {}
        self._annotation_store: dict[str, StockAnnotation] = {}
        self._config: AppConfig = self._default_config()
        self._latest_rows: dict[str, ScreenerResult] = {}
        self._ai_record_store: list[AIAnalysisRecord] = self._default_ai_records()
        self._web_evidence_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._quote_profile_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._signals_cache: dict[str, tuple[float, SignalsResponse]] = {}
        self._app_state_path = self._resolve_app_state_path(app_state_path)
        self._load_or_init_app_state()
        self._sim_engine = SimAccountEngine(
            get_candles=self._ensure_candles,
            resolve_symbol_name=self._resolve_symbol_name,
            now_date=self._now_date,
            now_datetime=self._now_datetime,
            state_path=sim_state_path or os.getenv("TDX_TREND_SIM_STATE_PATH", "").strip() or None,
        )

    @staticmethod
    def _resolve_user_path(value: str) -> Path:
        expanded = os.path.expandvars(os.path.expanduser(str(value).strip()))
        return Path(expanded)

    @classmethod
    def _resolve_app_state_path(cls, app_state_path: str | None = None) -> Path:
        if app_state_path and str(app_state_path).strip():
            return cls._resolve_user_path(app_state_path)
        env_value = os.getenv("TDX_TREND_APP_STATE_PATH", "").strip()
        if env_value:
            return cls._resolve_user_path(env_value)
        return Path.home() / ".tdx-trend" / "app_state.json"

    def _build_app_state_payload(self) -> dict[str, object]:
        return {
            "schema_version": self._APP_STATE_SCHEMA_VERSION,
            "config": self._config.model_dump(),
            "ai_records": [item.model_dump() for item in self._ai_record_store],
            "annotations": {symbol: item.model_dump() for symbol, item in self._annotation_store.items()},
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

    @staticmethod
    def _days_ago(days: int) -> str:
        return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

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
            real_candles = load_candles_for_symbol(
                self._config.tdx_data_path,
                symbol,
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

    def create_screener_run(self, params: ScreenerParams) -> ScreenerRunDetail:
        real_input_pool, real_error = load_input_pool_from_tdx(
            tdx_root=self._config.tdx_data_path,
            markets=params.markets,
            return_window_days=params.return_window_days,
            as_of_date=params.as_of_date,
        )
        if real_input_pool:
            run_id = f"{int(datetime.now().timestamp() * 1000)}-{uuid4().hex[:6]}"
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
                degraded=has_degraded_rows,
                degraded_reason=real_error if has_degraded_rows else None,
            )
            latest_rows = {row.symbol: row for row in real_input_pool}
            latest_rows.update({row.symbol: row for row in step1_pool})
            latest_rows.update({row.symbol: row for row in step2_pool})
            latest_rows.update({row.symbol: row for row in step3_pool})
            latest_rows.update({row.symbol: row for row in step4_pool})
            self._latest_rows = latest_rows
            self._run_store[run_id] = detail
            return detail

        mode = params.mode
        run_id = f"{int(datetime.now().timestamp() * 1000)}-{uuid4().hex[:6]}"

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
        latest_rows = {row.symbol: row for row in input_pool}
        latest_rows.update({row.symbol: row for row in step4_pool})
        self._latest_rows = latest_rows
        self._run_store[run_id] = detail
        return detail

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

        source, error = load_input_pool_from_tdx(
            tdx_root=self._config.tdx_data_path,
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

        source.sort(key=lambda row: row.score + row.ai_confidence * 20, reverse=True)
        max_candidates = 1500
        return source[:max_candidates], error, None, as_of_date

    def _calc_wyckoff_snapshot(
        self,
        row: ScreenerResult,
        window_days: int,
        *,
        as_of_date: str | None = None,
    ) -> dict[str, object]:
        """Calculate Wyckoff snapshot using SignalAnalyzer."""
        candles, resolved_as_of_date = self._slice_candles_as_of(
            self._ensure_candles(row.symbol), as_of_date
        )
        return SignalAnalyzer.calculate_wyckoff_snapshot(row, candles, window_days)

    def _signals_cache_key(
        self,
        *,
        mode: SignalScanMode,
        run_id: str | None,
        trend_step: TrendPoolStep,
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
        source_count = len(candidates)
        cache_key = self._signals_cache_key(
            mode=mode,
            run_id=resolved_run_id if mode == "trend_pool" else run_id,
            trend_step=trend_step if mode == "trend_pool" else "auto",
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
            if resolved_as_of_date:
                try:
                    as_of_dt = datetime.strptime(resolved_as_of_date, "%Y-%m-%d")
                    expire_dt = as_of_dt if as_of_dt >= trigger_dt else trigger_dt
                except ValueError:
                    pass
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
        return payload

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
        self._persist_app_state()
        return self._config

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
