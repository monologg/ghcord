"""GitHub App auth bootstrap.

App JWT signing → installation token issuance/caching/refresh are all handled
by githubkit's AppAuthStrategy (meep pattern). This module only goes as far as
reading credentials from env and building clients.
"""

import os
from pathlib import Path

from githubkit import AppAuthStrategy, GitHub


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
