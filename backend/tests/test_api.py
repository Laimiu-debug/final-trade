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

from app.main import app
from app.store import store
from app.tdx_loader import load_candles_for_symbol


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_sim_account() -> None:
    resp = client.post("/api/sim/reset")
    assert resp.status_code == 200


def _load_symbol_dates(symbol: str) -> list[str]:
    resp = client.get(f"/api/stocks/{symbol}/candles")
    assert resp.status_code == 200
    candles = resp.json()["candles"]
    assert len(candles) >= 10
    return [item["time"] for item in candles]


def _post_buy(symbol: str, submit_date: str, quantity: int = 100) -> dict[str, object]:
    payload = {
        "symbol": symbol,
        "side": "buy",
        "quantity": quantity,
        "signal_date": submit_date,
        "submit_date": submit_date,
    }
    resp = client.post("/api/sim/orders", json=payload)
    assert resp.status_code == 200
    return resp.json()["order"]


def _post_sell(symbol: str, submit_date: str, quantity: int = 100) -> dict[str, object]:
    payload = {
        "symbol": symbol,
        "side": "sell",
        "quantity": quantity,
        "signal_date": submit_date,
        "submit_date": submit_date,
    }
    resp = client.post("/api/sim/orders", json=payload)
    assert resp.status_code == 200
    return resp.json()["order"]


