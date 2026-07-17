"""`/github open · close · reopen` GitHub calls: kwargs shaping + error translation."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from githubkit.exception import RequestFailed
from githubkit.response import Response

from app.interactions.actions import ActionError, create_issue, set_issue_state


def _issue(**overrides):
    base = {
        "number": 7,
        "title": "Bug",
        "html_url": "https://github.com/o/r/issues/7",
        "state": "open",
        "body": None,
        "user": SimpleNamespace(login="monologg"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _request_failed(status_code: int) -> RequestFailed:
    raw = httpx.Response(status_code, request=httpx.Request("POST", "https://api.github.com/x"))
    return RequestFailed(Response(raw, dict))


class _FakeGitHub:
    """Records issue create/update calls; raises `failure` instead when set."""

    def __init__(self, failure: RequestFailed | None = None):
        self.calls: list[tuple] = []
        self.failure = failure

        async def async_create(owner, repo, **kwargs):
            self.calls.append((owner, repo, kwargs))
            if self.failure:
                raise self.failure
            return SimpleNamespace(parsed_data=_issue(title=kwargs["title"]))

        async def async_update(owner, repo, number, **kwargs):
            self.calls.append((owner, repo, number, kwargs))
            if self.failure:
                raise self.failure
            return SimpleNamespace(parsed_data=_issue(number=number, state=kwargs["state"]))

        self.rest = SimpleNamespace(issues=SimpleNamespace(async_create=async_create, async_update=async_update))


@pytest.fixture
def gh(monkeypatch):
    fake = _FakeGitHub()

    async def fake_client(owner, repo):
        return fake

    monkeypatch.setattr("app.interactions.actions.repo_installation_client", fake_client)
    return fake


def test_create_issue_returns_embed(gh):
    embed = asyncio.run(create_issue("o", "r", "Bug", None))
    assert embed["title"] == "#7 Bug"
    assert embed["author"]["name"] == "o/r"
    assert gh.calls == [("o", "r", {"title": "Bug"})]


def test_create_issue_forwards_body_only_when_given(gh):
    asyncio.run(create_issue("o", "r", "Bug", "details"))
    assert gh.calls == [("o", "r", {"title": "Bug", "body": "details"})]


def test_set_issue_state_close_with_reason(gh):
    embed = asyncio.run(set_issue_state("o", "r", 7, state="closed", reason="not_planned"))
    assert "closed" in embed["footer"]["text"]
    assert gh.calls == [("o", "r", 7, {"state": "closed", "state_reason": "not_planned"})]


def test_set_issue_state_reopen_omits_reason(gh):
    asyncio.run(set_issue_state("o", "r", 7, state="open"))
    assert gh.calls == [("o", "r", 7, {"state": "open"})]


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (403, "Issues write permission"),
        (404, "`o/r#7` not found"),
        (410, "issues are disabled"),
        (500, "HTTP 500"),
    ],
)
def test_set_issue_state_translates_github_errors(gh, status, match):
    gh.failure = _request_failed(status)
    with pytest.raises(ActionError, match=match):
        asyncio.run(set_issue_state("o", "r", 7, state="closed"))


def test_create_issue_translates_installation_lookup_404(monkeypatch):
    # repo_installation_client itself fails when the repo is outside the install scope
    async def fake_client(owner, repo):
        raise _request_failed(404)

    monkeypatch.setattr("app.interactions.actions.repo_installation_client", fake_client)
    with pytest.raises(ActionError, match="`o/r` not found"):
        asyncio.run(create_issue("o", "r", "Bug", None))
