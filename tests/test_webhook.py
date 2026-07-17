import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


SECRET = "test-secret"

PUSH_PAYLOAD = {
    "ref": "refs/heads/master",
    "repository": {"full_name": "monologg/ghcord"},
    "commits": [],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    # isolate from the real local config.toml (same pattern as test_relay)
    config = tmp_path / "config.toml"
    config.write_text('[default]\nwebhook_url = "https://discord.com/api/webhooks/0/test"\n')
    monkeypatch.setenv("GHCORD_CONFIG", str(config))
    return TestClient(app)


def sign(raw_body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def post_signed(client, payload: dict, secret: str = SECRET, **extra_headers):
    raw = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "x-hub-signature-256": sign(raw, secret),
        "x-github-event": "push",
        "x-github-delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
        **extra_headers,
    }
    return client.post("/webhook/github", content=raw, headers=headers)


def test_healthcheck_returns_200(client):
    assert client.get("/").status_code == 200


def test_head_healthcheck_returns_200(client):
    # for external monitoring — FastAPI does not auto-add HEAD to GET routes
    assert client.head("/").status_code == 200


def test_valid_signature_returns_202(client):
    res = post_signed(client, PUSH_PAYLOAD)
    assert res.status_code == 202


def test_invalid_signature_returns_401(client):
    res = post_signed(client, PUSH_PAYLOAD, secret="wrong-secret")
    assert res.status_code == 401


def test_missing_signature_header_returns_401(client):
    raw = json.dumps(PUSH_PAYLOAD).encode()
    res = client.post("/webhook/github", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 401


def test_missing_secret_env_rejects_even_valid_signature(monkeypatch):
    # fail-closed: exposed with no secret configured, everything must be rejected
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    client = TestClient(app)
    res = post_signed(client, PUSH_PAYLOAD)
    assert res.status_code == 401


def test_oversize_content_length_returns_413(client):
    res = client.post(
        "/webhook/github",
        content=b"{}",
        headers={"Content-Length": "99999999999", "x-hub-signature-256": sign(b"{}")},
    )
    assert res.status_code == 413


def test_ping_event_returns_202(client):
    # ping GitHub sends right after App registration — must show as success in Recent Deliveries
    res = post_signed(client, {"zen": "Keep it logically awesome."}, **{"x-github-event": "ping"})
    assert res.status_code == 202
