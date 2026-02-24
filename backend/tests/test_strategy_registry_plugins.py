from __future__ import annotations

from app.core.strategy_registry import StrategyRegistry
from app.models import ScreenerResult, SignalResult


def _build_row(symbol: str, **overrides: object) -> ScreenerResult:
    payload: dict[str, object] = {
        "symbol": symbol,
        "name": symbol,
        "latest_price": 10.0,
        "day_change": 0.1,
        "day_change_pct": 0.01,
        "score": 75,
        "ret40": 0.20,
        "turnover20": 0.08,
        "amount20": 8e8,
        "amplitude20": 0.05,
        "retrace20": 0.12,
        "pullback_days": 2,
        "ma10_above_ma20_days": 8,
        "ma5_above_ma10_days": 6,
        "price_vs_ma20": 0.05,
        "vol_slope20": 0.08,
        "up_down_volume_ratio": 1.35,
        "pullback_volume_ratio": 0.8,
        "has_blowoff_top": False,
        "has_divergence_5d": False,
        "has_upper_shadow_risk": False,
        "ai_confidence": 0.7,
        "theme_stage": "发酵中",
        "trend_class": "A",
        "stage": "Mid",
        "labels": [],
        "reject_reasons": [],
        "degraded": False,
        "degraded_reason": None,
    }
    payload.update(overrides)
    return ScreenerResult(**payload)


def _build_signal(symbol: str, *, health: float, event: float) -> SignalResult:
    return SignalResult(
        symbol=symbol,
        name=symbol,
        primary_signal="A",
        secondary_signals=[],
        trigger_date="2025-01-10",
        expire_date="2025-01-12",
        trigger_reason="test",
        priority=2,
        health_score=health,
        event_score=event,
    )


def test_registry_contains_relative_strength_strategy() -> None:
    registry = StrategyRegistry()
    assert registry.get("relative_strength_breakout_v1") is not None


def test_relative_strength_plugin_filters_signal_universe() -> None:
    registry = StrategyRegistry()
    rows = [
        _build_row("sz300750", ret40=0.35, retrace20=0.10, up_down_volume_ratio=1.60, vol_slope20=0.12),
        _build_row("sz300751", ret40=0.08, retrace20=0.12, up_down_volume_ratio=1.30, vol_slope20=0.10),
    ]
    filtered = registry.build_universe(
        strategy_id="relative_strength_breakout_v1",
        candidates=rows,
        params={
            "min_ret40": 0.12,
            "max_retrace20": 0.22,
            "min_up_down_volume_ratio": 1.15,
            "min_vol_slope20": 0.02,
        },
        mode="signals",
    )
    symbols = [row.symbol for row in filtered]
    assert "sz300750" in symbols
    assert "sz300751" not in symbols


def test_relative_strength_plugin_rank_uses_strength_metrics() -> None:
    registry = StrategyRegistry()
    strong_row = _build_row("sz300750", ret40=0.36, up_down_volume_ratio=1.70, retrace20=0.10)
    weak_row = _build_row("sz300751", ret40=0.14, up_down_volume_ratio=1.12, retrace20=0.22)
    signal = _build_signal("sz300750", health=65.0, event=62.0)
    strong_rank = registry.rank_signals(
        strategy_id="relative_strength_breakout_v1",
        signal=signal,
        row=strong_row,
        params={
            "rank_weight_health": 0.25,
            "rank_weight_event": 0.25,
            "rank_weight_strength": 0.30,
            "rank_weight_volume": 0.10,
            "rank_weight_structure": 0.10,
        },
        fallback_score=63.5,
    )
    weak_rank = registry.rank_signals(
        strategy_id="relative_strength_breakout_v1",
        signal=signal,
        row=weak_row,
        params={
            "rank_weight_health": 0.25,
            "rank_weight_event": 0.25,
            "rank_weight_strength": 0.30,
            "rank_weight_volume": 0.10,
            "rank_weight_structure": 0.10,
        },
        fallback_score=63.5,
    )
    assert strong_rank > weak_rank

