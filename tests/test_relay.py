"""End-to-end: signed webhook POST → routing/filters → Discord send (respx mocking)."""

import hashlib
import hmac
import json
import uuid

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.main import app


SECRET = "test-secret"
DEFAULT_URL = "https://discord.com/api/webhooks/1/default"
GHCORD_URL = "https://discord.com/api/webhooks/2/ghcord"
OPS_URL = "https://discord.com/api/webhooks/3/ops"

CONFIG_TOML = f"""
[ops]
webhook_url = "{OPS_URL}"

[users]
monologg-dm = "999888777"

[default]
webhook_url = "{DEFAULT_URL}"

[repos."monologg/ghcord"]
webhook_url = "{GHCORD_URL}"
events = ["commits", "pulls", "issues"]
branches = ["master"]
labels = []

[repos."monologg/labeled"]
webhook_url = "{GHCORD_URL}"
events = ["issues"]
labels = ["bug"]
"""


def make_push(repo: str = "monologg/ghcord", branch: str = "master") -> dict:
    return {
        "ref": f"refs/heads/{branch}",
        "compare": "https://github.com/compare/abc...def",
        "repository": {
            "full_name": repo,
            "html_url": f"https://github.com/{repo}",
            "default_branch": "master",
        },
        "commits": [
            {"id": "a" * 40, "url": "https://github.com/c/a", "message": "Fix", "author": {"name": "monologg"}}
        ],
    }


def make_issue(repo: str, labels: list[str]) -> dict:
    return {
        "action": "opened",
        "issue": {
            "number": 1,
            "title": "T",
            "html_url": "https://github.com/i/1",
            "body": "",
            "user": {"login": "monologg"},
            "labels": [{"name": name} for name in labels],
        },
        "repository": {"full_name": repo, "html_url": f"https://github.com/{repo}", "default_branch": "master"},
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(CONFIG_TOML)
    monkeypatch.setenv("GHCORD_CONFIG", str(config))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    return TestClient(app)


def post_event(client, event: str, payload: dict, delivery: str | None = None):
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook/github",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "x-hub-signature-256": signature,
            "x-github-event": event,
            "x-github-delivery": delivery or str(uuid.uuid4()),
        },
    )


@respx.mock
def test_push_routes_to_repo_channel(client):
    mock = respx.post(GHCORD_URL).mock(return_value=Response(204))
    res = post_event(client, "push", make_push())
    assert res.status_code == 202
    assert res.text == "Sent"
    body = json.loads(mock.calls.last.request.content)
    assert "1 new commit" in body["content"]
    assert "pushed to `master` by" in body["content"]


@respx.mock
def test_unlisted_repo_routes_to_default_channel(client):
    mock = respx.post(DEFAULT_URL).mock(return_value=Response(204))
    res = post_event(client, "push", make_push(repo="monologg/other"))
    assert res.status_code == 202
    assert res.text == "Sent"
    assert mock.called


@respx.mock
def test_non_default_branch_filtered(client):
    res = post_event(client, "push", make_push(branch="feature/x"))
    assert res.status_code == 202
    assert res.text == "Ignored"


@respx.mock
def test_unsubscribed_feature_ignored(client):
    # monologg/ghcord is not subscribed to comments
    payload = {
        "action": "created",
        "issue": {"number": 1, "title": "T", "labels": []},
        "comment": {"body": "hi", "html_url": "https://github.com/c/1", "user": {"login": "x"}},
        "repository": {"full_name": "monologg/ghcord", "html_url": "https://github.com/r", "default_branch": "master"},
    }
    res = post_event(client, "issue_comment", payload)
    assert res.status_code == 202
    assert res.text == "Ignored"


@respx.mock
def test_label_filter_blocks_and_passes(client):
    mock = respx.post(GHCORD_URL).mock(return_value=Response(204))
    blocked = post_event(client, "issues", make_issue("monologg/labeled", labels=["docs"]))
    assert blocked.text == "Ignored"
    passed = post_event(client, "issues", make_issue("monologg/labeled", labels=["bug"]))
    assert passed.text == "Sent"
    assert mock.call_count == 1


