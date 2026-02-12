from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from .models import (
    AIAnalysisRecord,
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
            self._latest_rows = {row.symbol: row for row in real_input_pool}
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
        self._latest_rows = {row.symbol: row for row in step4_pool}
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

    def get_ai_records(self) -> list[AIAnalysisRecord]:
        return [
            AIAnalysisRecord(
                provider="openai",
                symbol="sz300750",
                fetched_at=self._now_datetime(),
                source_urls=["https://example.com/news/ev-1", "https://example.com/forum/battery"],
                summary="板块热度持续，头部与补涨梯队完整。",
                conclusion="发酵中",
                confidence=0.78,
            ),
            AIAnalysisRecord(
                provider="openai",
                symbol="sh600519",
                fetched_at=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                source_urls=["https://example.com/news/consumption"],
                summary="消费主线维持，成交稳定。",
                conclusion="高潮",
                confidence=0.66,
            ),
        ]

    def get_config(self) -> AppConfig:
        return self._config

    def set_config(self, payload: AppConfig) -> AppConfig:
        self._config = payload
        self._candles_map = {}
        self._latest_rows = {}
        return self._config


store = InMemoryStore()
