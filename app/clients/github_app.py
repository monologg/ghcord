"""GitHub App auth bootstrap.

App JWT signing → installation token issuance/caching/refresh are all handled
by githubkit's AppAuthStrategy (meep pattern). This module only goes as far as
reading credentials from env and building clients.
"""

import os
from pathlib import Path

from githubkit import AppAuthStrategy, GitHub
from githubkit.exception import GitHubException, RequestFailed
from loguru import logger


def load_private_key() -> str:
    inline = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if inline:
        # docker-compose env cannot hold newlines, so support single-line \n notation
        return inline.replace("\\n", "\n")
    path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    if path:
        return Path(path).read_text()
    raise RuntimeError("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH must be set")


def app_client() -> GitHub:
    app_id = os.environ.get("GITHUB_APP_ID")
    if not app_id:
        raise RuntimeError("GITHUB_APP_ID must be set")
    return GitHub(AppAuthStrategy(app_id=app_id, private_key=load_private_key()))


def installation_client(github: GitHub, installation_id: int) -> GitHub:
    return github.with_auth(github.auth.as_installation(installation_id))


async def repo_installation_client(owner: str, repo: str) -> GitHub:
    """Client for the installation this repo belongs to — 404 means outside the install scope."""
    github = app_client()
    installation = await github.rest.apps.async_get_repo_installation(owner, repo)
    return installation_client(github, installation.parsed_data.id)


async def primary_installation_client() -> GitHub:
    """Client for the first (only) installation — for lookups not tied to a repo (search etc.)."""
    github = app_client()
    installations = (await github.rest.apps.async_list_installations()).parsed_data
    if not installations:
        raise RuntimeError("App has no installations")
    return installation_client(github, installations[0].id)


class InstallationMissing(Exception):
    """No installation covers the target — the App was never installed there (or it doesn't exist)."""

    def __init__(self, target: str, install_url: str | None) -> None:
        subject = "repository" if "/" in target else "account"
        # masked link with <> — a bare URL makes Discord paste GitHub's generic preview card
        install = f" [Install it to proceed](<{install_url}>)" if install_url else " Install it to proceed."
        super().__init__(f"Either ghcord isn't installed on `{target}` or the {subject} doesn't exist.{install}")
        self.target = target
        self.install_url = install_url


async def _install_url(github: GitHub) -> str | None:
    """Account picker for this App — None if the slug lookup fails, which must not mask the real error."""
    try:
        app = (await github.rest.apps.async_get_authenticated()).parsed_data
    except GitHubException:
        return None
    # /installations/new redirects to an existing installation, so the picker URL is the one to hand out
    return f"https://github.com/apps/{app.slug}/installations/select_target"


async def verify_installed(target: str) -> None:
    """Raise InstallationMissing unless an installation covers `owner` or `owner/repo`.

    GitHub delivers webhooks only for repositories inside an installation, so subscribing
    to anything outside it stores a subscription that can never fire. Checking up front
    mirrors the Slack app, which refuses with an install link instead of a silent success.
    Skipped when App credentials are absent — a relay-only deployment has nothing to ask.
    """
    try:
        github = app_client()
    except (RuntimeError, OSError) as exc:
        logger.warning("Skipping installation check for {} — App credentials unavailable ({})", target, exc)
        return

    owner, _, repo = target.partition("/")
    try:
        if repo:
            await github.rest.apps.async_get_repo_installation(owner, repo)
            return
        try:
            await github.rest.apps.async_get_org_installation(owner)
        except RequestFailed as exc:
            if exc.response.status_code != 404:
                raise
            # a bare owner may be a personal account, which the org endpoint reports as 404
            await github.rest.apps.async_get_user_installation(owner)
    except RequestFailed as exc:
        if exc.response.status_code != 404:
            raise
        raise InstallationMissing(target, await _install_url(github)) from exc
