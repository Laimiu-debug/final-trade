from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models import CandlePoint, ScreenerResult
from app.store import store


def _build_row(symbol: str) -> ScreenerResult:
    return ScreenerResult(
        symbol=symbol,
        name="测试标的",
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


def test_store_get_signals_supports_signal_age_filter(monkeypatch) -> None:
    symbol = "sz300750"
    row = _build_row(symbol)
    candles = [
        CandlePoint(time="2026-01-02", open=10.0, high=10.2, low=9.8, close=10.1, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-05", open=10.1, high=10.3, low=9.9, close=10.2, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-06", open=10.2, high=10.4, low=10.0, close=10.3, volume=100000, amount=1_000_000.0),
    ]

    def fake_resolve_signal_candidates(
        *,
        mode,
        run_id,
        trend_step="auto",
        as_of_date=None,
    ):
        _ = (mode, run_id, trend_step, as_of_date)
        return [row], None, "mock-run", "2026-01-06"

    def fake_snapshot(*args, **kwargs):
        _ = (args, kwargs)
        return {
            "events": ["SOS"],
            "risk_events": [],
            "event_dates": {"SOS": "2026-01-02"},
            "event_chain": [{"event": "SOS", "date": "2026-01-02", "category": "accumulation"}],
            "sequence_ok": True,
            "entry_quality_score": 82.0,
            "trigger_date": "2026-01-02",
            "signal": "SOS",
            "phase": "吸筹D",
            "phase_hint": "测试信号",
            "structure_hhh": "HH|HL|HC",
            "event_strength_score": 70.0,
            "phase_score": 72.0,
            "structure_score": 68.0,
            "trend_score": 66.0,
            "volatility_score": 64.0,
        }

    monkeypatch.setattr(store, "_resolve_signal_candidates", fake_resolve_signal_candidates)
    monkeypatch.setattr(store, "_calc_wyckoff_snapshot", fake_snapshot)
    monkeypatch.setattr(store, "_ensure_candles", lambda raw_symbol: list(candles) if raw_symbol == symbol else [])
    store._signals_cache.clear()

    matched = store.get_signals(
        mode="trend_pool",
        run_id="mock-run",
        as_of_date="2026-01-06",
        refresh=True,
        min_score=0.0,
        min_event_count=0,
        signal_age_min=2,
        signal_age_max=2,
    )
    assert len(matched.items) == 1
    assert matched.items[0].signal_age_days == 2

    filtered = store.get_signals(
        mode="trend_pool",
        run_id="mock-run",
        as_of_date="2026-01-06",
        refresh=True,
        min_score=0.0,
        min_event_count=0,
        signal_age_min=3,
    )
    assert filtered.items == []


def test_store_signal_age_uses_trading_day_diff_with_missing_calendar_days(monkeypatch) -> None:
    symbol = "sz300750"
    row = _build_row(symbol)
    # 2026-01-07 / 2026-01-08 缺失，模拟停牌/无交易日
    candles = [
        CandlePoint(time="2026-01-02", open=10.0, high=10.2, low=9.8, close=10.1, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-05", open=10.1, high=10.3, low=9.9, close=10.2, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-06", open=10.2, high=10.4, low=10.0, close=10.3, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-09", open=10.3, high=10.5, low=10.1, close=10.4, volume=100000, amount=1_000_000.0),
        CandlePoint(time="2026-01-12", open=10.4, high=10.6, low=10.2, close=10.5, volume=100000, amount=1_000_000.0),
    ]

    def fake_resolve_signal_candidates(
        *,
        mode,
        run_id,
        trend_step="auto",
        as_of_date=None,
    ):
        _ = (mode, run_id, trend_step, as_of_date)
        return [row], None, "mock-run", "2026-01-12"

    def fake_snapshot(*args, **kwargs):
        _ = (args, kwargs)
        return {
            "events": ["SOS"],
            "risk_events": [],
            "event_dates": {"SOS": "2026-01-06"},
            "event_chain": [{"event": "SOS", "date": "2026-01-06", "category": "accumulation"}],
            "sequence_ok": True,
            "entry_quality_score": 82.0,
            "trigger_date": "2026-01-06",
            "signal": "SOS",
            "phase": "鍚哥D",
            "phase_hint": "娴嬭瘯淇″彿",
            "structure_hhh": "HH|HL|HC",
            "event_strength_score": 70.0,
            "phase_score": 72.0,
            "structure_score": 68.0,
            "trend_score": 66.0,
            "volatility_score": 64.0,
        }

    monkeypatch.setattr(store, "_resolve_signal_candidates", fake_resolve_signal_candidates)
    monkeypatch.setattr(store, "_calc_wyckoff_snapshot", fake_snapshot)
    monkeypatch.setattr(store, "_ensure_candles", lambda raw_symbol: list(candles) if raw_symbol == symbol else [])
    store._signals_cache.clear()

    resp = store.get_signals(
        mode="trend_pool",
        run_id="mock-run",
        as_of_date="2026-01-12",
        refresh=True,
        min_score=0.0,
        min_event_count=0,
        signal_age_min=2,
        signal_age_max=2,
    )
    assert len(resp.items) == 1
    # trading days: 2026-01-06 -> 2026-01-09 -> 2026-01-12 => age=2
    assert resp.items[0].signal_age_days == 2
