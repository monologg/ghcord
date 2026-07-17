"""GitHub link previews: URL parsing + embed build — no network."""

from types import SimpleNamespace

from app.clients.embeds import GRAY, GREEN, PURPLE, RED
from app.interactions import preview


def test_parse_url_pull_and_issue():
    assert preview.parse_url("https://github.com/monologg/ghcord/pull/11") == ("monologg", "ghcord", "pull", 11)
    assert preview.parse_url("https://github.com/o/r.dot/issues/3") == ("o", "r.dot", "issues", 3)


def test_parse_url_rejects_other_shapes():
    assert preview.parse_url("https://github.com/monologg/ghcord") is None
    assert preview.parse_url("https://github.com/o/r/commit/abc123") is None
    assert preview.parse_url("https://gitlab.com/o/r/issues/1") is None
    assert preview.parse_url("garbage input") is None


def _pr(**overrides):
    base = {
        "number": 11,
        "title": "Add feature",
        "html_url": "https://github.com/o/r/pull/11",
        "state": "open",
        "merged": False,
        "draft": False,
        "body": "body text",
        "user": SimpleNamespace(login="monologg"),
        "base": SimpleNamespace(ref="main"),
        "head": SimpleNamespace(ref="feat/x"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pr_embed_states_map_to_colors():
    assert preview.pr_embed("o/r", _pr())["color"] == GREEN
    assert preview.pr_embed("o/r", _pr(draft=True))["color"] == GRAY
    assert preview.pr_embed("o/r", _pr(state="closed"))["color"] == RED
    merged = preview.pr_embed("o/r", _pr(state="closed", merged=True))
    assert merged["color"] == PURPLE
    assert "merged" in merged["footer"]["text"]


def test_pr_embed_contents():
    embed = preview.pr_embed("o/r", _pr())
    assert embed["title"] == "#11 Add feature"
    assert embed["url"] == "https://github.com/o/r/pull/11"
    assert "`main` ← `feat/x`" in embed["description"]
    assert "body text" in embed["description"]
    assert embed["author"]["name"] == "o/r"


def test_issue_embed_contents_and_state():
    issue = SimpleNamespace(
        number=7,
        title="Bug",
        html_url="https://github.com/o/r/issues/7",
        state="closed",
        body=None,
        user=SimpleNamespace(login="monologg"),
    )
    embed = preview.issue_embed("o/r", issue)
    assert embed["title"] == "#7 Bug"
    assert embed["color"] == RED
    assert "closed" in embed["footer"]["text"]
    assert "monologg" in embed["description"]
