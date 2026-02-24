from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.backtest_engine import BacktestEngine
from app.core.backtest_matrix_engine import MatrixBundle
from app.core.backtest_signal_matrix import BacktestSignalMatrix
from app.models import BacktestRunRequest, CandlePoint


def _build_candles(dates: list[str], base_price: float) -> list[CandlePoint]:
    candles: list[CandlePoint] = []
    for idx, day in enumerate(dates):
        px = base_price + idx * 0.1
        candles.append(
            CandlePoint(
                time=day,
                open=px,
                high=px * 1.02,
                low=px * 0.98,
                close=px * 1.01,
                volume=100000,
                amount=px * 100000,
            )
        )
    return candles


def _build_trading_days(start: str, count: int) -> list[str]:
    out: list[str] = []
    cursor = datetime.strptime(start, "%Y-%m-%d")
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return out


def _build_linear_candles(dates: list[str], *, start: float = 10.0, step: float = 1.0) -> list[CandlePoint]:
    candles: list[CandlePoint] = []
    for idx, day in enumerate(dates):
        px = float(start + idx * step)
        candles.append(
            CandlePoint(
                time=day,
                open=px,
                high=px * 1.02,
                low=px * 0.98,
                close=px * 1.01,
                volume=100000,
                amount=px * 100000,
            )
        )
    return candles


