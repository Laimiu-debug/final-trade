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
