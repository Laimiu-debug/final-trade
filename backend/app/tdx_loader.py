from __future__ import annotations

import csv
import os
import struct
from pathlib import Path
from typing import TypedDict

from .models import CandlePoint, IntradayPoint, ScreenerResult, Stage, ThemeStage, TrendClass

DAY_RECORD = struct.Struct("<IIIIIfII")
LC1_RECORD = struct.Struct("<HHfffffII")
TNF_HEADER_SIZE = 50
TNF_RECORD_SIZE = 360
DBF_HEADER = struct.Struct("<BBBBIHH20x")
DBF_FIELD_SIZE = 32
DBF_TERMINATOR = 0x0D


class ParsedSeries(TypedDict):
    symbol: str
    total_bars: int
    dates: list[str]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    amount: list[float]
    volume: list[int]


class DbfField(TypedDict):
    offset: int
    length: int


def _safe_mean(values: list[float] | list[int]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _resolve_tdx_base_dir(tdx_root: str) -> Path:
    base = Path(tdx_root)
    if base.name.lower() == "vipdoc":
        return base.parent
    return base


def _akshare_cache_root(akshare_cache_dir: str = "") -> Path:
    override = str(akshare_cache_dir).strip()
    if override:
        return Path(os.path.expanduser(os.path.expandvars(override)))
    override = os.getenv("AKSHARE_CACHE_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(os.path.expandvars(override)))
    return Path.home() / ".tdx-trend" / "akshare" / "daily"


def _normalize_symbol(stem: str, market: str) -> str | None:
    raw = stem.lower()
    if raw.startswith(("sh", "sz", "bj")) and len(raw) >= 8:
        symbol = raw[:8]
    elif len(raw) >= 6 and raw[:6].isdigit():
        symbol = f"{market}{raw[:6]}"
    else:
        return None

    code = symbol[2:]
    if len(code) != 6 or not code.isdigit():
        return None
    return symbol


def _tnf_file_for_market(market: str) -> str:
    if market == "sh":
        return "shs.tnf"
    if market == "sz":
        return "szs.tnf"
    if market == "bj":
        return "bjs.tnf"
    return ""


def _load_symbol_name_map_from_tnf(tdx_root: str, markets: list[str]) -> dict[str, str]:
    base = _resolve_tdx_base_dir(tdx_root)
    root = base / "T0002" / "hq_cache"
    if not root.exists():
        return {}

    symbol_name_map: dict[str, str] = {}
    for market in markets:
        tnf_file = _tnf_file_for_market(market)
        if not tnf_file:
            continue
        path = root / tnf_file
        if not path.exists():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue

        if len(data) <= TNF_HEADER_SIZE + TNF_RECORD_SIZE:
            continue

        for offset in range(TNF_HEADER_SIZE, len(data) - TNF_RECORD_SIZE + 1, TNF_RECORD_SIZE):
            record = data[offset : offset + TNF_RECORD_SIZE]
            code = record[0:6].decode("ascii", "ignore").strip("\x00").strip()
            if len(code) != 6 or not code.isdigit():
                continue

            raw_name = record[31 : 31 + 16]
            name = raw_name.split(b"\x00", 1)[0].decode("gbk", "ignore").strip()
            if not name:
                continue

            symbol = f"{market}{code}"
            symbol_name_map[symbol] = name

    return symbol_name_map


def _decode_ascii_field(raw: bytes) -> str:
    return raw.decode("ascii", "ignore").strip("\x00").strip()


def _parse_dbf_numeric(raw: bytes) -> float | None:
    text = _decode_ascii_field(raw)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_dbf_fields(raw: bytes) -> dict[str, DbfField]:
    fields: dict[str, DbfField] = {}
    position = 1
    offset = DBF_HEADER.size

    while offset + DBF_FIELD_SIZE <= len(raw) and raw[offset] != DBF_TERMINATOR:
        descriptor = raw[offset : offset + DBF_FIELD_SIZE]
        name = descriptor[0:11].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        length = int(descriptor[16])
        if name:
            fields[name] = DbfField(offset=position, length=length)
        position += length
        offset += DBF_FIELD_SIZE
    return fields


def _market_from_dbf_sc(sc_value: str) -> str | None:
    if sc_value == "0":
        return "sz"
    if sc_value == "1":
        return "sh"
    if sc_value == "2":
        return "bj"
    return None


def _load_float_shares_from_base_dbf(
    tdx_root: str,
    markets: list[str],
) -> tuple[dict[str, float], str | None]:
    base = _resolve_tdx_base_dir(tdx_root)
    candidates = [base / "T0002" / "hq_cache" / "base.dbf", base / "base.dbf"]
    requested_markets = set(markets)
    last_error = "FLOAT_SHARES_DBF_NOT_FOUND"

    for file_path in candidates:
        if not file_path.exists():
            continue

        try:
            raw = file_path.read_bytes()
        except OSError:
            last_error = "FLOAT_SHARES_DBF_READ_FAILED"
            continue

        if len(raw) < DBF_HEADER.size:
            last_error = "FLOAT_SHARES_DBF_INVALID"
            continue

        try:
            _, _, _, _, record_count, header_len, record_len = DBF_HEADER.unpack(raw[: DBF_HEADER.size])
        except struct.error:
            last_error = "FLOAT_SHARES_DBF_INVALID"
            continue

        if record_count <= 0 or header_len <= DBF_HEADER.size or record_len <= 1:
            last_error = "FLOAT_SHARES_DBF_EMPTY"
            continue

        fields = _parse_dbf_fields(raw)
        sc_field = fields.get("SC")
        code_field = fields.get("GPDM")
        ltag_field = fields.get("LTAG")
        if not sc_field or not code_field or not ltag_field:
            last_error = "FLOAT_SHARES_FIELDS_MISSING"
            continue

        result: dict[str, float] = {}
        for i in range(record_count):
            start = header_len + i * record_len
            record = raw[start : start + record_len]
            if len(record) < record_len:
                break
            if record[0] == 0x2A:  # Deleted record marker.
                continue

            sc_value = _decode_ascii_field(
                record[sc_field["offset"] : sc_field["offset"] + sc_field["length"]]
            )
            market = _market_from_dbf_sc(sc_value)
            if market is None or market not in requested_markets:
                continue

            code = _decode_ascii_field(
                record[code_field["offset"] : code_field["offset"] + code_field["length"]]
            )
            if len(code) != 6 or not code.isdigit():
                continue

            float_shares_10k = _parse_dbf_numeric(
                record[ltag_field["offset"] : ltag_field["offset"] + ltag_field["length"]]
            )
            if float_shares_10k is None or float_shares_10k <= 0:
                continue

            symbol = f"{market}{code}"
            result[symbol] = float_shares_10k * 10000.0

        if result:
            return result, None

        last_error = "FLOAT_SHARES_DBF_EMPTY"

    return {}, last_error


def _is_a_share_symbol(symbol: str) -> bool:
    code = symbol[2:]
    market = symbol[:2]
    if market == "sh":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if market == "sz":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if market == "bj":
        return code.startswith(("8", "4"))
    return False


def _parse_day_file(file_path: Path, symbol: str, *, max_bars: int = 360) -> ParsedSeries | None:
    try:
        size = file_path.stat().st_size
    except OSError:
        return None

    if size < DAY_RECORD.size * 60:
        return None

    total_bars = size // DAY_RECORD.size
    read_bars = min(total_bars, max(60, int(max_bars)))
    start_offset = (total_bars - read_bars) * DAY_RECORD.size

    dates: list[str] = []
    open_list: list[float] = []
    high_list: list[float] = []
    low_list: list[float] = []
    close_list: list[float] = []
    amount_list: list[float] = []
    volume_list: list[int] = []

    try:
        with file_path.open("rb") as fp:
            fp.seek(start_offset)
            raw = fp.read(read_bars * DAY_RECORD.size)
    except OSError:
        return None

    for offset in range(0, len(raw), DAY_RECORD.size):
        chunk = raw[offset : offset + DAY_RECORD.size]
        if len(chunk) < DAY_RECORD.size:
            continue
        day, open_raw, high_raw, low_raw, close_raw, amount_raw, volume_raw, _ = DAY_RECORD.unpack(chunk)
        if day <= 19900101 or close_raw <= 0 or high_raw <= 0 or low_raw <= 0:
            continue

        day_text = str(day)
        if len(day_text) != 8:
            continue
        date_text = f"{day_text[0:4]}-{day_text[4:6]}-{day_text[6:8]}"

        open_price = open_raw / 100.0
        high_price = high_raw / 100.0
        low_price = low_raw / 100.0
        close_price = close_raw / 100.0
        if high_price < low_price:
            high_price, low_price = low_price, high_price

        dates.append(date_text)
        open_list.append(round(open_price, 2))
        high_list.append(round(high_price, 2))
        low_list.append(round(low_price, 2))
        close_list.append(round(close_price, 2))
        amount_list.append(float(amount_raw))
        volume_list.append(int(volume_raw))

    if len(close_list) < 60:
        return None

    return ParsedSeries(
        symbol=symbol,
        total_bars=int(total_bars),
        dates=dates,
        open=open_list,
        high=high_list,
        low=low_list,
        close=close_list,
        amount=amount_list,
        volume=volume_list,
    )


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _load_candles_from_akshare_cache(
    symbol: str,
    window: int = 120,
    akshare_cache_dir: str = "",
) -> list[CandlePoint] | None:
    root = _akshare_cache_root(akshare_cache_dir)
    if len(symbol) < 8:
        return None
    symbol = symbol.lower()
    code = symbol[2:]
    candidates = [root / f"{symbol}.csv", root / f"{code}.csv"]
    target = next((path for path in candidates if path.exists()), None)
    if target is None:
        return None

    rows: list[CandlePoint] = []
    try:
        with target.open("r", encoding="utf-8-sig") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                date_text = str(row.get("date") or row.get("日期") or "").strip()
                if len(date_text) < 10:
                    continue
                date_text = date_text[:10]
                open_price = _to_float(row.get("open") or row.get("开盘"))
                high_price = _to_float(row.get("high") or row.get("最高"))
                low_price = _to_float(row.get("low") or row.get("最低"))
                close_price = _to_float(row.get("close") or row.get("收盘"))
                volume_value = _to_float(row.get("volume") or row.get("成交量"))
                amount_value = _to_float(row.get("amount") or row.get("成交额"))
                if (
                    open_price is None
                    or high_price is None
                    or low_price is None
                    or close_price is None
                    or open_price <= 0
                    or high_price <= 0
                    or low_price <= 0
                    or close_price <= 0
                ):
                    continue
                if high_price < low_price:
                    high_price, low_price = low_price, high_price
                volume = int(max(0.0, volume_value or 0.0))
                amount = float(amount_value) if amount_value is not None else float(close_price * max(volume, 1))
                rows.append(
                    CandlePoint(
                        time=date_text,
                        open=round(open_price, 2),
                        high=round(high_price, 2),
                        low=round(low_price, 2),
                        close=round(close_price, 2),
                        volume=volume,
                        amount=float(amount),
                        price_source="approx",
                    )
                )
    except OSError:
        return None

    if not rows:
        return None
    rows.sort(key=lambda item: item.time)
    start = max(0, len(rows) - max(window, 1))
    return rows[start:]


def _ma_at(prices: list[float], idx: int, period: int) -> float | None:
    if idx + 1 < period:
        return None
    window = prices[idx - period + 1 : idx + 1]
    return _safe_mean(window)


def _count_pullback_days(closes: list[float]) -> int:
    days = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] <= closes[i - 1]:
            days += 1
        else:
            break
    return days


def _resolve_series_end_index(dates: list[str], as_of_date: str | None) -> int | None:
    if not dates:
        return None
    if not as_of_date:
        return len(dates) - 1
    for idx in range(len(dates) - 1, -1, -1):
        if dates[idx] <= as_of_date:
            return idx
    return None


def _build_row(
    series: ParsedSeries,
    return_window_days: int,
    float_shares: float | None,
    as_of_date: str | None = None,
) -> ScreenerResult | None:
    end_idx = _resolve_series_end_index(series["dates"], as_of_date)
    if end_idx is None:
        return None

    effective_end = end_idx + 1
    closes = series["close"][:effective_end]
    highs = series["high"][:effective_end]
    lows = series["low"][:effective_end]
    opens = series["open"][:effective_end]
    volumes = series["volume"][:effective_end]
    amounts = series["amount"][:effective_end]

    if len(closes) < max(return_window_days + 1, 40):
        return None
    if series["total_bars"] <= 250:
        return None

    window = min(return_window_days, len(closes) - 1)
    look20 = min(20, len(closes))
    start20 = len(closes) - look20

    latest = closes[-1]
    prev = closes[-2]
    start_close = closes[-window]
    ret_window = (latest / max(start_close, 0.01)) - 1

    high20 = highs[start20:]
    low20 = lows[start20:]
    close20 = closes[start20:]
    volume20 = volumes[start20:]
    amount20 = amounts[start20:]
    turnover20 = 0.0
    degraded = False
    degraded_reason: str | None = None
    if float_shares is not None and float_shares > 0:
        turnover20 = _safe_mean([max(0, volume) / float_shares for volume in volume20])
    else:
        degraded = True
        degraded_reason = "FLOAT_SHARES_NOT_FOUND"

    amplitude20 = _safe_mean([((h - l) / max(c, 0.01)) for h, l, c in zip(high20, low20, close20)])
    peak20 = max(high20) if high20 else latest
    retrace20 = (peak20 - latest) / max(peak20, 0.01)

    ma20_last = _safe_mean(closes[-20:])
    price_vs_ma20 = (latest - ma20_last) / max(ma20_last, 0.01)

    ma10_above_ma20_days = 0
    ma5_above_ma10_days = 0
    count_start = max(0, len(closes) - 20)
    for idx in range(count_start, len(closes)):
        ma10 = _ma_at(closes, idx, 10)
        ma20 = _ma_at(closes, idx, 20)
        ma5 = _ma_at(closes, idx, 5)
        if ma10 is not None and ma20 is not None and ma10 > ma20:
            ma10_above_ma20_days += 1
        if ma5 is not None and ma10 is not None and ma5 > ma10:
            ma5_above_ma10_days += 1

    vol_slope20 = 0.0
    if len(volume20) >= 2:
        vol_slope20 = (volume20[-1] - volume20[0]) / max(volume20[0], 1)

    up_volume: list[int] = []
    down_volume: list[int] = []
    for idx in range(max(1, len(closes) - 20), len(closes)):
        if closes[idx] >= closes[idx - 1]:
            up_volume.append(volumes[idx])
        else:
            down_volume.append(volumes[idx])

    mean_up = _safe_mean(up_volume)
    mean_down = _safe_mean(down_volume)
    up_down_volume_ratio = mean_up / max(mean_down, 1.0)
    pullback_volume_ratio = (mean_down / max(_safe_mean(volume20), 1.0)) if down_volume else 0.6

    limit_up_days = 0
    for idx in range(max(1, len(closes) - 20), len(closes)):
        pct = (closes[idx] - closes[idx - 1]) / max(closes[idx - 1], 0.01)
        if pct >= 0.095:
            limit_up_days += 1

    trend_class: TrendClass
    if limit_up_days >= 2:
        trend_class = "B"
    elif ret_window >= 0.5:
        trend_class = "A_B"
    elif ret_window > 0:
        trend_class = "A"
    else:
        trend_class = "Unknown"

    stage: Stage
    if ret_window < 0.30:
        stage = "Early"
    elif ret_window <= 0.80:
        stage = "Mid"
    else:
        stage = "Late"

    theme_stage: ThemeStage
    if ret_window < 0.30:
        theme_stage = "发酵中"
    elif ret_window < 0.80 and up_down_volume_ratio >= 1.0:
        theme_stage = "高潮"
    else:
        theme_stage = "退潮"

    avg_volume20 = _safe_mean(volume20)
    has_blowoff_top = False
    for idx in range(start20, len(closes)):
        if volumes[idx] > avg_volume20 * 2.5 and closes[idx] <= opens[idx]:
            has_blowoff_top = True
            break

    has_divergence_5d = False
    if len(closes) >= 10:
        price_rise = closes[-1] > closes[-6]
        avg_v5 = _safe_mean(volumes[-5:])
        avg_prev5 = _safe_mean(volumes[-10:-5])
        has_divergence_5d = price_rise and avg_v5 < avg_prev5 * 0.9

    has_upper_shadow_risk = False
    for idx in range(max(0, len(closes) - 5), len(closes)):
        bar_range = highs[idx] - lows[idx]
        if bar_range <= 0:
            continue
        body_high = max(opens[idx], closes[idx])
        upper_shadow = highs[idx] - body_high
        if upper_shadow / bar_range > 0.5 and closes[idx] <= opens[idx]:
            has_upper_shadow_risk = True
            break

    score_raw = (
        45
        + ret_window * 90
        + up_down_volume_ratio * 8
        - pullback_volume_ratio * 15
        + max(0.0, (0.08 - abs(price_vs_ma20)) * 200)
    )
    score = int(round(_clamp(score_raw, 0, 100)))
    ai_confidence = round(
        _clamp(
            0.50 + ret_window * 0.30 + (up_down_volume_ratio - 1.0) * 0.10 - max(0.0, pullback_volume_ratio - 0.8) * 0.2,
            0.35,
            0.95,
        ),
        2,
    )

    labels = ["真实数据", "高波动" if trend_class == "B" else "趋势延续"]

    return ScreenerResult(
        symbol=series["symbol"],
        name=series["symbol"].upper(),
        latest_price=round(latest, 2),
        day_change=round(latest - prev, 2),
        day_change_pct=round((latest - prev) / max(prev, 0.01), 4),
        score=score,
        ret40=round(ret_window, 4),
        turnover20=round(turnover20, 4),
        amount20=float(_safe_mean(amount20)),
        amplitude20=round(amplitude20, 4),
        retrace20=round(retrace20, 4),
        pullback_days=_count_pullback_days(closes),
        ma10_above_ma20_days=ma10_above_ma20_days,
        ma5_above_ma10_days=ma5_above_ma10_days,
        price_vs_ma20=round(price_vs_ma20, 4),
        vol_slope20=round(vol_slope20, 4),
        up_down_volume_ratio=round(up_down_volume_ratio, 4),
        pullback_volume_ratio=round(pullback_volume_ratio, 4),
        has_blowoff_top=has_blowoff_top,
        has_divergence_5d=has_divergence_5d,
        has_upper_shadow_risk=has_upper_shadow_risk,
        ai_confidence=ai_confidence,
        theme_stage=theme_stage,
        trend_class=trend_class,
        stage=stage,
        labels=labels,
        reject_reasons=[],
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


def load_candles_for_symbol(
    tdx_root: str,
    symbol: str,
    window: int = 120,
    market_data_source: str = "tdx_then_akshare",
    akshare_cache_dir: str = "",
) -> list[CandlePoint] | None:
    if market_data_source not in {"tdx_only", "tdx_then_akshare", "akshare_only"}:
        market_data_source = "tdx_then_akshare"
    use_tdx = market_data_source in {"tdx_only", "tdx_then_akshare"}
    use_akshare = market_data_source in {"akshare_only", "tdx_then_akshare"}
    if not use_tdx:
        return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir) if use_akshare else None

    root = Path(tdx_root)
    if not root.exists() or len(symbol) < 8:
        if use_akshare:
            return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir)
        return None

    market = symbol[:2]
    market_dir = root / market / "lday"
    if not market_dir.exists():
        if use_akshare:
            return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir)
        return None

    file_path = market_dir / f"{symbol}.day"
    if not file_path.exists() and symbol[2:].isdigit():
        file_path = market_dir / f"{symbol[2:]}.day"
    if not file_path.exists():
        if use_akshare:
            return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir)
        return None

    parsed = _parse_day_file(file_path, symbol)
    if not parsed:
        if use_akshare:
            return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir)
        return None

    start = max(0, len(parsed["close"]) - window)
    points: list[CandlePoint] = []
    for i in range(start, len(parsed["close"])):
        points.append(
            CandlePoint(
                time=parsed["dates"][i],
                open=parsed["open"][i],
                high=parsed["high"][i],
                low=parsed["low"][i],
                close=parsed["close"][i],
                volume=parsed["volume"][i],
                amount=parsed["amount"][i],
                price_source="vwap",
            )
        )
    if points:
        return points
    if use_akshare:
        return _load_candles_from_akshare_cache(symbol, window, akshare_cache_dir)
    return None


