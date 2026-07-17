"""Subscription storage + feature token parsing: SQLite subscriptions take precedence over config.toml."""

import pytest

from app import subscriptions
from app.config import DEFAULT_EVENTS


WEBHOOK = "https://discord.com/api/webhooks/10/token-a"


def test_parse_features_empty_falls_back_to_defaults():
    events, branches = subscriptions.parse_features("")
    assert events == tuple(sorted(DEFAULT_EVENTS))
    assert branches == ()


def test_parse_features_tokens_and_branch_patterns():
    events, branches = subscriptions.parse_features("issues commits:main commits:release/*")
    assert set(events) == {"issues", "commits"}
    assert branches == ("main", "release/*")


def test_parse_features_invalid_token_raises_with_guidance():
    with pytest.raises(ValueError, match="pushes"):
        subscriptions.parse_features("issues pushes")


def test_upsert_and_for_channel_roundtrip():
    subscriptions.upsert("ch-1", "Monologg/GHCord", ["issues", "pulls"], label="bug")
    rows = subscriptions.for_channel("ch-1")
    assert len(rows) == 1
    assert rows[0]["repo"] == "monologg/ghcord"  # lowercase normalization
    assert rows[0]["features"] == ["issues", "pulls"]
    assert rows[0]["label"] == "bug"


def test_upsert_replaces_features():
    # Same idempotent UX as Slack — resubscribing replaces
    subscriptions.upsert("ch-1", "o/r", ["issues"], label=None)
    subscriptions.upsert("ch-1", "o/r", ["pulls"], label="p1")
    rows = subscriptions.for_channel("ch-1")
    assert len(rows) == 1
    assert rows[0]["features"] == ["pulls"]
    assert rows[0]["label"] == "p1"


def test_remove_returns_whether_existed():
    subscriptions.upsert("ch-1", "o/r", ["issues"], label=None)
    assert subscriptions.remove("ch-1", "o/r") is True
    assert subscriptions.remove("ch-1", "o/r") is False
    assert subscriptions.for_channel("ch-1") == []


def test_webhook_save_and_lookup():
    assert subscriptions.webhook_url_for("ch-1") is None
    subscriptions.save_webhook("ch-1", "wh-1", WEBHOOK)
    assert subscriptions.webhook_url_for("ch-1") == WEBHOOK


def test_routes_for_builds_routes_from_subscriptions():
    subscriptions.save_webhook("ch-1", "wh-1", WEBHOOK)
    subscriptions.upsert("ch-1", "o/r", ["issues", "commits:main"], label="bug")
    routes = subscriptions.routes_for("o/r")
    assert len(routes) == 1
    assert routes[0].webhook_url == WEBHOOK
    assert routes[0].events == frozenset({"issues", "commits"})
    assert routes[0].branches == ("main",)
    assert routes[0].labels == ("bug",)


def test_routes_for_skips_channel_without_webhook():
    subscriptions.upsert("ch-orphan", "o/r", ["issues"], label=None)
    assert subscriptions.routes_for("o/r") == []


def test_routes_for_unknown_repo_empty():
    assert subscriptions.routes_for("nobody/nothing") == []


# --- Slack incremental semantics + +label token ---


def test_split_label_tokens():
    rest, labels = subscriptions.split_label_tokens('reviews +label:"priority: high" comments')
    assert rest.split() == ["reviews", "comments"]
    assert labels == ["priority: high"]


def test_split_label_tokens_malformed_raises():
    with pytest.raises(ValueError, match="label"):
        subscriptions.split_label_tokens("+label:no-quotes")


def test_subscribe_merge_new_gets_defaults_plus_optins():
    # Slack: the 5 defaults are always on; specified tokens are opt-in additions
    result = subscriptions.subscribe_merge("ch-1", "o/r", "reviews comments", None)
    assert set(result["features"]) == set(DEFAULT_EVENTS) | {"reviews", "comments"}