@respx.mock
def test_duplicate_delivery_suppressed(client):
    respx.post(GHCORD_URL).mock(return_value=Response(204))
    delivery = str(uuid.uuid4())
    first = post_event(client, "push", make_push(), delivery=delivery)
    second = post_event(client, "push", make_push(), delivery=delivery)
    assert first.text == "Sent"
    assert second.text == "Duplicate ignored"


@respx.mock
def test_failed_send_returns_502_and_allows_redelivery(client):
    respx.post(OPS_URL).mock(return_value=Response(204))
    respx.post(GHCORD_URL).mock(return_value=Response(500))
    delivery = str(uuid.uuid4())
    res = post_event(client, "push", make_push(), delivery=delivery)
    assert res.status_code == 502
    # A failed delivery stays in the ledger as failed so a GitHub redelivery must pass
    respx.post(GHCORD_URL).mock(return_value=Response(204))
    retry = post_event(client, "push", make_push(), delivery=delivery)
    assert retry.text == "Sent"


@respx.mock
def test_failed_send_alerts_ops_channel(client):
    ops = respx.post(OPS_URL).mock(return_value=Response(204))
    respx.post(GHCORD_URL).mock(return_value=Response(500))
    res = post_event(client, "push", make_push(), delivery="alert-me")
    assert res.status_code == 502
    assert ops.called
    body = json.loads(ops.calls.last.request.content)
    alert_text = json.dumps(body["embeds"])
    assert "monologg/ghcord" in alert_text
    assert "alert-me" in alert_text
    assert "500" in alert_text


@respx.mock
def test_ops_alert_failure_is_swallowed(client):
    # Even if the ops channel itself is down, the original response (502) stands — alert failure is log-only
    respx.post(OPS_URL).mock(return_value=Response(500))
    respx.post(GHCORD_URL).mock(return_value=Response(500))
    res = post_event(client, "push", make_push())
    assert res.status_code == 502


@respx.mock
def test_self_failure_skips_ops_alert(monkeypatch, tmp_path):
    # If the failing channel is the ops channel itself, send no alert (separate path = log)
    config = tmp_path / "config.toml"
    config.write_text(f'[ops]\nwebhook_url = "{OPS_URL}"\n[default]\nwebhook_url = "{OPS_URL}"\n')
    monkeypatch.setenv("GHCORD_CONFIG", str(config))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    client = TestClient(app)
    ops = respx.post(OPS_URL).mock(return_value=Response(500))
    res = post_event(client, "push", make_push())
    assert res.status_code == 502
    assert ops.call_count == 1  # only the original send — no alert retry


@respx.mock
def test_ledger_records_sent_delivery(client):
    from app import ledger

    respx.post(GHCORD_URL).mock(return_value=Response(204))
    post_event(client, "push", make_push(), delivery="ledger-check")
    row = ledger.recent(1)[0]
    assert row["delivery_id"] == "ledger-check"
    assert row["outcome"] == "sent"
    assert row["repo"] == "monologg/ghcord"
    assert row["feature"] == "commits"
    assert row["duration_ms"] is not None


def test_missing_config_returns_500(monkeypatch, tmp_path):
    monkeypatch.setenv("GHCORD_CONFIG", str(tmp_path / "nope.toml"))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    client = TestClient(app)
    res = post_event(client, "push", make_push())
    assert res.status_code == 500


def test_unformatted_event_ignored(client):
    res = post_event(client, "workflow_run", {"action": "completed", "repository": {"full_name": "monologg/ghcord"}})
    assert res.status_code == 202
    assert res.text == "Ignored"


# --- Personal DM notifications: independent of channel routing ---