def load_input_pool_from_tdx(
    tdx_root: str,
    markets: list[str],
    return_window_days: int,
    as_of_date: str | None = None,
) -> tuple[list[ScreenerResult], str | None]:
    root = Path(tdx_root)
    if not root.exists():
        return [], "TDX_PATH_NOT_FOUND"

    symbol_name_map = _load_symbol_name_map_from_tnf(tdx_root, markets)
    float_shares_map, float_shares_error = _load_float_shares_from_base_dbf(tdx_root, markets)
    rows: list[ScreenerResult] = []
    missing_float_shares = 0
    for market in markets:
        market_dir = root / market / "lday"
        if not market_dir.exists():
            continue

        for file_path in market_dir.glob("*.day"):
            symbol = _normalize_symbol(file_path.stem, market)
            if not symbol or not _is_a_share_symbol(symbol):
                continue
            parsed = _parse_day_file(file_path, symbol, max_bars=3000 if as_of_date else 360)
            if not parsed:
                continue
            row = _build_row(parsed, return_window_days, float_shares_map.get(symbol), as_of_date)
            if row:
                mapped_name = symbol_name_map.get(symbol)
                if mapped_name:
                    row = row.model_copy(update={"name": mapped_name})
                if row.degraded:
                    missing_float_shares += 1
                rows.append(row)

    if not rows:
        return [], "TDX_VALID_SERIES_NOT_FOUND"

    rows.sort(key=lambda item: item.ret40, reverse=True)

    if not float_shares_map:
        return rows, float_shares_error or "FLOAT_SHARES_NOT_FOUND"
    if missing_float_shares > 0:
        return rows, "PARTIAL_FLOAT_SHARES_MISSING"
    return rows, None


