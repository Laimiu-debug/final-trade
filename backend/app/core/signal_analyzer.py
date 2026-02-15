"""
Wyckoff signal detection and analysis.

This module implements the Wyckoff methodology for detecting accumulation
and distribution patterns in stock price movements.
"""

from typing import Optional

from ..models import CandlePoint, ScreenerResult, Stage, ThemeStage


# Wyckoff event constants
WYCKOFF_ACC_EVENTS = ("PS", "SC", "AR", "ST", "TSO", "Spring", "SOS", "JOC", "LPS")
WYCKOFF_DIST_EVENTS = ("PSY", "BC", "AR(d)", "ST(d)")
WYCKOFF_RISK_EVENTS = (*WYCKOFF_DIST_EVENTS, "UTAD", "SOW", "LPSY")
WYCKOFF_EVENT_ORDER = (*WYCKOFF_ACC_EVENTS, *WYCKOFF_RISK_EVENTS)


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
    def clamp_score(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
        """Clamp a value to a specified range."""
        return max(lower, min(upper, value))

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

        # Analyze structure (HH/HL/HC)
        structure_hhh = cls._analyze_structure(highs, lows, closes)

        # Determine phase
        phase = cls._determine_phase(events, risk_events, ret20, ma20, row)

        # Calculate scores
        scores = cls._calculate_scores(
            phase, events, risk_events, structure_hhh, row, ret20, ret10
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
            "trigger_date": trigger_date,
            **scores,
        }

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
            "event_strength_score": 0.0,
            "phase_score": 45.0,
            "structure_score": 0.0,
            "trend_score": 0.0,
            "volatility_score": 0.0,
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

        # PS / SC / AR / ST (Accumulation Phase A)
        push_event("PS", tr_pos <= 0.38 and avg_v5 >= avg_v20 * 1.12)

        look_sc_start = max(0, len(closes) - 30)
        sc_idx = look_sc_start + max(
            range(len(volumes[look_sc_start:])),
            key=lambda idx: volumes[look_sc_start + idx],
        )
        sc_range = max(highs[sc_idx] - lows[sc_idx], 0.01)
        sc_close_near_low = closes[sc_idx] <= lows[sc_idx] + sc_range * 0.38
        push_event("SC", sc_close_near_low, sc_idx)

        ar_idx: int | None = None
        if "SC" in event_dates and sc_idx < len(closes) - 3:
            rebound_slice = closes[sc_idx + 1:]
            rebound_max = max(rebound_slice) if rebound_slice else closes[sc_idx]
            if rebound_max >= closes[sc_idx] * 1.08:
                ar_idx = sc_idx + rebound_slice.index(rebound_max) + 1
                push_event("AR", True, ar_idx)

        if "SC" in event_dates and len(closes) >= sc_idx + 6:
            sc_low = lows[sc_idx]
            st_idx = None
            for idx in range(sc_idx + 1, len(closes)):
                near_sc_low = abs(lows[idx] - sc_low) / max(sc_low, 0.01) <= 0.04
                lower_volume = volumes[idx] <= volumes[sc_idx] * 0.85
                if near_sc_low and lower_volume:
                    st_idx = idx
            push_event("ST", st_idx is not None, st_idx)

        # TSO / Spring / SOS / JOC / LPS (Accumulation Phases B-E)
        support_20 = min(lows[-20:])
        prior_support = min(lows[-25:-5]) if len(lows) > 25 else support_20
        push_event(
            "TSO",
            lows[-1] < prior_support * 0.99 and closes[-1] > prior_support and avg_v5 >= avg_v20,
        )
        push_event(
            "Spring",
            lows[-1] < support_20 * 0.985 and closes[-1] > support_20 and volumes[-1] >= avg_v20 * 1.15,
        )
        push_event(
            "SOS",
            closes[-1] > ma20 * 1.01 and ret10 > 0.05 and avg_v5 >= avg_v20 * 1.05,
        )
        prior_high_20 = max(highs[-21:-1]) if len(highs) > 21 else max(highs[:-1])
        push_event(
            "JOC",
            closes[-1] >= prior_high_20 * 1.005 and volumes[-1] >= avg_v20 * 1.2,
        )
        push_event(
            "LPS",
            (("SOS" in event_dates) or ("JOC" in event_dates))
            and closes[-1] > ma20
            and row.pullback_volume_ratio <= 0.95
            and row.pullback_days <= 4,
        )

        # Distribution early events: PSY / BC / AR(d) / ST(d)
        push_event("PSY", tr_pos >= 0.62 and avg_v5 >= avg_v20 * 1.05, category="distributionRisk")

        look_bc_start = max(0, len(closes) - 30)
        bc_idx = look_bc_start + max(
            range(len(volumes[look_bc_start:])),
            key=lambda idx: volumes[look_bc_start + idx],
        )
        bc_range = max(highs[bc_idx] - lows[bc_idx], 0.01)
        bc_close_near_high = closes[bc_idx] >= highs[bc_idx] - bc_range * 0.32
        bc_condition = bc_close_near_high and highs[bc_idx] >= max(highs[max(0, bc_idx - 20):bc_idx + 1]) * 0.995
        push_event("BC", bc_condition, bc_idx, category="distributionRisk")

        ar_d_idx: int | None = None
        if "BC" in event_dates and bc_idx < len(closes) - 2:
            decline_slice = closes[bc_idx + 1:]
            decline_min = min(decline_slice) if decline_slice else closes[bc_idx]
            if decline_min <= closes[bc_idx] * 0.94:
                ar_d_idx = bc_idx + decline_slice.index(decline_min) + 1
                push_event("AR(d)", True, ar_d_idx, category="distributionRisk")

        if "BC" in event_dates and len(closes) >= bc_idx + 4:
            bc_high = highs[bc_idx]
            st_d_idx = None
            for idx in range(bc_idx + 1, len(closes)):
                near_bc_high = abs(highs[idx] - bc_high) / max(bc_high, 0.01) <= 0.04
                lower_volume = volumes[idx] <= volumes[bc_idx] * 0.9
                close_weak = closes[idx] <= highs[idx] * 0.985
                if near_bc_high and lower_volume and close_weak:
                    st_d_idx = idx
            push_event("ST(d)", st_d_idx is not None, st_d_idx, category="distributionRisk")

        # Risk-side events (Distribution)
        upper_shadow_ratio = (highs[-1] - max(opens[-1], closes[-1])) / max(highs[-1] - lows[-1], 0.01)
        push_event(
            "UTAD",
            highs[-1] >= prior_high_20 * 1.01
            and closes[-1] < prior_high_20
            and upper_shadow_ratio >= 0.5
            and volumes[-1] >= avg_v20 * 1.2,
            category="distributionRisk",
        )
        push_event(
            "SOW",
            ret10 <= -0.05 and closes[-1] < ma20 and avg_v5 >= avg_v20 * 1.1,
            category="distributionRisk",
        )
        recent_high_5 = max(highs[-5:])
        prev_high_5 = max(highs[-10:-5]) if len(highs) >= 10 else recent_high_5
        push_event(
            "LPSY",
            ("SOW" in event_dates or "UTAD" in event_dates)
            and closes[-1] < ma20
            and recent_high_5 <= prev_high_5 * 0.99,
            category="distributionRisk",
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
    def _calculate_scores(
        cls,
        phase: str,
        events: list[str],
        risk_events: list[str],
        structure_hhh: str,
        row: ScreenerResult,
        ret20: float,
        ret10: float,
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
        for event in events:
            event_strength_score += positive_event_weights.get(event, 0)
        for event in risk_events:
            event_strength_score += risk_event_penalty.get(event, 0)
        event_strength_score = cls.clamp_score(event_strength_score)

        # Structure score
        hh, hl, hc = [part != "-" for part in structure_hhh.split("|")]
        structure_score = cls.clamp_score(35 + (22 if hh else 0) + (22 if hl else 0) + (21 if hc else 0))

        # Trend score
        trend_score = cls.clamp_score(50 + row.ret40 * 110 - row.retrace20 * 35)

        # Volatility score
        volatility_score = cls.clamp_score(100 - row.amplitude20 * 620)

        # Entry quality score (weighted composite)
        risk_penalty = len(risk_events) * 4.5
        entry_quality_score = cls.clamp_score(
            phase_score * 0.34
            + event_strength_score * 0.24
            + structure_score * 0.20
            + trend_score * 0.14
            + volatility_score * 0.08
            - risk_penalty
        )

        return {
            "event_strength_score": round(event_strength_score, 2),
            "phase_score": round(phase_score, 2),
            "structure_score": round(structure_score, 2),
            "trend_score": round(trend_score, 2),
            "volatility_score": round(volatility_score, 2),
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