@respx.mock
def test_review_request_sends_dm_despite_no_channel_notification(client, monkeypatch):
    from app.clients import discord_api

    sent = []

    async def fake_send_dm(http, user_id, embed):
        sent.append((user_id, embed["footer"]["text"]))

    monkeypatch.setattr(discord_api, "send_dm", fake_send_dm)
    payload = {
        "action": "review_requested",
        "pull_request": {"number": 1, "title": "T", "html_url": "https://github.com/p/1"},
        "requested_reviewer": {"login": "monologg-dm"},
        "sender": {"login": "someone-else"},
        "repository": {"full_name": "monologg/other", "html_url": "https://github.com/r", "default_branch": "main"},
    }
    res = post_event(client, "pull_request", payload)
    assert res.text == "Ignored"  # review_requested is not a channel-notification event — the DM still goes out
    assert sent == [("999888777", "GitHub · review requested by someone-else")]


# --- SQLite subscription routing: command subscriptions > config.toml ---

SUB_URL_A = "https://discord.com/api/webhooks/20/sub-a"
SUB_URL_B = "https://discord.com/api/webhooks/21/sub-b"


@respx.mock
def test_sqlite_subscription_overrides_config(client):
    from app import subscriptions

    subscriptions.save_webhook("ch-a", "wa", SUB_URL_A)
    subscriptions.upsert("ch-a", "monologg/ghcord", ["commits:master"], label=None)
    sub_mock = respx.post(SUB_URL_A).mock(return_value=Response(204))
    config_mock = respx.post(GHCORD_URL).mock(return_value=Response(204))
    res = post_event(client, "push", make_push())
    assert res.text == "Sent"
    assert sub_mock.called
    assert not config_mock.called  # config route is ignored when a subscription exists


@respx.mock
def test_fanout_to_multiple_subscribed_channels(client):
    from app import subscriptions

    for ch, url in [("ch-a", SUB_URL_A), ("ch-b", SUB_URL_B)]:
        subscriptions.save_webhook(ch, f"w-{ch}", url)
        subscriptions.upsert(ch, "monologg/ghcord", ["commits:master"], label=None)
    mock_a = respx.post(SUB_URL_A).mock(return_value=Response(204))
    mock_b = respx.post(SUB_URL_B).mock(return_value=Response(204))
    res = post_event(client, "push", make_push())
    assert res.text == "Sent"
    assert mock_a.called
    assert mock_b.called


@respx.mock
def test_subscription_feature_filter_applies_per_channel(client):
    from app import subscriptions

    # ch-a subscribes to commits, ch-b to issues only — push goes to ch-a only
    subscriptions.save_webhook("ch-a", "wa", SUB_URL_A)
    subscriptions.upsert("ch-a", "monologg/ghcord", ["commits:master"], label=None)
    subscriptions.save_webhook("ch-b", "wb", SUB_URL_B)
    subscriptions.upsert("ch-b", "monologg/ghcord", ["issues"], label=None)
    mock_a = respx.post(SUB_URL_A).mock(return_value=Response(204))
    mock_b = respx.post(SUB_URL_B).mock(return_value=Response(204))
    res = post_event(client, "push", make_push())
    assert res.text == "Sent"
    assert mock_a.called
    assert not mock_b.called


@respx.mock
def test_partial_fanout_failure_returns_502_and_alerts(client):
    from app import subscriptions

    for ch, url in [("ch-a", SUB_URL_A), ("ch-b", SUB_URL_B)]:
        subscriptions.save_webhook(ch, f"w-{ch}", url)
        subscriptions.upsert(ch, "monologg/ghcord", ["commits:master"], label=None)
    respx.post(SUB_URL_A).mock(return_value=Response(204))
    respx.post(SUB_URL_B).mock(return_value=Response(500))
    ops = respx.post(OPS_URL).mock(return_value=Response(204))
    res = post_event(client, "push", make_push())
    assert res.status_code == 502  # any failure = failed (allows GitHub redelivery)
    assert ops.called
