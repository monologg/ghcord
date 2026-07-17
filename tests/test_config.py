import pytest

from app.config import DEFAULT_EVENTS, branch_allowed, labels_allowed, load_config, resolve_route


CONFIG = {
    "default": {
        "webhook_url": "https://discord.com/api/webhooks/1/default",
        "events": ["issues", "pulls", "commits"],
    },
    "repos": {
        "monologg/ghcord": {
            "webhook_url": "https://discord.com/api/webhooks/2/ghcord",
            "events": ["pulls", "reviews"],
            "branches": ["master", "release/*"],
            "labels": ["bug"],
        },
        "monologg/blog": {},
    },
}


def test_unknown_repo_falls_back_to_default():
    route = resolve_route(CONFIG, "monologg/unknown")
    assert route.webhook_url.endswith("/1/default")
    assert route.events == {"issues", "pulls", "commits"}


def test_repo_override_wins():
    route = resolve_route(CONFIG, "monologg/ghcord")
    assert route.webhook_url.endswith("/2/ghcord")
    assert route.events == {"pulls", "reviews"}
    assert route.branches == ("master", "release/*")
    assert route.labels == ("bug",)


def test_empty_repo_section_inherits_default():
    route = resolve_route(CONFIG, "monologg/blog")
    assert route.webhook_url.endswith("/1/default")
    assert route.events == {"issues", "pulls", "commits"}


def test_no_webhook_url_anywhere_returns_none():
    assert resolve_route({"default": {}}, "x/y") is None


def test_default_events_are_slack_five():
    route = resolve_route({"default": {"webhook_url": "https://d/1"}}, "x/y")
    assert route.events == set(DEFAULT_EVENTS)
    assert route.events == {"issues", "pulls", "commits", "releases", "deployments"}


def test_branch_filter_defaults_to_default_branch():
    route = resolve_route({"default": {"webhook_url": "https://d/1"}}, "x/y")
    assert branch_allowed(route, "master", default_branch="master")
    assert not branch_allowed(route, "feature/x", default_branch="master")


def test_branch_filter_glob_patterns():
    route = resolve_route(CONFIG, "monologg/ghcord")
    assert branch_allowed(route, "master", default_branch="master")
    assert branch_allowed(route, "release/v1.2", default_branch="master")
    assert not branch_allowed(route, "feature/x", default_branch="master")


def test_branch_filter_star_matches_all():
    config = {"default": {"webhook_url": "https://d/1", "branches": ["*"]}}
    route = resolve_route(config, "x/y")
    assert branch_allowed(route, "anything/goes", default_branch="master")


def test_label_filter_empty_allows_all():
    route = resolve_route({"default": {"webhook_url": "https://d/1"}}, "x/y")
    assert labels_allowed(route, [])
    assert labels_allowed(route, ["whatever"])


def test_label_filter_requires_intersection():
    route = resolve_route(CONFIG, "monologg/ghcord")
    assert labels_allowed(route, ["bug", "urgent"])
    assert not labels_allowed(route, ["docs"])
    assert not labels_allowed(route, [])


def test_load_config_reads_ghcord_config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[default]\nwebhook_url = "https://d/1"\n')
    monkeypatch.setenv("GHCORD_CONFIG", str(path))
    assert load_config()["default"]["webhook_url"] == "https://d/1"


def test_load_config_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("GHCORD_CONFIG", str(tmp_path / "nope.toml"))
    with pytest.raises(OSError):
        load_config()
