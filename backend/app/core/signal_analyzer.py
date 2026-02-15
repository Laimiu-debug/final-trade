"""
Wyckoff signal detection and analysis.

This module implements the Wyckoff methodology for detecting accumulation
and distribution patterns in stock price movements.
"""

from typing import Callable, Optional

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
            base = vol_avg_at(idx, window)
            return volumes[idx] / max(base, 1.0)

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