def test_subscribe_merge_adds_to_existing():
    subscriptions.subscribe_merge("ch-1", "o/r", "", None)
    result = subscriptions.subscribe_merge("ch-1", "o/r", "reviews", None)
    assert "reviews" in result["features"]
    assert set(DEFAULT_EVENTS) <= set(result["features"])  # existing kept — not replaced


def test_subscribe_merge_branch_patterns_replace():
    subscriptions.subscribe_merge("ch-1", "o/r", "commits:main", None)
    result = subscriptions.subscribe_merge("ch-1", "o/r", "commits:release/*", None)
    assert "commits:release/*" in result["features"]
    assert "commits:main" not in result["features"]  # specifying a new pattern replaces (Slack filter behavior)


def test_subscribe_merge_label_token_sets_and_replaces():
    subscriptions.subscribe_merge("ch-1", "o/r", '+label:"bug"', None)
    assert subscriptions.for_channel("ch-1")[0]["label"] == "bug"
    subscriptions.subscribe_merge("ch-1", "o/r", '+label:"urgent"', None)
    assert subscriptions.for_channel("ch-1")[0]["label"] == "urgent"  # one per repo, replaced


def test_unsubscribe_features_removes_only_those():
    subscriptions.subscribe_merge("ch-1", "o/r", "reviews", None)
    outcome = subscriptions.unsubscribe_features("ch-1", "o/r", "pulls reviews")
    assert outcome == "updated"
    features = subscriptions.for_channel("ch-1")[0]["features"]
    assert "pulls" not in features
    assert "reviews" not in features
    assert "issues" in features


def test_unsubscribe_label_token_clears_filter():
    subscriptions.subscribe_merge("ch-1", "o/r", '+label:"bug"', None)
    assert subscriptions.unsubscribe_features("ch-1", "o/r", '+label:"bug"') == "updated"
    assert subscriptions.for_channel("ch-1")[0]["label"] is None


def test_unsubscribe_last_feature_removes_subscription():
    subscriptions.subscribe_merge("ch-1", "o/r", "", None)
    outcome = subscriptions.unsubscribe_features("ch-1", "o/r", "issues pulls commits releases deployments")
    assert outcome == "removed"
    assert subscriptions.for_channel("ch-1") == []


def test_unsubscribe_features_unknown_subscription():
    assert subscriptions.unsubscribe_features("ch-1", "o/none", "issues") == "missing"


# --- owner(org)-level subscriptions ---


def test_owner_subscription_routes_any_repo_of_owner():
    subscriptions.save_webhook("ch-1", "wh-1", WEBHOOK)
    subscriptions.subscribe_merge("ch-1", "monologg", "", None)
    assert len(subscriptions.routes_for("monologg/anything")) == 1
    assert len(subscriptions.routes_for("monologg/another-new-repo")) == 1
    assert subscriptions.routes_for("someone-else/repo") == []


def test_repo_subscription_wins_over_owner_in_same_channel():
    # Slack double-sends when org+repo are both subscribed — within one channel we keep only the more specific repo sub
    subscriptions.save_webhook("ch-1", "wh-1", WEBHOOK)
    subscriptions.subscribe_merge("ch-1", "monologg", "", None)
    subscriptions.subscribe_merge("ch-1", "monologg/ghcord", "commits:main", None)
    routes = subscriptions.routes_for("monologg/ghcord")
    assert len(routes) == 1
    assert routes[0].branches == ("main",)  # the repo subscription's filter applies


def test_owner_and_repo_subs_in_different_channels_both_route():
    subscriptions.save_webhook("ch-1", "wh-1", WEBHOOK)
    subscriptions.save_webhook("ch-2", "wh-2", "https://discord.com/api/webhooks/11/token-b")
    subscriptions.subscribe_merge("ch-1", "monologg", "", None)
    subscriptions.subscribe_merge("ch-2", "monologg/ghcord", "", None)
    assert len(subscriptions.routes_for("monologg/ghcord")) == 2
