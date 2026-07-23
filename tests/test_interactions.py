"""Discord interactions endpoint: Ed25519 verification + PING/PONG + dispatcher skeleton."""

import json

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from app.main import app


TIMESTAMP = "1752566400"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def signing_key(monkeypatch):
    key = SigningKey.generate()
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", key.verify_key.encode().hex())
    return key


def signed_post(client, key, payload, timestamp=TIMESTAMP):
    body = json.dumps(payload).encode()
    signature = key.sign(timestamp.encode() + body).signature.hex()
    return client.post(
        "/interactions/discord",
        content=body,
        headers={
            "X-Signature-Ed25519": signature,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )


def gh_command(sub: str, options: dict | None = None) -> dict:
    opts = [{"type": 3, "name": k, "value": v} for k, v in (options or {}).items()]
    return {
        "type": 2,
        "id": "itx-1",
        "token": "itx-token",
        "data": {"name": "github", "options": [{"type": 1, "name": sub, "options": opts}]},
        "channel_id": "ch-1",
    }


def test_rejects_when_public_key_not_configured(client, monkeypatch):
    # fail-closed: exposed with no key configured we would accept forged interactions — reject
    monkeypatch.delenv("DISCORD_PUBLIC_KEY", raising=False)
    res = client.post("/interactions/discord", json={"type": 1})
    assert res.status_code == 401


def test_rejects_missing_signature_headers(client, signing_key):
    res = client.post("/interactions/discord", json={"type": 1})
    assert res.status_code == 401


def test_rejects_signature_from_wrong_key(client, signing_key):
    imposter = SigningKey.generate()
    res = signed_post(client, imposter, {"type": 1})
    assert res.status_code == 401


def test_rejects_tampered_body(client, signing_key):
    body = json.dumps({"type": 1}).encode()
    signature = signing_key.sign(TIMESTAMP.encode() + body).signature.hex()
    res = client.post(
        "/interactions/discord",
        content=json.dumps({"type": 2}).encode(),
        headers={"X-Signature-Ed25519": signature, "X-Signature-Timestamp": TIMESTAMP},
    )
    assert res.status_code == 401


def test_rejects_malformed_signature_hex(client, signing_key):
    res = client.post(
        "/interactions/discord",
        content=b'{"type": 1}',
        headers={"X-Signature-Ed25519": "not-hex", "X-Signature-Timestamp": TIMESTAMP},
    )
    assert res.status_code == 401


def test_ping_pong(client, signing_key):
    res = signed_post(client, signing_key, {"type": 1})
    assert res.status_code == 200
    assert res.json() == {"type": 1}


def test_unknown_subcommand_gets_ephemeral_error(client, signing_key):
    res = signed_post(client, signing_key, gh_command("frobnicate"))
    assert res.status_code == 200
    body = res.json()
    assert body["type"] == 4  # CHANNEL_MESSAGE_WITH_SOURCE
    assert body["data"]["flags"] == 64  # ephemeral — visible to the invoker only
    assert "not a supported" in body["data"]["content"]


def test_command_name_is_github():
    # Muscle-memory compat with the official Slack app (/github subscribe ...)
    from scripts.register_commands import GH_COMMAND

    assert GH_COMMAND["name"] == "github"


def test_unknown_subcommand_error_references_github(client, signing_key):
    res = signed_post(client, signing_key, gh_command("frobnicate"))
    assert "/github frobnicate" in res.json()["data"]["content"]


def test_unsupported_interaction_type_rejected(client, signing_key):
    res = signed_post(client, signing_key, {"type": 99})
    assert res.status_code == 400


# --- /github subscribe · unsubscribe · list ---


@pytest.fixture
def discord_stub(monkeypatch):
    """Fake the bot REST calls — capture created webhooks and followup messages."""
    from app.clients import discord_api

    calls = {"ensure": 0, "followup": None}

    async def fake_ensure(http, channel_id):
        calls["ensure"] += 1
        return "wh-new", f"https://discord.com/api/webhooks/wh-new/{channel_id}"

    async def fake_edit(http, interaction_token, content):
        calls["followup"] = content

    monkeypatch.setattr(discord_api, "ensure_channel_webhook", fake_ensure)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    return calls


def test_subscribe_defers_then_saves_subscription(client, signing_key, discord_stub):
    from app import subscriptions

    res = signed_post(client, signing_key, gh_command("subscribe", {"repo": "Monologg/GHCord"}))
    body = res.json()
    assert body["type"] == 5  # DEFERRED — handles the 3-second limit
    assert body["data"]["flags"] == 64
    rows = subscriptions.for_channel("ch-1")
    assert rows[0]["repo"] == "monologg/ghcord"
    assert discord_stub["ensure"] == 1
    assert subscriptions.webhook_url_for("ch-1") is not None
    assert "monologg/ghcord" in discord_stub["followup"]


def test_subscribe_reuses_stored_webhook(client, signing_key, discord_stub):
    from app import subscriptions

    subscriptions.save_webhook("ch-1", "wh-old", "https://discord.com/api/webhooks/wh-old/t")
    signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r"}))
    assert discord_stub["ensure"] == 0  # reuses the stored webhook — no API call
    assert subscriptions.for_channel("ch-1")[0]["repo"] == "o/r"


def test_subscribe_with_features_and_label(client, signing_key, discord_stub):
    from app import subscriptions
    from app.config import DEFAULT_EVENTS

    cmd = gh_command("subscribe", {"repo": "o/r", "features": "issues commits:main", "label": "bug"})
    signed_post(client, signing_key, cmd)
    row = subscriptions.for_channel("ch-1")[0]
    # Slack semantics: 5 defaults ∪ specified (commits replaced by the pattern token)
    assert set(row["features"]) == (set(DEFAULT_EVENTS) - {"commits"}) | {"commits:main"}
    assert row["label"] == "bug"


def test_subscribe_owner_only_creates_owner_subscription(client, signing_key, discord_stub):
    from app import subscriptions

    res_defer = signed_post(client, signing_key, gh_command("subscribe", {"repo": "Monologg"}))
    assert res_defer.json()["type"] == 5
    rows = subscriptions.for_channel("ch-1")
    assert rows[0]["repo"] == "monologg"  # no slash = owner-wide subscription
    assert "monologg" in discord_stub["followup"]


def test_list_marks_owner_subscriptions(client, signing_key):
    from app import subscriptions

    subscriptions.upsert("ch-1", "monologg", ["issues"], label=None)
    res = signed_post(client, signing_key, gh_command("list"))
    assert "all repos" in res.json()["data"]["content"]


def test_subscribe_is_incremental_not_replace(client, signing_key, discord_stub):
    from app import subscriptions

    signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r"}))
    signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r", "features": "reviews"}))
    features = subscriptions.for_channel("ch-1")[0]["features"]
    assert "reviews" in features
    assert "issues" in features  # existing subscription kept — not replaced (Slack parity)


def test_subscribe_label_token_in_features(client, signing_key, discord_stub):
    from app import subscriptions

    cmd = gh_command("subscribe", {"repo": "o/r", "features": 'reviews +label:"priority: high"'})
    signed_post(client, signing_key, cmd)
    row = subscriptions.for_channel("ch-1")[0]
    assert row["label"] == "priority: high"
    assert "reviews" in row["features"]


def test_unsubscribe_with_features_removes_partially(client, signing_key, discord_stub):
    from app import subscriptions

    signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r", "features": "reviews"}))
    res = signed_post(client, signing_key, gh_command("unsubscribe", {"repo": "o/r", "features": "reviews pulls"}))
    assert "reviews" in res.json()["data"]["content"]
    features = subscriptions.for_channel("ch-1")[0]["features"]
    assert "reviews" not in features
    assert "pulls" not in features
    assert "issues" in features  # the rest are kept


def test_subscribe_rejects_bad_repo_format(client, signing_key, discord_stub):
    from app import subscriptions

    # only owner (no slash) or owner/repo is valid — anything else errors immediately (no deferred)
    res = signed_post(client, signing_key, gh_command("subscribe", {"repo": "a/b/c"}))
    body = res.json()
    assert body["type"] == 4
    assert "owner/repo" in body["data"]["content"]
    assert subscriptions.for_channel("ch-1") == []


def test_subscribe_rejects_unknown_feature_token(client, signing_key, discord_stub):
    res = signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r", "features": "issues pushes"}))
    body = res.json()
    assert body["type"] == 4
    assert "pushes" in body["data"]["content"]


def test_subscribe_refuses_when_app_not_installed(client, signing_key, discord_stub, monkeypatch):
    # GitHub delivers no webhooks outside the installation, so the subscription would be dead on arrival
    from app import subscriptions
    from app.clients import github_app

    async def not_installed(target):
        raise github_app.InstallationMissing(target, "https://github.com/apps/ghcord/installations/select_target")

    monkeypatch.setattr(github_app, "verify_installed", not_installed)
    res = signed_post(client, signing_key, gh_command("subscribe", {"repo": "poppy-labs/dotfiles-ai"}))
    assert res.json()["type"] == 5  # still deferred — the check is an API call
    assert subscriptions.for_channel("ch-1") == []  # nothing stored
    assert discord_stub["ensure"] == 0  # and no Discord webhook created for a subscription we refused
    assert "isn't installed" in discord_stub["followup"]
    assert "installations/select_target" in discord_stub["followup"]


def test_subscribe_proceeds_when_installation_covers_repo(client, signing_key, discord_stub, monkeypatch):
    from app import subscriptions
    from app.clients import github_app

    checked = []

    async def covered(target):
        checked.append(target)

    monkeypatch.setattr(github_app, "verify_installed", covered)
    signed_post(client, signing_key, gh_command("subscribe", {"repo": "Monologg/GHCord"}))
    assert checked == ["monologg/ghcord"]  # normalized target is what gets checked
    assert subscriptions.for_channel("ch-1")[0]["repo"] == "monologg/ghcord"


def test_subscribe_reports_webhook_failure(client, signing_key, monkeypatch):
    from app import subscriptions
    from app.clients import discord_api

    async def failing_ensure(http, channel_id):
        raise discord_api.DiscordAPIError("Manage Webhooks permission required")

    captured = {}

    async def fake_edit(http, interaction_token, content):
        captured["msg"] = content

    monkeypatch.setattr(discord_api, "ensure_channel_webhook", failing_ensure)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    signed_post(client, signing_key, gh_command("subscribe", {"repo": "o/r"}))
    assert "permission" in captured["msg"]
    assert subscriptions.for_channel("ch-1") == []  # no subscription left behind on failure


def test_unsubscribe_removes_and_reports(client, signing_key):
    from app import subscriptions

    subscriptions.upsert("ch-1", "o/r", ["issues"], label=None)
    res = signed_post(client, signing_key, gh_command("unsubscribe", {"repo": "O/R"}))
    body = res.json()
    assert body["type"] == 4
    assert "Unsubscribed" in body["data"]["content"]
    assert subscriptions.for_channel("ch-1") == []


def test_unsubscribe_unknown_repo_says_so(client, signing_key):
    res = signed_post(client, signing_key, gh_command("unsubscribe", {"repo": "o/none"}))
    assert "not subscribed" in res.json()["data"]["content"]


def test_list_shows_channel_subscriptions(client, signing_key):
    from app import subscriptions

    subscriptions.upsert("ch-1", "o/alpha", ["issues", "pulls"], label=None)
    subscriptions.upsert("ch-1", "o/beta", ["commits:*"], label="bug")
    subscriptions.upsert("ch-other", "o/gamma", ["issues"], label=None)
    res = signed_post(client, signing_key, gh_command("list"))
    content = res.json()["data"]["content"]
    assert "o/alpha" in content
    assert "o/beta" in content
    assert "o/gamma" not in content  # other channels' subscriptions are hidden


def test_list_empty_channel_gives_guidance(client, signing_key):
    res = signed_post(client, signing_key, gh_command("list"))
    assert "No subscriptions" in res.json()["data"]["content"]


# --- /github preview ---


def test_preview_rejects_unsupported_url_immediately(client, signing_key):
    res = signed_post(client, signing_key, gh_command("preview", {"url": "https://github.com/o/r/commit/abc"}))
    body = res.json()
    assert body["type"] == 4
    assert "pull" in body["data"]["content"]  # supported-format guidance


def test_preview_defers_then_sends_embed(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import preview

    captured = {}

    async def fake_fetch(url):
        captured["url"] = url
        return {"title": "#11 Add feature", "color": 1}

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        captured["embeds"] = embeds

    monkeypatch.setattr(preview, "fetch_embed", fake_fetch)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    res = signed_post(client, signing_key, gh_command("preview", {"url": "https://github.com/o/r/pull/11"}))
    body = res.json()
    assert body["type"] == 5  # DEFERRED — the GitHub REST lookup runs outside the 3-second limit
    assert body["data"]["flags"] == 64
    assert captured["url"] == "https://github.com/o/r/pull/11"
    assert captured["embeds"][0]["title"] == "#11 Add feature"


# --- /github signin · signout ---


def with_member(payload: dict, user_id: str = "discord-u1") -> dict:
    return {**payload, "member": {"user": {"id": user_id}}}


def test_signin_returns_authorize_link_with_state(client, signing_key, monkeypatch):
    from app.identity import user_links

    monkeypatch.setenv("GITHUB_CLIENT_ID", "Iv23ctTEST")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "s3cr3t")
    res = signed_post(client, signing_key, with_member(gh_command("signin")))
    content = res.json()["data"]["content"]
    assert "github.com/login/oauth/authorize" in content
    assert "client_id=Iv23ctTEST" in content
    state = content.split("state=")[1].split(")")[0].rstrip(">")
    assert user_links.consume_state(state) == "discord-u1"


def test_signin_without_oauth_config_explains(client, signing_key, monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    res = signed_post(client, signing_key, with_member(gh_command("signin")))
    assert "OAuth" in res.json()["data"]["content"]


def test_signout_removes_link(client, signing_key):
    from app.identity import user_links

    user_links.link("monologg", "discord-u1")
    res = signed_post(client, signing_key, with_member(gh_command("signout")))
    assert "monologg" in res.json()["data"]["content"]
    assert user_links.mapping() == {}


def test_signout_when_not_linked(client, signing_key):
    res = signed_post(client, signing_key, with_member(gh_command("signout")))
    assert "No linked" in res.json()["data"]["content"]


def test_oauth_callback_links_and_confirms(client, monkeypatch):
    from app.clients import discord_api
    from app.identity import oauth, user_links

    dm = []

    async def fake_exchange(http, code):
        assert code == "code-1"
        return "monologg"

    async def fake_send_dm(http, user_id, embed):
        dm.append(user_id)

    monkeypatch.setenv("GITHUB_CLIENT_ID", "x")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "y")
    monkeypatch.setattr(oauth, "exchange_code_for_login", fake_exchange)
    monkeypatch.setattr(discord_api, "send_dm", fake_send_dm)
    state = user_links.create_state("discord-u1")
    res = client.get(f"/oauth/github/callback?code=code-1&state={state}")
    assert res.status_code == 200
    assert "is now connected" in res.text
    assert user_links.mapping() == {"monologg": "discord-u1"}
    assert dm == ["discord-u1"]


def test_oauth_callback_rejects_bad_state(client):
    res = client.get("/oauth/github/callback?code=c&state=bogus")
    assert res.status_code == 400


# --- /github remind (subcommand group) ---


def remind_command(action: str, options: dict | None = None) -> dict:
    opts = [{"type": 3, "name": k, "value": v} for k, v in (options or {}).items()]
    return {
        "type": 2,
        "id": "itx-remind-1",
        "token": "itx-token",
        "channel_id": "ch-1",
        "data": {
            "name": "github",
            "options": [{"type": 2, "name": "remind", "options": [{"type": 1, "name": action, "options": opts}]}],
        },
    }


def test_remind_set_stores_and_confirms(client, signing_key):
    from app import reminders

    res = signed_post(client, signing_key, remind_command("set", {"time": "09:30", "user": "monologg"}))
    body = res.json()
    assert body["type"] == 4
    assert "09:30" in body["data"]["content"]
    row = reminders.get_reminder("ch-1")
    assert row["github_login"] == "monologg"
    assert row["send_at"] == "09:30"


def test_remind_set_rejects_bad_time(client, signing_key):
    from app import reminders

    res = signed_post(client, signing_key, remind_command("set", {"time": "25:99", "user": "monologg"}))
    assert "HH:MM" in res.json()["data"]["content"]
    assert reminders.get_reminder("ch-1") is None


def test_remind_status_and_off(client, signing_key):
    from app import reminders

    reminders.set_reminder("ch-1", "monologg", "09:30")
    res = signed_post(client, signing_key, remind_command("status"))
    assert "09:30" in res.json()["data"]["content"]
    res = signed_post(client, signing_key, remind_command("off"))
    assert "turned off" in res.json()["data"]["content"]
    assert reminders.get_reminder("ch-1") is None


def test_remind_status_when_unset(client, signing_key):
    res = signed_post(client, signing_key, remind_command("status"))
    assert "No reminder" in res.json()["data"]["content"]


# --- /github open · close · reopen ---


def modal_submit(repo: str, title: str, body: str = "") -> dict:
    return {
        "type": 5,  # MODAL_SUBMIT
        "id": "itx-modal-1",
        "token": "itx-token",
        "channel_id": "ch-1",
        "data": {
            "custom_id": f"open:{repo}",
            "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": "title", "value": title}]},
                {"type": 1, "components": [{"type": 4, "custom_id": "body", "value": body}]},
            ],
        },
    }


