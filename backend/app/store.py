from __future__ import annotations

import math
import json
import os
import random
import re
import time
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

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
    SignalResult,
    SimTradeFill,
    SimTradeOrder,
    Stage,
    StockAnalysis,
    StockAnalysisResponse,
    StockAnnotation,
    ThemeStage,
    TradeRecord,
    TrendClass,
)
from .tdx_loader import (
    load_candles_for_symbol,
    load_input_pool_from_tdx,
    load_intraday_for_symbol_date,
)

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

THEME_STAGES: tuple[ThemeStage, ThemeStage, ThemeStage] = ("发酵中", "高潮", "退潮")


class InMemoryStore:
    def __init__(self) -> None:
        self._candles_map: dict[str, list[CandlePoint]] = {}
        self._run_store: dict[str, ScreenerRunDetail] = {}
        self._annotation_store: dict[str, StockAnnotation] = {}
        self._config: AppConfig = self._default_config()
        self._latest_rows: dict[str, ScreenerResult] = {}
        self._ai_record_store: list[AIAnalysisRecord] = self._default_ai_records()

    @staticmethod
    def _default_config() -> AppConfig:
        return AppConfig(
            tdx_data_path=r"D:\new_tdx\vipdoc",
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

        base = next((item for item in STOCK_POOL if item["symbol"] == symbol), None)
        if base and base.get("name"):
            return str(base["name"])
        return symbol.upper()

    @staticmethod
    def _safe_mean(values: list[float] | list[int]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    def _build_row_from_candles(self, symbol: str) -> ScreenerResult | None:
        candles = self._ensure_candles(symbol)
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
        theme_candidates = [
            "固态电池",
            "算力与AI应用",
            "有色资源",
            "机器人",
            "高端消费",
            "创新药",
            "低空经济",
            "半导体设备",
        ]
        seed = self._hash_seed(symbol)
        return theme_candidates[seed % len(theme_candidates)]

    def _infer_breakout_date(self, symbol: str, row: ScreenerResult | None) -> str:
        if row is None:
            return self._days_ago(12 + self._hash_seed(symbol) % 12)
        offset = 8 + int(max(0.0, min(30.0, row.retrace20 * 100 / 2)))
        return self._days_ago(offset)

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
        theme_name = self._guess_theme_name(symbol, row)
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
            f"趋势类型 {row.trend_class}，阶段 {row.stage}，窗口涨幅 {ret_text}，"
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
        prompt = (
            "Return JSON only with keys: "
            "conclusion, confidence, summary, breakout_date, rise_reasons, trend_bull_type, theme_name. "
            "conclusion must be one of 发酵中/高潮/退潮/Unknown.\n"
            f"symbol={symbol}\n"
            f"name={stock_name}\n"
            f"features={row_text}\n"
            f"context={context_text}\n"
            f"sources={source_urls}"
        )
        body = {
            "model": provider.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": "You are an A-share short-term trend analyst."},
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
            if len(summary) > 220:
                summary = f"{summary[:220]}..."

            breakout_date = str(parsed.get("breakout_date", "")).strip() if parsed else ""
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", breakout_date):
                breakout_date = baseline.breakout_date or self._now_date()

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

            return AIAnalysisRecord(
                provider=provider.id,
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
                rise_reasons=rise_reasons[:6],
                error_code=None,
            )
        except httpx.TimeoutException:
            return baseline.model_copy(
                update={
                    "provider": provider.id,
                    "summary": "AI请求超时，已回退本地规则分析。",
                    "error_code": "AI_TIMEOUT",
                }
            )
        except Exception:
            return baseline.model_copy(
                update={
                    "provider": provider.id,
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
            real_candles = load_candles_for_symbol(self._config.tdx_data_path, symbol)
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
        )
        if real_input_pool:
            run_id = f"{int(datetime.now().timestamp() * 1000)}-{uuid4().hex[:6]}"
            preview = sorted(
                real_input_pool,
                key=lambda row: row.score + row.ai_confidence * 20,
                reverse=True,
            )[:5]
            step4_pool = [
                row.model_copy(update={"labels": list({*row.labels, "待买观察"})})
                for row in preview
            ]
            has_degraded_rows = any(row.degraded for row in real_input_pool)

            detail = ScreenerRunDetail(
                run_id=run_id,
                created_at=self._now_datetime(),
                params=params,
                step_summary=ScreenerStepSummary(
                    input_count=len(real_input_pool),
                    step1_count=0,
                    step2_count=0,
                    step3_count=0,
                    step4_count=len(step4_pool),
                ),
                step_pools=ScreenerStepPools(
                    input=real_input_pool,
                    step1=[],
                    step2=[],
                    step3=[],
                    step4=step4_pool,
                ),
                results=step4_pool,
                degraded=has_degraded_rows,
                degraded_reason=real_error if has_degraded_rows else None,
            )
            latest_rows = {row.symbol: row for row in real_input_pool}
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

    def get_signals(self) -> list[SignalResult]:
        raw = [
            {
                "symbol": "sz300750",
                "name": "宁德时代",
                "trigger_reason": "突破新高后缩量回踩",
                "signals": ["A", "B"],
            },
            {
                "symbol": "sh601899",
                "name": "紫金矿业",
                "trigger_reason": "板块分歧后转一致",
                "signals": ["A", "C"],
            },
            {"symbol": "sh600519", "name": "贵州茅台", "trigger_reason": "MA10回踩确认", "signals": ["A"]},
        ]
        items: list[SignalResult] = []
        for index, item in enumerate(raw):
            primary, secondary = self._resolve_signal_priority(item["signals"])
            items.append(
                SignalResult(
                    symbol=item["symbol"],
                    name=item["name"],
                    primary_signal=primary,  # type: ignore[arg-type]
                    secondary_signals=secondary,  # type: ignore[arg-type]
                    trigger_date=self._days_ago(index),
                    expire_date=(datetime.now() + timedelta(days=2 - index)).strftime("%Y-%m-%d"),
                    trigger_reason=item["trigger_reason"],
                    priority=3 if primary == "B" else 2 if primary == "A" else 1,
                )
            )
        return items

    def create_order(self, payload: CreateOrderRequest) -> CreateOrderResponse:
        order_id = f"ord-{int(datetime.now().timestamp() * 1000)}-{random.randint(100, 999)}"
        order = SimTradeOrder(
            order_id=order_id,
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            signal_date=payload.signal_date,
            submit_date=payload.submit_date,
            status="filled",
        )
        fill = SimTradeFill(
            order_id=order_id,
            symbol=payload.symbol,
            fill_date=payload.submit_date,
            fill_price=86.35,
            price_source="vwap",
            fee_commission=5.0,
            fee_stamp_tax=16.2 if payload.side == "sell" else 0.0,
            fee_transfer=0.5,
        )
        return CreateOrderResponse(order=order, fill=fill)

    @staticmethod
    def get_portfolio() -> PortfolioSnapshot:
        return PortfolioSnapshot(
            total_asset=1_082_000,
            cash=308_000,
            position_value=774_000,
            positions=[
                PortfolioPosition(
                    symbol="sz300750",
                    name="宁德时代",
                    quantity=1500,
                    avg_cost=165.3,
                    current_price=174.2,
                    pnl_ratio=0.0538,
                    holding_days=9,
                ),
                PortfolioPosition(
                    symbol="sh601899",
                    name="紫金矿业",
                    quantity=12000,
                    avg_cost=16.8,
                    current_price=17.6,
                    pnl_ratio=0.0476,
                    holding_days=14,
                ),
            ],
        )

    @staticmethod
    def get_review() -> ReviewResponse:
        return ReviewResponse(
            stats=ReviewStats(
                win_rate=0.62,
                total_return=0.128,
                max_drawdown=0.071,
                avg_pnl_ratio=0.034,
            ),
            trades=[
                TradeRecord(
                    symbol="sz300750",
                    buy_date="2026-01-16",
                    buy_price=160.5,
                    sell_date="2026-01-23",
                    sell_price=172.4,
                    holding_days=7,
                    pnl_amount=17_850,
                    pnl_ratio=0.074,
                ),
                TradeRecord(
                    symbol="sh601899",
                    buy_date="2026-01-08",
                    buy_price=15.6,
                    sell_date="2026-01-20",
                    sell_price=17.2,
                    holding_days=12,
                    pnl_amount=9_600,
                    pnl_ratio=0.102,
                ),
            ],
        )

    def analyze_stock_with_ai(self, symbol: str) -> AIAnalysisRecord:
        row = self._latest_rows.get(symbol) or self._build_row_from_candles(symbol)
        if row and symbol not in self._latest_rows:
            self._latest_rows[symbol] = row
        source_urls = self._enabled_ai_source_urls()
        fallback = self._heuristic_ai_analysis(symbol, row, source_urls)
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

        self._ai_record_store.insert(0, record)
        if len(self._ai_record_store) > 200:
            self._ai_record_store = self._ai_record_store[:200]
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
            return True
        return False

    def get_config(self) -> AppConfig:
        return self._config

    def set_config(self, payload: AppConfig) -> AppConfig:
        self._config = payload
        self._candles_map = {}
        self._latest_rows = {}
        return self._config


store = InMemoryStore()
