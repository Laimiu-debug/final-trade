from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np

from ..models import (
    BacktestResponse,
    BacktestRunRequest,
    BacktestTrade,
    CandlePoint,
    DrawdownPoint,
    EquityPoint,
    MonthlyReturnPoint,
    ReviewRange,
    ReviewStats,
    SimTradingConfig,
)
from .backtest_matrix_engine import MatrixBundle
from .backtest_signal_matrix import BacktestSignalMatrix

ENTRY_EVENT_WEIGHTS: dict[str, float] = {
    "PS": 1.0,
    "SC": 1.2,
    "AR": 1.4,
    "ST": 1.6,
    "TSO": 2.5,
    "Spring": 3.0,
    "SOS": 3.4,
    "JOC": 4.0,
    "LPS": 2.8,
    "UTAD": 1.5,
    "SOW": 1.5,
    "LPSY": 1.3,
}

PHASE_PRIORITY_SCORE: dict[str, float] = {
    "吸筹A": 1.1,
    "吸筹B": 1.4,
    "吸筹C": 2.2,
    "吸筹D": 2.0,
    "吸筹E": 0.2,
    "阶段未明": 0.0,
    "派发A": -0.8,
    "派发B": -1.2,
    "派发C": -2.0,
    "派发D": -2.2,
    "派发E": -2.5,
}


@dataclass
class CandidateTrade:
    symbol: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_signal: str
    entry_phase: str
    entry_quality_score: float
    entry_phase_score: float
    entry_events_weight: float
    entry_structure_score: int
    entry_trend_score: float
    entry_volatility_score: float
    entry_price: float
    exit_price: float
    holding_days: int
    exit_reason: str


@dataclass
class MatrixEntryIntent:
    symbol: str
    signal_index: int
    entry_index: int
    signal_date: str
    entry_date: str
    entry_signal: str
    entry_phase: str
    entry_quality_score: float
    entry_phase_score: float
    entry_events_weight: float
    entry_structure_score: int
    entry_trend_score: float
    entry_volatility_score: float
    entry_price: float


