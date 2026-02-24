"""
Wyckoff signal detection and analysis.

This module implements the Wyckoff methodology for detecting accumulation
and distribution patterns in stock price movements.
"""

import math
from datetime import datetime
from typing import Callable, Optional

from ..models import CandlePoint, ScreenerResult, Stage, ThemeStage


# Wyckoff event constants
WYCKOFF_ACC_EVENTS = ("PS", "SC", "AR", "ST", "TSO", "Spring", "SOS", "JOC", "LPS")
WYCKOFF_DIST_EVENTS = ("PSY", "BC", "AR(d)", "ST(d)")
WYCKOFF_RISK_EVENTS = (*WYCKOFF_DIST_EVENTS, "UTAD", "SOW", "LPSY")
WYCKOFF_EVENT_ORDER = (*WYCKOFF_ACC_EVENTS, *WYCKOFF_RISK_EVENTS)
WYCKOFF_KEY_CONFIRM_EVENTS = ("SOS", "LPS", "Spring", "JOC")
WYCKOFF_PREREQUISITE_MAP: dict[str, tuple[str, ...]] = {
    "TSO": ("SC", "ST"),
    "Spring": ("SC", "ST", "AR"),
    "SOS": ("SC", "AR", "ST", "Spring", "TSO"),
    "JOC": ("SOS", "Spring", "ST", "TSO"),
    "LPS": ("SOS", "JOC"),
    "UTAD": ("BC", "AR(d)", "ST(d)", "PSY"),
    "SOW": ("UTAD", "AR(d)", "ST(d)"),
    "LPSY": ("SOW", "UTAD", "ST(d)"),
}
EVENT_DECAY_LAMBDA_DEFAULT = 0.075
EVENT_DECAY_MAX_AGE_DAYS = 45
VOLUME_CALENDAR_BASE_LOOKBACK = 20
VOLUME_CALENDAR_EXT_LOOKBACK = 60
COST_CENTER_EMA_WINDOW = 20
EVENT_DECAY_LAMBDA_MAP: dict[str, float] = {
    "PS": 0.08,
    "SC": 0.08,
    "AR": 0.075,
    "ST": 0.075,
    "TSO": 0.07,
    "Spring": 0.07,
    "SOS": 0.065,
    "JOC": 0.065,
    "LPS": 0.06,
    "PSY": 0.09,
    "BC": 0.09,
    "AR(d)": 0.085,
    "ST(d)": 0.085,
    "UTAD": 0.08,
    "SOW": 0.08,
    "LPSY": 0.08,
}


