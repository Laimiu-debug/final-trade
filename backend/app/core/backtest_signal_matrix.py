from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .backtest_matrix_engine import MatrixBundle


@dataclass(slots=True)
class BacktestSignalMatrix:
    s1: np.ndarray
    s2: np.ndarray
    s3: np.ndarray
    s4: np.ndarray
    s5: np.ndarray
    s6: np.ndarray
    s7: np.ndarray
    s8: np.ndarray
    s9: np.ndarray
    in_pool: np.ndarray
    buy_signal: np.ndarray
    sell_signal: np.ndarray
    score: np.ndarray


def _to_bool_array(frame: pd.DataFrame) -> np.ndarray:
    values = frame.fillna(False).to_numpy(dtype=bool)
    return values


def compute_backtest_signal_matrix(
    bundle: MatrixBundle,
    *,
    top_n: int = 500,
) -> BacktestSignalMatrix:
    t, n = bundle.shape()
    if t <= 0 or n <= 0:
        empty_bool = np.zeros((t, n), dtype=bool)
        empty_score = np.zeros((t, n), dtype=np.float64)
        return BacktestSignalMatrix(
            s1=empty_bool,
            s2=empty_bool,
            s3=empty_bool,
            s4=empty_bool,
            s5=empty_bool,
            s6=empty_bool,
            s7=empty_bool,
            s8=empty_bool,
            s9=empty_bool,
            in_pool=empty_bool,
            buy_signal=empty_bool,
            sell_signal=empty_bool,
            score=empty_score,
        )

    close = pd.DataFrame(bundle.close, index=bundle.dates, columns=bundle.symbols)
    high = pd.DataFrame(bundle.high, index=bundle.dates, columns=bundle.symbols)
    low = pd.DataFrame(bundle.low, index=bundle.dates, columns=bundle.symbols)
    volume = pd.DataFrame(bundle.volume, index=bundle.dates, columns=bundle.symbols)

    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    vol_ma10 = volume.rolling(10, min_periods=10).mean()
    vol_ma20 = volume.rolling(20, min_periods=20).mean()
    vol_ma60 = volume.rolling(60, min_periods=60).mean()

    range20 = high.rolling(20, min_periods=20).max() - low.rolling(20, min_periods=20).min()
    range60 = high.rolling(60, min_periods=60).max() - low.rolling(60, min_periods=60).min()
    atr_ratio = range20 / range60.replace(0.0, np.nan)
    s1 = atr_ratio < 0.7

    vol_ratio = vol_ma10 / vol_ma60.replace(0.0, np.nan)
    s2 = vol_ratio < 0.6

    ret_40d = close.pct_change(40, fill_method=None)
    rank_40d = ret_40d.rank(axis=1, ascending=False, method='first')
    s3 = rank_40d <= max(1, int(top_n))

    # 横盘识别：20日振幅收敛且价格靠近20日均线。
    sideways_ratio = range20 / close.replace(0.0, np.nan)
    near_ma20 = (close - ma20).abs() / ma20.replace(0.0, np.nan)
    s4 = (sideways_ratio < 0.18) & (near_ma20 < 0.06)

    high20_prev = high.rolling(20, min_periods=20).max().shift(1)
    s5 = (close > high20_prev) & (volume > vol_ma20 * 1.2)

    low10_prev = low.rolling(10, min_periods=10).min().shift(1)
    s6 = (
        (close > ma10)
        & (close.shift(1) <= ma10.shift(1))
        & (close > low10_prev)
    )

    s7 = (ma10 > ma20) & (ma20 > ma60)

    low20_prev = low.rolling(20, min_periods=20).min().shift(1)
    s8 = (close < low20_prev) | (close < ma20 * 0.97)

    s9 = (close < ma10) & (volume > vol_ma20 * 1.4) & (ret_40d < 0)

    s1_b = _to_bool_array(s1)
    s2_b = _to_bool_array(s2)
    s3_b = _to_bool_array(s3)
    s4_b = _to_bool_array(s4)
    s5_b = _to_bool_array(s5)
    s6_b = _to_bool_array(s6)
    s7_b = _to_bool_array(s7)
    s8_b = _to_bool_array(s8)
    s9_b = _to_bool_array(s9)

    pool_score = s1_b.astype(np.int16) + s2_b.astype(np.int16) + s3_b.astype(np.int16) + s4_b.astype(np.int16)
    in_pool = pool_score >= 2

    buy_signal = (s5_b | s6_b) & in_pool
    sell_signal = s8_b | s9_b

    raw_score = (
        pool_score.astype(np.float64)
        + s5_b.astype(np.float64) * 2.0
        + s6_b.astype(np.float64) * 1.5
        + s7_b.astype(np.float64) * 1.0
    )
    score = np.clip(raw_score / 8.5 * 100.0, 0.0, 100.0)

    valid_mask = np.asarray(bundle.valid_mask, dtype=bool)
    s1_b &= valid_mask
    s2_b &= valid_mask
    s3_b &= valid_mask
    s4_b &= valid_mask
    s5_b &= valid_mask
    s6_b &= valid_mask
    s7_b &= valid_mask
    s8_b &= valid_mask
    s9_b &= valid_mask
    in_pool &= valid_mask
    buy_signal &= valid_mask
    sell_signal &= valid_mask
    score = np.where(valid_mask, score, 0.0)

    return BacktestSignalMatrix(
        s1=s1_b,
        s2=s2_b,
        s3=s3_b,
        s4=s4_b,
        s5=s5_b,
        s6=s6_b,
        s7=s7_b,
        s8=s8_b,
        s9=s9_b,
        in_pool=in_pool,
        buy_signal=buy_signal,
        sell_signal=sell_signal,
        score=score,
    )