class BacktestEngine:
    def __init__(
        self,
        get_candles: Callable[[str], list[CandlePoint]],
        build_row: Callable[[str, str | None], Any | None],
        calc_snapshot: Callable[[Any, int, str | None], dict[str, Any]],
        resolve_symbol_name: Callable[[str], str],
    ) -> None:
        self._get_candles = get_candles
        self._build_row = build_row
        self._calc_snapshot = calc_snapshot
        self._resolve_symbol_name = resolve_symbol_name

    @staticmethod
    def _parse_date(date_text: str) -> datetime | None:
        try:
            return datetime.strptime(date_text, "%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _normalize_event_dates(raw: Any) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        out: dict[str, str] = {}
        for event_code, event_date in raw.items():
            code_text = str(event_code).strip()
            date_text = str(event_date).strip()
            if not code_text or not date_text:
                continue
            out[code_text] = date_text
        return out

    @staticmethod
    def _normalize_event_count(snapshot: dict[str, Any]) -> int:
        event_chain = snapshot.get("event_chain")
        if isinstance(event_chain, list):
            valid = 0
            for row in event_chain:
                if isinstance(row, dict) and str(row.get("event", "")).strip():
                    valid += 1
            if valid > 0:
                return valid
        events = snapshot.get("events")
        risk_events = snapshot.get("risk_events")
        event_count = len(events) if isinstance(events, list) else 0
        event_count += len(risk_events) if isinstance(risk_events, list) else 0
        return event_count

    @staticmethod
    def _structure_score(structure_hhh: str) -> int:
        parts = [part.strip() for part in str(structure_hhh).split("|")]
        return sum(1 for part in parts if part and part != "-")

    @staticmethod
    def _candidate_sort_key(
        row: CandidateTrade,
        *,
        priority_mode: str,
    ) -> tuple[Any, ...]:
        if priority_mode == "phase_first":
            return (
                row.entry_date,
                -row.entry_phase_score,
                -row.entry_quality_score,
                -row.entry_events_weight,
                -row.entry_structure_score,
                row.symbol,
                row.exit_date,
            )
        if priority_mode == "momentum":
            return (
                row.entry_date,
                -row.entry_trend_score,
                -row.entry_quality_score,
                -row.entry_events_weight,
                -row.entry_structure_score,
                row.symbol,
                row.exit_date,
            )
        return (
            row.entry_date,
            -row.entry_quality_score,
            -row.entry_phase_score,
            -row.entry_events_weight,
            -row.entry_structure_score,
            row.symbol,
            row.exit_date,
        )

    @staticmethod
    def _resolve_exit(
        candles: list[CandlePoint],
        entry_index: int,
        exit_signal_events_by_index: dict[int, list[str]],
        payload: BacktestRunRequest,
    ) -> tuple[int, float, str] | None:
        if entry_index >= len(candles):
            return None
        entry_price = float(candles[entry_index].open)
        if not math.isfinite(entry_price) or entry_price <= 0:
            return None

        stop_price = entry_price * (1 - payload.stop_loss) if payload.stop_loss > 0 else None
        take_price = entry_price * (1 + payload.take_profit) if payload.take_profit > 0 else None
        entry_date = candles[entry_index].time
        last_sellable_index: int | None = None

        for bar_index in range(entry_index, len(candles)):
            bar = candles[bar_index]
            sellable_today = True
            if payload.enforce_t1:
                sellable_today = bar.time > entry_date
            if not sellable_today:
                continue

            last_sellable_index = bar_index

            if stop_price is not None and float(bar.low) <= stop_price:
                return bar_index, float(stop_price), "stop_loss"
            if take_price is not None and float(bar.high) >= take_price:
                return bar_index, float(take_price), "take_profit"
            if bar_index in exit_signal_events_by_index:
                event_names = [item for item in exit_signal_events_by_index.get(bar_index, []) if item]
                if event_names:
                    return bar_index, float(bar.close), f"event_exit:{'/'.join(event_names)}"
                return bar_index, float(bar.close), "event_exit"
            if (bar_index - entry_index + 1) >= payload.max_hold_days:
                return bar_index, float(bar.close), "time_exit"

        if payload.enforce_t1 and last_sellable_index is None:
            return None
        fallback_index = last_sellable_index if last_sellable_index is not None else (len(candles) - 1)
        return fallback_index, float(candles[fallback_index].close), "eod_exit"

    @staticmethod
    def _resolve_exit_matrix(
        *,
        entry_index: int,
        entry_price: float,
        high_col: np.ndarray,
        low_col: np.ndarray,
        close_col: np.ndarray,
        valid_col: np.ndarray,
        sell_col: np.ndarray,
        payload: BacktestRunRequest,
    ) -> tuple[int, float, str] | None:
        total_bars = int(valid_col.shape[0])
        if entry_index >= total_bars:
            return None
        if (not math.isfinite(entry_price)) or entry_price <= 0:
            return None

        stop_price = entry_price * (1 - payload.stop_loss) if payload.stop_loss > 0 else None
        take_price = entry_price * (1 + payload.take_profit) if payload.take_profit > 0 else None
        last_sellable_index: int | None = None

        start_index = entry_index + 1 if payload.enforce_t1 else entry_index
        for bar_index in range(start_index, total_bars):
            if not bool(valid_col[bar_index]):
                continue
            last_sellable_index = bar_index

            low_price = float(low_col[bar_index])
            high_price = float(high_col[bar_index])
            close_price = float(close_col[bar_index])
            if not (math.isfinite(low_price) and math.isfinite(high_price) and math.isfinite(close_price)):
                continue
            if low_price <= 0 or high_price <= 0 or close_price <= 0:
                continue

            if stop_price is not None and low_price <= stop_price:
                return bar_index, float(stop_price), "stop_loss"
            if take_price is not None and high_price >= take_price:
                return bar_index, float(take_price), "take_profit"
            if bool(sell_col[bar_index]):
                return bar_index, float(close_price), "event_exit:MATRIX_SELL"
            if (bar_index - entry_index + 1) >= payload.max_hold_days:
                return bar_index, float(close_price), "time_exit"

        if payload.enforce_t1 and last_sellable_index is None:
            return None
        fallback_index = last_sellable_index if last_sellable_index is not None else (total_bars - 1)
        fallback_price = float(close_col[fallback_index]) if math.isfinite(float(close_col[fallback_index])) else entry_price
        if fallback_price <= 0:
            fallback_price = entry_price
        return fallback_index, fallback_price, "eod_exit"

    def _build_candidates_from_matrix(
        self,
        *,
        payload: BacktestRunRequest,
        symbols: list[str],
        start_date: str,
        end_date: str,
        matrix_bundle: MatrixBundle,
        matrix_signals: BacktestSignalMatrix,
        allowed_symbols_by_date: dict[str, set[str]] | None = None,
        allow_reentry_after_skipped: bool = False,
        control_callback: Callable[[], None] | None = None,
    ) -> tuple[list[CandidateTrade], int]:
        dates = list(matrix_bundle.dates)
        if not dates:
            return [], 0

        total_shape = (len(dates), len(matrix_bundle.symbols))
        if (
            matrix_bundle.open.shape != total_shape
            or matrix_bundle.high.shape != total_shape
            or matrix_bundle.low.shape != total_shape
            or matrix_bundle.close.shape != total_shape
            or matrix_bundle.valid_mask.shape != total_shape
            or matrix_signals.buy_signal.shape != total_shape
            or matrix_signals.sell_signal.shape != total_shape
            or matrix_signals.score.shape != total_shape
        ):
            raise ValueError("matrix bundle / signals shape mismatch")

        in_range_mask = np.fromiter(
            (start_date <= day <= end_date for day in dates),
            dtype=bool,
            count=len(dates),
        )
        if int(np.count_nonzero(in_range_mask)) < 2:
            return [], 0

        symbol_to_col = matrix_bundle.symbol_to_index()
        out: list[CandidateTrade] = []
        t1_no_sellable_skips = 0
        in_range_valid_buy = matrix_signals.buy_signal & matrix_bundle.valid_mask & in_range_mask[:, np.newaxis]
        buy_any_by_col = np.any(in_range_valid_buy, axis=0)

        for raw_symbol in symbols:
            if control_callback is not None:
                control_callback()
            symbol = str(raw_symbol).strip().lower()
            col = symbol_to_col.get(symbol)
            if col is None:
                continue
            if not bool(buy_any_by_col[col]):
                continue

            open_col = matrix_bundle.open[:, col]
            high_col = matrix_bundle.high[:, col]
            low_col = matrix_bundle.low[:, col]
            close_col = matrix_bundle.close[:, col]
            valid_col = matrix_bundle.valid_mask[:, col]

            sell_col = matrix_signals.sell_signal[:, col]
            score_col = matrix_signals.score[:, col]

            buy_indexes = np.flatnonzero(in_range_valid_buy[:, col])
            if buy_indexes.size <= 0:
                continue
            if allowed_symbols_by_date is not None:
                filtered_indexes = [
                    int(idx)
                    for idx in buy_indexes.tolist()
                    if symbol in allowed_symbols_by_date.get(dates[int(idx)], set())
                ]
                if not filtered_indexes:
                    continue
                buy_indexes = np.asarray(filtered_indexes, dtype=np.int64)

            blocked_until = -1
            for signal_index in buy_indexes.tolist():
                if control_callback is not None:
                    control_callback()
                if (not allow_reentry_after_skipped) and signal_index <= blocked_until:
                    continue

                entry_index = signal_index + 1
                if entry_index >= len(dates):
                    continue
                if not bool(valid_col[entry_index]):
                    continue

                entry_price = float(open_col[entry_index])
                if (not math.isfinite(entry_price)) or entry_price <= 0:
                    continue

                exit_resolved = self._resolve_exit_matrix(
                    entry_index=entry_index,
                    entry_price=entry_price,
                    high_col=high_col,
                    low_col=low_col,
                    close_col=close_col,
                    valid_col=valid_col,
                    sell_col=sell_col,
                    payload=payload,
                )
                if exit_resolved is None:
                    t1_no_sellable_skips += 1
                    continue

                exit_index, exit_price, exit_reason = exit_resolved
                entry_tags: list[str] = []
                if bool(matrix_signals.s5[signal_index, col]):
                    entry_tags.append("M5")
                if bool(matrix_signals.s6[signal_index, col]):
                    entry_tags.append("M6")
                if not entry_tags:
                    entry_tags.append("MATRIX")
                entry_phase = "吸筹D" if bool(matrix_signals.s7[signal_index, col]) else "阶段未明"
                entry_quality_score = float(score_col[signal_index]) if math.isfinite(float(score_col[signal_index])) else 0.0

                out.append(
                    CandidateTrade(
                        symbol=symbol,
                        signal_date=dates[signal_index],
                        entry_date=dates[entry_index],
                        exit_date=dates[exit_index],
                        entry_signal=" / ".join(entry_tags),
                        entry_phase=entry_phase,
                        entry_quality_score=max(0.0, min(100.0, entry_quality_score)),
                        entry_phase_score=float(PHASE_PRIORITY_SCORE.get(entry_phase, 0.0)),
                        entry_events_weight=float(len(entry_tags)),
                        entry_structure_score=int(bool(matrix_signals.in_pool[signal_index, col])),
                        entry_trend_score=max(0.0, min(100.0, entry_quality_score)),
                        entry_volatility_score=max(0.0, min(100.0, entry_quality_score)),
                        entry_price=entry_price,
                        exit_price=float(exit_price),
                        holding_days=max(0, exit_index - entry_index + 1),
                        exit_reason=exit_reason,
                    )
                )
                if not allow_reentry_after_skipped:
                    blocked_until = max(blocked_until, int(exit_index))

        return out, t1_no_sellable_skips

    def _build_candidates_for_symbol(
        self,
        symbol: str,
        payload: BacktestRunRequest,
        start_date: str,
        end_date: str,
        allowed_symbols_by_date: dict[str, set[str]] | None = None,
        allow_reentry_after_skipped: bool = False,
        control_callback: Callable[[], None] | None = None,
    ) -> tuple[list[CandidateTrade], int]:
        candles = self._get_candles(symbol)
        if len(candles) < 30:
            return [], 0

        in_range_indexes = [
            idx
            for idx, candle in enumerate(candles)
            if start_date <= candle.time <= end_date
        ]
        if len(in_range_indexes) < 2:
            return [], 0

        entry_meta_by_index: dict[int, dict[str, Any]] = {}
        exit_signal_events_by_index: dict[int, list[str]] = {}
        t1_no_sellable_skips = 0

        for idx in in_range_indexes:
            if control_callback is not None:
                control_callback()
            as_of_date = candles[idx].time
            if allowed_symbols_by_date is not None:
                allowed_today = allowed_symbols_by_date.get(as_of_date, set())
                if symbol not in allowed_today:
                    continue
            row = self._build_row(symbol, as_of_date)
            if row is None:
                continue
            snapshot = self._calc_snapshot(row, payload.window_days, as_of_date)

            event_dates = self._normalize_event_dates(snapshot.get("event_dates"))
            day_entry_events = [
                event_name
                for event_name in payload.entry_events
                if event_dates.get(event_name) == as_of_date
            ]
            day_exit_events = [
                event_name
                for event_name in payload.exit_events
                if event_dates.get(event_name) == as_of_date
            ]
            if day_exit_events:
                exit_signal_events_by_index[idx] = day_exit_events
            if not day_entry_events:
                continue

            event_count = self._normalize_event_count(snapshot)
            sequence_ok = bool(snapshot.get("sequence_ok"))
            entry_quality_score = float(snapshot.get("entry_quality_score", 0.0) or 0.0)
            if event_count < payload.min_event_count:
                continue
            if payload.require_sequence and not sequence_ok:
                continue
            if entry_quality_score < payload.min_score:
                continue

            entry_phase = str(snapshot.get("phase", "阶段未明"))
            structure_hhh = str(snapshot.get("structure_hhh", "-"))
            entry_meta_by_index[idx] = {
                "entry_signal": " / ".join(day_entry_events),
                "entry_phase": entry_phase,
                "entry_quality_score": entry_quality_score,
                "entry_phase_score": PHASE_PRIORITY_SCORE.get(entry_phase, 0.0),
                "entry_events_weight": float(sum(ENTRY_EVENT_WEIGHTS.get(evt, 1.0) for evt in day_entry_events)),
                "entry_structure_score": self._structure_score(structure_hhh),
                "entry_trend_score": float(snapshot.get("trend_score", 50.0) or 50.0),
                "entry_volatility_score": float(snapshot.get("volatility_score", 50.0) or 50.0),
            }

        out: list[CandidateTrade] = []
        cursor = 0
        while cursor < len(in_range_indexes) - 1:
            signal_index = in_range_indexes[cursor]
            meta = entry_meta_by_index.get(signal_index)
            if not meta:
                cursor += 1
                continue

            entry_index = signal_index + 1
            if entry_index >= len(candles):
                break
            entry_bar = candles[entry_index]
            entry_price = float(entry_bar.open)
            if not math.isfinite(entry_price) or entry_price <= 0:
                cursor += 1
                continue

            exit_resolved = self._resolve_exit(candles, entry_index, exit_signal_events_by_index, payload)
            if exit_resolved is None:
                t1_no_sellable_skips += 1
                cursor += 1
                continue

            exit_index, exit_price, exit_reason = exit_resolved
            out.append(
                CandidateTrade(
                    symbol=symbol,
                    signal_date=candles[signal_index].time,
                    entry_date=entry_bar.time,
                    exit_date=candles[exit_index].time,
                    entry_signal=str(meta["entry_signal"]),
                    entry_phase=str(meta["entry_phase"]),
                    entry_quality_score=float(meta["entry_quality_score"]),
                    entry_phase_score=float(meta["entry_phase_score"]),
                    entry_events_weight=float(meta["entry_events_weight"]),
                    entry_structure_score=int(meta["entry_structure_score"]),
                    entry_trend_score=float(meta["entry_trend_score"]),
                    entry_volatility_score=float(meta["entry_volatility_score"]),
                    entry_price=entry_price,
                    exit_price=float(exit_price),
                    holding_days=max(0, exit_index - entry_index + 1),
                    exit_reason=exit_reason,
                )
            )

            if allow_reentry_after_skipped:
                cursor += 1
            else:
                while cursor < len(in_range_indexes) and in_range_indexes[cursor] <= exit_index:
                    cursor += 1

        return out, t1_no_sellable_skips

    @staticmethod
    def _matrix_intent_sort_key(
        row: MatrixEntryIntent,
        *,
        priority_mode: str,
    ) -> tuple[Any, ...]:
        if priority_mode == "phase_first":
            return (
                row.entry_date,
                -row.entry_phase_score,
                -row.entry_quality_score,
                -row.entry_events_weight,
                -row.entry_structure_score,
                row.symbol,
                row.signal_date,
            )
        if priority_mode == "momentum":
            return (
                row.entry_date,
                -row.entry_trend_score,
                -row.entry_quality_score,
                -row.entry_events_weight,
                -row.entry_structure_score,
                row.symbol,
                row.signal_date,
            )
        return (
            row.entry_date,
            -row.entry_quality_score,
            -row.entry_phase_score,
            -row.entry_events_weight,
            -row.entry_structure_score,
            row.symbol,
            row.signal_date,
        )

    def _build_matrix_entry_intents(
        self,
        *,
        payload: BacktestRunRequest,
        symbols: list[str],
        start_date: str,
        end_date: str,
        matrix_bundle: MatrixBundle,
        matrix_signals: BacktestSignalMatrix,
        allowed_symbols_by_date: dict[str, set[str]] | None = None,
        control_callback: Callable[[], None] | None = None,
    ) -> list[MatrixEntryIntent]:
        dates = list(matrix_bundle.dates)
        if not dates:
            return []

        total_shape = (len(dates), len(matrix_bundle.symbols))
        if (
            matrix_bundle.open.shape != total_shape
            or matrix_bundle.valid_mask.shape != total_shape
            or matrix_signals.buy_signal.shape != total_shape
            or matrix_signals.score.shape != total_shape
        ):
            raise ValueError("matrix bundle / signals shape mismatch")

        in_range_mask = np.fromiter(
            (start_date <= day <= end_date for day in dates),
            dtype=bool,
            count=len(dates),
        )
        if int(np.count_nonzero(in_range_mask)) < 2:
            return []

        symbol_to_col = matrix_bundle.symbol_to_index()
        in_range_valid_buy = matrix_signals.buy_signal & matrix_bundle.valid_mask & in_range_mask[:, np.newaxis]
        buy_any_by_col = np.any(in_range_valid_buy, axis=0)
        out: list[MatrixEntryIntent] = []

        for raw_symbol in symbols:
            if control_callback is not None:
                control_callback()
            symbol = str(raw_symbol).strip().lower()
            col = symbol_to_col.get(symbol)
            if col is None:
                continue
            if not bool(buy_any_by_col[col]):
                continue

            open_col = matrix_bundle.open[:, col]
            valid_col = matrix_bundle.valid_mask[:, col]
            score_col = matrix_signals.score[:, col]
            buy_indexes = np.flatnonzero(in_range_valid_buy[:, col])
            if buy_indexes.size <= 0:
                continue
            if allowed_symbols_by_date is not None:
                filtered_indexes = [
                    int(idx)
                    for idx in buy_indexes.tolist()
                    if symbol in allowed_symbols_by_date.get(dates[int(idx)], set())
                ]
                if not filtered_indexes:
                    continue
                buy_indexes = np.asarray(filtered_indexes, dtype=np.int64)

            for signal_index in buy_indexes.tolist():
                if control_callback is not None:
                    control_callback()
                entry_index = int(signal_index) + 1
                if entry_index >= len(dates):
                    continue
                if not bool(valid_col[entry_index]):
                    continue

                entry_price = float(open_col[entry_index])
                if (not math.isfinite(entry_price)) or entry_price <= 0:
                    continue

                entry_tags: list[str] = []
                if bool(matrix_signals.s5[signal_index, col]):
                    entry_tags.append("M5")
                if bool(matrix_signals.s6[signal_index, col]):
                    entry_tags.append("M6")
                if not entry_tags:
                    entry_tags.append("MATRIX")
                entry_phase = "吸筹D" if bool(matrix_signals.s7[signal_index, col]) else "阶段未明"
                raw_quality = float(score_col[signal_index]) if math.isfinite(float(score_col[signal_index])) else 0.0
                entry_quality_score = max(0.0, min(100.0, raw_quality))

                out.append(
                    MatrixEntryIntent(
                        symbol=symbol,
                        signal_index=int(signal_index),
                        entry_index=entry_index,
                        signal_date=dates[signal_index],
                        entry_date=dates[entry_index],
                        entry_signal=" / ".join(entry_tags),
                        entry_phase=entry_phase,
                        entry_quality_score=entry_quality_score,
                        entry_phase_score=float(PHASE_PRIORITY_SCORE.get(entry_phase, 0.0)),
                        entry_events_weight=float(len(entry_tags)),
                        entry_structure_score=int(bool(matrix_signals.in_pool[signal_index, col])),
                        entry_trend_score=entry_quality_score,
                        entry_volatility_score=entry_quality_score,
                        entry_price=entry_price,
                    )
                )
        return out

    def _execute_matrix_position_intents(
        self,
        *,
        payload: BacktestRunRequest,
        intents: list[MatrixEntryIntent],
        matrix_bundle: MatrixBundle,
        matrix_signals: BacktestSignalMatrix,
        control_callback: Callable[[], None] | None = None,
    ) -> tuple[list[BacktestTrade], int, dict[str, int], int]:
        intent_fee_rate = max(0.0, float(payload.fee_bps)) / 10000.0
        dates = list(matrix_bundle.dates)
        symbol_to_col = matrix_bundle.symbol_to_index()

        cash = float(payload.initial_capital)
        equity = float(payload.initial_capital)
        max_concurrent_positions = 0
        active_positions: list[dict[str, float | str]] = []
        active_symbols: set[str] = set()
        executed: list[BacktestTrade] = []
        t1_no_sellable_skips = 0
        skip_reasons: dict[str, int] = {
            "max_positions": 0,
            "insufficient_cash": 0,
            "invalid_price": 0,
            "duplicate_symbol": 0,
        }

        def release_until(current_entry_date: str) -> None:
            nonlocal cash, equity, active_positions, active_symbols
            if not active_positions:
                return
            remaining_positions: list[dict[str, float | str]] = []
            for item in active_positions:
                exit_date = str(item.get("exit_date", ""))
                if exit_date < current_entry_date:
                    cash += float(item.get("exit_amount", 0.0))
                    equity += float(item.get("pnl_amount", 0.0))
                    symbol_text = str(item.get("symbol", "")).strip().lower()
                    if symbol_text:
                        active_symbols.discard(symbol_text)
                else:
                    remaining_positions.append(item)
            active_positions = remaining_positions

        for row in intents:
            if control_callback is not None:
                control_callback()
            release_until(row.entry_date)

            if row.symbol in active_symbols:
                skip_reasons["duplicate_symbol"] += 1
                continue
            if len(active_positions) >= payload.max_positions:
                skip_reasons["max_positions"] += 1
                continue

            entry_exec = float(row.entry_price) * (1 + intent_fee_rate)
            if (not math.isfinite(entry_exec)) or entry_exec <= 0:
                skip_reasons["invalid_price"] += 1
                continue

            allocation = min(cash, max(0.0, equity * payload.position_pct))
            shares = int(math.floor(allocation / entry_exec / 100.0)) * 100
            if shares <= 0:
                skip_reasons["insufficient_cash"] += 1
                continue
            invested = shares * entry_exec
            if invested <= 0 or invested > cash + 1e-9:
                skip_reasons["insufficient_cash"] += 1
                continue

            col = symbol_to_col.get(row.symbol)
            if col is None:
                skip_reasons["invalid_price"] += 1
                continue

            exit_resolved = self._resolve_exit_matrix(
                entry_index=row.entry_index,
                entry_price=float(row.entry_price),
                high_col=matrix_bundle.high[:, col],
                low_col=matrix_bundle.low[:, col],
                close_col=matrix_bundle.close[:, col],
                valid_col=matrix_bundle.valid_mask[:, col],
                sell_col=matrix_signals.sell_signal[:, col],
                payload=payload,
            )
            if exit_resolved is None:
                t1_no_sellable_skips += 1
                continue
            exit_index, raw_exit_price, exit_reason = exit_resolved
            exit_price = float(raw_exit_price)
            if not math.isfinite(exit_price) or exit_price <= 0:
                skip_reasons["invalid_price"] += 1
                continue

            exit_exec = exit_price * (1 - intent_fee_rate)
            if (not math.isfinite(exit_exec)) or exit_exec <= 0:
                skip_reasons["invalid_price"] += 1
                continue

            exit_amount = shares * exit_exec
            pnl_amount = exit_amount - invested
            pnl_ratio = pnl_amount / invested if invested > 0 else 0.0
            cash -= invested

            exit_date = dates[int(exit_index)] if 0 <= int(exit_index) < len(dates) else row.entry_date
            holding_days = max(0, int(exit_index) - int(row.entry_index) + 1)
            active_positions.append(
                {
                    "symbol": row.symbol,
                    "exit_date": exit_date,
                    "exit_amount": float(exit_amount),
                    "pnl_amount": float(pnl_amount),
                }
            )
            active_symbols.add(row.symbol)
            max_concurrent_positions = max(max_concurrent_positions, len(active_positions))

            executed.append(
                BacktestTrade(
                    symbol=row.symbol,
                    name=self._resolve_symbol_name(row.symbol),
                    signal_date=row.signal_date,
                    entry_date=row.entry_date,
                    exit_date=exit_date,
                    entry_signal=row.entry_signal,
                    entry_phase=row.entry_phase,
                    entry_quality_score=round(row.entry_quality_score, 2),
                    exit_reason=exit_reason,
                    quantity=shares,
                    entry_price=round(row.entry_price, 4),
                    exit_price=round(exit_price, 4),
                    holding_days=holding_days,
                    pnl_amount=round(pnl_amount, 4),
                    pnl_ratio=round(pnl_ratio, 6),
                )
            )

        if active_positions:
            for item in sorted(active_positions, key=lambda row: str(row.get("exit_date", ""))):
                cash += float(item.get("exit_amount", 0.0))
                equity += float(item.get("pnl_amount", 0.0))

        return executed, max_concurrent_positions, skip_reasons, t1_no_sellable_skips

    def run(
        self,
        *,
        payload: BacktestRunRequest,
        symbols: list[str],
        allowed_symbols_by_date: dict[str, set[str]] | None = None,
        matrix_bundle: MatrixBundle | None = None,
        matrix_signals: BacktestSignalMatrix | None = None,
        control_callback: Callable[[], None] | None = None,
    ) -> BacktestResponse:
        if control_callback is not None:
            control_callback()
        start_dt = self._parse_date(payload.date_from)
        end_dt = self._parse_date(payload.date_to)
        if start_dt is None or end_dt is None:
            raise ValueError("date_from/date_to 必须是 YYYY-MM-DD")
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")
        allow_reentry_after_skipped = payload.pool_roll_mode == "position"
        use_matrix_position_intents = (
            allow_reentry_after_skipped
            and matrix_bundle is not None
            and matrix_signals is not None
        )

        notes: list[str] = []
        intents: list[MatrixEntryIntent] = []
        candidate_stage_start = time.perf_counter()
        if matrix_bundle is not None and matrix_signals is not None:
            if use_matrix_position_intents:
                candidates = []
                total_t1_skips = 0
                intents = self._build_matrix_entry_intents(
                    payload=payload,
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    matrix_bundle=matrix_bundle,
                    matrix_signals=matrix_signals,
                    allowed_symbols_by_date=allowed_symbols_by_date,
                    control_callback=control_callback,
                )
            else:
                candidates, total_t1_skips = self._build_candidates_from_matrix(
                    payload=payload,
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    matrix_bundle=matrix_bundle,
                    matrix_signals=matrix_signals,
                    allowed_symbols_by_date=allowed_symbols_by_date,
                    allow_reentry_after_skipped=allow_reentry_after_skipped,
                    control_callback=control_callback,
                )
            notes.append("矩阵信号引擎: 使用 (T,N) 信号切片路径，跳过逐股逐日 snapshot 重算。")
        else:
            candidates = []
            total_t1_skips = 0
            for symbol in symbols:
                if control_callback is not None:
                    control_callback()
                rows, t1_skips = self._build_candidates_for_symbol(
                    symbol,
                    payload,
                    start_date,
                    end_date,
                    allowed_symbols_by_date=allowed_symbols_by_date,
                    allow_reentry_after_skipped=allow_reentry_after_skipped,
                    control_callback=control_callback,
                )
                candidates.extend(rows)
                total_t1_skips += t1_skips
        if total_t1_skips > 0:
            notes.append(f"T+1 约束下有 {total_t1_skips} 笔信号因样本内无可卖出日被跳过。")
        if allow_reentry_after_skipped:
            notes.append("持仓触发滚动：未成交信号不会阻断同一标的后续信号。")

        if use_matrix_position_intents:
            if payload.prioritize_signals:
                intents.sort(key=lambda row: self._matrix_intent_sort_key(row, priority_mode=payload.priority_mode))
                notes.append(f"同日信号按优先级执行（模式: {payload.priority_mode}）。")
            else:
                intents.sort(key=lambda row: (row.entry_date, row.symbol, row.signal_date))
                if payload.priority_topk_per_day > 0:
                    notes.append("未启用优先级排序，priority_topk_per_day 配置未生效。")
        elif payload.prioritize_signals:
            candidates.sort(key=lambda row: self._candidate_sort_key(row, priority_mode=payload.priority_mode))
            notes.append(f"同日信号按优先级执行（模式: {payload.priority_mode}）。")
        else:
            candidates.sort(key=lambda row: (row.entry_date, row.symbol, row.exit_date))
            if payload.priority_topk_per_day > 0:
                notes.append("未启用优先级排序，priority_topk_per_day 配置未生效。")

        if use_matrix_position_intents and payload.prioritize_signals and payload.priority_topk_per_day > 0:
            before_count = len(intents)
            kept_intents: list[MatrixEntryIntent] = []
            day_counter: dict[str, int] = defaultdict(int)
            for row in intents:
                if day_counter[row.signal_date] >= payload.priority_topk_per_day:
                    continue
                kept_intents.append(row)
                day_counter[row.signal_date] += 1
            intents = kept_intents
            dropped = before_count - len(intents)
            if dropped > 0:
                notes.append(
                    f"同日 TopK 限流已生效：每日保留前 {payload.priority_topk_per_day} 笔候选，共过滤 {dropped} 笔。"
                )

        if (not use_matrix_position_intents) and payload.prioritize_signals and payload.priority_topk_per_day > 0:
            before_count = len(candidates)
            kept: list[CandidateTrade] = []
            day_counter: dict[str, int] = defaultdict(int)
            for row in candidates:
                if day_counter[row.signal_date] >= payload.priority_topk_per_day:
                    continue
                kept.append(row)
                day_counter[row.signal_date] += 1
            candidates = kept
            dropped = before_count - len(candidates)
            if dropped > 0:
                notes.append(
                    f"同日 TopK 限流已生效：每日保留前 {payload.priority_topk_per_day} 笔候选，共过滤 {dropped} 笔。"
                )

        candidate_count = len(intents) if use_matrix_position_intents else len(candidates)
        candidate_stage_elapsed = time.perf_counter() - candidate_stage_start

        fee_rate = max(0.0, float(payload.fee_bps)) / 10000.0
        if fee_rate > 0.01:
            notes.append("fee_bps 超过 100 时，cost_snapshot 仅展示截断后的 commission_rate=1%。")

        match_stage_start = time.perf_counter()
        if use_matrix_position_intents and matrix_bundle is not None and matrix_signals is not None:
            executed, max_concurrent_positions, skip_reasons, t1_skips_exec = self._execute_matrix_position_intents(
                payload=payload,
                intents=intents,
                matrix_bundle=matrix_bundle,
                matrix_signals=matrix_signals,
                control_callback=control_callback,
            )
            total_t1_skips += t1_skips_exec
            if t1_skips_exec > 0:
                notes.append(f"T+1 约束下有 {t1_skips_exec} 笔持仓候选因无可卖出日被跳过。")
        else:
            cash = float(payload.initial_capital)
            equity = float(payload.initial_capital)
            max_concurrent_positions = 0
            active_positions: list[dict[str, float | str]] = []
            executed: list[BacktestTrade] = []
            skip_reasons: dict[str, int] = {
                "max_positions": 0,
                "insufficient_cash": 0,
                "invalid_price": 0,
                "duplicate_symbol": 0,
            }
            active_symbols: set[str] = set()

            def release_until(current_entry_date: str) -> None:
                nonlocal cash, equity, active_positions, active_symbols
                if not active_positions:
                    return
                remaining_positions: list[dict[str, float | str]] = []
                for item in active_positions:
                    exit_date = str(item.get("exit_date", ""))
                    if exit_date < current_entry_date:
                        cash += float(item.get("exit_amount", 0.0))
                        equity += float(item.get("pnl_amount", 0.0))
                        symbol_text = str(item.get("symbol", "")).strip().lower()
                        if symbol_text:
                            active_symbols.discard(symbol_text)
                    else:
                        remaining_positions.append(item)
                active_positions = remaining_positions

            for row in candidates:
                if control_callback is not None:
                    control_callback()
                release_until(row.entry_date)

                if row.symbol in active_symbols:
                    skip_reasons["duplicate_symbol"] += 1
                    continue

                if len(active_positions) >= payload.max_positions:
                    skip_reasons["max_positions"] += 1
                    continue

                entry_exec = float(row.entry_price) * (1 + fee_rate)
                exit_exec = float(row.exit_price) * (1 - fee_rate)
                if not math.isfinite(entry_exec) or not math.isfinite(exit_exec) or entry_exec <= 0:
                    skip_reasons["invalid_price"] += 1
                    continue

                allocation = min(cash, max(0.0, equity * payload.position_pct))
                shares = int(math.floor(allocation / entry_exec / 100.0)) * 100
                if shares <= 0:
                    skip_reasons["insufficient_cash"] += 1
                    continue

                invested = shares * entry_exec
                if invested <= 0 or invested > cash + 1e-9:
                    skip_reasons["insufficient_cash"] += 1
                    continue

                exit_amount = shares * exit_exec
                pnl_amount = exit_amount - invested
                pnl_ratio = pnl_amount / invested if invested > 0 else 0.0
                cash -= invested

                active_positions.append(
                    {
                        "symbol": row.symbol,
                        "exit_date": row.exit_date,
                        "exit_amount": float(exit_amount),
                        "pnl_amount": float(pnl_amount),
                    }
                )
                active_symbols.add(row.symbol)
                max_concurrent_positions = max(max_concurrent_positions, len(active_positions))

                executed.append(
                    BacktestTrade(
                        symbol=row.symbol,
                        name=self._resolve_symbol_name(row.symbol),
                        signal_date=row.signal_date,
                        entry_date=row.entry_date,
                        exit_date=row.exit_date,
                        entry_signal=row.entry_signal,
                        entry_phase=row.entry_phase,
                        entry_quality_score=round(row.entry_quality_score, 2),
                        exit_reason=row.exit_reason,
                        quantity=shares,
                        entry_price=round(row.entry_price, 4),
                        exit_price=round(row.exit_price, 4),
                        holding_days=row.holding_days,
                        pnl_amount=round(pnl_amount, 4),
                        pnl_ratio=round(pnl_ratio, 6),
                    )
                )

            if active_positions:
                for item in sorted(active_positions, key=lambda row: str(row.get("exit_date", ""))):
                    cash += float(item.get("exit_amount", 0.0))
                    equity += float(item.get("pnl_amount", 0.0))

        execution_match_elapsed = time.perf_counter() - match_stage_start
        skipped_count = int(sum(skip_reasons.values()))
        fill_rate = (len(executed) / candidate_count) if candidate_count > 0 else 0.0
        if skipped_count > 0:
            detail = ", ".join(f"{key}:{value}" for key, value in skip_reasons.items() if value > 0)
            notes.append(f"组合约束跳过 {skipped_count} 笔信号（{detail}）。")

        trade_count = len(executed)
        win_count = sum(1 for row in executed if row.pnl_amount > 0)
        loss_count = sum(1 for row in executed if row.pnl_amount < 0)
        gross_profit = sum(row.pnl_amount for row in executed if row.pnl_amount > 0)
        gross_loss = sum(row.pnl_amount for row in executed if row.pnl_amount < 0)
        avg_pnl_ratio = (
            sum(row.pnl_ratio for row in executed) / trade_count
            if trade_count > 0
            else 0.0
        )
        win_rate = (win_count / trade_count) if trade_count > 0 else 0.0
        total_pnl = sum(row.pnl_amount for row in executed)
        final_equity = float(payload.initial_capital) + total_pnl
        total_return = (final_equity / payload.initial_capital - 1) if payload.initial_capital > 0 else 0.0

        if gross_loss < 0:
            profit_factor = gross_profit / abs(gross_loss)
        elif gross_profit > 0:
            profit_factor = math.inf
        else:
            profit_factor = 0.0

        curve_stage_start = time.perf_counter()
        entries_by_date: dict[str, list[tuple[int, BacktestTrade]]] = defaultdict(list)
        exits_by_date: dict[str, list[tuple[int, BacktestTrade]]] = defaultdict(list)
        for idx, trade in enumerate(executed):
            entries_by_date[trade.entry_date].append((idx, trade))
            exits_by_date[trade.exit_date].append((idx, trade))

        executed_symbols = {trade.symbol for trade in executed}
        input_symbols = {str(symbol).strip().lower() for symbol in symbols if str(symbol).strip()}
        calendar_dates_set: set[str] = set()
        close_map_by_symbol: dict[str, dict[str, float]] = {}
        if matrix_bundle is not None and matrix_bundle.dates:
            matrix_dates = list(matrix_bundle.dates)
            in_range_indexes = [
                idx for idx, day in enumerate(matrix_dates) if start_date <= day <= end_date
            ]
            for idx in in_range_indexes:
                calendar_dates_set.add(matrix_dates[idx])

            symbol_to_col = matrix_bundle.symbol_to_index()
            for symbol in executed_symbols:
                col = symbol_to_col.get(symbol)
                if col is None:
                    continue
                close_col = matrix_bundle.close[:, col]
                valid_col = matrix_bundle.valid_mask[:, col]
                day_close: dict[str, float] = {}
                for idx in in_range_indexes:
                    if not bool(valid_col[idx]):
                        continue
                    close_price = float(close_col[idx])
                    if math.isfinite(close_price) and close_price > 0:
                        day_close[matrix_dates[idx]] = close_price
                close_map_by_symbol[symbol] = day_close
        else:
            for symbol in input_symbols:
                day_close: dict[str, float] = {}
                for bar in self._get_candles(symbol):
                    if bar.time < start_date or bar.time > end_date:
                        continue
                    calendar_dates_set.add(bar.time)
                    if symbol not in executed_symbols:
                        continue
                    close_price = float(bar.close)
                    if math.isfinite(close_price) and close_price > 0:
                        day_close[bar.time] = close_price
                if symbol in executed_symbols:
                    close_map_by_symbol[symbol] = day_close

        for symbol in executed_symbols:
            if symbol in close_map_by_symbol:
                continue
            day_close: dict[str, float] = {}
            for bar in self._get_candles(symbol):
                if bar.time < start_date or bar.time > end_date:
                    continue
                calendar_dates_set.add(bar.time)
                close_price = float(bar.close)
                if math.isfinite(close_price) and close_price > 0:
                    day_close[bar.time] = close_price
            close_map_by_symbol[symbol] = day_close

        if not calendar_dates_set:
            calendar_dates_set.update(day for day in entries_by_date if start_date <= day <= end_date)
            calendar_dates_set.update(day for day in exits_by_date if start_date <= day <= end_date)

        if not calendar_dates_set:
            cursor_dt = start_dt
            while cursor_dt <= end_dt:
                if cursor_dt.weekday() < 5:
                    calendar_dates_set.add(cursor_dt.strftime("%Y-%m-%d"))
                cursor_dt += timedelta(days=1)

        trading_dates = sorted(calendar_dates_set) if calendar_dates_set else [start_date]
        notes.append("资金曲线按交易日盯市：周末及节假日不生成净值点。")
        running_realized_pnl = 0.0
        cash_mark = float(payload.initial_capital)
        open_positions: dict[int, dict[str, float | str]] = {}
        last_close_by_symbol: dict[str, float] = {}
        days_with_positions = 0

        equity_curve: list[EquityPoint] = []
        for day in trading_dates:
            if control_callback is not None:
                control_callback()
            for idx, trade in entries_by_date.get(day, []):
                entry_exec = float(trade.entry_price) * (1 + fee_rate)
                invested = float(trade.quantity) * entry_exec
                cash_mark -= invested
                open_positions[idx] = {
                    "symbol": trade.symbol,
                    "quantity": float(trade.quantity),
                    "entry_price": float(trade.entry_price),
                }

            for idx, trade in exits_by_date.get(day, []):
                exit_exec = float(trade.exit_price) * (1 - fee_rate)
                exit_amount = float(trade.quantity) * exit_exec
                cash_mark += exit_amount
                running_realized_pnl += float(trade.pnl_amount)
                open_positions.pop(idx, None)

            market_value = 0.0
            for position in open_positions.values():
                symbol = str(position.get("symbol", ""))
                quantity = float(position.get("quantity", 0.0))
                mark = close_map_by_symbol.get(symbol, {}).get(day)
                if mark is not None and math.isfinite(mark) and mark > 0:
                    last_close_by_symbol[symbol] = mark
                else:
                    mark = last_close_by_symbol.get(symbol)
                if mark is None or not math.isfinite(mark) or mark <= 0:
                    mark = float(position.get("entry_price", 0.0))
                market_value += quantity * mark
            if open_positions:
                days_with_positions += 1

            equity_curve.append(
                EquityPoint(
                    date=day,
                    equity=round(cash_mark + market_value, 4),
                    realized_pnl=round(running_realized_pnl, 4),
                )
            )

        if not equity_curve:
            equity_curve.append(
                EquityPoint(
                    date=start_date,
                    equity=round(float(payload.initial_capital), 4),
                    realized_pnl=0.0,
                )
            )
        notes.append(
            f"并发持仓峰值: {max_concurrent_positions}/{payload.max_positions}；"
            f"持仓覆盖交易日: {days_with_positions}/{len(trading_dates)}。"
        )

        curve_elapsed = time.perf_counter() - curve_stage_start
        notes.append(
            f"执行细分耗时[候选={candidate_stage_elapsed:.2f}s, 撮合={execution_match_elapsed:.2f}s, 曲线={curve_elapsed:.2f}s]"
        )

        drawdown_curve: list[DrawdownPoint] = []
        peak = -float("inf")
        max_drawdown_raw = 0.0
        for row in equity_curve:
            peak = max(peak, row.equity)
            drawdown = (row.equity - peak) / peak if peak > 0 else 0.0
            max_drawdown_raw = min(max_drawdown_raw, drawdown)
            drawdown_curve.append(DrawdownPoint(date=row.date, drawdown=round(drawdown, 6)))

        monthly_agg: dict[str, dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "count": 0.0})
        for row in executed:
            month = row.exit_date[:7]
            monthly_agg[month]["pnl"] += row.pnl_amount
            monthly_agg[month]["count"] += 1.0
        monthly_returns = [
            MonthlyReturnPoint(
                month=month,
                return_ratio=round(values["pnl"] / payload.initial_capital, 6) if payload.initial_capital > 0 else 0.0,
                pnl_amount=round(values["pnl"], 4),
                trade_count=int(values["count"]),
            )
            for month, values in sorted(monthly_agg.items())
        ]

        top_trades = sorted(executed, key=lambda row: row.pnl_amount, reverse=True)[:10]
        bottom_trades = sorted(executed, key=lambda row: row.pnl_amount)[:10]
        stats = ReviewStats(
            win_rate=round(win_rate, 6),
            total_return=round(total_return, 6),
            max_drawdown=round(abs(max_drawdown_raw), 6),
            avg_pnl_ratio=round(avg_pnl_ratio, 6),
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            profit_factor=round(profit_factor, 6) if math.isfinite(profit_factor) else 999.0,
        )

        cost_snapshot = SimTradingConfig(
            initial_capital=float(payload.initial_capital),
            commission_rate=min(0.01, fee_rate),
            min_commission=0.0,
            stamp_tax_rate=0.0,
            transfer_fee_rate=0.0,
            slippage_rate=0.0,
        )

        return BacktestResponse(
            stats=stats,
            trades=executed,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            monthly_returns=monthly_returns,
            top_trades=top_trades,
            bottom_trades=bottom_trades,
            cost_snapshot=cost_snapshot,
            range=ReviewRange(date_from=start_date, date_to=end_date, date_axis="sell"),
            notes=notes,
            candidate_count=candidate_count,
            skipped_count=skipped_count,
            fill_rate=round(fill_rate, 6),
            max_concurrent_positions=max_concurrent_positions,
        )