class SignalAnalyzer:
    """
    Analyzes stock price patterns to detect Wyckoff accumulation and distribution signals.
    """

    @staticmethod
    def safe_mean(values: list[float] | list[int]) -> float:
        """Calculate mean of values, handling empty lists."""
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def safe_std(values: list[float] | list[int]) -> float:
        """Calculate standard deviation, handling empty lists."""
        if not values:
            return 0.0
        mean = SignalAnalyzer.safe_mean(values)
        variance = SignalAnalyzer.safe_mean([(float(value) - mean) ** 2 for value in values])
        return variance ** 0.5

    @staticmethod
    def clamp_score(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
        """Clamp a value to a specified range."""
        return max(lower, min(upper, value))

    @staticmethod
    def _event_grade_from_score(score: float) -> str:
        if score >= 75.0:
            return "A"
        if score >= 60.0:
            return "B"
        return "C"

    @staticmethod
    def phase_hint(phase: str) -> str:
        """Get human-readable hint for a phase."""
        hints = {
            "\u5438\u7b79A": "\u5e95\u90e8\u652f\u6491\uff0c\u5173\u6ce8\u53cd\u5f39",
            "\u5438\u7b79B": "\u4e8c\u6b21\u63a2\u5e95\uff0c\u91cf\u80fd\u840e\u7f29",
            "\u5438\u7b79C": "\u5f39\u7c27\u63a2\u5e95\uff0c\u84c4\u52bf\u5f85\u53d1",
            "\u5438\u7b79D": "\u5f3a\u52bf\u7a81\u7834\uff0c\u91cf\u4ef7\u9f50\u5347",
            "\u5438\u7b79E": "\u56de\u8e29\u786e\u8ba4\uff0c\u826f\u673a\u5165\u573a",
            "\u6d3e\u53d1A": "\u9ad8\u4f4d\u9707\u8361\uff0c\u8b66\u60d5\u98ce\u9669",
            "\u6d3e\u53d1B": "\u4e0a\u653b\u4e4f\u529b\uff0c\u4e3b\u529b\u6d3e\u53d1",
            "\u6d3e\u53d1C": "\u7834\u4f4d\u4e0b\u884c\uff0c\u98ce\u9669\u52a0\u5267",
            "\u6d3e\u53d1D": "\u6301\u7eed\u4e0b\u8dcc\uff0c\u8d8b\u52bf\u8f6c\u5f31",
            "\u6d3e\u53d1E": "\u6050\u614c\u4e0b\u8dcc\uff0c\u8fdc\u79bb\u89c2\u671b",
            "\u9636\u6bb5\u672a\u660e": "\u4fe1\u53f7\u4e0d\u8db3\uff0c\u7ee7\u7eed\u89c2\u5bdf",
        }
        return hints.get(phase, "\u89c2\u5bdf\u4e3a\u4e3b\uff0c\u63a7\u5236\u4ed3\u4f4d")
    @staticmethod
    def is_subsequence(sequence: list[str], target: tuple[str, ...]) -> bool:
        """
        Check if sequence appears in target in the same order.

        Args:
            sequence: List of events in chronological order
            target: Expected event order

        Returns:
            True if sequence is a subsequence of target
        """
        it = iter(target)
        return all(event in it for event in sequence)

    @staticmethod
    def _event_decay_weight(event_name: str, age_days: int) -> float:
        age = max(0, int(age_days))
        if age >= EVENT_DECAY_MAX_AGE_DAYS:
            return 0.0
        decay_lambda = float(EVENT_DECAY_LAMBDA_MAP.get(event_name, EVENT_DECAY_LAMBDA_DEFAULT))
        return max(0.0, min(1.0, math.exp(-decay_lambda * float(age))))

    @classmethod
    def _build_event_age_days(
        cls,
        *,
        dates: list[str],
        event_chain: list[dict[str, str]],
    ) -> dict[str, int]:
        if not dates or not event_chain:
            return {}
        index_by_date = {str(day): idx for idx, day in enumerate(dates)}
        last_idx = len(dates) - 1
        out: dict[str, int] = {}
        for item in event_chain:
            event_name = str(item.get("event", "")).strip()
            event_date = str(item.get("date", "")).strip()
            if not event_name or event_date not in index_by_date:
                continue
            age_days = max(0, last_idx - int(index_by_date[event_date]))
            previous = out.get(event_name)
            if previous is None or age_days < previous:
                out[event_name] = age_days
        return out

    @classmethod
    def _calculate_phase_context_score(
        cls,
        *,
        events: list[str],
        risk_events: list[str],
        event_age_days: dict[str, int] | None = None,
    ) -> float:
        normalized_age = event_age_days or {}
        event_set = {str(item).strip() for item in [*events, *risk_events] if str(item).strip()}
        if not event_set:
            return 45.0

        score = 68.0
        for event_name in sorted(event_set):
            prerequisites = WYCKOFF_PREREQUISITE_MAP.get(event_name)
            if not prerequisites:
                continue
            matched = [
                ref
                for ref in prerequisites
                if ref in event_set and int(normalized_age.get(ref, EVENT_DECAY_MAX_AGE_DAYS)) <= 35
            ]
            if not matched:
                score -= 14.0
            elif len(matched) == 1:
                score += 3.0
            else:
                score += 6.0

        if {"SOS", "JOC", "LPS"} & event_set and not ({"SC", "AR", "ST", "Spring", "TSO"} & event_set):
            score -= 18.0
        if {"UTAD", "SOW", "LPSY"} & event_set and not ({"PSY", "BC", "AR(d)", "ST(d)"} & event_set):
            score -= 10.0

        stale_penalty = 0.0
        for event_name in event_set:
            age_days = int(normalized_age.get(event_name, EVENT_DECAY_MAX_AGE_DAYS))
            if age_days > 30:
                stale_penalty += min(10.0, float(age_days - 30) * 0.5)
        score -= stale_penalty
        return cls.clamp_score(score)

    @classmethod
    def _calculate_event_recency_score(
        cls,
        *,
        events: list[str],
        risk_events: list[str],
        event_age_days: dict[str, int] | None = None,
    ) -> float:
        names = [str(item).strip() for item in [*events, *risk_events] if str(item).strip()]
        if not names:
            return 40.0
        normalized_age = event_age_days or {}
        weights = [
            cls._event_decay_weight(name, int(normalized_age.get(name, EVENT_DECAY_MAX_AGE_DAYS)))
            for name in names
        ]
        return cls.clamp_score(cls.safe_mean(weights) * 100.0)

    @staticmethod
    def _parse_trading_date(text: str) -> datetime | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d")
        except Exception:
            return None

    @classmethod
    def _weekday_adjusted_volume_baseline(
        cls,
        *,
        volumes: list[int],
        dates: list[str],
        idx: int,
        window: int = VOLUME_CALENDAR_BASE_LOOKBACK,
    ) -> float:
        if idx < 0 or idx >= len(volumes):
            return 1.0
        recent_left = max(0, int(idx) - max(5, int(window)))
        recent_samples = [float(volumes[pos]) for pos in range(recent_left, idx)]
        if not recent_samples:
            return max(1.0, float(volumes[idx]))
        ma_base = max(1.0, cls.safe_mean(recent_samples))

        weekday_base = 0.0
        target_dt = cls._parse_trading_date(dates[idx] if idx < len(dates) else "")
        if target_dt is not None:
            target_weekday = target_dt.weekday()
            ext_left = max(0, idx - max(window * 3, VOLUME_CALENDAR_EXT_LOOKBACK))
            weekday_samples: list[float] = []
            for pos in range(ext_left, idx):
                probe_dt = cls._parse_trading_date(dates[pos] if pos < len(dates) else "")
                if probe_dt is None or probe_dt.weekday() != target_weekday:
                    continue
                weekday_samples.append(float(volumes[pos]))
            if weekday_samples:
                weekday_base = cls.safe_mean(weekday_samples[-8:])

        baseline = ma_base if weekday_base <= 0 else ma_base * 0.55 + weekday_base * 0.45

        # Long holiday windows tend to produce artificial volume spikes.
        if idx > 0 and idx < len(dates):
            current_dt = cls._parse_trading_date(dates[idx])
            previous_dt = cls._parse_trading_date(dates[idx - 1])
            if current_dt is not None and previous_dt is not None:
                gap_days = (current_dt - previous_dt).days
                if gap_days > 4:
                    baseline *= min(1.35, 1.0 + float(gap_days - 4) * 0.045)

        return max(1.0, float(baseline))

    @classmethod
    def _volume_ratio_with_calendar_adjustment(
        cls,
        *,
        volumes: list[int],
        dates: list[str],
        idx: int,
        window: int = VOLUME_CALENDAR_BASE_LOOKBACK,
    ) -> float:
        if idx < 0 or idx >= len(volumes):
            return 0.0
        baseline = cls._weekday_adjusted_volume_baseline(
            volumes=volumes,
            dates=dates,
            idx=idx,
            window=window,
        )
        ratio = float(volumes[idx]) / max(1.0, baseline)

        short_left = max(0, idx - max(8, window))
        short_samples = [float(volumes[pos]) for pos in range(short_left, idx)]
        if len(short_samples) >= 8:
            z_mean = cls.safe_mean(short_samples)
            z_std = max(1.0, cls.safe_std(short_samples))
            zscore = (float(volumes[idx]) - z_mean) / z_std
            if zscore >= 2.5:
                ratio *= 0.92
            elif zscore <= -2.0:
                ratio *= 1.05
        return max(0.0, float(ratio))

    @staticmethod
    def _candle_shape_metrics(
        *,
        idx: int,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> tuple[float, float, float, float]:
        if idx < 0 or idx >= len(opens):
            return 0.0, 0.0, 0.0, 0.0
        open_px = float(opens[idx])
        high_px = float(highs[idx])
        low_px = float(lows[idx])
        close_px = float(closes[idx])
        candle_range = max(high_px - low_px, 0.01)
        body_ratio = abs(close_px - open_px) / candle_range
        upper_shadow_ratio = max(0.0, high_px - max(open_px, close_px)) / candle_range
        lower_shadow_ratio = max(0.0, min(open_px, close_px) - low_px) / candle_range
        close_location = (close_px - low_px) / candle_range
        return body_ratio, upper_shadow_ratio, lower_shadow_ratio, close_location

    @classmethod
    def _event_candle_quality_score(
        cls,
        *,
        event_name: str,
        idx: int,
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> float:
        body_ratio, upper_shadow_ratio, lower_shadow_ratio, close_location = cls._candle_shape_metrics(
            idx=idx,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
        )
        open_px = float(opens[idx]) if 0 <= idx < len(opens) else 0.0
        close_px = float(closes[idx]) if 0 <= idx < len(closes) else 0.0
        is_bull = close_px >= open_px

        event_text = str(event_name).strip()
        if event_text in set(WYCKOFF_RISK_EVENTS):
            score = (
                40.0
                + body_ratio * 12.0
                + upper_shadow_ratio * 34.0
                + (1.0 - close_location) * 28.0
                + lower_shadow_ratio * 8.0
            )
            score += 6.0 if not is_bull else -4.0
            return cls.clamp_score(score)

        score = (
            36.0
            + body_ratio * 24.0
            + close_location * 30.0
            + (1.0 - upper_shadow_ratio) * 16.0
        )
        score += 6.0 if is_bull else -4.0
        if event_text in {"Spring", "SC", "ST", "TSO"}:
            score += lower_shadow_ratio * 10.0
        if event_text in {"SOS", "JOC", "LPS"}:
            score += body_ratio * 10.0
            score -= lower_shadow_ratio * 4.0
        return cls.clamp_score(score)

    @classmethod
    def _calculate_candle_quality_score(
        cls,
        *,
        events: list[str],
        risk_events: list[str],
        event_dates: dict[str, str],
        dates: list[str],
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> float:
        if not dates:
            return 45.0
        index_by_date = {str(day): idx for idx, day in enumerate(dates)}
        last_idx = len(dates) - 1
        weighted_scores: list[float] = []
        weights: list[float] = []
        for event_name in [*events, *risk_events]:
            event_text = str(event_name).strip()
            if not event_text:
                continue
            event_date = str(event_dates.get(event_text, "")).strip()
            idx = index_by_date.get(event_date)
            if idx is None:
                continue
            age_days = max(0, last_idx - int(idx))
            decay_weight = max(0.1, cls._event_decay_weight(event_text, age_days))
            if event_text in set(WYCKOFF_RISK_EVENTS):
                decay_weight *= 1.1
            score = cls._event_candle_quality_score(
                event_name=event_text,
                idx=int(idx),
                opens=opens,
                highs=highs,
                lows=lows,
                closes=closes,
            )
            weighted_scores.append(score * decay_weight)
            weights.append(decay_weight)
        if not weights:
            return 45.0
        return cls.clamp_score(sum(weighted_scores) / max(sum(weights), 0.01))

    @staticmethod
    def _ema(values: list[float], window: int) -> list[float]:
        if not values:
            return []
        span = max(1, int(window))
        alpha = 2.0 / (float(span) + 1.0)
        out: list[float] = []
        prev = float(values[0])
        out.append(prev)
        for value in values[1:]:
            prev = alpha * float(value) + (1.0 - alpha) * prev
            out.append(prev)
        return out

    @classmethod
    def _calculate_cost_center_shift_score(
        cls,
        *,
        closes: list[float],
        volumes: list[int],
        row: ScreenerResult,
    ) -> float:
        if len(closes) < 10 or len(closes) != len(volumes):
            return 45.0

        weighted_price = [float(close_px) * max(0.0, float(vol)) for close_px, vol in zip(closes, volumes)]
        ema_weighted = cls._ema(weighted_price, COST_CENTER_EMA_WINDOW)
        ema_volume = cls._ema([max(0.0, float(vol)) for vol in volumes], COST_CENTER_EMA_WINDOW)
        cost_center_series: list[float] = []
        for idx in range(len(closes)):
            denom = max(ema_volume[idx], 1.0)
            cost_center_series.append(float(ema_weighted[idx]) / denom)

        lookback = min(10, len(cost_center_series) - 1)
        base_idx = len(cost_center_series) - 1 - lookback
        latest_idx = len(cost_center_series) - 1
        base_cost = max(abs(float(cost_center_series[base_idx])), 0.01)
        base_price = max(abs(float(closes[base_idx])), 0.01)

        cost_shift = (float(cost_center_series[latest_idx]) - float(cost_center_series[base_idx])) / base_cost
        price_shift = (float(closes[latest_idx]) - float(closes[base_idx])) / base_price
        divergence = float(price_shift - cost_shift)

        spread_series: list[float] = []
        for idx in range(base_idx, latest_idx + 1):
            close_px = max(float(closes[idx]), 0.01)
            spread_series.append((float(closes[idx]) - float(cost_center_series[idx])) / close_px)
        spread_std = cls.safe_std(spread_series)

        score = (
            56.0
            + cost_shift * 210.0
            - max(0.0, divergence) * 175.0
            - max(0.0, float(row.retrace20) - 0.15) * 80.0
            - spread_std * 180.0
        )
        return cls.clamp_score(score)

    @classmethod
    def _calculate_weekly_context_metrics(
        cls,
        *,
        dates: list[str],
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[int],
    ) -> tuple[float, float]:
        if not dates or len(dates) < 15:
            return 50.0, 1.0

        weekly_rows: list[dict[str, float | int | str]] = []
        current_week_key = ""
        current: dict[str, float | int | str] | None = None

        for idx, day_text in enumerate(dates):
            dt = cls._parse_trading_date(day_text)
            if dt is None:
                continue
            week_info = dt.isocalendar()
            week_key = f"{week_info.year:04d}-{int(week_info.week):02d}"
            if week_key != current_week_key:
                if current is not None:
                    weekly_rows.append(current)
                current_week_key = week_key
                current = {
                    "week": week_key,
                    "open": float(opens[idx]),
                    "high": float(highs[idx]),
                    "low": float(lows[idx]),
                    "close": float(closes[idx]),
                    "volume": max(0.0, float(volumes[idx])),
                }
            else:
                if current is None:
                    continue
                current["high"] = max(float(current["high"]), float(highs[idx]))
                current["low"] = min(float(current["low"]), float(lows[idx]))
                current["close"] = float(closes[idx])
                current["volume"] = float(current["volume"]) + max(0.0, float(volumes[idx]))
        if current is not None:
            weekly_rows.append(current)

        if len(weekly_rows) < 4:
            return 50.0, 1.0

        weekly_closes = [float(item["close"]) for item in weekly_rows]
        weekly_highs = [float(item["high"]) for item in weekly_rows]
        weekly_lows = [float(item["low"]) for item in weekly_rows]

        fast_window = min(5, len(weekly_closes))
        slow_window = min(10, len(weekly_closes))
        weekly_ma_fast = cls.safe_mean(weekly_closes[-fast_window:])
        weekly_ma_slow = cls.safe_mean(weekly_closes[-slow_window:])
        latest_close = float(weekly_closes[-1])
        base_idx = max(0, len(weekly_closes) - 5)
        base_close = max(float(weekly_closes[base_idx]), 0.01)
        weekly_ret = (latest_close - float(weekly_closes[base_idx])) / base_close

        range_window = min(20, len(weekly_highs))
        recent_high = max(weekly_highs[-range_window:])
        recent_low = min(weekly_lows[-range_window:])
        weekly_pos = (latest_close - recent_low) / max(recent_high - recent_low, 0.01)

        score = 50.0
        score += 10.0 if latest_close > weekly_ma_fast else -8.0
        score += 12.0 if weekly_ma_fast > weekly_ma_slow else -10.0
        score += weekly_ret * 120.0
        score += (weekly_pos - 0.5) * 30.0
        score -= max(0.0, 0.35 - weekly_pos) * 40.0
        weekly_context_score = cls.clamp_score(score)
        weekly_multiplier = max(0.85, min(1.15, 0.88 + weekly_context_score / 100.0 * 0.24))
        return weekly_context_score, weekly_multiplier

    @classmethod
    def calculate_wyckoff_snapshot(
        cls,
        row: ScreenerResult,
        candles: list[CandlePoint],
        window_days: int,
    ) -> dict:
        """
        Calculate Wyckoff analysis snapshot for a stock.

        This is a comprehensive method that analyzes price and volume patterns
        to detect accumulation and distribution signals.

        Args:
            row: Screener result with stock metrics
            candles: List of candlestick data points
            window_days: Number of days to analyze

        Returns:
            Dictionary with events, scores, phase, and signal information
        """
        if len(candles) < 25:
            return cls._insufficient_data_snapshot(candles)

        window = max(20, min(window_days, len(candles)))
        segment = candles[-window:]

        # Extract price and volume data
        dates = [point.time for point in segment]
        opens = [point.open for point in segment]
        highs = [point.high for point in segment]
        lows = [point.low for point in segment]
        closes = [point.close for point in segment]
        volumes = [max(0, int(point.volume)) for point in segment]

        # Pass opens to event detection
        opens_list = opens  # For use in event detection

        # Calculate key metrics
        latest_close = closes[-1]
        latest_high = highs[-1]
        latest_low = lows[-1]
        tr_high = max(highs)
        tr_low = min(lows)
        tr_width = max(tr_high - tr_low, 0.01)
        tr_pos = (latest_close - tr_low) / tr_width

        # Volume metrics
        avg_v5 = cls.safe_mean(volumes[-5:])
        avg_v10 = cls.safe_mean(volumes[-10:])
        avg_v20 = cls.safe_mean(volumes[-20:])

        # Price metrics
        ma20 = cls.safe_mean(closes[-20:])
        ret10 = (latest_close - closes[-11]) / max(closes[-11], 0.01) if len(closes) > 10 else 0.0
        ret20 = (latest_close - closes[-21]) / max(closes[-21], 0.01) if len(closes) > 20 else ret10

        # Detect events
        event_dates, event_chain = cls._detect_wyckoff_events(
            highs, lows, closes, volumes, dates, ma20, avg_v5, avg_v20, row, tr_pos, ret10, opens_list
        )
        event_confirmation_map = cls._evaluate_event_confirmation_map(
            event_dates=event_dates,
            dates=dates,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
        )

        # Categorize events
        events = [event for event in WYCKOFF_ACC_EVENTS if event in event_dates]
        risk_events = [event for event in WYCKOFF_RISK_EVENTS if event in event_dates]

        # Check sequence validity
        ordered_events = sorted(
            event_chain,
            key=lambda item: (
                str(item.get("date", "")),
                WYCKOFF_EVENT_ORDER.index(str(item.get("event", "")))
                if str(item.get("event", "")) in WYCKOFF_EVENT_ORDER
                else len(WYCKOFF_EVENT_ORDER),
            ),
        )
        sequence = [str(item["event"]) for item in ordered_events if str(item.get("event", "")) in WYCKOFF_ACC_EVENTS]
        sequence_ok = cls.is_subsequence(sequence, WYCKOFF_ACC_EVENTS)
        event_age_days = cls._build_event_age_days(dates=dates, event_chain=ordered_events)
        phase_context_score = cls._calculate_phase_context_score(
            events=events,
            risk_events=risk_events,
            event_age_days=event_age_days,
        )

        # Analyze structure (HH/HL/HC)
        structure_hhh = cls._analyze_structure(highs, lows, closes)

        # Determine phase
        phase = cls._determine_phase(events, risk_events, ret20, ma20, row)

        # Trend health diagnostics (M2)
        health_metrics = cls._calculate_health_metrics(
            closes=closes,
            highs=highs,
            lows=lows,
            ma20=ma20,
            row=row,
        )
        candle_quality_score = cls._calculate_candle_quality_score(
            events=events,
            risk_events=risk_events,
            event_dates=event_dates,
            dates=dates,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
        )
        cost_center_shift_score = cls._calculate_cost_center_shift_score(
            closes=closes,
            volumes=volumes,
            row=row,
        )
        weekly_context_score, weekly_context_multiplier = cls._calculate_weekly_context_metrics(
            dates=dates,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
        )

        # Calculate scores
        scores = cls._calculate_scores(
            phase=phase,
            events=events,
            risk_events=risk_events,
            structure_hhh=structure_hhh,
            row=row,
            ret20=ret20,
            ret10=ret10,
            tr_pos=tr_pos,
            sequence_ok=sequence_ok,
            health_metrics=health_metrics,
            event_age_days=event_age_days,
            phase_context_score=phase_context_score,
            candle_quality_score=candle_quality_score,
            cost_center_shift_score=cost_center_shift_score,
            weekly_context_score=weekly_context_score,
            weekly_context_multiplier=weekly_context_multiplier,
            event_confirmation_map=event_confirmation_map,
        )

        # Determine primary signal
        wyckoff_signal = cls._resolve_primary_signal(event_dates)
        trigger_date = event_dates.get(wyckoff_signal, dates[-1])

        return {
            "events": events,
            "risk_events": risk_events,
            "event_dates": event_dates,
            "event_chain": event_chain,
            "phase": phase,
            "phase_hint": cls.phase_hint(phase),
            "signal": wyckoff_signal,
            "structure_hhh": structure_hhh,
            "sequence_ok": sequence_ok,
            "event_confirmation_map": event_confirmation_map,
            "phase_context_score": round(float(phase_context_score), 2),
            "trigger_date": trigger_date,
            **scores,
        }

    @classmethod
    def _evaluate_event_confirmation_map(
        cls,
        *,
        event_dates: dict[str, str],
        dates: list[str],
        opens: list[float],
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[int],
    ) -> dict[str, str]:
        index_by_date = {str(day): idx for idx, day in enumerate(dates)}
        last_idx = len(dates) - 1
        if last_idx < 0:
            return {}

        def ma_at(idx: int, window: int = 20) -> float:
            if idx < 0:
                return 0.0
            start = max(0, idx - window + 1)
            return cls.safe_mean(closes[start:idx + 1])

        def prior_high_at(idx: int, lookback: int = 20) -> float:
            start = max(0, idx - lookback)
            if start >= idx:
                return highs[idx]
            return max(highs[start:idx])

        def vol_avg_at(idx: int, window: int = 5) -> float:
            if idx <= 0:
                return float(volumes[idx]) if 0 <= idx < len(volumes) else 0.0
            start = max(0, idx - window)
            return cls.safe_mean(volumes[start:idx])

        out: dict[str, str] = {}
        for event_name in WYCKOFF_KEY_CONFIRM_EVENTS:
            event_day = str(event_dates.get(event_name, "")).strip()
            idx = index_by_date.get(event_day)
            if idx is None:
                continue
            if idx >= last_idx:
                out[event_name] = "pending"
                continue

            if event_name == "SOS":
                breakout_level = max(prior_high_at(idx, 20), ma_at(idx, 20))
                end = min(last_idx, idx + 3)
                future_closes = closes[idx + 1 : end + 1]
                if not future_closes:
                    out[event_name] = "pending"
                    continue
                holds = min(future_closes) >= breakout_level * 0.995
                out[event_name] = "confirmed" if holds else "failed"
                continue

            if event_name == "Spring":
                next_idx = idx + 1
                if next_idx > last_idx:
                    out[event_name] = "pending"
                    continue
                not_break_low = lows[next_idx] >= lows[idx] * 0.997
                bullish_confirm = closes[next_idx] >= max(opens[next_idx], closes[idx] * 0.998)
                out[event_name] = "confirmed" if (not_break_low and bullish_confirm) else "failed"
                continue

            if event_name == "JOC":
                breakout_level = prior_high_at(idx, 20)
                end = min(last_idx, idx + 2)
                future_closes = closes[idx + 1 : end + 1]
                if not future_closes:
                    out[event_name] = "pending"
                    continue
                no_fast_fail = min(future_closes) >= breakout_level * 0.99
                out[event_name] = "confirmed" if no_fast_fail else "failed"
                continue

            if event_name == "LPS":
                end = min(last_idx, idx + 2)
                prev_vol = max(1.0, float(vol_avg_at(idx, 5)))
                vol_shrink = float(volumes[idx]) <= prev_vol * 0.95
                bullish_reversal = False
                for probe in range(idx, end + 1):
                    if closes[probe] >= opens[probe] * 1.002 and closes[probe] >= ma_at(probe, 20) * 0.995:
                        bullish_reversal = True
                        break
                out[event_name] = "confirmed" if (vol_shrink and bullish_reversal) else "failed"
                continue

        return out

    @classmethod
    def _insufficient_data_snapshot(cls, candles: list[CandlePoint]) -> dict:
        """Return snapshot for insufficient data case."""
        fallback_date = candles[-1].time if candles else ""
        return {
            "events": [],
            "risk_events": [],
            "event_dates": {},
            "event_chain": [],
            "phase": "\u9636\u6bb5\u672a\u660e",
            "phase_hint": cls.phase_hint("\u9636\u6bb5\u672a\u660e"),
            "signal": "",
            "structure_hhh": "-",
            "sequence_ok": False,
            "event_confirmation_map": {},
            "event_strength_score": 0.0,
            "phase_score": 45.0,
            "structure_score": 0.0,
            "trend_score": 0.0,
            "volatility_score": 0.0,
            "health_score": 0.0,
            "slope_stability": 0.0,
            "volatility_stability": 0.0,
            "pullback_quality": 0.0,
            "event_score": 0.0,
            "event_grade": "C",
            "event_background_score": 0.0,
            "event_position_score": 0.0,
            "event_vol_price_score": 0.0,
            "event_confirmation_score": 0.0,
            "event_recency_score": 0.0,
            "phase_context_score": 0.0,
            "candle_quality_score": 0.0,
            "cost_center_shift_score": 0.0,
            "weekly_context_score": 0.0,
            "weekly_context_multiplier": 1.0,
            "risk_score": 0.0,
            "confirmation_status": "unconfirmed",
            "event_grade_map": {},
            "entry_quality_score": 0.0,
            "trigger_date": fallback_date,
        }
    @classmethod
    def _detect_wyckoff_events(
        cls,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[int],
        dates: list[str],
        ma20: float,
        avg_v5: float,
        avg_v20: float,
        row: ScreenerResult,
        tr_pos: float,
        ret10: float,
        opens: list[float],
    ) -> tuple[dict[str, str], list[dict[str, str]]]:
        """Detect Wyckoff events from price and volume data."""
        event_dates: dict[str, str] = {}
        event_chain: list[dict[str, str]] = []
        last_idx = len(dates) - 1
        if last_idx < 0:
            return event_dates, event_chain

        def ma_at(idx: int, window: int = 20) -> float:
            start = max(0, idx - window + 1)
            return cls.safe_mean(closes[start:idx + 1])

        def vol_avg_at(idx: int, window: int = 20) -> float:
            if idx < 0:
                return 0.0
            start = max(0, idx - window + 1)
            return cls.safe_mean(volumes[start:idx + 1])

        def vol_ratio_at(idx: int, window: int = 20) -> float:
            return cls._volume_ratio_with_calendar_adjustment(
                volumes=volumes,
                dates=dates,
                idx=idx,
                window=window,
            )

        def ret_at(idx: int, lookback: int = 10) -> float:
            start = max(0, idx - lookback)
            return (closes[idx] - closes[start]) / max(closes[start], 0.01)

        def tr_pos_at(idx: int, lookback: int = 40) -> float:
            start = max(0, idx - lookback + 1)
            segment_high = max(highs[start:idx + 1])
            segment_low = min(lows[start:idx + 1])
            width = max(segment_high - segment_low, 0.01)
            return (closes[idx] - segment_low) / width

        def prior_high_at(idx: int, lookback: int = 20) -> float:
            start = max(0, idx - lookback)
            if start >= idx:
                return highs[idx]
            return max(highs[start:idx])

        def prior_low_at(idx: int, lookback: int = 20) -> float:
            start = max(0, idx - lookback)
            if start >= idx:
                return lows[idx]
            return min(lows[start:idx])

        def upper_shadow_ratio_at(idx: int) -> float:
            body_high = max(opens[idx], closes[idx])
            candle_range = max(highs[idx] - lows[idx], 0.01)
            return (highs[idx] - body_high) / candle_range

        def latest_index_where(start_idx: int, end_idx: int, predicate: Callable[[int], bool]) -> int | None:
            if end_idx < start_idx:
                return None
            left = max(0, start_idx)
            right = min(last_idx, end_idx)
            for idx in range(right, left - 1, -1):
                if predicate(idx):
                    return idx
            return None

        def first_index_where(start_idx: int, end_idx: int, predicate: Callable[[int], bool]) -> int | None:
            if end_idx < start_idx:
                return None
            left = max(0, start_idx)
            right = min(last_idx, end_idx)
            for idx in range(left, right + 1):
                if predicate(idx):
                    return idx
            return None

        def push_event(
            name: str,
            condition: bool,
            idx: int | None = None,
            *,
            category: str = "accumulation",
        ) -> None:
            if not condition:
                return
            target_idx = len(dates) - 1 if idx is None else max(0, min(idx, len(dates) - 1))
            event_date = dates[target_idx]
            event_dates[name] = event_date
            event_chain.append({
                "event": name,
                "date": event_date,
                "category": category,
            })

        lookback_start = max(0, last_idx - 40)

        # SC anchor: prefer high-volume, low-position climax-like bars in the recent window.
        look_sc_start = max(0, len(closes) - 35)
        sc_idx = latest_index_where(
            look_sc_start,
            last_idx,
            lambda idx: (
                tr_pos_at(idx) <= 0.45
                and closes[idx] <= opens[idx] * 1.02
                and vol_ratio_at(idx, 20) >= 1.2
            ),
        )
        if sc_idx is None:
            sc_idx = look_sc_start + max(
                range(len(volumes[look_sc_start:])),
                key=lambda idx: volumes[look_sc_start + idx],
            )
        sc_range = max(highs[sc_idx] - lows[sc_idx], 0.01)
        sc_close_near_low = closes[sc_idx] <= lows[sc_idx] + sc_range * 0.38
        sc_condition = sc_close_near_low and tr_pos_at(sc_idx) <= 0.55 and vol_ratio_at(sc_idx, 20) >= 1.05
        push_event("SC", sc_condition, sc_idx)

        # PS / SC / AR / ST (Accumulation Phase A)
        ps_idx = latest_index_where(
            max(0, sc_idx - 25),
            max(0, sc_idx - 1),
            lambda idx: tr_pos_at(idx) <= 0.42 and vol_ratio_at(idx, 20) >= 1.08 and closes[idx] <= ma_at(idx) * 1.02,
        )
        push_event("PS", ps_idx is not None, ps_idx)

        ar_idx: int | None = None
        if "SC" in event_dates and sc_idx < last_idx - 1:
            rebound_scan_end = min(last_idx, sc_idx + 18)
            rebound_slice = closes[sc_idx + 1:rebound_scan_end + 1]
            rebound_max = max(rebound_slice) if rebound_slice else closes[sc_idx]
            if rebound_max >= closes[sc_idx] * 1.05:
                ar_idx = sc_idx + rebound_slice.index(rebound_max) + 1
                push_event("AR", True, ar_idx)

        st_idx: int | None = None
        if "SC" in event_dates and sc_idx < last_idx:
            sc_low = lows[sc_idx]
            st_start = (ar_idx + 1) if ar_idx is not None else (sc_idx + 2)
            st_end = min(last_idx, (ar_idx + 12) if ar_idx is not None else (sc_idx + 18))
            for idx in range(st_start, st_end + 1):
                near_sc_low = abs(lows[idx] - sc_low) / max(sc_low, 0.01) <= 0.04
                lower_volume = volumes[idx] <= volumes[sc_idx] * 0.85
                if near_sc_low and lower_volume:
                    st_idx = idx
                    break
            push_event("ST", st_idx is not None, st_idx)

        # TSO / Spring / SOS / JOC / LPS (Accumulation Phases B-E)
        pattern_seed = max([idx for idx in (st_idx, ar_idx, sc_idx) if idx is not None], default=lookback_start)
        pattern_start = max(1, pattern_seed + 1)
        pattern_end = min(last_idx, pattern_start + 28)
        spring_idx = first_index_where(
            pattern_start,
            min(last_idx, pattern_end + 8),
            lambda idx: (
                lows[idx] < prior_low_at(idx, 20) * 0.985
                and closes[idx] > prior_low_at(idx, 20)
                and vol_ratio_at(idx, 20) >= 1.15
            ),
        )
        tso_end = (spring_idx - 1) if spring_idx is not None else pattern_end
        tso_idx = first_index_where(
            pattern_start,
            tso_end,
            lambda idx: (
                lows[idx] < prior_low_at(idx, 20) * 0.99
                and closes[idx] > prior_low_at(idx, 20)
                and vol_ratio_at(idx, 20) >= 1.0
            ),
        )
        push_event(
            "TSO",
            tso_idx is not None,
            tso_idx,
        )

        push_event(
            "Spring",
            spring_idx is not None,
            spring_idx,
        )

        base_idx = max(
            [idx for idx in (spring_idx, tso_idx, st_idx, ar_idx, sc_idx) if idx is not None],
            default=lookback_start,
        )
        signal_start = max(lookback_start, base_idx + 1)
        sos_idx = first_index_where(
            signal_start,
            last_idx,
            lambda idx: (
                closes[idx] > ma_at(idx) * 1.01
                and ret_at(idx, 10) > 0.05
                and vol_ratio_at(idx, 20) >= 1.05
            ),
        )
        push_event(
            "SOS",
            sos_idx is not None,
            sos_idx,
        )

        joc_start = max(signal_start, (sos_idx + 1) if sos_idx is not None else signal_start)
        joc_idx = first_index_where(
            joc_start,
            last_idx,
            lambda idx: idx > 0 and closes[idx] >= prior_high_at(idx, 20) * 1.005 and vol_ratio_at(idx, 20) >= 1.2,
        )
        push_event(
            "JOC",
            joc_idx is not None,
            joc_idx,
        )

        lps_idx: int | None = None
        lps_anchor_idx = max([idx for idx in (sos_idx, joc_idx) if idx is not None], default=-1)
        if lps_anchor_idx >= 0 and lps_anchor_idx < last_idx:
            lps_end = min(last_idx, lps_anchor_idx + 12)
            lps_idx = first_index_where(
                lps_anchor_idx + 1,
                lps_end,
                lambda idx: (
                    closes[idx] > ma_at(idx) * 0.995
                    and volumes[idx] <= max(vol_avg_at(idx - 1, 5), 1.0) * 0.95
                    and (idx - lps_anchor_idx) <= 6
                ),
            )
        push_event(
            "LPS",
            lps_idx is not None,
            lps_idx,
        )

        # Distribution early events: PSY / BC / AR(d) / ST(d)
        look_bc_start = max(0, len(closes) - 35)
        bc_idx = latest_index_where(
            look_bc_start,
            last_idx,
            lambda idx: (
                tr_pos_at(idx) >= 0.62
                and closes[idx] >= opens[idx] * 0.98
                and vol_ratio_at(idx, 20) >= 1.2
                and highs[idx] >= prior_high_at(idx, 20) * 0.995
            ),
        )
        if bc_idx is None:
            bc_idx = look_bc_start + max(
                range(len(volumes[look_bc_start:])),
                key=lambda idx: volumes[look_bc_start + idx],
            )
        bc_range = max(highs[bc_idx] - lows[bc_idx], 0.01)
        bc_close_near_high = closes[bc_idx] >= highs[bc_idx] - bc_range * 0.32
        bc_condition = (
            bc_close_near_high
            and tr_pos_at(bc_idx) >= 0.58
            and vol_ratio_at(bc_idx, 20) >= 1.05
            and highs[bc_idx] >= max(highs[max(0, bc_idx - 20):bc_idx + 1]) * 0.995
        )

        psy_idx = first_index_where(
            max(0, bc_idx - 20),
            max(0, bc_idx - 1),
            lambda idx: tr_pos_at(idx) >= 0.62 and vol_ratio_at(idx, 20) >= 1.05 and closes[idx] >= ma_at(idx) * 0.98,
        ) if bc_idx > 0 else None
        push_event("PSY", psy_idx is not None, psy_idx, category="distributionRisk")

        push_event("BC", bc_condition, bc_idx, category="distributionRisk")

        ar_d_idx: int | None = None
        if "BC" in event_dates and bc_idx < last_idx - 1:
            decline_scan_end = min(last_idx, bc_idx + 18)
            decline_slice = closes[bc_idx + 1:decline_scan_end + 1]
            decline_min = min(decline_slice) if decline_slice else closes[bc_idx]
            if decline_min <= closes[bc_idx] * 0.94:
                ar_d_idx = bc_idx + decline_slice.index(decline_min) + 1
                push_event("AR(d)", True, ar_d_idx, category="distributionRisk")

        st_d_idx: int | None = None
        if "BC" in event_dates and bc_idx < last_idx:
            bc_high = highs[bc_idx]
            st_d_start = (ar_d_idx + 1) if ar_d_idx is not None else (bc_idx + 2)
            st_d_end = min(last_idx, bc_idx + 24)
            for idx in range(st_d_start, st_d_end + 1):
                near_bc_high = abs(highs[idx] - bc_high) / max(bc_high, 0.01) <= 0.04
                lower_volume = volumes[idx] <= volumes[bc_idx] * 0.9
                close_weak = closes[idx] <= highs[idx] * 0.985
                if near_bc_high and lower_volume and close_weak:
                    st_d_idx = idx
                    break
            push_event("ST(d)", st_d_idx is not None, st_d_idx, category="distributionRisk")

        # Risk-side events (Distribution)
        utad_start = max(
            lookback_start,
            (st_d_idx + 1) if "ST(d)" in event_dates and st_d_idx is not None else (bc_idx + 1),
        )
        utad_idx = first_index_where(
            utad_start,
            last_idx,
            lambda idx: (
                idx > 0
                and highs[idx] >= prior_high_at(idx, 20) * 1.01
                and closes[idx] < prior_high_at(idx, 20)
                and upper_shadow_ratio_at(idx) >= 0.5
                and vol_ratio_at(idx, 20) >= 1.2
            ),
        )
        push_event(
            "UTAD",
            utad_idx is not None,
            utad_idx,
            category="distributionRisk",
        )

        sow_start = max(
            lookback_start,
            (utad_idx + 1) if utad_idx is not None else ((ar_d_idx + 1) if ar_d_idx is not None else (bc_idx + 1)),
        )
        sow_idx = first_index_where(
            sow_start,
            last_idx,
            lambda idx: ret_at(idx, 10) <= -0.05 and closes[idx] < ma_at(idx) * 0.995 and vol_ratio_at(idx, 20) >= 1.1,
        )
        push_event(
            "SOW",
            sow_idx is not None,
            sow_idx,
            category="distributionRisk",
        )

        lpsy_anchor_idx = max([idx for idx in (sow_idx, utad_idx) if idx is not None], default=-1)
        lpsy_idx: int | None = None
        if lpsy_anchor_idx >= 0 and lpsy_anchor_idx < last_idx:
            lpsy_end = min(last_idx, lpsy_anchor_idx + 16)
            lpsy_idx = first_index_where(
                lpsy_anchor_idx + 1,
                lpsy_end,
                lambda idx: (
                    closes[idx] < ma_at(idx)
                    and max(highs[max(0, idx - 4):idx + 1])
                    <= max(highs[max(0, idx - 9):max(0, idx - 4)] or highs[max(0, idx - 4):idx + 1]) * 0.99
                ),
            )
        push_event(
            "LPSY",
            lpsy_idx is not None,
            lpsy_idx,
            category="distributionRisk",
        )

        event_chain.sort(
            key=lambda item: (
                str(item.get("date", "")),
                WYCKOFF_EVENT_ORDER.index(str(item.get("event", "")))
                if str(item.get("event", "")) in WYCKOFF_EVENT_ORDER
                else len(WYCKOFF_EVENT_ORDER),
            )
        )
        return event_dates, event_chain

    @classmethod
    def _analyze_structure(cls, highs: list[float], lows: list[float], closes: list[float]) -> str:
        """Analyze price structure (Higher High, Higher Low, Higher Close)."""
        latest_high = highs[-1]
        latest_low = lows[-1]

        hh = latest_high >= max(highs[-10:-1]) * 1.003 if len(highs) > 10 else False
        hl = (
            min(lows[-5:]) >= min(lows[-15:-5]) * 1.01
            if len(lows) >= 15
            else latest_low >= min(lows[:-1]) * 1.005
        )
        hc = closes[-1] > closes[-5] > closes[-10] if len(closes) >= 10 else closes[-1] > closes[-2]

        return f"{'HH' if hh else '-'}|{'HL' if hl else '-'}|{'HC' if hc else '-'}"

    @classmethod
    def _determine_phase(
        cls,
        events: list[str],
        risk_events: list[str],
        ret20: float,
        ma20: float,
        row: ScreenerResult,
    ) -> str:
        """Determine the current phase based on events."""
        if risk_events:
            risk_set = set(risk_events)
            if "LPSY" in risk_set and ret20 <= -0.12:
                return "\u6d3e\u53d1D" if ret20 > -0.2 else "\u6d3e\u53d1E"
            if "SOW" in risk_set and "UTAD" in risk_set:
                return "\u6d3e\u53d1C"
            if "SOW" in risk_set:
                return "\u6d3e\u53d1C"
            if "UTAD" in risk_set or "AR(d)" in risk_set or "ST(d)" in risk_set:
                return "\u6d3e\u53d1B"
            return "\u6d3e\u53d1A"
        if "LPS" in events:
            return "\u5438\u7b79E"
        if "JOC" in events or "SOS" in events:
            return "\u5438\u7b79D"
        if "Spring" in events:
            return "\u5438\u7b79C"
        if "ST" in events or "TSO" in events:
            return "\u5438\u7b79B"
        if {"PS", "SC", "AR"} & set(events):
            return "\u5438\u7b79A"
        return "\u9636\u6bb5\u672a\u660e"

    @classmethod
    def _calculate_health_metrics(
        cls,
        *,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        ma20: float,
        row: ScreenerResult,
    ) -> dict[str, float]:
        daily_returns: list[float] = []
        for idx in range(1, len(closes)):
            prev = max(float(closes[idx - 1]), 0.01)
            daily_returns.append((float(closes[idx]) - float(closes[idx - 1])) / prev)
        slope_std = cls.safe_std(daily_returns[-20:])
        slope_stability = cls.clamp_score(100.0 - slope_std * 900.0)

        range_ratios: list[float] = []
        for idx in range(len(closes)):
            close_px = max(float(closes[idx]), 0.01)
            range_ratios.append(max(0.0, float(highs[idx]) - float(lows[idx])) / close_px)
        range_mean = cls.safe_mean(range_ratios[-20:])
        volatility_stability = cls.clamp_score(100.0 - range_mean * 700.0)

        retrace_center = abs(float(row.retrace20) - 0.12)
        retrace_component = cls.clamp_score(100.0 - retrace_center / 0.12 * 100.0)
        ma_hold_bonus = 10.0 if closes[-1] >= ma20 * 0.99 else -10.0
        rebound_bonus = 0.0
        if len(closes) >= 6 and closes[-1] >= closes[-6]:
            rebound_bonus = 8.0
        pullback_quality = cls.clamp_score(25.0 + retrace_component * 0.75 + ma_hold_bonus + rebound_bonus)

        health_score = cls.clamp_score(
            slope_stability * 0.40
            + volatility_stability * 0.35
            + pullback_quality * 0.25
        )
        return {
            "slope_stability": round(slope_stability, 2),
            "volatility_stability": round(volatility_stability, 2),
            "pullback_quality": round(pullback_quality, 2),
            "health_score": round(health_score, 2),
        }

    @classmethod
    def _calculate_scores(
        cls,
        *,
        phase: str,
        events: list[str],
        risk_events: list[str],
        structure_hhh: str,
        row: ScreenerResult,
        ret20: float,
        ret10: float,
        tr_pos: float,
        sequence_ok: bool,
        health_metrics: dict[str, float] | None = None,
        event_age_days: dict[str, int] | None = None,
        phase_context_score: float | None = None,
        candle_quality_score: float | None = None,
        cost_center_shift_score: float | None = None,
        weekly_context_score: float | None = None,
        weekly_context_multiplier: float | None = None,
        event_confirmation_map: dict[str, str] | None = None,
    ) -> dict:
        """Calculate various analysis scores."""
        # Phase score
        phase_scores: dict[str, float] = {
            "\u5438\u7b79A": 58,
            "\u5438\u7b79B": 66,
            "\u5438\u7b79C": 76,
            "\u5438\u7b79D": 86,
            "\u5438\u7b79E": 91,
            "\u6d3e\u53d1A": 36,
            "\u6d3e\u53d1B": 28,
            "\u6d3e\u53d1C": 20,
            "\u6d3e\u53d1D": 14,
            "\u6d3e\u53d1E": 10,
            "\u9636\u6bb5\u672a\u660e": 45,
        }
        phase_score = phase_scores.get(phase, 45)

        # Event strength score
        positive_event_weights = {
            "PS": 5, "SC": 8, "AR": 7, "ST": 6, "TSO": 6,
            "Spring": 10, "SOS": 11, "JOC": 10, "LPS": 10,
        }
        risk_event_penalty = {"PSY": -4, "BC": -6, "AR(d)": -6, "ST(d)": -6, "UTAD": -10, "SOW": -9, "LPSY": -8}
        event_strength_score = 48.0
        normalized_event_age = event_age_days or {}
        for event in events:
            event_strength_score += (
                positive_event_weights.get(event, 0)
                * cls._event_decay_weight(event, int(normalized_event_age.get(event, EVENT_DECAY_MAX_AGE_DAYS)))
            )
        for event in risk_events:
            event_strength_score += (
                risk_event_penalty.get(event, 0)
                * cls._event_decay_weight(event, int(normalized_event_age.get(event, EVENT_DECAY_MAX_AGE_DAYS)))
            )
        event_strength_score = cls.clamp_score(event_strength_score)
        computed_phase_context_score = cls.clamp_score(
            float(
                phase_context_score
                if phase_context_score is not None
                else cls._calculate_phase_context_score(
                    events=events,
                    risk_events=risk_events,
                    event_age_days=normalized_event_age,
                )
            )
        )
        event_recency_score = cls._calculate_event_recency_score(
            events=events,
            risk_events=risk_events,
            event_age_days=normalized_event_age,
        )
        normalized_candle_quality = cls.clamp_score(float(candle_quality_score if candle_quality_score is not None else 45.0))
        normalized_cost_center_shift = cls.clamp_score(
            float(cost_center_shift_score if cost_center_shift_score is not None else 45.0)
        )
        normalized_weekly_context = cls.clamp_score(
            float(weekly_context_score if weekly_context_score is not None else 50.0)
        )
        resolved_weekly_multiplier = float(
            weekly_context_multiplier
            if weekly_context_multiplier is not None
            else max(0.85, min(1.15, 0.88 + normalized_weekly_context / 100.0 * 0.24))
        )
        resolved_weekly_multiplier = max(0.85, min(1.15, resolved_weekly_multiplier))

        phase_background_bonus = {
            "\u5438\u7b79A": 6.0,
            "\u5438\u7b79B": 10.0,
            "\u5438\u7b79C": 14.0,
            "\u5438\u7b79D": 18.0,
            "\u5438\u7b79E": 20.0,
            "\u6d3e\u53d1A": -10.0,
            "\u6d3e\u53d1B": -14.0,
            "\u6d3e\u53d1C": -18.0,
            "\u6d3e\u53d1D": -22.0,
            "\u6d3e\u53d1E": -24.0,
        }
        background_score = cls.clamp_score(
            45.0
            + phase_background_bonus.get(phase, 0.0)
            + float(row.ret40) * 90.0
            - max(0.0, float(row.retrace20) - 0.15) * 180.0
            - len(risk_events) * 6.0
            + (normalized_weekly_context - 50.0) * 0.28
        )
        position_score = cls.clamp_score(100.0 - abs(float(tr_pos) - 0.65) * 120.0)
        vol_price_score = cls.clamp_score(event_strength_score * 0.75 + normalized_cost_center_shift * 0.25)
        risk_score_raw = 0.0
        for event in risk_events:
            risk_weight = abs(float(risk_event_penalty.get(event, -6)))
            risk_score_raw += risk_weight * cls._event_decay_weight(
                event,
                int(normalized_event_age.get(event, EVENT_DECAY_MAX_AGE_DAYS)),
            )
        risk_score_raw += max(0.0, 52.0 - normalized_cost_center_shift) * 0.22
        risk_score = cls.clamp_score(risk_score_raw * 3.0)
        key_confirm_map = event_confirmation_map or {}
        key_confirmed = sum(
            1
            for event_name in events
            if event_name in set(WYCKOFF_KEY_CONFIRM_EVENTS) and str(key_confirm_map.get(event_name, "")) == "confirmed"
        )
        key_pending = sum(
            1
            for event_name in events
            if event_name in set(WYCKOFF_KEY_CONFIRM_EVENTS) and str(key_confirm_map.get(event_name, "")) == "pending"
        )
        key_failed = sum(
            1
            for event_name in events
            if event_name in set(WYCKOFF_KEY_CONFIRM_EVENTS) and str(key_confirm_map.get(event_name, "")) == "failed"
        )
        confirm_bonus = 0.0
        if {"SOS", "JOC", "LPS"} & set(events):
            confirm_bonus += 18.0
        elif events:
            confirm_bonus += 8.0
        confirm_bonus += float(key_confirmed) * 5.0
        confirm_bonus -= float(key_pending) * 4.0
        confirm_bonus -= float(key_failed) * 10.0
        confirmation_score = cls.clamp_score(
            28.0
            + (24.0 if sequence_ok else -12.0)
            + confirm_bonus
            + computed_phase_context_score * 0.20
            + event_recency_score * 0.12
            + normalized_candle_quality * 0.10
            + normalized_weekly_context * 0.08
            + normalized_cost_center_shift * 0.10
            - risk_score * 0.28
        )
        event_score_raw = cls.clamp_score(
            background_score * 0.22
            + position_score * 0.16
            + vol_price_score * 0.18
            + confirmation_score * 0.18
            + computed_phase_context_score * 0.12
            + event_recency_score * 0.08
            + normalized_candle_quality * 0.06
            + normalized_cost_center_shift * 0.04
            + normalized_weekly_context * 0.04
            - risk_score * 0.20
        )
        if key_failed > 0:
            event_score_raw -= min(18.0, float(key_failed) * 8.0)
        if key_pending > 0:
            event_score_raw -= min(10.0, float(key_pending) * 3.5)
        event_score = cls.clamp_score(event_score_raw * resolved_weekly_multiplier)
        event_grade = cls._event_grade_from_score(event_score)

        event_grade_map: dict[str, str] = {}
        event_set = [str(item).strip() for item in [*events, *risk_events] if str(item).strip()]
        for event_name in event_set:
            event_decay = cls._event_decay_weight(
                event_name,
                int(normalized_event_age.get(event_name, EVENT_DECAY_MAX_AGE_DAYS)),
            )
            event_level_score = float(event_score) * (0.6 + event_decay * 0.4)
            if event_name in {"SOS", "JOC", "LPS", "Spring", "TSO"}:
                event_level_score += 6.0
            if event_name in {"PS", "SC", "AR", "ST"}:
                event_level_score -= 4.0
            if event_name in set(risk_events):
                event_level_score -= 12.0
            if event_name in set(WYCKOFF_KEY_CONFIRM_EVENTS):
                status = str(key_confirm_map.get(event_name, "")).strip().lower()
                if status == "failed":
                    event_level_score -= 14.0
                elif status == "pending":
                    event_level_score -= 7.0
            event_grade_map[event_name] = cls._event_grade_from_score(cls.clamp_score(event_level_score))

        # Structure score
        hh, hl, hc = [part != "-" for part in structure_hhh.split("|")]
        structure_score = cls.clamp_score(35 + (22 if hh else 0) + (22 if hl else 0) + (21 if hc else 0))

        # Trend score
        trend_score = cls.clamp_score(50 + row.ret40 * 110 - row.retrace20 * 35)

        # Volatility score
        volatility_score = cls.clamp_score(100 - row.amplitude20 * 620)

        normalized_health = health_metrics or {}
        health_score = cls.clamp_score(float(normalized_health.get("health_score", 0.0) or 0.0))
        slope_stability = cls.clamp_score(float(normalized_health.get("slope_stability", 0.0) or 0.0))
        volatility_stability = cls.clamp_score(
            float(normalized_health.get("volatility_stability", 0.0) or 0.0)
        )
        pullback_quality = cls.clamp_score(float(normalized_health.get("pullback_quality", 0.0) or 0.0))

        # Entry quality score (weighted composite)
        risk_penalty = len(risk_events) * 3.5 + risk_score * 0.18
        entry_quality_score = cls.clamp_score(
            phase_score * 0.22
            + event_strength_score * 0.14
            + structure_score * 0.12
            + trend_score * 0.09
            + volatility_score * 0.07
            + health_score * 0.10
            + event_score * 0.08
            + computed_phase_context_score * 0.06
            + event_recency_score * 0.04
            + normalized_candle_quality * 0.06
            + normalized_cost_center_shift * 0.06
            + normalized_weekly_context * 0.04
            - risk_penalty
        )
        has_strong_confirmation = bool({"SOS", "JOC", "LPS"} & set(events))
        if risk_score >= 60.0:
            confirmation_status = "risk_blocked"
        elif key_failed > 0:
            confirmation_status = "unconfirmed"
        elif key_pending > 0 and has_strong_confirmation:
            confirmation_status = "partial"
        elif sequence_ok and computed_phase_context_score >= 70.0 and has_strong_confirmation:
            confirmation_status = "confirmed"
        elif sequence_ok and computed_phase_context_score >= 55.0 and bool(events):
            confirmation_status = "partial"
        else:
            confirmation_status = "unconfirmed"

        return {
            "event_strength_score": round(event_strength_score, 2),
            "phase_score": round(phase_score, 2),
            "structure_score": round(structure_score, 2),
            "trend_score": round(trend_score, 2),
            "volatility_score": round(volatility_score, 2),
            "health_score": round(health_score, 2),
            "slope_stability": round(slope_stability, 2),
            "volatility_stability": round(volatility_stability, 2),
            "pullback_quality": round(pullback_quality, 2),
            "event_score": round(event_score, 2),
            "event_grade": event_grade,
            "event_background_score": round(background_score, 2),
            "event_position_score": round(position_score, 2),
            "event_vol_price_score": round(vol_price_score, 2),
            "event_confirmation_score": round(confirmation_score, 2),
            "event_recency_score": round(event_recency_score, 2),
            "phase_context_score": round(computed_phase_context_score, 2),
            "candle_quality_score": round(normalized_candle_quality, 2),
            "cost_center_shift_score": round(normalized_cost_center_shift, 2),
            "weekly_context_score": round(normalized_weekly_context, 2),
            "weekly_context_multiplier": round(resolved_weekly_multiplier, 4),
            "risk_score": round(risk_score, 2),
            "confirmation_status": confirmation_status,
            "event_confirmation_map": key_confirm_map,
            "event_grade_map": event_grade_map,
            "entry_quality_score": round(entry_quality_score, 2),
        }

    @staticmethod
    def _resolve_primary_signal(event_dates: dict[str, str]) -> str:
        """Resolve the primary signal based on priority."""
        signal_priority = [
            "LPS", "JOC", "SOS", "Spring", "TSO", "ST", "AR", "SC", "PS",
            "LPSY", "SOW", "UTAD", "ST(d)", "AR(d)", "BC", "PSY",
        ]
        return next((event for event in signal_priority if event in event_dates), "")



