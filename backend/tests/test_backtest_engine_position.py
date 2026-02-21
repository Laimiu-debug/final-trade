from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

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
