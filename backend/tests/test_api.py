from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
