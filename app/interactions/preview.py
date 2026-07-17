"""On-demand GitHub link preview.

Link unfurling (D1) needs always-on channel message access, so it's a non-goal —
instead `/github preview <url>` looks it up on the spot. Private repos are
visible too if within the App installation's permission scope. Embed display
follows the same conventions as the relay formatters.
"""

import re

from githubkit.exception import RequestFailed

from app.clients.embeds import GRAY, GREEN, PURPLE, RED, build_embed, preview_text
from app.clients.github_app import app_client, installation_client


URL_PATTERN = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/(pull|issues)/(\d+)")

USAGE = "Supported URLs: `https://github.com/owner/repo/pull/N` or `.../issues/N`"


class PreviewError(RuntimeError):
    pass


def parse_url(url: str) -> tuple[str, str, str, int] | None:
    match = URL_PATTERN.match(url.strip())
    if not match:
        return None
    owner, repo, kind, number = match.groups()
    return owner, repo, kind, int(number)


def pr_embed(owner_repo: str, pr) -> dict:
    if pr.merged:
        color, state = PURPLE, "merged"
    elif pr.state == "closed":
        color, state = RED, "closed"
    elif pr.draft:
        color, state = GRAY, "draft"
    else:
        color, state = GREEN, "open"
    author = pr.user.login if pr.user else "?"
    description = f"`{pr.base.ref}` ← `{pr.head.ref}` — by {author}"
    body = preview_text(pr.body)
    if body:
        description += f"\n\n{body}"
    embed = build_embed(f"#{pr.number} {pr.title}", pr.html_url, color, f"pull request · {state}", description)
    embed["author"] = {"name": owner_repo, "url": f"https://github.com/{owner_repo}"}
    return embed


def issue_embed(owner_repo: str, issue) -> dict:
    state = issue.state or "open"
    color = GREEN if state == "open" else RED
    author = issue.user.login if issue.user else "?"
    description = f"by {author}"
    body = preview_text(issue.body)
    if body:
        description += f"\n\n{body}"
    embed = build_embed(f"#{issue.number} {issue.title}", issue.html_url, color, f"issue · {state}", description)
    embed["author"] = {"name": owner_repo, "url": f"https://github.com/{owner_repo}"}
    return embed


async def fetch_embed(url: str) -> dict:
    """Look up the URL via GitHub REST and build an embed. Every failure is a PreviewError (user message)."""
    parsed = parse_url(url)
    if not parsed:
        raise PreviewError(USAGE)
    owner, repo, kind, number = parsed
    try:
        github = app_client()
        installation = await github.rest.apps.async_get_repo_installation(owner, repo)
        gh = installation_client(github, installation.parsed_data.id)
        if kind == "pull":
            res = await gh.rest.pulls.async_get(owner, repo, number)
            return pr_embed(f"{owner}/{repo}", res.parsed_data)
        res = await gh.rest.issues.async_get(owner, repo, number)
        return issue_embed(f"{owner}/{repo}", res.parsed_data)
    except RequestFailed as exc:
        if exc.response.status_code == 404:
            raise PreviewError(
                f"`{owner}/{repo}#{number}` not found — outside the App's installation scope, or no such number"
            ) from exc
        raise PreviewError(f"GitHub lookup failed: HTTP {exc.response.status_code}") from exc
    except RuntimeError as exc:
        # e.g. missing credentials in app_client — the user only gets a summary
        raise PreviewError(f"GitHub authentication failed: {exc}") from exc
