from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
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

    @staticmethod
    def _resolve_cache_dir(cache_dir: str | Path | None) -> Path:
        if cache_dir is not None and str(cache_dir).strip():
            return Path(str(cache_dir).strip()).expanduser()
        env_value = str(__import__('os').getenv('TDX_TREND_BACKTEST_MATRIX_CACHE_DIR', '')).strip()
        if env_value:
            return Path(env_value).expanduser()
        return Path.home() / '.tdx-trend' / 'backtest-matrix-cache'

    @staticmethod
    def _parse_date(value: str) -> datetime:
        return datetime.strptime(value, '%Y-%m-%d')

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
            return MatrixBundle(
                dates=dates,
                symbols=symbols,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                valid_mask=valid_mask,
            )
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

        for symbol in deduped_symbols:
            candles = get_candles(symbol)
            rows: list[CandlePoint] = []
            for item in candles:
                day = str(item.time).strip()
                if not day:
                    continue
                if day < lookback_start or day > date_to:
                    continue
                rows.append(item)
                all_dates.add(day)
            filtered_rows_by_symbol[symbol] = rows

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
