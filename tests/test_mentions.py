"""Personal DM mention notifications: target resolution + sending — no network."""

import asyncio

from app.identity import mentions


def sender(login="acting-user"):
    return {"sender": {"login": login}}


def subject(number=7, title="T", url="https://github.com/o/r/issues/7"):
    return {"number": number, "title": title, "html_url": url}


def test_assigned_does_not_dm():
    # Usage feedback: assign DMs are too noisy — Slack real-time alerts doesn't have them either
    payload = {
        "action": "assigned",
        "issue": subject(),
        "assignee": {"login": "monologg"},
        **sender(),
    }
    assert mentions.collect("issues", payload) == {}
    assert mentions.collect("pull_request", {**payload, "pull_request": subject(), "issue": None}) == {}


def test_review_requested_targets_reviewer():
    payload = {
        "action": "review_requested",
        "pull_request": subject(),
        "requested_reviewer": {"login": "monologg"},
        **sender(),
    }
    out = mentions.collect("pull_request", payload)
    assert set(out) == {"monologg"}
    assert "review requested" in out["monologg"]["footer"]["text"]


def test_review_submitted_targets_pr_author():
    payload = {
        "action": "submitted",
        "pull_request": {**subject(), "user": {"login": "monologg"}},
        "review": {"state": "approved", "body": "LGTM"},
        **sender(),
    }
    out = mentions.collect("pull_request_review", payload)
    assert set(out) == {"monologg"}
    assert "approved" in out["monologg"]["footer"]["text"]


def test_comment_mention_targets_mentioned_login():
    payload = {
        "action": "created",
        "issue": subject(),
        "comment": {"body": "cc @monologg @other-user please take a look", "html_url": "https://x/c/1"},
        **sender(),
    }
    out = mentions.collect("issue_comment", payload)
    assert set(out) == {"monologg", "other-user"}
    assert "mentioned" in out["monologg"]["footer"]["text"]


def test_own_action_is_excluded():
    # never DM the user who triggered the event
    payload = {
        "action": "review_requested",
        "pull_request": subject(),
        "requested_reviewer": {"login": "monologg"},
        **sender("monologg"),
    }
    assert mentions.collect("pull_request", payload) == {}


def test_unrelated_event_returns_nothing():
    assert mentions.collect("push", {"ref": "refs/heads/main", **sender()}) == {}
    assert mentions.collect("issues", {"action": "labeled", "issue": subject(), **sender()}) == {}


def test_notify_sends_dm_only_to_mapped_users(monkeypatch):
    sent = []

    async def fake_send_dm(http, user_id, embed):
        sent.append(user_id)

    monkeypatch.setattr(mentions.discord_api, "send_dm", fake_send_dm)
    config = {"users": {"monologg": "111222333"}}
    payload = {
        "action": "created",
        "issue": subject(),
        "comment": {"body": "@monologg @unmapped-user", "html_url": "https://x/c/1"},
        **sender(),
    }
    count = asyncio.run(mentions.notify(config, "issue_comment", payload, delivery="d-1"))
    assert count == 1
    assert sent == ["111222333"]


def test_notify_without_mapping_is_noop(monkeypatch):
    async def exploding_send_dm(http, user_id, embed):
        raise AssertionError("must not be called")

    monkeypatch.setattr(mentions.discord_api, "send_dm", exploding_send_dm)
    payload = {
        "action": "review_requested",
        "pull_request": subject(),
        "requested_reviewer": {"login": "monologg"},
        **sender(),
    }
    assert asyncio.run(mentions.notify({}, "pull_request", payload, delivery="d-2")) == 0
