from __future__ import annotations

import math
from typing import Any, Protocol

from ..models import BacktestRunRequest, ScreenerResult, SignalResult


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


class StrategyPlugin(Protocol):
    strategy_id: str

    def build_universe(
        self,
        *,
        candidates: list[ScreenerResult],
        params: dict[str, Any],
        mode: str,
    ) -> list[ScreenerResult]:
        ...

    def generate_signals(
        self,
        *,
        row: ScreenerResult,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        ...

    def rank_signals(
        self,
        *,
        signal: SignalResult,
        row: ScreenerResult,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        ...

    def entry_policy(
        self,
        *,
        payload: BacktestRunRequest,
        params: dict[str, Any],
    ) -> BacktestRunRequest:
        ...

    def exit_policy(
        self,
        *,
        payload: BacktestRunRequest,
        params: dict[str, Any],
    ) -> BacktestRunRequest:
        ...


class BaseStrategyPlugin:
    strategy_id = "base"

    def build_universe(
        self,
        *,
        candidates: list[ScreenerResult],
        params: dict[str, Any],
        mode: str,
    ) -> list[ScreenerResult]:
        _ = params, mode
        return list(candidates)

    def generate_signals(
        self,
        *,
        row: ScreenerResult,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        _ = row, snapshot, params
        return True

    def rank_signals(
        self,
        *,
        signal: SignalResult,
        row: ScreenerResult,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        _ = signal, row, params
        return float(fallback_score)

    def entry_policy(
        self,
        *,
        payload: BacktestRunRequest,
        params: dict[str, Any],
    ) -> BacktestRunRequest:
        _ = params
        return payload

    def exit_policy(
        self,
        *,
        payload: BacktestRunRequest,
        params: dict[str, Any],
    ) -> BacktestRunRequest:
        _ = params
        return payload


class WyckoffTrendPlugin(BaseStrategyPlugin):
    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = str(strategy_id).strip() or "wyckoff_trend_v1"


class ScoreOnlyRankPlugin(BaseStrategyPlugin):
    strategy_id = "score_only_rank_v1"

    @staticmethod
    def _safe_float(params: dict[str, Any], key: str, fallback: float) -> float:
        try:
            value = float(params.get(key, fallback))
        except Exception:
            return float(fallback)
        if not math.isfinite(value):
            return float(fallback)
        return float(value)

    def generate_signals(
        self,
        *,
        row: ScreenerResult,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        _ = row
        min_score = self._safe_float(params, "min_score", 55.0)
        try:
            entry_quality_score = float(snapshot.get("entry_quality_score", 0.0) or 0.0)
        except Exception:
            entry_quality_score = 0.0
        if not math.isfinite(entry_quality_score):
            entry_quality_score = 0.0
        return entry_quality_score >= float(min_score)

    def rank_signals(
        self,
        *,
        signal: SignalResult,
        row: ScreenerResult,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        _ = row, params
        try:
            quality = float(signal.entry_quality_score)
        except Exception:
            quality = float(fallback_score)
        if not math.isfinite(quality):
            quality = float(fallback_score)
        return _clamp_score(quality)


class MatrixSignalPlugin(BaseStrategyPlugin):
    """矩阵信号策略插件 — 将 backtest_signal_matrix 的 S1-S9 向量化逻辑
    适配为逐票评估接口，使其可在策略中心统一管理。

    S1: 波动收敛 (ATR ratio < threshold)
    S2: 量能萎缩 (vol_ma10/vol_ma60 < threshold)
    S3: 40日涨幅 top_n (由 build_universe 预筛)
    S4: 横盘整理 (振幅收敛 + 价格靠近MA20)
    S5: 突破买入 (创20日新高 + 放量)
    S6: 均线回踩买入 (站上MA10 + 高于10日低点)
    S7: 多头排列 (MA10 > MA20 > MA60)
    S8: 破位卖出 (破20日低点 或 跌破MA20*0.97)
    S9: 放量下跌 (跌破MA10 + 放量 + 40日负收益)
    """

    strategy_id = "matrix_signal_v1"

    @staticmethod
    def _safe_float(params: dict[str, Any], key: str, fallback: float) -> float:
        try:
            value = float(params.get(key, fallback))
        except Exception:
            return float(fallback)
        if not __import__("math").isfinite(value):
            return float(fallback)
        return float(value)

    def build_universe(
        self,
        *,
        candidates: list[ScreenerResult],
        params: dict[str, Any],
        mode: str,
    ) -> list[ScreenerResult]:
        """池筛选：pool_score >= min_pool_score 才入池。
        pool_score = S1 + S2 + S3 + S4 (各 0/1)。
        S3 由 ret40 排名 top_n 近似。
        """
        _ = mode
        atr_ratio_max = self._safe_float(params, "atr_ratio_max", 0.7)
        vol_ratio_max = self._safe_float(params, "vol_ratio_max", 0.6)
        sideways_range_max = self._safe_float(params, "sideways_range_max", 0.18)
        near_ma20_max = self._safe_float(params, "near_ma20_max", 0.06)
        min_pool_score = int(self._safe_float(params, "min_pool_score", 2))
        ret40_top_n = int(self._safe_float(params, "ret40_top_n", 500))

        # 先按 ret40 降序取 top_n 作为 S3 候选
        sorted_by_ret40 = sorted(candidates, key=lambda r: float(r.ret40), reverse=True)
        s3_symbols: set[str] = set()
        for i, row in enumerate(sorted_by_ret40):
            if i >= ret40_top_n:
                break
            s3_symbols.add(row.symbol)

        out: list[ScreenerResult] = []
        for row in candidates:
            s1 = 1 if float(row.retrace20) < atr_ratio_max else 0
            s2 = 1 if float(row.vol_slope20) < vol_ratio_max else 0
            s3 = 1 if row.symbol in s3_symbols else 0
            s4 = 1 if (float(row.retrace20) < sideways_range_max and float(row.price_vs_ma20) < near_ma20_max) else 0
            pool_score = s1 + s2 + s3 + s4
            if pool_score >= min_pool_score:
                out.append(row)
        return out

    def generate_signals(
        self,
        *,
        row: ScreenerResult,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        """买入信号：(S5 | S6) & in_pool。
        S5: 突破20日高点 + 放量 (近似: ret40 > 0 且 up_down_volume_ratio > breakout_vol_ratio)
        S6: 均线回踩 (近似: price_vs_ma20 接近0 且 pullback_days <= max_pullback_days)
        """
        _ = snapshot
        breakout_vol_ratio = self._safe_float(params, "breakout_vol_ratio", 1.2)
        max_pullback_days = int(self._safe_float(params, "max_pullback_days", 3))

        # S5: 突破买入 — 涨幅为正 + 量比达标
        s5 = float(row.ret40) > 0 and float(row.up_down_volume_ratio) >= breakout_vol_ratio
        # S6: 回踩买入 — 价格靠近MA20 + 回调天数有限
        s6 = abs(float(row.price_vs_ma20)) < 0.06 and int(row.pullback_days) <= max_pullback_days
        return s5 or s6

    def rank_signals(
        self,
        *,
        signal: SignalResult,
        row: ScreenerResult,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        """评分逻辑与矩阵引擎一致：
        raw_score = pool_score + S5*2.0 + S6*1.5 + S7*1.0
        score = clamp(raw_score / 8.5 * 100, 0, 100)
        """
        atr_ratio_max = self._safe_float(params, "atr_ratio_max", 0.7)
        vol_ratio_max = self._safe_float(params, "vol_ratio_max", 0.6)
        sideways_range_max = self._safe_float(params, "sideways_range_max", 0.18)
        near_ma20_max = self._safe_float(params, "near_ma20_max", 0.06)
        breakout_vol_ratio = self._safe_float(params, "breakout_vol_ratio", 1.2)
        max_pullback_days = int(self._safe_float(params, "max_pullback_days", 3))

        s1 = 1.0 if float(row.retrace20) < atr_ratio_max else 0.0
        s2 = 1.0 if float(row.vol_slope20) < vol_ratio_max else 0.0
        s4 = 1.0 if (float(row.retrace20) < sideways_range_max and float(row.price_vs_ma20) < near_ma20_max) else 0.0
        # S3 在 rank 阶段近似为 ret40 > 0
        s3 = 1.0 if float(row.ret40) > 0 else 0.0
        pool_score = s1 + s2 + s3 + s4

        s5 = 1.0 if (float(row.ret40) > 0 and float(row.up_down_volume_ratio) >= breakout_vol_ratio) else 0.0
        s6 = 1.0 if (abs(float(row.price_vs_ma20)) < 0.06 and int(row.pullback_days) <= max_pullback_days) else 0.0
        # S7: 多头排列 — 近似: MA10 > MA20 天数足够
        s7 = 1.0 if int(row.ma10_above_ma20_days) >= 5 else 0.0

        raw_score = pool_score + s5 * 2.0 + s6 * 1.5 + s7 * 1.0
        score = max(0.0, min(100.0, raw_score / 8.5 * 100.0))
        return score


class RelativeStrengthBreakoutPlugin(BaseStrategyPlugin):
    strategy_id = "relative_strength_breakout_v1"

    @staticmethod
    def _safe_float(params: dict[str, Any], key: str, fallback: float) -> float:
        try:
            return float(params.get(key, fallback))
        except Exception:
            return float(fallback)

    def build_universe(
        self,
        *,
        candidates: list[ScreenerResult],
        params: dict[str, Any],
        mode: str,
    ) -> list[ScreenerResult]:
        _ = mode
        min_ret40 = self._safe_float(params, "min_ret40", 0.12)
        max_retrace20 = self._safe_float(params, "max_retrace20", 0.22)
        min_up_down_volume_ratio = self._safe_float(params, "min_up_down_volume_ratio", 1.15)
        min_vol_slope20 = self._safe_float(params, "min_vol_slope20", 0.02)
        min_ai_confidence = self._safe_float(params, "min_ai_confidence", 0.0)

        out: list[ScreenerResult] = []
        for row in candidates:
            if float(row.ret40) < min_ret40:
                continue
            if float(row.retrace20) > max_retrace20:
                continue
            if float(row.up_down_volume_ratio) < min_up_down_volume_ratio:
                continue
            if float(row.vol_slope20) < min_vol_slope20:
                continue
            if float(row.ai_confidence) < min_ai_confidence:
                continue
            out.append(row)
        return out

    def generate_signals(
        self,
        *,
        row: ScreenerResult,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        _ = snapshot
        min_ret40 = self._safe_float(params, "min_ret40", 0.12)
        max_retrace20 = self._safe_float(params, "max_retrace20", 0.22)
        min_up_down_volume_ratio = self._safe_float(params, "min_up_down_volume_ratio", 1.15)
        return (
            float(row.ret40) >= min_ret40
            and float(row.retrace20) <= max_retrace20
            and float(row.up_down_volume_ratio) >= min_up_down_volume_ratio
        )

    def rank_signals(
        self,
        *,
        signal: SignalResult,
        row: ScreenerResult,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        _ = fallback_score
        w_health = self._safe_float(params, "rank_weight_health", 0.25)
        w_event = self._safe_float(params, "rank_weight_event", 0.25)
        w_strength = self._safe_float(params, "rank_weight_strength", 0.30)
        w_volume = self._safe_float(params, "rank_weight_volume", 0.10)
        w_structure = self._safe_float(params, "rank_weight_structure", 0.10)
        weight_sum = max(0.01, w_health + w_event + w_strength + w_volume + w_structure)

        strength_score = _clamp_score(float(row.ret40) / 0.40 * 100.0)
        volume_score = _clamp_score((float(row.up_down_volume_ratio) - 1.0) / 0.8 * 100.0)
        structure_score = _clamp_score(
            100.0
            - abs(float(row.retrace20) - 0.12) / 0.20 * 100.0
            - max(0.0, float(row.pullback_volume_ratio) - 0.92) * 100.0
        )
        score = (
            float(signal.health_score) * w_health
            + float(signal.event_score) * w_event
            + strength_score * w_strength
            + volume_score * w_volume
            + structure_score * w_structure
        ) / weight_sum
        return _clamp_score(score)
