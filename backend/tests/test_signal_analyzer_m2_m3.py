from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.signal_analyzer import SignalAnalyzer
from app.models import CandlePoint, ScreenerResult


def _build_row(symbol: str = "sz300750") -> ScreenerResult:
    return ScreenerResult(
        symbol=symbol,
        name="test",
        latest_price=10.0,
        day_change=0.1,
        day_change_pct=0.01,
        score=80,
        ret40=0.25,
        turnover20=0.08,
        amount20=8e8,
        amplitude20=0.05,
        retrace20=0.03,
        pullback_days=3,
        ma10_above_ma20_days=8,
        ma5_above_ma10_days=6,
        price_vs_ma20=0.06,
        vol_slope20=0.1,
        up_down_volume_ratio=1.4,
        pullback_volume_ratio=0.7,
        has_blowoff_top=False,
        has_divergence_5d=False,
        has_upper_shadow_risk=False,
        ai_confidence=0.7,
        theme_stage="发酵中",
        trend_class="A",
        stage="Mid",
        labels=[],
        reject_reasons=[],
        degraded=False,
        degraded_reason=None,
    )


def _build_candles(start: str = "2025-01-02", count: int = 90) -> list[CandlePoint]:
    out: list[CandlePoint] = []
    cursor = datetime.strptime(start, "%Y-%m-%d")
    price = 10.0
    while len(out) < count:
        if cursor.weekday() >= 5:
            cursor += timedelta(days=1)
            continue
        open_px = price
        close_px = open_px * 1.004
        high_px = close_px * 1.01
        low_px = open_px * 0.99
        out.append(
            CandlePoint(
                time=cursor.strftime("%Y-%m-%d"),
                open=open_px,
                high=high_px,
                low=low_px,
                close=close_px,
                volume=120000,
                amount=close_px * 120000,
            )
        )
        cursor += timedelta(days=1)
        price = close_px
    return out


def test_signal_analyzer_outputs_m2_m3_scores() -> None:
    row = _build_row()
    candles = _build_candles()
    snapshot = SignalAnalyzer.calculate_wyckoff_snapshot(row, candles, 60)

    assert 0.0 <= float(snapshot["health_score"]) <= 100.0
    assert 0.0 <= float(snapshot["slope_stability"]) <= 100.0
    assert 0.0 <= float(snapshot["volatility_stability"]) <= 100.0
    assert 0.0 <= float(snapshot["pullback_quality"]) <= 100.0

    assert 0.0 <= float(snapshot["event_score"]) <= 100.0
    assert snapshot["event_grade"] in {"A", "B", "C"}
    assert 0.0 <= float(snapshot["event_background_score"]) <= 100.0
    assert 0.0 <= float(snapshot["event_position_score"]) <= 100.0
    assert 0.0 <= float(snapshot["event_vol_price_score"]) <= 100.0
    assert 0.0 <= float(snapshot["event_confirmation_score"]) <= 100.0
    assert isinstance(snapshot["event_grade_map"], dict)

