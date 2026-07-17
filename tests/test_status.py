"""Status endpoint: last N deliveries + success rate."""

import pytest
from fastapi.testclient import TestClient

from app import ledger
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_status_empty_ledger(client):
    res = client.get("/status")
    assert res.status_code == 200
    body = res.json()
    assert body["deliveries"] == []
    assert body["totals"] == {}
    assert body["success_rate"] is None


def test_status_reports_recent_and_success_rate(client):
    for delivery, outcome in [("d1", "sent"), ("d2", "failed"), ("d3", "sent"), ("d4", "sent")]:
        ledger.begin(delivery, "push")
        ledger.finish(delivery, outcome=outcome, repo="monologg/ghcord", feature="commits", duration_ms=10.0)
    body = client.get("/status").json()
    assert [d["delivery_id"] for d in body["deliveries"]] == ["d4", "d3", "d2", "d1"]
    assert body["deliveries"][0]["outcome"] == "sent"
    assert body["totals"] == {"sent": 3, "failed": 1}
    assert body["success_rate"] == 0.75


def test_docs_endpoints_disabled(client):
    # public deployment, so minimize surface — FastAPI auto-docs endpoints stay closed
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_status_limit_param_clamped(client):
    for i in range(5):
        ledger.begin(f"d{i}", "push")
    assert len(client.get("/status?limit=2").json()["deliveries"]) == 2
    # out-of-range limit is clamped to a safe range
    assert len(client.get("/status?limit=0").json()["deliveries"]) == 1
    assert len(client.get("/status?limit=99999").json()["deliveries"]) == 5
