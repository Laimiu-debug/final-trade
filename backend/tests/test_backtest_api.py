from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_STATE_ROOT = Path(tempfile.mkdtemp(prefix="backtest-api-state-"))
os.environ.setdefault("TDX_TREND_APP_STATE_PATH", str(TEST_STATE_ROOT / "app_state.json"))
os.environ.setdefault("TDX_TREND_SIM_STATE_PATH", str(TEST_STATE_ROOT / "sim_state.json"))
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_PATH", str(TEST_STATE_ROOT / "wyckoff_events.sqlite"))
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_ENABLED", "1")
os.environ.setdefault("TDX_TREND_WYCKOFF_STORE_READ_ONLY", "0")

from app.main import app
from app.models import ScreenerParams
from app.store import store

client = TestClient(app)


def _wait_backtest_task(task_id: str, timeout_sec: float = 180.0) -> dict:
    deadline = time.time() + timeout_sec
    last_payload: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/backtest/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        last_payload = body
        if body.get("status") in {"succeeded", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"回测任务超时未结束: task_id={task_id}, last={last_payload}")


def _load_symbol_dates(symbol: str) -> list[str]:
    resp = client.get(f"/api/stocks/{symbol}/candles")
    assert resp.status_code == 200
    candles = resp.json()["candles"]
    assert len(candles) >= 40
    return [item["time"] for item in candles]


def _create_trend_pool_run(as_of_date: str) -> str:
    run_payload = {
        "markets": ["sh", "sz"],
        "mode": "strict",
        "as_of_date": as_of_date,
        "return_window_days": 40,
        "top_n": 500,
        "turnover_threshold": 0.05,
        "amount_threshold": 500000000,
        "amplitude_threshold": 0.03,
    }
    run_resp = client.post("/api/screener/run", json=run_payload)
    assert run_resp.status_code == 200
    return str(run_resp.json()["run_id"])


def _detect_board(symbol: str) -> str:
    text = str(symbol).strip().lower()
    if len(text) < 8:
        return "unknown"
    market = text[:2]
    code = text[2:]
    if market == "bj":
        return "beijing"
    if market == "sh":
        if code.startswith("688") or code.startswith("689"):
            return "star"
        return "main"
    if market == "sz":
        if code.startswith("300") or code.startswith("301"):
            return "gem"
        return "main"
    return "unknown"


def test_backtest_run_trend_pool_smoke() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-35]
    date_to = dates[-8]
    run_id = _create_trend_pool_run(date_to)

    payload = {
        "mode": "trend_pool",
        "run_id": run_id,
        "trend_step": "auto",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "require_sequence": False,
        "min_event_count": 1,
        "entry_events": ["Spring", "SOS", "JOC", "LPS"],
        "exit_events": ["UTAD", "SOW", "LPSY"],
        "initial_capital": 1_000_000,
        "position_pct": 0.2,
        "max_positions": 5,
        "stop_loss": 0.05,
        "take_profit": 0.15,
        "max_hold_days": 60,
        "fee_bps": 8.0,
        "prioritize_signals": True,
        "priority_mode": "balanced",
        "priority_topk_per_day": 0,
        "enforce_t1": True,
        "max_symbols": 120,
        "pool_roll_mode": "weekly",
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert body["candidate_count"] >= body["stats"]["trade_count"]
    assert 0.0 <= body["fill_rate"] <= 1.0
    assert isinstance(body["notes"], list)
    assert isinstance(body["trades"], list)
    assert isinstance(body["equity_curve"], list)


def test_backtest_run_falls_back_when_run_missing() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-35]
    date_to = dates[-8]

    payload = {
        "mode": "trend_pool",
        "run_id": "missing-run-id",
        "trend_step": "auto",
        "pool_roll_mode": "position",
        "date_from": date_from,
        "date_to": date_to,
    }
    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["trades"], list)
    assert any("已改用系统筛选参数重建滚动池" in note for note in body["notes"])


def test_backtest_run_respects_board_filters() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-35]
    date_to = dates[-8]
    run_id = _create_trend_pool_run(date_to)

    detail_resp = client.get(f"/api/screener/runs/{run_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    source_rows = (
        detail.get("step_pools", {}).get("step4")
        or detail.get("step_pools", {}).get("step3")
        or detail.get("results")
        or []
    )
    assert source_rows
    source_symbols = [str(row["symbol"]) for row in source_rows if row.get("symbol")]
    assert source_symbols
    selected_board = next(
        (
            board
            for board in ("main", "gem", "star", "beijing")
            if any(_detect_board(symbol) == board for symbol in source_symbols)
        ),
        "main",
    )

    payload = {
        "mode": "trend_pool",
        "run_id": run_id,
        "trend_step": "auto",
        "board_filters": [selected_board],
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "require_sequence": False,
        "min_event_count": 1,
        "entry_events": ["Spring", "SOS", "JOC", "LPS"],
        "exit_events": ["UTAD", "SOW", "LPSY"],
        "initial_capital": 1_000_000,
        "position_pct": 0.2,
        "max_positions": 5,
        "stop_loss": 0.05,
        "take_profit": 0.15,
        "max_hold_days": 60,
        "fee_bps": 8.0,
        "prioritize_signals": True,
        "priority_mode": "balanced",
        "priority_topk_per_day": 0,
        "enforce_t1": True,
        "max_symbols": 120,
        "pool_roll_mode": "weekly",
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert any("候选池板块过滤" in note for note in body["notes"])
    for row in body["trades"]:
        assert _detect_board(row["symbol"]) == selected_board


def test_backtest_task_full_market_daily_smoke() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-18]
    date_to = dates[-14]

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
        "priority_topk_per_day": 0,
    }

    start_resp = client.post("/api/backtest/tasks", json=payload)
    assert start_resp.status_code == 200
    task_id = str(start_resp.json()["task_id"])
    assert task_id.startswith("bt_")

    task = _wait_backtest_task(task_id)
    assert task["status"] == "succeeded"
    progress = task["progress"]
    assert progress["total_dates"] >= 1
    assert progress["processed_dates"] >= progress["total_dates"]
    result = task["result"]
    assert result["range"]["date_from"] == date_from
    assert result["range"]["date_to"] == date_to
    assert any("全市场候选池构建" in note for note in result["notes"])


