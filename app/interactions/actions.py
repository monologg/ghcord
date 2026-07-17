"""One-shot GitHub issue operations from Discord.

Only issue create/close/reopen via the App installation token — PR operations
have their own review/merge flow and are out of scope. Without Issues write
permission (403), point to the approval procedure.
"""

from githubkit.exception import RequestFailed

from app.clients.github_app import repo_installation_client
from app.interactions.preview import issue_embed


class ActionError(RuntimeError):
    pass


def _translate(exc: RequestFailed, subject: str) -> ActionError:
    code = exc.response.status_code
    if code == 403:
        return ActionError(
            "The App needs Issues write permission — set Issues to Read and write in the App settings, then approve the request (docs/01)"
        )
    if code == 404:
        return ActionError(f"{subject} not found — outside the App's installation scope, or no such target")
    if code == 410:
        return ActionError(f"{subject} — issues are disabled for this repository")
    return ActionError(f"GitHub call failed: HTTP {code}")


async def create_issue(owner: str, repo: str, title: str, body: str | None) -> dict:
    kwargs = {"title": title}
    if body:
        kwargs["body"] = body
    try:
        gh = await repo_installation_client(owner, repo)
        res = await gh.rest.issues.async_create(owner, repo, **kwargs)
    except RequestFailed as exc:
        raise _translate(exc, f"`{owner}/{repo}`") from exc
    return issue_embed(f"{owner}/{repo}", res.parsed_data)


async def set_issue_state(owner: str, repo: str, number: int, *, state: str, reason: str | None = None) -> dict:
    kwargs = {"state": state}
    if reason:
        kwargs["state_reason"] = reason
    try:
        gh = await repo_installation_client(owner, repo)
        res = await gh.rest.issues.async_update(owner, repo, number, **kwargs)
    except RequestFailed as exc:
        raise _translate(exc, f"`{owner}/{repo}#{number}`") from exc
    return issue_embed(f"{owner}/{repo}", res.parsed_data)