def test_open_returns_modal_with_repo_in_custom_id(client, signing_key):
    res = signed_post(client, signing_key, gh_command("open", {"repo": "Monologg/GHCord"}))
    body = res.json()
    assert body["type"] == 9  # MODAL — must be the first response
    assert body["data"]["custom_id"] == "open:monologg/ghcord"
    inputs = [c["components"][0]["custom_id"] for c in body["data"]["components"]]
    assert inputs == ["title", "body"]


def test_open_rejects_bad_repo_before_modal(client, signing_key):
    res = signed_post(client, signing_key, gh_command("open", {"repo": "nope"}))
    assert res.json()["type"] == 4
    assert "owner/repo" in res.json()["data"]["content"]


def test_modal_submit_creates_issue_and_follows_up(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import actions

    captured = {}

    async def fake_create(owner, repo, title, body):
        captured["args"] = (owner, repo, title, body)
        return {"title": f"#1 {title}"}

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        captured["embeds"] = embeds

    monkeypatch.setattr(actions, "create_issue", fake_create)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    res = signed_post(client, signing_key, modal_submit("o/r", "Found a bug", "Details here"))
    assert res.json()["type"] == 5  # deferred
    assert captured["args"] == ("o", "r", "Found a bug", "Details here")
    assert captured["embeds"][0]["title"] == "#1 Found a bug"


def test_modal_submit_reports_action_error(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import actions

    captured = {}

    async def failing_create(owner, repo, title, body):
        raise actions.ActionError("The App needs Issues write permission")

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        captured["content"] = content

    monkeypatch.setattr(actions, "create_issue", failing_create)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    signed_post(client, signing_key, modal_submit("o/r", "Title"))
    assert "permission" in captured["content"]


def test_close_defers_and_updates_issue_state(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import actions

    captured = {}

    async def fake_set_state(owner, repo, number, *, state, reason=None):
        captured["args"] = (owner, repo, number, state, reason)
        return {"title": f"#{number} T"}

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        captured["embeds"] = embeds

    monkeypatch.setattr(actions, "set_issue_state", fake_set_state)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    cmd = gh_command("close", {"url": "https://github.com/o/r/issues/7", "reason": "not_planned"})
    res = signed_post(client, signing_key, cmd)
    assert res.json()["type"] == 5
    assert captured["args"] == ("o", "r", 7, "closed", "not_planned")
    assert captured["embeds"][0]["title"] == "#7 T"


def test_reopen_sets_state_open(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import actions

    captured = {}

    async def fake_set_state(owner, repo, number, *, state, reason=None):
        captured["args"] = (owner, repo, number, state, reason)
        return {"title": "#7 T"}

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        pass

    monkeypatch.setattr(actions, "set_issue_state", fake_set_state)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    signed_post(client, signing_key, gh_command("reopen", {"url": "https://github.com/o/r/issues/7"}))
    assert captured["args"] == ("o", "r", 7, "open", None)


def test_close_rejects_pr_url(client, signing_key):
    res = signed_post(client, signing_key, gh_command("close", {"url": "https://github.com/o/r/pull/3"}))
    body = res.json()
    assert body["type"] == 4
    assert "Issues only" in body["data"]["content"]


def test_close_rejects_unsupported_url(client, signing_key):
    res = signed_post(client, signing_key, gh_command("close", {"url": "https://github.com/o/r"}))
    assert res.json()["type"] == 4


def test_preview_reports_fetch_failure(client, signing_key, monkeypatch):
    from app.clients import discord_api
    from app.interactions import preview

    captured = {}

    async def failing_fetch(url):
        raise preview.PreviewError("not found — outside the App's installation scope")

    async def fake_edit(http, interaction_token, content=None, embeds=None):
        captured["content"] = content

    monkeypatch.setattr(preview, "fetch_embed", failing_fetch)
    monkeypatch.setattr(discord_api, "edit_original", fake_edit)
    signed_post(client, signing_key, gh_command("preview", {"url": "https://github.com/o/r/pull/999"}))
    assert "not found" in captured["content"]