def test_backtest_task_full_market_weekly_smoke() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-28]
    date_to = dates[-12]

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "weekly",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    start_resp = client.post("/api/backtest/tasks", json=payload)
    assert start_resp.status_code == 200
    task_id = str(start_resp.json()["task_id"])

    task = _wait_backtest_task(task_id)
    assert task["status"] == "succeeded"
    progress = task["progress"]
    assert progress["mode"] == "weekly"
    assert progress["processed_dates"] >= 1
    result = task["result"]
    assert result["range"]["date_from"] == date_from
    assert result["range"]["date_to"] == date_to
    assert any("全市场候选池构建: 每周滚动" in note for note in result["notes"])


def test_backtest_run_full_market_reports_system_limit_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-16]
    date_to = dates[-14]

    monkeypatch.setattr(store, "_FULL_MARKET_SYSTEM_PROTECT_LIMIT", 5)
    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 120,
    }
    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert any("触发系统保护上限" in note for note in body["notes"])


def test_backtest_run_full_market_position_mode() -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-20]
    date_to = dates[-14]

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "position",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert any("持仓触发滚动" in note for note in body["notes"])


def test_backtest_task_rejects_when_candle_coverage_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_scan_dates(_: str, __: str) -> list[str]:
        return ["2025-01-02", "2025-01-03"]

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        return ["sz300750", "sh600519"], {}, [], ["2025-01-02", "2025-01-03"], ["2025-01-02"]

    def _fake_candles(_: str):
        return [
            SimpleNamespace(time="2025-11-03"),
            SimpleNamespace(time="2026-02-13"),
        ]

    monkeypatch.setattr(store, "_build_backtest_scan_dates", _fake_scan_dates)
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)
    monkeypatch.setattr(store, "_ensure_candles", _fake_candles)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 120,
    }

    resp = client.post("/api/backtest/tasks", json=payload)
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "BACKTEST_DATA_COVERAGE_INSUFFICIENT"
    assert "2025-01-01" in body["message"]
    assert "2025-11-03" in body["message"]


def test_backtest_run_full_market_daily_matrix_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-10]
    date_to = dates[-6]

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        return ["sz300750"], allowed, ["mock matrix universe"], scan_dates, scan_dates

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert any("矩阵引擎已启用" in note for note in body["notes"])


def test_backtest_run_full_market_position_matrix_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-20]
    date_to = dates[-12]

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        refresh_dates = kwargs.get("refresh_dates")
        refresh_used = list(refresh_dates) if refresh_dates else [scan_dates[0]]
        return ["sz300750"], allowed, ["mock position matrix universe"], scan_dates, refresh_used

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "position",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert any("矩阵引擎已启用" in note for note in body["notes"])


def test_backtest_run_full_market_weekly_matrix_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-20]
    date_to = dates[-12]

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        refresh_dates = kwargs.get("refresh_dates")
        refresh_used = list(refresh_dates) if refresh_dates else store._build_weekly_refresh_dates(scan_dates)
        return ["sz300750"], allowed, ["mock weekly matrix universe"], scan_dates, refresh_used

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "weekly",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert any("矩阵引擎已启用" in note for note in body["notes"])


def test_backtest_run_trend_pool_weekly_matrix_path(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = _load_symbol_dates("sz300750")
    date_from = dates[-20]
    date_to = dates[-12]

    def _fake_resolve(run_id: str):  # noqa: ANN001
        params = ScreenerParams(
            markets=["sh", "sz"],
            mode="strict",
            as_of_date=date_to,
            return_window_days=40,
            top_n=500,
            turnover_threshold=0.05,
            amount_threshold=500000000,
            amplitude_threshold=0.03,
        )
        return params, run_id, None, None

    def _fake_build(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        refresh_dates = kwargs.get("refresh_dates")
        if refresh_dates:
            refresh_used = list(refresh_dates)
        else:
            refresh_used = store._build_weekly_refresh_dates(scan_dates)
        return ["sz300750"], allowed, ["mock trend_pool matrix universe"], scan_dates, refresh_used

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setattr(store, "_resolve_backtest_trend_pool_params", _fake_resolve)
    monkeypatch.setattr(store, "_build_trend_pool_rolling_universe", _fake_build)

    payload = {
        "mode": "trend_pool",
        "run_id": "mock-run",
        "pool_roll_mode": "weekly",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp = client.post("/api/backtest/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"]["date_from"] == date_from
    assert body["range"]["date_to"] == date_to
    assert any("矩阵引擎已启用" in note for note in body["notes"])
    assert any("使用筛选任务: mock-run" in note for note in body["notes"])
