from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

from .strategy_plugins import (
    BaseStrategyPlugin,
    RelativeStrengthBreakoutPlugin,
    StrategyPlugin,
    WyckoffTrendPlugin,
)


@dataclass(frozen=True)
class StrategyCapabilities:
    supports_matrix: bool
    supports_signal_age_filter: bool
    supports_entry_delay: bool


@dataclass(frozen=True)
class StrategyDescriptor:
    strategy_id: str
    name: str
    version: str
    enabled: bool
    is_default: bool
    capabilities: StrategyCapabilities
    params_schema: dict[str, dict[str, Any]]
    default_params: dict[str, Any]


class StrategyRegistry:
    _DEFAULT_STRATEGY_ID = "wyckoff_trend_v1"

    def __init__(self) -> None:
        self._strategies: dict[str, StrategyDescriptor] = {}
        self._plugins: dict[str, StrategyPlugin] = {}
        self._fallback_plugin: StrategyPlugin = BaseStrategyPlugin()
        self._register_builtin()

    def _register_builtin(self) -> None:
        v1 = StrategyDescriptor(
            strategy_id="wyckoff_trend_v1",
            name="Wyckoff Trend V1",
            version="1.0.0",
            enabled=True,
            is_default=True,
            capabilities=StrategyCapabilities(
                supports_matrix=True,
                supports_signal_age_filter=True,
                supports_entry_delay=True,
            ),
            params_schema={},
            default_params={},
        )
        v2_schema: dict[str, dict[str, Any]] = {
            "matrix_event_semantic_version": {
                "type": "enum",
                "title": "Matrix Semantic Version",
                "options": ["matrix_v1", "aligned_wyckoff_v2"],
                "default": "aligned_wyckoff_v2",
            },
            "rank_weight_health": {
                "type": "number",
                "title": "Health Score Weight",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
            },
            "rank_weight_event": {
                "type": "number",
                "title": "Event Score Weight",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
            },
            "health_score_min": {
                "type": "number",
                "title": "Health Score Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 55.0,
            },
            "event_score_min": {
                "type": "number",
                "title": "Event Score Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 55.0,
            },
            "event_grade_min": {
                "type": "enum",
                "title": "Event Grade Minimum",
                "options": ["A", "B", "C"],
                "default": "B",
            },
            "require_key_event_confirmation": {
                "type": "boolean",
                "title": "Require Key Event Confirmation",
                "default": True,
            },
            "min_score": {
                "type": "number",
                "title": "Entry Quality Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 60.0,
            },
            "min_event_count": {
                "type": "integer",
                "title": "Minimum Event Count",
                "minimum": 0,
                "maximum": 12,
                "default": 1,
            },
            "require_sequence": {
                "type": "boolean",
                "title": "Require Event Sequence",
                "default": False,
            },
        }
        v2 = StrategyDescriptor(
            strategy_id="wyckoff_trend_v2",
            name="Wyckoff Trend V2",
            version="2.0.0-alpha",
            enabled=True,
            is_default=False,
            capabilities=StrategyCapabilities(
                supports_matrix=True,
                supports_signal_age_filter=True,
                supports_entry_delay=True,
            ),
            params_schema=v2_schema,
            default_params={
                "matrix_event_semantic_version": "aligned_wyckoff_v2",
                "rank_weight_health": 0.5,
                "rank_weight_event": 0.5,
                "health_score_min": 55.0,
                "event_score_min": 55.0,
                "event_grade_min": "B",
                "require_key_event_confirmation": True,
            },
        )
        self._strategies[v1.strategy_id] = v1
        self._strategies[v2.strategy_id] = v2
        v3_schema: dict[str, dict[str, Any]] = {
            "min_ret40": {
                "type": "number",
                "title": "Minimum Ret40",
                "minimum": 0.0,
                "maximum": 1.5,
                "default": 0.12,
            },
            "max_retrace20": {
                "type": "number",
                "title": "Maximum Retrace20",
                "minimum": 0.01,
                "maximum": 0.60,
                "default": 0.22,
            },
            "min_up_down_volume_ratio": {
                "type": "number",
                "title": "Minimum Up/Down Volume Ratio",
                "minimum": 0.8,
                "maximum": 3.0,
                "default": 1.15,
            },
            "min_vol_slope20": {
                "type": "number",
                "title": "Minimum Volume Slope20",
                "minimum": -0.5,
                "maximum": 0.5,
                "default": 0.02,
            },
            "min_ai_confidence": {
                "type": "number",
                "title": "Minimum AI Confidence",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.0,
            },
            "rank_weight_health": {
                "type": "number",
                "title": "Rank Weight Health",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.25,
            },
            "rank_weight_event": {
                "type": "number",
                "title": "Rank Weight Event",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.25,
            },
            "rank_weight_strength": {
                "type": "number",
                "title": "Rank Weight Strength",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.30,
            },
            "rank_weight_volume": {
                "type": "number",
                "title": "Rank Weight Volume",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.10,
            },
            "rank_weight_structure": {
                "type": "number",
                "title": "Rank Weight Structure",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.10,
            },
            "min_score": {
                "type": "number",
                "title": "Entry Quality Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 52.0,
            },
            "min_event_count": {
                "type": "integer",
                "title": "Minimum Event Count",
                "minimum": 0,
                "maximum": 12,
                "default": 0,
            },
            "require_sequence": {
                "type": "boolean",
                "title": "Require Event Sequence",
                "default": False,
            },
            "health_score_min": {
                "type": "number",
                "title": "Health Score Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 45.0,
            },
            "event_score_min": {
                "type": "number",
                "title": "Event Score Minimum",
                "minimum": 0.0,
                "maximum": 100.0,
                "default": 45.0,
            },
            "event_grade_min": {
                "type": "enum",
                "title": "Event Grade Minimum",
                "options": ["A", "B", "C"],
                "default": "C",
            },
            "require_key_event_confirmation": {
                "type": "boolean",
                "title": "Require Key Event Confirmation",
                "default": False,
            },
        }
        v3 = StrategyDescriptor(
            strategy_id="relative_strength_breakout_v1",
            name="Relative Strength Breakout V1",
            version="1.0.0-alpha",
            enabled=True,
            is_default=False,
            capabilities=StrategyCapabilities(
                supports_matrix=False,
                supports_signal_age_filter=True,
                supports_entry_delay=True,
            ),
            params_schema=v3_schema,
            default_params={
                "min_ret40": 0.12,
                "max_retrace20": 0.22,
                "min_up_down_volume_ratio": 1.15,
                "min_vol_slope20": 0.02,
                "min_ai_confidence": 0.0,
                "rank_weight_health": 0.25,
                "rank_weight_event": 0.25,
                "rank_weight_strength": 0.30,
                "rank_weight_volume": 0.10,
                "rank_weight_structure": 0.10,
                "min_score": 52.0,
                "min_event_count": 0,
                "require_sequence": False,
                "health_score_min": 45.0,
                "event_score_min": 45.0,
                "event_grade_min": "C",
                "require_key_event_confirmation": False,
            },
        )
        self._strategies[v3.strategy_id] = v3

        self._plugins = {
            v1.strategy_id: WyckoffTrendPlugin(v1.strategy_id),
            v2.strategy_id: WyckoffTrendPlugin(v2.strategy_id),
            v3.strategy_id: RelativeStrengthBreakoutPlugin(),
        }

    @property
    def default_strategy_id(self) -> str:
        for item in self._strategies.values():
            if bool(item.is_default):
                return str(item.strategy_id)
        if self._DEFAULT_STRATEGY_ID in self._strategies:
            return self._DEFAULT_STRATEGY_ID
        if self._strategies:
            return next(iter(self._strategies.keys()))
        return self._DEFAULT_STRATEGY_ID

    def normalize_strategy_id(self, raw_strategy_id: str | None) -> str:
        text = str(raw_strategy_id or "").strip()
        if not text:
            return self._DEFAULT_STRATEGY_ID
        return text

    def get(self, strategy_id: str) -> StrategyDescriptor | None:
        return self._strategies.get(str(strategy_id).strip())

    def list(self) -> list[StrategyDescriptor]:
        return list(self._strategies.values())

    def update_descriptor(
        self,
        *,
        strategy_id: str,
        enabled: bool | None = None,
        is_default: bool | None = None,
        version: str | None = None,
    ) -> StrategyDescriptor:
        target_id = str(strategy_id).strip()
        descriptor = self.get(target_id)
        if descriptor is None:
            available = ",".join(item.strategy_id for item in self.list())
            raise ValueError(f"策略不存在: {target_id}（可用: {available}）")

        updated = descriptor
        if enabled is not None:
            updated = replace(updated, enabled=bool(enabled))
        if version is not None:
            normalized_version = str(version).strip()
            if normalized_version:
                updated = replace(updated, version=normalized_version)

        # Apply non-default updates first.
        self._strategies[target_id] = updated

        if is_default is not None:
            if bool(is_default):
                for item_id, item in list(self._strategies.items()):
                    self._strategies[item_id] = replace(item, is_default=(item_id == target_id))
            else:
                self._strategies[target_id] = replace(self._strategies[target_id], is_default=False)
                if not any(bool(item.is_default) for item in self._strategies.values()):
                    fallback_id = self._DEFAULT_STRATEGY_ID if self._DEFAULT_STRATEGY_ID in self._strategies else target_id
                    fallback = self._strategies[fallback_id]
                    self._strategies[fallback_id] = replace(fallback, is_default=True)

        return self._strategies[target_id]

    def _get_plugin(self, strategy_id: str) -> StrategyPlugin:
        text = str(strategy_id).strip()
        return self._plugins.get(text, self._fallback_plugin)

    @staticmethod
    def _clamp_number(value: Any, *, minimum: float | None, maximum: float | None) -> float | None:
        try:
            parsed = float(value)
        except Exception:
            return None
        if minimum is not None and parsed < float(minimum):
            parsed = float(minimum)
        if maximum is not None and parsed > float(maximum):
            parsed = float(maximum)
        return parsed

    @staticmethod
    def _clamp_integer(value: Any, *, minimum: int | None, maximum: int | None) -> int | None:
        try:
            parsed = int(value)
        except Exception:
            return None
        if minimum is not None and parsed < int(minimum):
            parsed = int(minimum)
        if maximum is not None and parsed > int(maximum):
            parsed = int(maximum)
        return parsed

    def normalize_params(self, strategy_id: str, raw_params: dict[str, Any] | None) -> dict[str, Any]:
        descriptor = self.get(strategy_id)
        if descriptor is None:
            return {}
        params = raw_params if isinstance(raw_params, dict) else {}
        normalized: dict[str, Any] = {}
        for key, spec in descriptor.params_schema.items():
            if key not in params:
                continue
            value = params.get(key)
            type_name = str(spec.get("type") or "").strip().lower()
            if type_name == "number":
                parsed = self._clamp_number(
                    value,
                    minimum=float(spec["minimum"]) if "minimum" in spec else None,
                    maximum=float(spec["maximum"]) if "maximum" in spec else None,
                )
                if parsed is not None:
                    normalized[key] = float(parsed)
                continue
            if type_name == "integer":
                parsed = self._clamp_integer(
                    value,
                    minimum=int(spec["minimum"]) if "minimum" in spec else None,
                    maximum=int(spec["maximum"]) if "maximum" in spec else None,
                )
                if parsed is not None:
                    normalized[key] = int(parsed)
                continue
            if type_name == "boolean":
                if isinstance(value, bool):
                    normalized[key] = value
                    continue
                value_text = str(value).strip().lower()
                if value_text in {"1", "true", "yes", "y", "on"}:
                    normalized[key] = True
                elif value_text in {"0", "false", "no", "n", "off"}:
                    normalized[key] = False
                continue
            if type_name == "enum":
                options = [str(item) for item in spec.get("options", [])]
                value_text = str(value).strip()
                if value_text in options:
                    normalized[key] = value_text
                continue
        return normalized

    def resolve_backtest_overrides(self, strategy_id: str, normalized_params: dict[str, Any]) -> dict[str, Any]:
        _ = strategy_id
        allowed = {
            "matrix_event_semantic_version",
            "rank_weight_health",
            "rank_weight_event",
            "health_score_min",
            "event_score_min",
            "event_grade_min",
            "require_key_event_confirmation",
            "min_score",
            "min_event_count",
            "require_sequence",
        }
        return {
            key: value
            for key, value in normalized_params.items()
            if key in allowed
        }

    def resolve_signal_overrides(self, strategy_id: str, normalized_params: dict[str, Any]) -> dict[str, Any]:
        _ = strategy_id
        allowed = {
            "min_score",
            "min_event_count",
            "require_sequence",
            "health_score_min",
            "event_score_min",
            "event_grade_min",
            "require_key_event_confirmation",
        }
        return {
            key: value
            for key, value in normalized_params.items()
            if key in allowed
        }

    def build_universe(
        self,
        *,
        strategy_id: str,
        candidates: list[Any],
        params: dict[str, Any],
        mode: str,
    ) -> list[Any]:
        plugin = self._get_plugin(strategy_id)
        return plugin.build_universe(
            candidates=candidates,
            params=params,
            mode=mode,
        )

    def generate_signals(
        self,
        *,
        strategy_id: str,
        row: Any,
        snapshot: dict[str, Any],
        params: dict[str, Any],
    ) -> bool:
        plugin = self._get_plugin(strategy_id)
        return bool(
            plugin.generate_signals(
                row=row,
                snapshot=snapshot,
                params=params,
            )
        )

    def rank_signals(
        self,
        *,
        strategy_id: str,
        signal: Any,
        row: Any,
        params: dict[str, Any],
        fallback_score: float,
    ) -> float:
        plugin = self._get_plugin(strategy_id)
        return float(
            plugin.rank_signals(
                signal=signal,
                row=row,
                params=params,
                fallback_score=fallback_score,
            )
        )

    def entry_policy(
        self,
        *,
        strategy_id: str,
        payload: Any,
        params: dict[str, Any],
    ) -> Any:
        plugin = self._get_plugin(strategy_id)
        return plugin.entry_policy(payload=payload, params=params)

    def exit_policy(
        self,
        *,
        strategy_id: str,
        payload: Any,
        params: dict[str, Any],
    ) -> Any:
        plugin = self._get_plugin(strategy_id)
        return plugin.exit_policy(payload=payload, params=params)

    @staticmethod
    def params_hash(normalized_params: dict[str, Any]) -> str:
        raw = json.dumps(normalized_params, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