def _decode_lc1_date(raw_date: int) -> str | None:
    date_part = raw_date & 0x07FF
    year = (raw_date >> 11) + 2004
    month = date_part // 100
    day = date_part % 100
    if year < 2004 or not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _decode_lc1_time(raw_time: int) -> str | None:
    hour = raw_time // 60
    minute = raw_time % 60
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def load_intraday_for_symbol_date(
    tdx_root: str,
    symbol: str,
    target_date: str,
) -> tuple[list[IntradayPoint] | None, str | None]:
    root = Path(tdx_root)
    if not root.exists() or len(symbol) < 8:
        return None, None

    market = symbol[:2]
    market_dir = root / market / "minline"
    if not market_dir.exists():
        return None, None

    file_path = market_dir / f"{symbol}.lc1"
    if not file_path.exists() and symbol[2:].isdigit():
        file_path = market_dir / f"{symbol[2:]}.lc1"
    if not file_path.exists():
        return None, None

    try:
        raw = file_path.read_bytes()
    except OSError:
        return None, None

    if len(raw) < LC1_RECORD.size:
        return None, None

    by_date: dict[str, list[tuple[str, float, float, int]]] = {}
    for offset in range(0, len(raw), LC1_RECORD.size):
        chunk = raw[offset : offset + LC1_RECORD.size]
        if len(chunk) < LC1_RECORD.size:
            continue
        (
            raw_date,
            raw_time,
            _open_price,
            _high_price,
            _low_price,
            close_price,
            amount,
            volume,
            _reserved,
        ) = LC1_RECORD.unpack(chunk)

        date_text = _decode_lc1_date(raw_date)
        time_text = _decode_lc1_time(raw_time)
        if date_text is None or time_text is None:
            continue

        if close_price <= 0:
            continue

        by_date.setdefault(date_text, []).append(
            (time_text, float(close_price), float(amount), max(0, int(volume)))
        )

    if not by_date:
        return None, None

    selected_date = target_date if target_date and target_date in by_date else max(by_date.keys())
    day_rows = sorted(by_date[selected_date], key=lambda item: item[0])
    if not day_rows:
        return None, None

    points: list[IntradayPoint] = []
    turnover = 0.0
    total_volume = 0
    last_avg = day_rows[0][1]
    for time_text, close_price, amount, volume in day_rows:
        effective_amount = amount if amount > 0 else close_price * max(volume, 1)
        turnover += effective_amount
        total_volume += max(volume, 1)
        avg_price = turnover / max(total_volume, 1)
        last_avg = avg_price
        points.append(
            IntradayPoint(
                time=time_text,
                price=round(close_price, 2),
                avg_price=round(avg_price, 2),
                volume=max(volume, 0),
                price_source="vwap",
            )
        )

    if points:
        points[0] = points[0].model_copy(update={"avg_price": round(last_avg if len(points) == 1 else points[0].price, 2)})

    return points, selected_date
