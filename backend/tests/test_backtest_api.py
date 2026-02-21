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
import app.store as store_module
from app.models import BacktestResponse, BacktestRunRequest, ReviewRange, ReviewStats, ScreenerParams, ScreenerResult
from app.store import BacktestValidationError, store

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
        if body.get("status") in {"succeeded", "failed", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"task timeout: task_id={task_id}, last={last_payload}")


def _wait_backtest_task_status(task_id: str, expected: set[str], timeout_sec: float = 30.0) -> dict:
    deadline = time.time() + timeout_sec
    last_payload: dict | None = None
    while time.time() < deadline:
        resp = client.get(f"/api/backtest/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        last_payload = body
        if body.get("status") in expected:
            return body
        time.sleep(0.05)
    raise AssertionError(f"task status wait timeout: task_id={task_id}, expected={expected}, last={last_payload}")


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


def test_backtest_plateau_endpoint_handles_truncation_and_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run_backtest(payload, *, progress_callback=None, control_callback=None):  # noqa: ANN001
        _ = (progress_callback, control_callback)
        if float(payload.min_score) >= 58.0:
            raise ValueError("mock failure for plateau")
        total_return = float(payload.min_score) / 100.0
        return BacktestResponse(
            stats=ReviewStats(
                win_rate=0.55,
                total_return=total_return,
                max_drawdown=-0.12,
                avg_pnl_ratio=0.03,
                trade_count=12,
                win_count=7,
                loss_count=5,
                profit_factor=1.4,
            ),
            trades=[],
            range=ReviewRange(date_from=payload.date_from, date_to=payload.date_to, date_axis="sell"),
            notes=[],
            candidate_count=120,
            skipped_count=8,
            fill_rate=0.75,
            max_concurrent_positions=int(payload.max_positions),
        )

    monkeypatch.setattr(store, "run_backtest", _fake_run_backtest)

    base_payload = {
        "mode": "full_market",
        "run_id": "",
        "trend_step": "auto",
        "pool_roll_mode": "daily",
        "board_filters": [],
        "date_from": "2025-01-02",
        "date_to": "2025-03-31",
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
        "take_profit": 0.2,
        "max_hold_days": 30,
        "fee_bps": 8.0,
        "prioritize_signals": True,
        "priority_mode": "balanced",
        "priority_topk_per_day": 10,
        "enforce_t1": True,
        "max_symbols": 100,
    }
    payload = {
        "base_payload": base_payload,
        "sampling_mode": "grid",
        "window_days_list": [40, 60],
        "min_score_list": [55, 58],
        "max_points": 3,
    }
    resp = client.post("/api/backtest/plateau", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_combinations"] == 4
    assert body["evaluated_combinations"] == 3
    assert len(body["points"]) == 3
    assert body["best_point"] is not None
    assert any("参数组合总数" in note for note in body["notes"])
    assert any("参数评估失败" in note for note in body["notes"])
    assert sum(1 for point in body["points"] if point.get("error")) >= 1


def test_backtest_plateau_endpoint_lhs_sampling_is_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_run_backtest(payload, *, progress_callback=None, control_callback=None):  # noqa: ANN001
        _ = (progress_callback, control_callback)
        score_raw = (
            float(payload.min_score) * 0.4
            + float(payload.take_profit) * 100.0
            - float(payload.stop_loss) * 120.0
            + float(payload.position_pct) * 20.0
        )
        total_return = round(score_raw / 100.0, 6)
        return BacktestResponse(
            stats=ReviewStats(
                win_rate=0.52,
                total_return=total_return,
                max_drawdown=-0.1,
                avg_pnl_ratio=0.025,
                trade_count=10,
                win_count=5,
                loss_count=5,
                profit_factor=1.2,
            ),
            trades=[],
            range=ReviewRange(date_from=payload.date_from, date_to=payload.date_to, date_axis="sell"),
            notes=[],
            candidate_count=80,
            skipped_count=6,
            fill_rate=0.7,
            max_concurrent_positions=int(payload.max_positions),
        )

    monkeypatch.setattr(store, "run_backtest", _fake_run_backtest)

    base_payload = {
        "mode": "full_market",
        "run_id": "",
        "trend_step": "auto",
        "pool_roll_mode": "daily",
        "board_filters": [],
        "date_from": "2025-01-02",
        "date_to": "2025-02-28",
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
        "take_profit": 0.2,
        "max_hold_days": 30,
        "fee_bps": 8.0,
        "prioritize_signals": True,
        "priority_mode": "balanced",
        "priority_topk_per_day": 10,
        "enforce_t1": True,
        "max_symbols": 100,
    }
    payload = {
        "base_payload": base_payload,
        "sampling_mode": "lhs",
        "sample_points": 12,
        "random_seed": 20260221,
        "window_days_list": [40, 120],
        "min_score_list": [50, 70],
        "stop_loss_list": [0.03, 0.08],
        "take_profit_list": [0.1, 0.4],
        "max_positions_list": [3, 10],
        "position_pct_list": [0.1, 0.4],
        "max_symbols_list": [80, 300],
        "priority_topk_per_day_list": [0, 20],
    }

    resp1 = client.post("/api/backtest/plateau", json=payload)
    assert resp1.status_code == 200
    body1 = resp1.json()
    resp2 = client.post("/api/backtest/plateau", json=payload)
    assert resp2.status_code == 200
    body2 = resp2.json()

    assert body1["total_combinations"] == 12
    assert body1["evaluated_combinations"] == 12
    assert len(body1["points"]) == 12
    assert body1["points"] == body2["points"]
    assert any("参数采样模式: lhs" in note for note in body1["notes"])
    assert any("LHS 随机种子: 20260221" in note for note in body1["notes"])


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


def test_backtest_task_supports_pause_resume_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_precheck(payload):  # noqa: ANN001
        return None

    def _fake_total_dates(payload):  # noqa: ANN001
        return 120

    def _fake_run_backtest(payload, *, progress_callback=None, control_callback=None):  # noqa: ANN001
        total = 120
        for idx in range(total):
            if control_callback is not None:
                control_callback()
            if progress_callback is not None:
                progress_callback(
                    f"2025-01-{(idx % 28) + 1:02d}",
                    idx + 1,
                    total,
                    f"fake progress {idx + 1}/{total}",
                )
            time.sleep(0.01)
        return BacktestResponse(
            stats=ReviewStats(
                win_rate=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                avg_pnl_ratio=0.0,
                trade_count=0,
                win_count=0,
                loss_count=0,
                profit_factor=0.0,
            ),
            trades=[],
            range=ReviewRange(date_from=payload.date_from, date_to=payload.date_to, date_axis="sell"),
        )

    monkeypatch.setattr(store, "_precheck_backtest_data_coverage_before_task", _fake_precheck)
    monkeypatch.setattr(store, "_estimate_backtest_progress_total_dates", _fake_total_dates)
    monkeypatch.setattr(store, "run_backtest", _fake_run_backtest)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    start_resp = client.post("/api/backtest/tasks", json=payload)
    assert start_resp.status_code == 200
    task_id = str(start_resp.json()["task_id"])

    running = _wait_backtest_task_status(task_id, {"running"})
    assert running["status"] == "running"

    pause_resp = client.post(f"/api/backtest/tasks/{task_id}/pause")
    assert pause_resp.status_code == 200
    paused = pause_resp.json()
    assert paused["status"] == "paused"
    paused_processed = int(paused["progress"]["processed_dates"])
    time.sleep(0.15)
    paused_after = client.get(f"/api/backtest/tasks/{task_id}").json()
    assert paused_after["status"] == "paused"
    assert int(paused_after["progress"]["processed_dates"]) <= paused_processed + 1

    resume_resp = client.post(f"/api/backtest/tasks/{task_id}/resume")
    assert resume_resp.status_code == 200
    resumed = resume_resp.json()
    assert resumed["status"] in {"pending", "running"}

    _wait_backtest_task_status(task_id, {"running"})

    cancel_resp = client.post(f"/api/backtest/tasks/{task_id}/cancel")
    assert cancel_resp.status_code == 200
    cancelled = cancel_resp.json()
    assert cancelled["status"] == "cancelled"

    final = _wait_backtest_task_status(task_id, {"cancelled"})
    assert final["status"] == "cancelled"


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


def test_backtest_task_async_precheck_fails_in_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    call_counter = {"precheck": 0, "run": 0}

    def _fake_precheck(payload):  # noqa: ANN001
        _ = payload
        call_counter["precheck"] += 1
        raise BacktestValidationError("BACKTEST_DATA_COVERAGE_INSUFFICIENT", "mock coverage insufficient")

    def _fake_run_backtest(payload, *, progress_callback=None, control_callback=None):  # noqa: ANN001
        _ = (payload, progress_callback, control_callback)
        call_counter["run"] += 1
        return BacktestResponse(
            stats=ReviewStats(
                win_rate=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                avg_pnl_ratio=0.0,
                trade_count=0,
                win_count=0,
                loss_count=0,
                profit_factor=0.0,
            ),
            trades=[],
            range=ReviewRange(date_from="2025-01-01", date_to="2025-01-02", date_axis="sell"),
        )

    monkeypatch.setenv("TDX_TREND_BACKTEST_TASK_PRECHECK_ASYNC", "1")
    monkeypatch.setattr(store, "_run_backtest_precheck_with_cache", _fake_precheck)
    monkeypatch.setattr(store, "run_backtest", _fake_run_backtest)

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": "2025-01-01",
        "date_to": "2025-01-02",
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    start_resp = client.post("/api/backtest/tasks", json=payload)
    assert start_resp.status_code == 200
    task_id = str(start_resp.json()["task_id"])

    final = _wait_backtest_task(task_id, timeout_sec=20.0)
    assert final["status"] == "failed"
    assert final["error_code"] == "BACKTEST_DATA_COVERAGE_INSUFFICIENT"
    assert "mock coverage insufficient" in str(final.get("error") or "")
    assert call_counter["precheck"] == 1
    assert call_counter["run"] == 0


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


def test_backtest_run_matrix_signal_runtime_cache_reuses_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.backtest_signal_matrix import compute_backtest_signal_matrix as _real_compute

    dates = _load_symbol_dates("sz300750")
    date_from = dates[-10]
    date_to = dates[-6]
    call_counter = {"count": 0}

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        return ["sz300750"], allowed, ["mock matrix universe"], scan_dates, scan_dates

    def _fake_compute(bundle, *, top_n=500):  # noqa: ANN001
        call_counter["count"] += 1
        return _real_compute(bundle, top_n=top_n)

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_RESULT_CACHE", "0")
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_RUNTIME_CACHE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_DISK_CACHE", "0")
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)
    monkeypatch.setattr(store_module, "compute_backtest_signal_matrix", _fake_compute)

    store._backtest_matrix_engine.clear_runtime_cache()
    store._clear_backtest_signal_matrix_runtime_cache()

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp1 = client.post("/api/backtest/run", json=payload)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert any("signal_cache=miss" in note for note in body1["notes"])

    resp2 = client.post("/api/backtest/run", json=payload)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert any("signal_cache=runtime" in note for note in body2["notes"])
    assert call_counter["count"] == 1


def test_backtest_run_matrix_signal_disk_cache_reuses_signals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core.backtest_signal_matrix import compute_backtest_signal_matrix as _real_compute

    dates = _load_symbol_dates("sz300750")
    date_from = dates[-10]
    date_to = dates[-6]
    call_counter = {"count": 0}

    def _fake_universe(*args, **kwargs):  # noqa: ANN002, ANN003
        scan_dates = store._build_backtest_scan_dates(date_from, date_to)
        allowed = {day: {"sz300750"} for day in scan_dates}
        return ["sz300750"], allowed, ["mock matrix universe"], scan_dates, scan_dates

    def _fake_compute(bundle, *, top_n=500):  # noqa: ANN001
        call_counter["count"] += 1
        return _real_compute(bundle, top_n=top_n)

    monkeypatch.setenv("TDX_TREND_BACKTEST_MATRIX_ENGINE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_RESULT_CACHE", "0")
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_RUNTIME_CACHE", "0")
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_DISK_CACHE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_CACHE_DIR", str(tmp_path / "signal-matrix-cache"))
    monkeypatch.setenv("TDX_TREND_BACKTEST_SIGNAL_MATRIX_CACHE_TTL_SEC", "3600")
    monkeypatch.setattr(store, "_build_full_market_rolling_universe", _fake_universe)
    monkeypatch.setattr(store_module, "compute_backtest_signal_matrix", _fake_compute)

    store._clear_backtest_signal_matrix_runtime_cache()

    payload = {
        "mode": "full_market",
        "pool_roll_mode": "daily",
        "date_from": date_from,
        "date_to": date_to,
        "window_days": 60,
        "min_score": 55,
        "max_symbols": 20,
    }

    resp1 = client.post("/api/backtest/run", json=payload)
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert any("signal_cache=miss" in note for note in body1["notes"])

    resp2 = client.post("/api/backtest/run", json=payload)
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert any("signal_cache=disk" in note for note in body2["notes"])
    assert call_counter["count"] == 1


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


def test_backtest_input_pool_disk_cache_reuses_refresh_day_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TDX_TREND_BACKTEST_INPUT_POOL_CACHE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_INPUT_POOL_CACHE_DIR", str(tmp_path / "input-pool-cache"))
    monkeypatch.setenv("TDX_TREND_BACKTEST_INPUT_POOL_CACHE_TTL_SEC", "3600")
    call_counter = {"count": 0}

    def _fake_loader(
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        as_of_date: str | None = None,
    ) -> tuple[list[ScreenerResult], str | None]:
        _ = (tdx_root, markets, return_window_days)
        call_counter["count"] += 1
        day = str(as_of_date or "2025-01-02")
        row = ScreenerResult(
            symbol="sz300750",
            name="宁德时代",
            latest_price=10.0,
            day_change=0.1,
            day_change_pct=0.01,
            score=80,
            ret40=0.25,
            turnover20=0.08,
            amount20=8e8,
            amplitude20=0.05,
            retrace20=0.03,
            pullback_days=3,
            ma10_above_ma20_days=8,
            ma5_above_ma10_days=6,
            price_vs_ma20=0.06,
            vol_slope20=0.1,
            up_down_volume_ratio=1.4,
            pullback_volume_ratio=0.7,
            has_blowoff_top=False,
            has_divergence_5d=False,
            has_upper_shadow_risk=False,
            ai_confidence=0.7,
            theme_stage="发酵中",
            trend_class="A",
            stage="Mid",
            labels=[day],
            reject_reasons=[],
            degraded=False,
            degraded_reason=None,
        )
        return [row], None

    monkeypatch.setattr(store_module, "load_input_pool_from_tdx", _fake_loader)

    refresh_dates = ["2025-01-02", "2025-01-03"]
    rows1, stats1 = store._load_backtest_input_rows_by_dates(
        tdx_root="D:/new_tdx/vipdoc",
        markets=["sh", "sz"],
        return_window_days=40,
        refresh_dates=refresh_dates,
    )
    assert call_counter["count"] == 2
    assert stats1["cache_hit_days"] == 0
    assert stats1["cache_miss_days"] == 2
    assert stats1["cache_write_days"] == 2
    assert all(len(items[0]) == 1 for items in rows1.values())

    rows2, stats2 = store._load_backtest_input_rows_by_dates(
        tdx_root="D:/new_tdx/vipdoc",
        markets=["sh", "sz"],
        return_window_days=40,
        refresh_dates=refresh_dates,
    )
    assert call_counter["count"] == 2
    assert stats2["cache_hit_days"] == 2
    assert stats2["cache_miss_days"] == 0
    assert stats2["cache_write_days"] == 0
    assert all(len(items[0]) == 1 for items in rows2.values())


def test_trend_pool_rolling_universe_reuses_trend_filter_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TDX_TREND_BACKTEST_TREND_FILTER_CACHE", "1")
    monkeypatch.setenv(
        "TDX_TREND_BACKTEST_TREND_FILTER_CACHE_DIR",
        str(tmp_path / "trend-filter-cache"),
    )
    monkeypatch.setenv("TDX_TREND_BACKTEST_TREND_FILTER_CACHE_TTL_SEC", "3600")

    calls = {"loader": 0, "filters": 0}

    def _build_row(day: str) -> ScreenerResult:
        return ScreenerResult(
            symbol="sz300750",
            name="宁德时代",
            latest_price=10.0,
            day_change=0.1,
            day_change_pct=0.01,
            score=80,
            ret40=0.25,
            turnover20=0.08,
            amount20=8e8,
            amplitude20=0.05,
            retrace20=0.03,
            pullback_days=3,
            ma10_above_ma20_days=8,
            ma5_above_ma10_days=6,
            price_vs_ma20=0.06,
            vol_slope20=0.1,
            up_down_volume_ratio=1.4,
            pullback_volume_ratio=0.7,
            has_blowoff_top=False,
            has_divergence_5d=False,
            has_upper_shadow_risk=False,
            ai_confidence=0.7,
            theme_stage="发酵中",
            trend_class="A",
            stage="Mid",
            labels=[day],
            reject_reasons=[],
            degraded=False,
            degraded_reason=None,
        )

    def _fake_load_backtest_input_rows_by_dates(
        *,
        tdx_root: str,
        markets: list[str],
        return_window_days: int,
        refresh_dates: list[str],
        progress_callback=None,
    ) -> tuple[dict[str, tuple[list[object], str | None]], dict[str, int]]:
        _ = (tdx_root, markets, return_window_days, progress_callback)
        calls["loader"] += 1
        rows_by_date: dict[str, tuple[list[object], str | None]] = {}
        for day in refresh_dates:
            rows_by_date[day] = ([_build_row(day)], None)
        return rows_by_date, {"cache_hit_days": 0, "cache_miss_days": len(refresh_dates), "cache_write_days": 0}

    def _fake_run_filters(
        rows: list[ScreenerResult],
        params: ScreenerParams,
    ) -> tuple[list[ScreenerResult], list[ScreenerResult], list[ScreenerResult], list[ScreenerResult]]:
        _ = params
        calls["filters"] += 1
        return list(rows), list(rows), list(rows), list(rows)

    monkeypatch.setattr(store, "_load_backtest_input_rows_by_dates", _fake_load_backtest_input_rows_by_dates)
    monkeypatch.setattr(store, "_run_screener_filters_for_backtest", staticmethod(_fake_run_filters))

    payload = BacktestRunRequest(
        mode="trend_pool",
        trend_step="step1",
        pool_roll_mode="daily",
        date_from="2025-01-02",
        date_to="2025-01-03",
        max_symbols=30,
    )
    screener_params = ScreenerParams(
        markets=["sh", "sz"],
        mode="strict",
        as_of_date=None,
        return_window_days=40,
        top_n=500,
        turnover_threshold=0.05,
        amount_threshold=5e8,
        amplitude_threshold=0.03,
    )

    _, _, notes1, _, _ = store._build_trend_pool_rolling_universe(
        payload=payload,
        screener_params=screener_params,
        board_filters=[],
    )
    assert calls["loader"] == 1
    assert calls["filters"] == 2
    assert any("趋势快照缓存" in note for note in notes1)

    _, _, notes2, _, _ = store._build_trend_pool_rolling_universe(
        payload=payload,
        screener_params=screener_params,
        board_filters=[],
    )
    assert calls["loader"] == 1
    assert calls["filters"] == 2
    assert any("趋势快照缓存: hit 2 / miss 0 / write 0" in note for note in notes2)


def test_backtest_result_cache_reuses_persisted_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TDX_TREND_BACKTEST_RESULT_CACHE", "1")
    monkeypatch.setenv("TDX_TREND_BACKTEST_RESULT_CACHE_DIR", str(tmp_path / "backtest-result-cache"))
    monkeypatch.setenv("TDX_TREND_BACKTEST_RESULT_CACHE_TTL_SEC", "3600")

    call_counter = {"matrix": 0}

    def _fake_matrix_run(
        *,
        payload: BacktestRunRequest,
        board_filters: list[str],
        progress_callback=None,
        control_callback=None,
    ) -> BacktestResponse:
        _ = (board_filters, control_callback)
        call_counter["matrix"] += 1
        if progress_callback is not None:
            progress_callback(payload.date_to, 1, 1, "mock matrix")
        return BacktestResponse(
            stats=ReviewStats(
                win_rate=0.5,
                total_return=0.12,
                max_drawdown=-0.08,
                avg_pnl_ratio=0.03,
                trade_count=4,
                win_count=2,
                loss_count=2,
                profit_factor=1.2,
            ),
            trades=[],
            range=ReviewRange(date_from=payload.date_from, date_to=payload.date_to, date_axis="sell"),
            notes=["mock matrix result"],
            candidate_count=8,
            skipped_count=2,
            fill_rate=0.5,
            max_concurrent_positions=2,
        )

    monkeypatch.setattr(store, "_is_backtest_matrix_engine_enabled", lambda: True)
    monkeypatch.setattr(store, "_run_backtest_matrix", _fake_matrix_run)

    payload = BacktestRunRequest(
        mode="full_market",
        pool_roll_mode="daily",
        date_from="2025-01-02",
        date_to="2025-01-03",
        window_days=60,
        min_score=55,
        max_symbols=20,
    )

    first = store.run_backtest(payload)
    assert call_counter["matrix"] == 1
    assert all("回测结果缓存命中" not in note for note in first.notes)

    second = store.run_backtest(payload)
    assert call_counter["matrix"] == 1
    assert any("回测结果缓存命中" in note for note in second.notes)

