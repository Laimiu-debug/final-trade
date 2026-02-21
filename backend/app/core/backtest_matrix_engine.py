from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Callable

import numpy as np

from ..models import CandlePoint


@dataclass(slots=True)
class MatrixBundle:
    dates: list[str]
    symbols: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    valid_mask: np.ndarray

    def shape(self) -> tuple[int, int]:
        return int(self.close.shape[0]), int(self.close.shape[1])

    def symbol_to_index(self) -> dict[str, int]:
        return {symbol: idx for idx, symbol in enumerate(self.symbols)}


class BacktestMatrixEngine:
    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._cache_dir = self._resolve_cache_dir(cache_dir)
        self._runtime_cache: dict[str, tuple[float, MatrixBundle]] = {}
        self._runtime_cache_lock = RLock()

    @staticmethod
    def _resolve_cache_dir(cache_dir: str | Path | None) -> Path:
        if cache_dir is not None and str(cache_dir).strip():
            return Path(str(cache_dir).strip()).expanduser()
        env_value = str(os.getenv('TDX_TREND_BACKTEST_MATRIX_CACHE_DIR', '')).strip()
        if env_value:
            return Path(env_value).expanduser()
        return Path.home() / '.tdx-trend' / 'backtest-matrix-cache'

    @staticmethod
    def _parse_date(value: str) -> datetime:
        return datetime.strptime(value, '%Y-%m-%d')

    @staticmethod
    def _resolve_build_workers() -> int:
        raw = str(os.getenv('TDX_TREND_BACKTEST_MATRIX_BUILD_WORKERS', '')).strip()
        if raw:
            try:
                return max(1, int(raw))
            except Exception:
                pass
        cpu_count = os.cpu_count() or 4
        return max(1, min(8, cpu_count))

    @staticmethod
    def _is_runtime_cache_enabled() -> bool:
        raw = str(os.getenv('TDX_TREND_BACKTEST_MATRIX_RUNTIME_CACHE', '')).strip().lower()
        if not raw:
            return True
        if raw in {'1', 'true', 'yes', 'on', 'y'}:
            return True
        if raw in {'0', 'false', 'no', 'off', 'n'}:
            return False
        return True

    @staticmethod
    def _runtime_cache_ttl_sec() -> float:
        raw = str(os.getenv('TDX_TREND_BACKTEST_MATRIX_RUNTIME_CACHE_TTL_SEC', '')).strip()
        if not raw:
            return 15 * 60.0
        try:
            return max(0.0, float(raw))
        except Exception:
            return 15 * 60.0

    @staticmethod
    def _runtime_cache_max_items() -> int:
        raw = str(os.getenv('TDX_TREND_BACKTEST_MATRIX_RUNTIME_CACHE_MAX_ITEMS', '')).strip()
        if not raw:
            return 16
        try:
            return max(1, int(raw))
        except Exception:
            return 16

    def _load_runtime_cache(self, cache_key: str) -> MatrixBundle | None:
        if not self._is_runtime_cache_enabled():
            return None
        ttl_sec = self._runtime_cache_ttl_sec()
        with self._runtime_cache_lock:
            cached = self._runtime_cache.get(cache_key)
            if cached is None:
                return None
            created_at, bundle = cached
            if ttl_sec > 0 and (time.time() - created_at) > ttl_sec:
                self._runtime_cache.pop(cache_key, None)
                return None
            return bundle

    def _save_runtime_cache(self, cache_key: str, bundle: MatrixBundle) -> None:
        if not self._is_runtime_cache_enabled():
            return
        now_ts = time.time()
        with self._runtime_cache_lock:
            self._runtime_cache[cache_key] = (now_ts, bundle)
            max_items = self._runtime_cache_max_items()
            if len(self._runtime_cache) > max_items:
                stale_items = sorted(
                    self._runtime_cache.items(),
                    key=lambda item: float(item[1][0]),
                )
                overflow = len(self._runtime_cache) - max_items
                for key, _value in stale_items[:overflow]:
                    self._runtime_cache.pop(key, None)

    def clear_runtime_cache(self) -> None:
        with self._runtime_cache_lock:
            self._runtime_cache.clear()

    @classmethod
    def _with_lookback_start(cls, date_from: str, max_lookback_days: int) -> str:
        if max_lookback_days <= 0:
            return date_from
        start_dt = cls._parse_date(date_from)
        # 使用 3x 日历天近似覆盖交易日窗口，避免周末/节假日导致样本不足。
        lookback_dt = start_dt - timedelta(days=max_lookback_days * 3)
        return lookback_dt.strftime('%Y-%m-%d')

    @staticmethod
    def _symbols_hash(symbols: list[str]) -> str:
        normalized = [str(item).strip().lower() for item in symbols if str(item).strip()]
        raw = '\n'.join(sorted(set(normalized)))
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]

    def build_cache_key(
        self,
        *,
        symbols: list[str],
        date_from: str,
        date_to: str,
        data_version: str,
        window_set: tuple[int, ...],
        algo_version: str,
    ) -> str:
        payload = {
            'symbols_hash': self._symbols_hash(symbols),
            'date_range': f'{date_from}:{date_to}',
            'data_version': str(data_version).strip(),
            'window_set': list(window_set),
            'algo_version': str(algo_version).strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]

    def _cache_file(self, cache_key: str) -> Path:
        return self._cache_dir / f'{cache_key}.npz'

    def load_bundle_from_cache(self, cache_key: str) -> MatrixBundle | None:
        cached_runtime = self._load_runtime_cache(cache_key)
        if cached_runtime is not None:
            return cached_runtime

        path = self._cache_file(cache_key)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as data:
                dates = data['dates'].astype(str).tolist()
                symbols = data['symbols'].astype(str).tolist()
                # npz payload can be loaded as read-only arrays; use writable copies.
                open_ = np.array(data['open'], dtype=np.float64, copy=True)
                high = np.array(data['high'], dtype=np.float64, copy=True)
                low = np.array(data['low'], dtype=np.float64, copy=True)
                close = np.array(data['close'], dtype=np.float64, copy=True)
                volume = np.array(data['volume'], dtype=np.float64, copy=True)
                valid_mask = np.array(data['valid_mask'], dtype=bool, copy=True)
            expected_shape = (len(dates), len(symbols))
            if (
                open_.shape != expected_shape
                or high.shape != expected_shape
                or low.shape != expected_shape
                or close.shape != expected_shape
                or volume.shape != expected_shape
                or valid_mask.shape != expected_shape
            ):
                return None
            bundle = MatrixBundle(
                dates=dates,
                symbols=symbols,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                valid_mask=valid_mask,
            )
            self._save_runtime_cache(cache_key, bundle)
            return bundle
        except Exception:
            return None

    def save_bundle_to_cache(self, cache_key: str, bundle: MatrixBundle) -> None:
        path = self._cache_file(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp.npz')
        np.savez_compressed(
            tmp,
            dates=np.asarray(bundle.dates, dtype='U10'),
            symbols=np.asarray(bundle.symbols, dtype='U16'),
            open=bundle.open,
            high=bundle.high,
            low=bundle.low,
            close=bundle.close,
            volume=bundle.volume,
            valid_mask=bundle.valid_mask.astype(np.uint8),
        )
        tmp.replace(path)
        self._save_runtime_cache(cache_key, bundle)

    def build_bundle(
        self,
        *,
        symbols: list[str],
        get_candles: Callable[[str], list[CandlePoint]],
        date_from: str,
        date_to: str,
        max_lookback_days: int,
        cache_key: str,
        use_cache: bool = True,
    ) -> tuple[MatrixBundle, bool]:
        if use_cache:
            cached = self.load_bundle_from_cache(cache_key)
            if cached is not None:
                return cached, True

        normalized_symbols = [str(item).strip().lower() for item in symbols if str(item).strip()]
        deduped_symbols = sorted(set(normalized_symbols))
        if not deduped_symbols:
            empty = np.zeros((0, 0), dtype=np.float64)
            return (
                MatrixBundle(
                    dates=[],
                    symbols=[],
                    open=empty,
                    high=empty,
                    low=empty,
                    close=empty,
                    volume=empty,
                    valid_mask=np.zeros((0, 0), dtype=bool),
                ),
                False,
            )

        lookback_start = self._with_lookback_start(date_from, max_lookback_days)
        filtered_rows_by_symbol: dict[str, list[CandlePoint]] = {}
        all_dates: set[str] = set()

        def _load_symbol_rows(symbol: str) -> tuple[str, list[CandlePoint], list[str]]:
            candles = get_candles(symbol)
            rows: list[CandlePoint] = []
            local_dates: list[str] = []
            for item in candles:
                day = str(item.time).strip()
                if not day:
                    continue
                if day < lookback_start or day > date_to:
                    continue
                rows.append(item)
                local_dates.append(day)
            return symbol, rows, local_dates

        workers = self._resolve_build_workers()
        if workers <= 1 or len(deduped_symbols) <= 1:
            for symbol in deduped_symbols:
                loaded_symbol, rows, local_dates = _load_symbol_rows(symbol)
                filtered_rows_by_symbol[loaded_symbol] = rows
                all_dates.update(local_dates)
        else:
            with ThreadPoolExecutor(max_workers=min(workers, len(deduped_symbols))) as executor:
                future_map = {
                    executor.submit(_load_symbol_rows, symbol): symbol
                    for symbol in deduped_symbols
                }
                for future in as_completed(future_map):
                    loaded_symbol, rows, local_dates = future.result()
                    filtered_rows_by_symbol[loaded_symbol] = rows
                    all_dates.update(local_dates)

        dates = sorted(all_dates)
        date_to_idx = {day: idx for idx, day in enumerate(dates)}
        t = len(dates)
        n = len(deduped_symbols)

        open_ = np.full((t, n), np.nan, dtype=np.float64)
        high = np.full((t, n), np.nan, dtype=np.float64)
        low = np.full((t, n), np.nan, dtype=np.float64)
        close = np.full((t, n), np.nan, dtype=np.float64)
        volume = np.full((t, n), np.nan, dtype=np.float64)
        valid_mask = np.zeros((t, n), dtype=bool)

        for col, symbol in enumerate(deduped_symbols):
            for row in filtered_rows_by_symbol.get(symbol, []):
                idx = date_to_idx.get(str(row.time).strip())
                if idx is None:
                    continue
                o = float(row.open)
                h = float(row.high)
                l = float(row.low)
                c = float(row.close)
                v = float(row.volume)
                if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and np.isfinite(c) and np.isfinite(v)):
                    continue
                if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                    continue
                open_[idx, col] = o
                high[idx, col] = h
                low[idx, col] = l
                close[idx, col] = c
                volume[idx, col] = max(0.0, v)
                valid_mask[idx, col] = True

        bundle = MatrixBundle(
            dates=dates,
            symbols=deduped_symbols,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            valid_mask=valid_mask,
        )
        if use_cache:
            self.save_bundle_to_cache(cache_key, bundle)
        return bundle, False