def test_load_candles_fallback_to_akshare_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_file = tmp_path / "sz300750.csv"
    cache_file.write_text(
        "\n".join(
            [
                "date,open,high,low,close,volume,amount,symbol",
                "2026-02-10,100,101,99,100.5,123400,123450000,sz300750",
                "2026-02-11,101,102,100,101.5,133400,135450000,sz300750",
                "2026-02-12,102,103,101,102.5,143400,147450000,sz300750",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AKSHARE_CACHE_DIR", str(tmp_path))
    candles = load_candles_for_symbol(r"Z:\not-exists\vipdoc", "sz300750", window=2)
    assert candles is not None
    assert len(candles) == 2
    assert candles[-1].time == "2026-02-12"
    assert candles[-1].price_source == "approx"


def test_load_candles_with_configured_data_source(tmp_path: Path) -> None:
    cache_file = tmp_path / "sz300750.csv"
    cache_file.write_text(
        "\n".join(
            [
                "date,open,high,low,close,volume,amount,symbol",
                "2026-02-12,102,103,101,102.5,143400,147450000,sz300750",
            ]
        ),
        encoding="utf-8",
    )
    candles = load_candles_for_symbol(
        r"Z:\not-exists\vipdoc",
        "sz300750",
        window=1,
        market_data_source="akshare_only",
        akshare_cache_dir=str(tmp_path),
    )
    assert candles is not None
    assert len(candles) == 1
    assert candles[-1].time == "2026-02-12"

    candles_tdx_only = load_candles_for_symbol(
        r"Z:\not-exists\vipdoc",
        "sz300750",
        window=1,
        market_data_source="tdx_only",
        akshare_cache_dir=str(tmp_path),
    )
    assert candles_tdx_only is None


def test_run_and_get_screener() -> None:
    payload = {
        "markets": ["sh", "sz"],
        "mode": "strict",
        "return_window_days": 40,
        "top_n": 500,
        "turnover_threshold": 0.05,
        "amount_threshold": 500000000,
        "amplitude_threshold": 0.03,
    }

    run_resp = client.post("/api/screener/run", json=payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    detail_resp = client.get(f"/api/screener/runs/{run_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["step_summary"]["input_count"] > 0
    assert body["step_pools"]["input"][0]["name"] != "科技样本1"


def test_annotation_roundtrip() -> None:
    decision_keep = chr(0x4FDD) + chr(0x7559)
    payload = {
        "symbol": "sh600519",
        "start_date": "2026-01-01",
        "stage": "Mid",
        "trend_class": "A",
        "decision": decision_keep,
        "notes": "manual test",
        "updated_by": "manual",
    }

    save_resp = client.put("/api/stocks/sh600519/annotations", json=payload)
    assert save_resp.status_code == 200
    assert save_resp.json()["annotation"]["symbol"] == "sh600519"

    get_resp = client.get("/api/stocks/sh600519/analysis")
    assert get_resp.status_code == 200
    assert get_resp.json()["annotation"]["symbol"] == "sh600519"


def test_config_update() -> None:
    config_resp = client.get("/api/config")
    assert config_resp.status_code == 200
    config = config_resp.json()

    config["ai_provider"] = "deepseek"
    update_resp = client.put("/api/config", json=config)
    assert update_resp.status_code == 200
    assert update_resp.json()["ai_provider"] == "deepseek"


def test_config_akshare_switch_affects_candles_endpoint(tmp_path: Path) -> None:
    cache_file = tmp_path / "sz300750.csv"
    cache_file.write_text(
        "\n".join(
            [
                "date,open,high,low,close,volume,amount,symbol",
                "2026-02-12,102,103,101,102.5,143400,147450000,sz300750",
            ]
        ),
        encoding="utf-8",
    )
    original_config = client.get("/api/config").json()
    changed_config = dict(original_config)
    changed_config["tdx_data_path"] = r"Z:\not-exists\vipdoc"
    changed_config["market_data_source"] = "akshare_only"
    changed_config["akshare_cache_dir"] = str(tmp_path)

    try:
        update_resp = client.put("/api/config", json=changed_config)
        assert update_resp.status_code == 200
        candles_resp = client.get("/api/stocks/sz300750/candles")
        assert candles_resp.status_code == 200
        candles = candles_resp.json()["candles"]
        assert len(candles) == 1
        assert candles[0]["time"] == "2026-02-12"
        assert candles[0]["price_source"] == "approx"
    finally:
        restore_resp = client.put("/api/config", json=original_config)
        assert restore_resp.status_code == 200


def test_system_storage_endpoint() -> None:
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    body = resp.json()
    assert "app_state_path" in body
    assert "sim_state_path" in body
    assert "akshare_cache_candidates" in body
    assert isinstance(body["akshare_cache_candidates"], list)


def test_market_data_sync_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_sync_market_data(_payload):
        return {
            "ok": True,
            "provider": "baostock",
            "mode": "incremental",
            "message": "mock sync done",
            "out_dir": r"C:\\tmp\\market-data",
            "symbol_count": 10,
            "ok_count": 10,
            "fail_count": 0,
            "skipped_count": 6,
            "new_rows_total": 8,
            "started_at": "2026-02-13 10:00:00",
            "finished_at": "2026-02-13 10:00:02",
            "duration_sec": 2.0,
            "errors": [],
        }

    monkeypatch.setattr(store, "sync_market_data", fake_sync_market_data)
    resp = client.post(
        "/api/system/sync-market-data",
        json={
            "provider": "baostock",
            "mode": "incremental",
            "symbols": "",
            "all_market": True,
            "limit": 100,
            "start_date": "",
            "end_date": "",
            "initial_days": 180,
            "sleep_sec": 0.0,
            "out_dir": "",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "baostock"
    assert body["new_rows_total"] == 8


def test_intraday_endpoint_returns_points() -> None:
    resp = client.get("/api/stocks/sz000001/intraday", params={"date": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["points"]) > 0
    assert "date" in body


def test_ai_analyze_stock_endpoint() -> None:
    resp = client.post("/api/stocks/sz300750/ai-analyze")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "sz300750"
    assert body["name"]
    assert "summary" in body and body["summary"]
    assert "breakout_date" in body and body["breakout_date"]
    assert "rise_reasons" in body and isinstance(body["rise_reasons"], list)


def test_ai_prompt_preview_endpoint() -> None:
    resp = client.get("/api/stocks/sz000070/ai-prompt-preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "sz000070"
    assert "prompt" in body and "rise_reasons" in body["prompt"]


def test_ai_provider_test_endpoint() -> None:
    payload = {
        "provider": {
            "id": "custom-test",
            "label": "Custom",
            "base_url": "https://example.com/v1",
            "model": "demo-model",
            "api_key": "",
            "api_key_path": "",
            "enabled": True,
        },
        "fallback_api_key": "",
        "fallback_api_key_path": "",
        "timeout_sec": 5,
    }
    resp = client.post("/api/ai/providers/test", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_code"] == "AI_KEY_MISSING"


def test_delete_ai_record_endpoint() -> None:
    create_resp = client.post("/api/stocks/sz300750/ai-analyze")
    assert create_resp.status_code == 200
    record = create_resp.json()

    delete_resp = client.delete(
        "/api/ai/records",
        params={
            "symbol": record["symbol"],
            "fetched_at": record["fetched_at"],
            "provider": record["provider"],
        },
    )
    assert delete_resp.status_code == 200
    delete_body = delete_resp.json()
    assert delete_body["deleted"] is True


def test_signals_endpoint_full_market_fields() -> None:
    resp = client.get(
        "/api/signals",
        params={
            "mode": "full_market",
            "window_days": 60,
            "min_score": 40,
            "require_sequence": False,
            "min_event_count": 0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "full_market"
    assert "generated_at" in body
    assert "cache_hit" in body
    assert "source_count" in body
    assert isinstance(body["items"], list)
    if body["items"]:
        first = body["items"][0]
        assert "wyckoff_phase" in first
        assert "wy_events" in first
        assert "entry_quality_score" in first
        assert "scan_mode" in first


def test_signals_endpoint_trend_pool_mode() -> None:
    run_payload = {
        "markets": ["sh", "sz"],
        "mode": "strict",
        "return_window_days": 40,
        "top_n": 500,
        "turnover_threshold": 0.05,
        "amount_threshold": 500000000,
        "amplitude_threshold": 0.03,
    }
    run_resp = client.post("/api/screener/run", json=run_payload)
    assert run_resp.status_code == 200
    run_id = run_resp.json()["run_id"]

    resp = client.get(
        "/api/signals",
        params={
            "mode": "trend_pool",
            "run_id": run_id,
            "min_score": 40,
            "min_event_count": 0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "trend_pool"
    assert body["source_count"] >= 0
    assert isinstance(body["items"], list)


def test_sim_order_buy_pending_then_settle_filled() -> None:
    dates = _load_symbol_dates("sz300750")
    submit_date = dates[-6]

    order_resp = client.post(
        "/api/sim/orders",
        json={
            "symbol": "sz300750",
            "side": "buy",
            "quantity": 100,
            "signal_date": submit_date,
            "submit_date": submit_date,
        },
    )
    assert order_resp.status_code == 200
    order = order_resp.json()["order"]
    assert order["status"] == "pending"

    settle_resp = client.post("/api/sim/settle")
    assert settle_resp.status_code == 200
    settle_body = settle_resp.json()
    assert settle_body["settled_count"] >= 1
    assert settle_body["filled_count"] >= 1

    orders = client.get("/api/sim/orders", params={"status": "filled"}).json()["items"]
    assert any(item["order_id"] == order["order_id"] for item in orders)

    fills = client.get("/api/sim/fills", params={"symbol": "sz300750"}).json()["items"]
    assert any(item["order_id"] == order["order_id"] for item in fills)


def test_sim_no_next_day_fallback_close() -> None:
    dates = _load_symbol_dates("sz300750")
    last_date = dates[-1]

    order = _post_buy("sz300750", last_date, quantity=100)
    assert order["status"] == "pending"

    settle_resp = client.post("/api/sim/settle")
    assert settle_resp.status_code == 200

    filled_orders = client.get("/api/sim/orders", params={"status": "filled"}).json()["items"]
    target = next(item for item in filled_orders if item["order_id"] == order["order_id"])
    assert target["status_reason"] == "NO_NEXT_DAY_FALLBACK_CLOSE"

    fills = client.get("/api/sim/fills", params={"symbol": "sz300750"}).json()["items"]
    fill = next(item for item in fills if item["order_id"] == order["order_id"])
    assert fill["warning"] == "NO_NEXT_DAY_FALLBACK_CLOSE"


def test_sim_sell_fifo_and_partial_lot_consumption() -> None:
    symbol = "sh601899"
    dates = _load_symbol_dates(symbol)
    buy_date_1 = dates[-8]
    buy_date_2 = dates[-7]
    sell_date = dates[-5]

    _post_buy(symbol, buy_date_1, quantity=100)
    _post_buy(symbol, buy_date_2, quantity=100)
    settle_resp = client.post("/api/sim/settle")
    assert settle_resp.status_code == 200

    sell_order = _post_sell(symbol, sell_date, quantity=100)
    assert sell_order["status"] == "pending"
    settle_resp2 = client.post("/api/sim/settle")
    assert settle_resp2.status_code == 200

    portfolio = client.get("/api/sim/portfolio").json()
    pos = next((item for item in portfolio["positions"] if item["symbol"] == symbol), None)
    assert pos is not None
    assert pos["quantity"] == 100

    review = client.get(
        "/api/review/stats",
        params={"date_from": dates[-15], "date_to": dates[-1], "date_axis": "sell"},
    ).json()
    assert review["trades"]
    filled_buys = client.get(
        "/api/sim/orders",
        params={"status": "filled", "side": "buy", "symbol": symbol},
    ).json()["items"]
    assert filled_buys
    earliest_buy_fill_date = min(item["filled_date"] for item in filled_buys if item.get("filled_date"))
    assert any(trade["buy_date"] == earliest_buy_fill_date for trade in review["trades"])


def test_sim_t_plus_one_buy_same_day_not_sellable() -> None:
    symbol = "sz300750"
    dates = _load_symbol_dates(symbol)
    buy_date = dates[-6]

    _post_buy(symbol, buy_date, quantity=100)
    client.post("/api/sim/settle")

    sell_same_day = client.post(
        "/api/sim/orders",
        json={
            "symbol": symbol,
            "side": "sell",
            "quantity": 100,
            "signal_date": buy_date,
            "submit_date": buy_date,
        },
    )
    assert sell_same_day.status_code == 400
    body = sell_same_day.json()
    assert body["code"] == "SIM_INSUFFICIENT_POSITION"


def test_sim_cancel_pending_and_filled_not_cancelable() -> None:
    symbol = "sz300750"
    dates = _load_symbol_dates(symbol)
    submit_date = dates[-6]

    pending = _post_buy(symbol, submit_date, quantity=100)
    cancel_resp = client.post(f"/api/sim/orders/{pending['order_id']}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["order"]["status"] == "cancelled"

    second = _post_buy(symbol, submit_date, quantity=100)
    client.post("/api/sim/settle")
    cancel_filled = client.post(f"/api/sim/orders/{second['order_id']}/cancel")
    assert cancel_filled.status_code == 400
    assert cancel_filled.json()["code"] == "SIM_ORDER_NOT_CANCELABLE"


def test_sim_reset_account_clears_positions_orders_and_fills() -> None:
    symbol = "sh601899"
    dates = _load_symbol_dates(symbol)
    _post_buy(symbol, dates[-6], quantity=100)
    client.post("/api/sim/settle")

    reset_resp = client.post("/api/sim/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["success"] is True

    orders = client.get("/api/sim/orders").json()
    fills = client.get("/api/sim/fills").json()
    portfolio = client.get("/api/sim/portfolio").json()
    config = client.get("/api/sim/config").json()

    assert orders["total"] == 0
    assert fills["total"] == 0
    assert portfolio["positions"] == []
    assert abs(portfolio["cash"] - config["initial_capital"]) < 1e-6


def test_sim_cost_calculation_min_commission_and_sell_stamp_tax() -> None:
    symbol = "sh601899"
    dates = _load_symbol_dates(symbol)
    buy_date = dates[-7]
    sell_date = dates[-5]

    buy = _post_buy(symbol, buy_date, quantity=100)
    assert buy["status"] == "pending"
    client.post("/api/sim/settle")

    buy_fill = next(
        item
        for item in client.get("/api/sim/fills", params={"side": "buy"}).json()["items"]
        if item["order_id"] == buy["order_id"]
    )
    assert buy_fill["fee_commission"] >= 5
    assert buy_fill["fee_stamp_tax"] == 0

    sell = _post_sell(symbol, sell_date, quantity=100)
    assert sell["status"] == "pending"
    client.post("/api/sim/settle")
    sell_fill = next(
        item
        for item in client.get("/api/sim/fills", params={"side": "sell"}).json()["items"]
        if item["order_id"] == sell["order_id"]
    )
    assert sell_fill["fee_stamp_tax"] > 0


def test_review_default_range_and_curve_fields() -> None:
    symbol = "sh601899"
    dates = _load_symbol_dates(symbol)
    _post_buy(symbol, dates[-8], quantity=100)
    client.post("/api/sim/settle")
    _post_sell(symbol, dates[-5], quantity=100)
    client.post("/api/sim/settle")

    resp = client.get("/api/review/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "range" in body
    assert body["range"]["date_axis"] == "sell"
    assert isinstance(body["equity_curve"], list)
    assert isinstance(body["drawdown_curve"], list)
    assert isinstance(body["monthly_returns"], list)
    assert "profit_factor" in body["stats"]
