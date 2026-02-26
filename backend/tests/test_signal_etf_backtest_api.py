from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_STATE_ROOT = ROOT / ".test-state"
TEST_STATE_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TDX_TREND_APP_STATE_PATH", str(TEST_STATE_ROOT / "app_state.json"))
os.environ.setdefault("TDX_TREND_SIM_STATE_PATH", str(TEST_STATE_ROOT / "sim_state.json"))
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_PATH", str(TEST_STATE_ROOT / "wyckoff_events.sqlite"))
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_ENABLED", "1")
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_READ_ONLY", "0")

from app.main import app
from app.models import CandlePoint
from app.store import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_signal_etf_store() -> None:
    store._signal_etf_backtest_store = {}
    yield
    store._signal_etf_backtest_store = {}


@pytest.fixture
def patch_signal_etf_candles(monkeypatch: pytest.MonkeyPatch):
    dates = [
        "2026-02-03",
        "2026-02-04",
        "2026-02-05",
        "2026-02-06",
        "2026-02-07",
        "2026-02-10",
    ]

    def _build(base_open: float, daily_step: float) -> list[CandlePoint]:
        out: list[CandlePoint] = []
        for idx, day in enumerate(dates):
            open_price = base_open + daily_step * idx
            close_price = open_price * (1 + 0.01 * ((idx % 3) - 1))
            out.append(
                CandlePoint(
                    time=day,
                    open=round(open_price, 2),
                    high=round(open_price * 1.02, 2),
                    low=round(open_price * 0.98, 2),
                    close=round(close_price, 2),
                    volume=1_000_000,
                    amount=round(close_price * 1_000_000, 2),
                    price_source="vwap",
                )
            )
        return out

    candles_map = {
        "sz300750": _build(100, 1.5),
        "sh600519": _build(200, 1.2),
        "sh000300": _build(300, 0.8),
    }

    def _fake_load_signal_etf_candles(
        symbol: str,
        *,
        window_bars: int,
        candle_cache: dict[str, list[CandlePoint]],
    ) -> list[CandlePoint]:
        _ = window_bars
        key = symbol.strip().lower()
        if key in candle_cache:
            return candle_cache[key]
        rows = [item.model_copy(deep=True) for item in candles_map.get(key, [])]
        candle_cache[key] = rows
        return rows

    monkeypatch.setattr(store, "_load_signal_etf_candles", _fake_load_signal_etf_candles)
    return dates


def _build_create_payload() -> dict[str, object]:
    return {
        "strategy_id": "wyckoff_trend_v1",
        "strategy_name": "趋势策略A",
        "signal_date": "2026-02-03",
        "constituents": [
            {
                "symbol": "sz300750",
                "name": "宁德时代",
                "signal_date": "2026-02-03",
                "signal_primary": "B",
                "signal_event": "SOS",
                "signal_reason": "测试信号1",
            },
            {
                "symbol": "sh600519",
                "name": "贵州茅台",
                "signal_date": "2026-02-03",
                "signal_primary": "A",
                "signal_event": "LPS",
                "signal_reason": "测试信号2",
            },
        ],
    }


def test_signal_etf_backtest_crud_flow(patch_signal_etf_candles) -> None:
    _ = patch_signal_etf_candles
    create_resp = client.post("/api/signals/etf-backtests", json=_build_create_payload())
    assert create_resp.status_code == 200
    created = create_resp.json()
    record_id = created["record_id"]
    assert record_id.startswith("setf_")
    assert created["name"] == "趋势策略A_2026-02-03"
    assert len(created["constituents"]) == 2

    list_resp = client.get("/api/signals/etf-backtests")
    assert list_resp.status_code == 200
    list_body = list_resp.json()
    assert len(list_body["items"]) == 1
    assert list_body["items"][0]["summary"]["strategy_stats"]["total_records"] == 1

    detail_resp = client.get(f"/api/signals/etf-backtests/{record_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["record_id"] == record_id
    assert len(detail["curve"]) > 0

    patch_resp = client.patch(
        f"/api/signals/etf-backtests/{record_id}",
        json={"name": "自定义ETF名称", "notes": "这是备注"},
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["name"] == "自定义ETF名称"
    assert patched["notes"] == "这是备注"

    delete_resp = client.delete(f"/api/signals/etf-backtests/{record_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    list_after_delete = client.get("/api/signals/etf-backtests")
    assert list_after_delete.status_code == 200
    assert list_after_delete.json()["items"] == []


def test_signal_etf_backtest_duplicate_name_suffix_and_strategy_stats(patch_signal_etf_candles) -> None:
    _ = patch_signal_etf_candles
    payload = _build_create_payload()

    first = client.post("/api/signals/etf-backtests", json=payload)
    second = client.post("/api/signals/etf-backtests", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["record_id"] != second.json()["record_id"]
    assert second.json()["name"] == "趋势策略A_2026-02-03-2"

    listed = client.get("/api/signals/etf-backtests")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 2
    names = {item["name"] for item in items}
    assert "趋势策略A_2026-02-03" in names
    assert "趋势策略A_2026-02-03-2" in names
    for row in items:
        stats = row["summary"]["strategy_stats"]
        assert stats["total_records"] == 2
        assert 0.0 <= stats["win_rate_t1"] <= 1.0
        assert 0.0 <= stats["win_rate_t2"] <= 1.0