@pytest.mark.parametrize("entry_delay_days", [1, 2, 3])
def test_legacy_entry_delay_days_controls_entry_date_and_price(entry_delay_days: int) -> None:
    dates = _build_trading_days("2025-01-02", 34)
    symbol = "sh600001"
    signal_day = dates[0]
    exit_day = dates[25]
    candles = _build_linear_candles(dates, start=10.0, step=1.0)

    def _get_candles(raw_symbol: str) -> list[CandlePoint]:
        return list(candles) if raw_symbol == symbol else []

    def _build_row(raw_symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if raw_symbol != symbol or as_of_date is None:
            return None
        return {"symbol": raw_symbol, "as_of_date": as_of_date}

    def _calc_snapshot(_row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        if day == signal_day:
            event_dates["E"] = day
            event_chain = [{"event": "E"}]
        if day == exit_day:
            event_dates["X"] = day
        return {
            "event_dates": event_dates,
            "event_chain": event_chain,
            "events": [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": 85.0,
            "phase": "吸筹D",
            "structure_hhh": "HH|HL|HC",
            "trend_score": 78.0,
            "volatility_score": 70.0,
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=False,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        entry_delay_days=entry_delay_days,
        delay_invalidation_enabled=False,
        max_symbols=20,
    )
    result = engine.run(payload=payload, symbols=[symbol])

    assert len(result.trades) == 1
    trade = result.trades[0]
    expected_entry_index = entry_delay_days
    assert trade.signal_date == signal_day
    assert trade.entry_date == dates[expected_entry_index]
    assert trade.entry_price == pytest.approx(candles[expected_entry_index].open, rel=1e-9)


@pytest.mark.parametrize("entry_delay_days", [1, 2, 3])
def test_matrix_entry_delay_days_controls_entry_date_and_price(entry_delay_days: int) -> None:
    dates = _build_trading_days("2025-01-02", 8)
    symbols = ["sh600001"]
    t, n = len(dates), len(symbols)

    open_px = [[10.0 + idx] for idx in range(t)]
    high_px = [[(10.0 + idx) * 1.02] for idx in range(t)]
    low_px = [[(10.0 + idx) * 0.98] for idx in range(t)]
    close_px = [[(10.0 + idx) * 1.01] for idx in range(t)]
    volume = [[100000.0] for _ in range(t)]
    valid = [[True] for _ in range(t)]

    buy = [[False] for _ in range(t)]
    buy[0][0] = True
    sell = [[False] for _ in range(t)]
    sell[6][0] = True
    score = [[0.0] for _ in range(t)]
    score[0][0] = 86.0

    bundle = MatrixBundle(
        dates=list(dates),
        symbols=list(symbols),
        open=np.asarray(open_px, dtype=np.float64),
        high=np.asarray(high_px, dtype=np.float64),
        low=np.asarray(low_px, dtype=np.float64),
        close=np.asarray(close_px, dtype=np.float64),
        volume=np.asarray(volume, dtype=np.float64),
        valid_mask=np.asarray(valid, dtype=bool),
    )
    signals = BacktestSignalMatrix(
        s1=np.zeros((t, n), dtype=bool),
        s2=np.zeros((t, n), dtype=bool),
        s3=np.zeros((t, n), dtype=bool),
        s4=np.zeros((t, n), dtype=bool),
        s5=np.asarray(buy, dtype=bool),
        s6=np.zeros((t, n), dtype=bool),
        s7=np.ones((t, n), dtype=bool),
        s8=np.zeros((t, n), dtype=bool),
        s9=np.zeros((t, n), dtype=bool),
        in_pool=np.asarray(buy, dtype=bool),
        buy_signal=np.asarray(buy, dtype=bool),
        sell_signal=np.asarray(sell, dtype=bool),
        score=np.asarray(score, dtype=np.float64),
    )

    engine = BacktestEngine(
        get_candles=lambda _: [],
        build_row=lambda symbol, as_of_date=None: {"symbol": symbol, "as_of_date": as_of_date},
        calc_snapshot=lambda row, window_days, as_of_date=None: {},
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        entry_delay_days=entry_delay_days,
        delay_invalidation_enabled=False,
        max_symbols=20,
    )
    result = engine.run(
        payload=payload,
        symbols=list(symbols),
        matrix_bundle=bundle,
        matrix_signals=signals,
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    expected_entry_index = entry_delay_days
    assert trade.signal_date == dates[0]
    assert trade.entry_date == dates[expected_entry_index]
    assert trade.entry_price == pytest.approx(float(open_px[expected_entry_index][0]), rel=1e-9)


def test_matrix_and_legacy_match_on_trade_timeline_for_same_signal_case() -> None:
    dates = _build_trading_days("2025-01-02", 34)
    symbol = "sh600001"
    signal_day = dates[0]
    exit_day = dates[25]
    candles = _build_linear_candles(dates, start=10.0, step=0.5)

    def _get_candles(raw_symbol: str) -> list[CandlePoint]:
        return list(candles) if raw_symbol == symbol else []

    def _build_row(raw_symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if raw_symbol != symbol or as_of_date is None:
            return None
        return {"symbol": raw_symbol, "as_of_date": as_of_date}

    def _calc_snapshot(_row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        if day == signal_day:
            event_dates["SOS"] = day
            event_chain = [{"event": "SOS"}]
        if day == exit_day:
            event_dates["X"] = day
        return {
            "event_dates": event_dates,
            "event_chain": event_chain,
            "events": ["SOS"] if day == signal_day else [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": 88.0,
            "phase": "吸筹D",
            "structure_hhh": "HH|HL|HC",
            "trend_score": 75.0,
            "volatility_score": 68.0,
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["SOS"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        entry_delay_days=2,
        delay_invalidation_enabled=False,
        max_symbols=20,
    )
    legacy_result = engine.run(payload=payload, symbols=[symbol])

    t = len(dates)
    open_px = np.asarray([[bar.open] for bar in candles], dtype=np.float64)
    high_px = np.asarray([[bar.high] for bar in candles], dtype=np.float64)
    low_px = np.asarray([[bar.low] for bar in candles], dtype=np.float64)
    close_px = np.asarray([[bar.close] for bar in candles], dtype=np.float64)
    volume = np.asarray([[float(bar.volume)] for bar in candles], dtype=np.float64)
    valid = np.ones((t, 1), dtype=bool)
    buy = np.zeros((t, 1), dtype=bool)
    buy[0, 0] = True
    sell = np.zeros((t, 1), dtype=bool)
    sell[25, 0] = True
    score = np.zeros((t, 1), dtype=np.float64)
    score[0, 0] = 88.0

    bundle = MatrixBundle(
        dates=list(dates),
        symbols=[symbol],
        open=open_px,
        high=high_px,
        low=low_px,
        close=close_px,
        volume=volume,
        valid_mask=valid,
    )
    signals = BacktestSignalMatrix(
        s1=np.zeros((t, 1), dtype=bool),
        s2=np.zeros((t, 1), dtype=bool),
        s3=np.zeros((t, 1), dtype=bool),
        s4=np.zeros((t, 1), dtype=bool),
        s5=buy.copy(),
        s6=np.zeros((t, 1), dtype=bool),
        s7=np.ones((t, 1), dtype=bool),
        s8=np.zeros((t, 1), dtype=bool),
        s9=np.zeros((t, 1), dtype=bool),
        in_pool=buy.copy(),
        buy_signal=buy.copy(),
        sell_signal=sell.copy(),
        score=score,
    )
    matrix_result = engine.run(
        payload=payload,
        symbols=[symbol],
        matrix_bundle=bundle,
        matrix_signals=signals,
    )

    assert len(legacy_result.trades) == 1
    assert len(matrix_result.trades) == 1
    legacy_trade = legacy_result.trades[0]
    matrix_trade = matrix_result.trades[0]
    assert matrix_trade.signal_date == legacy_trade.signal_date
    assert matrix_trade.entry_date == legacy_trade.entry_date
    assert matrix_trade.exit_date == legacy_trade.exit_date
    assert matrix_trade.entry_price == pytest.approx(legacy_trade.entry_price, rel=1e-9)
    assert matrix_trade.exit_price == pytest.approx(legacy_trade.exit_price, rel=1e-9)


def test_position_mode_refills_after_skipped_signal() -> None:
    dates = _build_trading_days("2025-01-02", 32)
    first_signal_day = dates[0]
    exit_day_for_a = dates[2]
    second_signal_day_for_b = dates[2]
    expected_second_entry_day = dates[3]
    symbol_a = "sh600001"
    symbol_b = "sh600002"
    candles_by_symbol = {
        symbol_a: _build_candles(dates, 10.0),
        symbol_b: _build_candles(dates, 12.0),
    }

    def _get_candles(symbol: str) -> list[CandlePoint]:
        return list(candles_by_symbol.get(symbol, []))

    def _build_row(symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if as_of_date is None:
            return None
        return {"symbol": symbol, "as_of_date": as_of_date}

    def _calc_snapshot(row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        symbol = str(row.get("symbol", "")).strip().lower()
        event_dates: dict[str, str] = {}
        entry_chain: list[dict[str, str]] = []

        if symbol == symbol_a and day == first_signal_day:
            event_dates["E"] = day
            entry_chain = [{"event": "E"}]
        if symbol == symbol_a and day == exit_day_for_a:
            event_dates["X"] = day

        if symbol == symbol_b and day in {first_signal_day, second_signal_day_for_b}:
            event_dates["E"] = day
            entry_chain = [{"event": "E"}]

        return {
            "event_dates": event_dates,
            "event_chain": entry_chain,
            "events": [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": 80.0,
            "phase": "阶段未明",
            "structure_hhh": "HH|HL|-",
            "trend_score": 80.0,
            "volatility_score": 80.0,
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda symbol: symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="position",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=False,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        max_symbols=20,
    )
    result = engine.run(payload=payload, symbols=[symbol_a, symbol_b])

    assert len(result.trades) == 2
    assert [trade.symbol for trade in result.trades] == [symbol_a, symbol_b]
    assert result.trades[1].entry_date == expected_second_entry_day
    assert result.max_concurrent_positions == 1


def test_position_mode_matrix_event_driven_refills_slots() -> None:
    dates = _build_trading_days("2025-01-02", 8)
    symbols = ["sh600001", "sh600002"]
    t, n = len(dates), len(symbols)

    open_px = [[10.0, 12.0] for _ in range(t)]
    high_px = [[10.4, 12.4] for _ in range(t)]
    low_px = [[9.6, 11.6] for _ in range(t)]
    close_px = [[10.1, 12.1] for _ in range(t)]
    volume = [[100000.0, 100000.0] for _ in range(t)]
    valid = [[True, True] for _ in range(t)]

    buy = [[False, False] for _ in range(t)]
    buy[0][0] = True
    buy[0][1] = True
    buy[2][1] = True

    sell = [[False, False] for _ in range(t)]
    sell[2][0] = True

    score = [[0.0, 0.0] for _ in range(t)]
    score[0][0] = 90.0
    score[0][1] = 80.0
    score[2][1] = 88.0

    bool_buy = buy
    bool_sell = sell

    bundle = MatrixBundle(
        dates=list(dates),
        symbols=list(symbols),
        open=np.asarray(open_px, dtype=np.float64),
        high=np.asarray(high_px, dtype=np.float64),
        low=np.asarray(low_px, dtype=np.float64),
        close=np.asarray(close_px, dtype=np.float64),
        volume=np.asarray(volume, dtype=np.float64),
        valid_mask=np.asarray(valid, dtype=bool),
    )
    signals = BacktestSignalMatrix(
        s1=np.zeros((t, n), dtype=bool),
        s2=np.zeros((t, n), dtype=bool),
        s3=np.zeros((t, n), dtype=bool),
        s4=np.zeros((t, n), dtype=bool),
        s5=np.asarray(bool_buy, dtype=bool),
        s6=np.zeros((t, n), dtype=bool),
        s7=np.zeros((t, n), dtype=bool),
        s8=np.zeros((t, n), dtype=bool),
        s9=np.zeros((t, n), dtype=bool),
        in_pool=np.asarray(bool_buy, dtype=bool),
        buy_signal=np.asarray(bool_buy, dtype=bool),
        sell_signal=np.asarray(bool_sell, dtype=bool),
        score=np.asarray(score, dtype=np.float64),
    )

    def _get_candles(_: str) -> list[CandlePoint]:
        return []

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=lambda symbol, as_of_date=None: {"symbol": symbol, "as_of_date": as_of_date},
        calc_snapshot=lambda row, window_days, as_of_date=None: {},
        resolve_symbol_name=lambda symbol: symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="position",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        max_symbols=20,
    )
    result = engine.run(
        payload=payload,
        symbols=list(symbols),
        matrix_bundle=bundle,
        matrix_signals=signals,
    )

    assert len(result.trades) == 2
    assert [trade.symbol for trade in result.trades] == ["sh600001", "sh600002"]
    assert result.trades[0].entry_date == dates[1]
    assert result.trades[1].entry_date == dates[3]
    assert result.max_concurrent_positions == 1


def test_entry_delay_and_legacy_delay_invalidation_by_risk_event() -> None:
    dates = _build_trading_days("2025-01-02", 34)
    symbol = "sh600001"
    first_signal_day = dates[0]
    risk_day = dates[1]
    candles_by_symbol = {
        symbol: _build_candles(dates, 10.0),
    }

    def _get_candles(raw_symbol: str) -> list[CandlePoint]:
        return list(candles_by_symbol.get(raw_symbol, []))

    def _build_row(raw_symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if as_of_date is None:
            return None
        return {"symbol": raw_symbol, "as_of_date": as_of_date}

    def _calc_snapshot(row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        risk_events: list[str] = []
        if day == first_signal_day:
            event_dates["E"] = day
            event_chain = [{"event": "E"}]
        if day == risk_day:
            event_dates["UTAD"] = day
            risk_events = ["UTAD"]
        return {
            "event_dates": event_dates,
            "event_chain": event_chain,
            "events": [],
            "risk_events": risk_events,
            "sequence_ok": True,
            "entry_quality_score": 80.0,
            "phase": "阶段未明",
            "structure_hhh": "HH|HL|-",
            "trend_score": 80.0,
            "volatility_score": 80.0,
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=False,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        entry_delay_days=3,
        delay_invalidation_enabled=True,
        max_symbols=20,
    )
    result = engine.run(payload=payload, symbols=[symbol])

    assert len(result.trades) == 0
    assert any("delay_invalidated_by_risk_event" in note for note in result.notes)


def test_matrix_delay_invalidation_by_sell_signal() -> None:
    dates = _build_trading_days("2025-01-02", 8)
    symbols = ["sh600001"]
    t, n = len(dates), len(symbols)

    open_px = [[10.0] for _ in range(t)]
    high_px = [[10.4] for _ in range(t)]
    low_px = [[9.6] for _ in range(t)]
    close_px = [[10.1] for _ in range(t)]
    volume = [[100000.0] for _ in range(t)]
    valid = [[True] for _ in range(t)]

    buy = [[False] for _ in range(t)]
    buy[0][0] = True

    sell = [[False] for _ in range(t)]
    sell[1][0] = True

    score = [[0.0] for _ in range(t)]
    score[0][0] = 88.0

    bundle = MatrixBundle(
        dates=list(dates),
        symbols=list(symbols),
        open=np.asarray(open_px, dtype=np.float64),
        high=np.asarray(high_px, dtype=np.float64),
        low=np.asarray(low_px, dtype=np.float64),
        close=np.asarray(close_px, dtype=np.float64),
        volume=np.asarray(volume, dtype=np.float64),
        valid_mask=np.asarray(valid, dtype=bool),
    )
    signals = BacktestSignalMatrix(
        s1=np.zeros((t, n), dtype=bool),
        s2=np.zeros((t, n), dtype=bool),
        s3=np.zeros((t, n), dtype=bool),
        s4=np.zeros((t, n), dtype=bool),
        s5=np.asarray(buy, dtype=bool),
        s6=np.zeros((t, n), dtype=bool),
        s7=np.zeros((t, n), dtype=bool),
        s8=np.zeros((t, n), dtype=bool),
        s9=np.zeros((t, n), dtype=bool),
        in_pool=np.asarray(buy, dtype=bool),
        buy_signal=np.asarray(buy, dtype=bool),
        sell_signal=np.asarray(sell, dtype=bool),
        score=np.asarray(score, dtype=np.float64),
    )

    engine = BacktestEngine(
        get_candles=lambda _: [],
        build_row=lambda symbol, as_of_date=None: {"symbol": symbol, "as_of_date": as_of_date},
        calc_snapshot=lambda row, window_days, as_of_date=None: {},
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        enforce_t1=True,
        entry_delay_days=3,
        delay_invalidation_enabled=True,
        max_symbols=20,
    )
    result = engine.run(
        payload=payload,
        symbols=list(symbols),
        matrix_bundle=bundle,
        matrix_signals=signals,
    )

    assert len(result.trades) == 0
    assert any("delay_invalidated_by_sell_signal" in note for note in result.notes)


def test_balanced_priority_prefers_health_event_composite_rank() -> None:
    dates = _build_trading_days("2025-01-02", 34)
    signal_day = dates[0]
    exit_day = dates[25]
    symbol_a = "sh600001"
    symbol_b = "sh600002"
    candles_by_symbol = {
        symbol_a: _build_linear_candles(dates, start=10.0, step=0.2),
        symbol_b: _build_linear_candles(dates, start=11.0, step=0.2),
    }

    def _get_candles(symbol: str) -> list[CandlePoint]:
        return list(candles_by_symbol.get(symbol, []))

    def _build_row(symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if as_of_date is None:
            return None
        return {"symbol": symbol, "as_of_date": as_of_date}

    def _calc_snapshot(row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        symbol = str(row.get("symbol", "")).strip().lower()
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        if day == signal_day:
            event_dates["E"] = day
            event_chain = [{"event": "E"}]
        if day == exit_day:
            event_dates["X"] = day
        if symbol == symbol_a:
            quality = 95.0
            health = 22.0
            event_score = 25.0
            event_grade = "C"
        else:
            quality = 72.0
            health = 92.0
            event_score = 90.0
            event_grade = "A"
        return {
            "event_dates": event_dates,
            "event_chain": event_chain,
            "events": [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": quality,
            "phase": "闃舵鏈槑",
            "structure_hhh": "HH|HL|-",
            "trend_score": quality,
            "volatility_score": quality,
            "health_score": health,
            "event_score": event_score,
            "event_grade": event_grade,
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda symbol: symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        rank_weight_health=0.45,
        rank_weight_event=0.55,
        enforce_t1=True,
        max_symbols=20,
    )
    result = engine.run(payload=payload, symbols=[symbol_a, symbol_b])

    assert len(result.trades) == 1
    # 预期 B 票虽然 quality 更低，但 health/event 复合分显著更高，应优先成交。
    assert result.trades[0].symbol == symbol_b
    assert result.trades[0].health_score > result.trades[0].entry_quality_score


def test_event_grade_gate_blocks_low_grade_entry() -> None:
    dates = _build_trading_days("2025-01-02", 34)
    symbol = "sh600001"
    signal_day = dates[0]
    exit_day = dates[25]
    candles_by_symbol = {symbol: _build_linear_candles(dates, start=10.0, step=0.2)}

    def _get_candles(raw_symbol: str) -> list[CandlePoint]:
        return list(candles_by_symbol.get(raw_symbol, []))

    def _build_row(raw_symbol: str, as_of_date: str | None) -> dict[str, str] | None:
        if as_of_date is None:
            return None
        return {"symbol": raw_symbol, "as_of_date": as_of_date}

    def _calc_snapshot(_row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        if day == signal_day:
            event_dates["E"] = day
            event_chain = [{"event": "E"}]
        if day == exit_day:
            event_dates["X"] = day
        return {
            "event_dates": event_dates,
            "event_chain": event_chain,
            "events": [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": 88.0,
            "phase": "闃舵鏈槑",
            "structure_hhh": "HH|HL|-",
            "trend_score": 78.0,
            "volatility_score": 75.0,
            "health_score": 85.0,
            "event_score": 84.0,
            "event_grade": "C",
        }

    engine = BacktestEngine(
        get_candles=_get_candles,
        build_row=_build_row,
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )
    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        event_grade_min="B",
        enforce_t1=True,
        max_symbols=20,
    )
    result = engine.run(payload=payload, symbols=[symbol])

    assert result.trades == []
    assert result.candidate_count == 0


def test_matrix_semantic_alignment_toggle_changes_candidate_filtering() -> None:
    dates = _build_trading_days("2025-01-02", 34)
    symbol = "sh600001"
    t, n = len(dates), 1

    open_px = [[10.0 + idx * 0.2] for idx in range(t)]
    high_px = [[(10.0 + idx * 0.2) * 1.02] for idx in range(t)]
    low_px = [[(10.0 + idx * 0.2) * 0.98] for idx in range(t)]
    close_px = [[(10.0 + idx * 0.2) * 1.01] for idx in range(t)]
    volume = [[100000.0] for _ in range(t)]
    valid = [[True] for _ in range(t)]
    buy = [[False] for _ in range(t)]
    buy[0][0] = True
    sell = [[False] for _ in range(t)]
    sell[25][0] = True
    score = [[0.0] for _ in range(t)]
    score[0][0] = 86.0

    bundle = MatrixBundle(
        dates=list(dates),
        symbols=[symbol],
        open=np.asarray(open_px, dtype=np.float64),
        high=np.asarray(high_px, dtype=np.float64),
        low=np.asarray(low_px, dtype=np.float64),
        close=np.asarray(close_px, dtype=np.float64),
        volume=np.asarray(volume, dtype=np.float64),
        valid_mask=np.asarray(valid, dtype=bool),
    )
    signals = BacktestSignalMatrix(
        s1=np.zeros((t, n), dtype=bool),
        s2=np.zeros((t, n), dtype=bool),
        s3=np.zeros((t, n), dtype=bool),
        s4=np.zeros((t, n), dtype=bool),
        s5=np.asarray(buy, dtype=bool),
        s6=np.zeros((t, n), dtype=bool),
        s7=np.ones((t, n), dtype=bool),
        s8=np.zeros((t, n), dtype=bool),
        s9=np.zeros((t, n), dtype=bool),
        in_pool=np.asarray(buy, dtype=bool),
        buy_signal=np.asarray(buy, dtype=bool),
        sell_signal=np.asarray(sell, dtype=bool),
        score=np.asarray(score, dtype=np.float64),
    )

    def _calc_snapshot(_row: dict[str, str], _window_days: int, as_of_date: str | None) -> dict[str, object]:
        day = str(as_of_date or "")
        # 故意不给 entry_event（E），用于验证 aligned 语义会过滤。
        event_dates = {"X": day} if day == dates[25] else {}
        return {
            "event_dates": event_dates,
            "event_chain": [],
            "events": [],
            "risk_events": [],
            "sequence_ok": True,
            "entry_quality_score": 90.0,
            "phase": "闃舵鏈槑",
            "structure_hhh": "HH|HL|-",
            "trend_score": 80.0,
            "volatility_score": 80.0,
            "health_score": 88.0,
            "event_score": 86.0,
            "event_grade": "A",
        }

    engine = BacktestEngine(
        get_candles=lambda _: [],
        build_row=lambda raw_symbol, as_of_date=None: {"symbol": raw_symbol, "as_of_date": as_of_date},
        calc_snapshot=_calc_snapshot,
        resolve_symbol_name=lambda raw_symbol: raw_symbol,
    )

    payload_v1 = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from=dates[0],
        date_to=dates[-1],
        window_days=60,
        min_score=0.0,
        require_sequence=False,
        min_event_count=1,
        entry_events=["E"],
        exit_events=["X"],
        initial_capital=100000.0,
        position_pct=1.0,
        max_positions=1,
        stop_loss=0.0,
        take_profit=0.0,
        max_hold_days=60,
        fee_bps=0.0,
        prioritize_signals=True,
        priority_mode="balanced",
        priority_topk_per_day=0,
        matrix_event_semantic_version="matrix_v1",
        enforce_t1=True,
        max_symbols=20,
    )
    payload_aligned = payload_v1.model_copy(update={"matrix_event_semantic_version": "aligned_wyckoff_v2"})

    result_v1 = engine.run(
        payload=payload_v1,
        symbols=[symbol],
        matrix_bundle=bundle,
        matrix_signals=signals,
    )
    result_aligned = engine.run(
        payload=payload_aligned,
        symbols=[symbol],
        matrix_bundle=bundle,
        matrix_signals=signals,
    )

    assert len(result_v1.trades) == 1
    assert result_aligned.trades == []
