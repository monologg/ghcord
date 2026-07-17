"""GitHub webhook payload → Discord message (content + embed) conversion.

Ports the official Slack app's display conventions: the action phrase
("Pull request opened by X") goes on the content line outside the embed, the
clickable title ("#12 title") in the embed, and state is distinguished by color.
Noise actions (PR synchronize, issue labeled, release created, etc.) are
filtered to None here.

Payload parsing is lenient — missing fields fall back to abbreviated forms
instead of raising KeyError.
"""

from app.clients.embeds import GRAY, GREEN, PURPLE, RED, build_embed, preview_text


COMMIT_LINES_LIMIT = 10


def _login(obj: dict | None) -> str:
    return (obj or {}).get("login") or "?"


def _sender(payload: dict) -> str:
    return _login(payload.get("sender"))


def _add_assignees(embed: dict, subject: dict) -> None:
    """PR/issue assignees as an "Assignees" field — the convention Slack uses on opened notifications."""
    links = [f"[{a['login']}]({a.get('html_url')})" for a in subject.get("assignees") or [] if (a or {}).get("login")]
    if links:
        embed["fields"] = [{"name": "Assignees", "value": ", ".join(links), "inline": True}]


def _push(payload: dict) -> tuple[str, str, dict] | None:
    ref = payload.get("ref") or ""
    if not ref.startswith("refs/heads/"):
        return None  # tag pushes are covered by the release/create events
    if payload.get("deleted"):
        return None  # branch deletions are covered by the delete event
    commits = payload.get("commits") or []
    if not commits:
        return None
    branch = ref.removeprefix("refs/heads/")

    lines = []
    for commit in commits[:COMMIT_LINES_LIMIT]:
        sha = (commit.get("id") or "")[:7]
        message = (commit.get("message") or "").splitlines()
        first_line = message[0] if message else ""
        author = (commit.get("author") or {}).get("name") or "?"
        lines.append(f"[`{sha}`]({commit.get('url')}) {first_line} — {author}")
    if len(commits) > COMMIT_LINES_LIMIT:
        lines.append(f"… and {len(commits) - COMMIT_LINES_LIMIT} more")

    count = len(commits)
    headline = f"{count} new commit{'s' if count > 1 else ''}"
    compare = payload.get("compare")
    if compare:
        headline = f"[{headline}]({compare})"
    content = f"{headline} pushed to `{branch}` by {_sender(payload)}"
    return "commits", content, build_embed(None, None, GRAY, "", "\n".join(lines))


PR_ACTIONS = {"opened", "reopened", "closed", "ready_for_review"}


def _pull_request(payload: dict) -> tuple[str, str, dict] | None:
    action = payload.get("action")
    if action not in PR_ACTIONS:
        return None
    pr = payload.get("pull_request") or {}
    number = payload.get("number") or pr.get("number")

    if action == "closed":
        if pr.get("merged"):
            phrase, color = "Pull request merged", PURPLE
        else:
            phrase, color = "Pull request closed", RED
    elif action == "ready_for_review":
        phrase, color = "Pull request ready for review", GREEN
    elif pr.get("draft"):
        phrase, color = f"Draft pull request {action}", GRAY
    else:
        phrase, color = f"Pull request {action}", GREEN

    base = (pr.get("base") or {}).get("ref") or "?"
    head = (pr.get("head") or {}).get("ref") or "?"
    description = f"`{base}` ← `{head}` — by {_login(pr.get('user'))}"
    # Body preview only on opened/ready_for_review — repeating the text in close/merge notifications is noise
    if action in ("opened", "ready_for_review"):
        body = preview_text(pr.get("body"))
        if body:
            description += f"\n\n{body}"
    title = f"#{number} {pr.get('title') or ''}"
    content = f"{phrase} by {_sender(payload)}"
    embed = build_embed(title, pr.get("html_url"), color, "", description)
    if action in ("opened", "ready_for_review"):
        _add_assignees(embed, pr)
    return "pulls", content, embed


ISSUE_ACTIONS = {"opened", "reopened", "closed"}


def _issues(payload: dict) -> tuple[str, str, dict] | None:
    action = payload.get("action")
    if action not in ISSUE_ACTIONS:
        return None
    issue = payload.get("issue") or {}
    color = RED if action == "closed" else GREEN
    # Body preview only on opened — repeating the text in close/reopen notifications is noise
    description = preview_text(issue.get("body")) if action == "opened" else None
    title = f"#{issue.get('number')} {issue.get('title') or ''}"
    content = f"Issue {action} by {_sender(payload)}"
    embed = build_embed(title, issue.get("html_url"), color, "", description)
    if action == "opened":
        _add_assignees(embed, issue)
    return "issues", content, embed


def _review(payload: dict) -> tuple[str, str, dict] | None:
    if payload.get("action") != "submitted":
        return None
    review = payload.get("review") or {}
    state = (review.get("state") or "").lower()
    body = preview_text(review.get("body"))
    if state == "commented" and not body:
        # Empty submitted sent per review-comment batch — individual comments are covered by the comments feature
        return None
    color = {"approved": GREEN, "changes_requested": RED}.get(state, GRAY)
    pr = payload.get("pull_request") or {}
    title = f"#{pr.get('number')} {pr.get('title') or ''}"
    content = f"Review {state.replace('_', ' ')} by {_sender(payload)}"
    return "reviews", content, build_embed(title, review.get("html_url"), color, "", body)


def _issue_comment(payload: dict) -> tuple[str, str, dict] | None:
    if payload.get("action") != "created":
        return None
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    title = f"💬 #{issue.get('number')} {issue.get('title') or ''}"
    content = f"New comment by {_sender(payload)}"
    return (
        "comments",
        content,
        build_embed(title, comment.get("html_url"), GRAY, "", preview_text(comment.get("body"))),
    )


def _review_comment(payload: dict) -> tuple[str, str, dict] | None:
    if payload.get("action") != "created":
        return None
    pr = payload.get("pull_request") or {}
    comment = payload.get("comment") or {}
    title = f"💬 #{pr.get('number')} {pr.get('title') or ''}"
    content = f"New review comment by {_sender(payload)}"
    return (
        "comments",
        content,
        build_embed(title, comment.get("html_url"), GRAY, "", preview_text(comment.get("body"))),
    )


def _release(payload: dict) -> tuple[str, str, dict] | None:
    if payload.get("action") != "published":
        return None
    release = payload.get("release") or {}
    tag = release.get("tag_name") or "?"
    name = release.get("name")
    title = f"Release {tag}" + (f" — {name}" if name and name != tag else "")
    content = f"Release published by {_sender(payload)}"
    return (
        "releases",
        content,
        build_embed(title, release.get("html_url"), GREEN, "", preview_text(release.get("body"))),
    )


def _create(payload: dict) -> tuple[str, str, dict] | None:
    ref_type = payload.get("ref_type")
    if ref_type not in ("branch", "tag"):
        return None
    ref = payload.get("ref") or "?"
    repo_url = (payload.get("repository") or {}).get("html_url")
    url = f"{repo_url}/tree/{ref}" if repo_url else None
    content = f"{ref_type.capitalize()} created by {_sender(payload)}"
    return "branches", content, build_embed(f"{ref_type} created: {ref}", url, GREEN, "")


def _delete(payload: dict) -> tuple[str, str, dict] | None:
    ref_type = payload.get("ref_type")
    if ref_type not in ("branch", "tag"):
        return None
    ref = payload.get("ref") or "?"
    repo_url = (payload.get("repository") or {}).get("html_url")
    content = f"{ref_type.capitalize()} deleted by {_sender(payload)}"
    return "branches", content, build_embed(f"{ref_type} deleted: {ref}", repo_url, RED, "")


def _deployment_status(payload: dict) -> tuple[str, str, dict] | None:
    status = payload.get("deployment_status") or {}
    state = status.get("state")
    if state not in ("success", "failure", "error"):
        return None  # pending/queued/in_progress are noise
    environment = (payload.get("deployment") or {}).get("environment") or "?"
    color = GREEN if state == "success" else RED
    url = status.get("target_url") or (payload.get("repository") or {}).get("html_url")
    content = f"Deployment {state} by {_sender(payload)}"
    return "deployments", content, build_embed(f"Deployment {state}: {environment}", url, color, "")


_HANDLERS = {
    "push": _push,
    "pull_request": _pull_request,
    "issues": _issues,
    "pull_request_review": _review,
    "issue_comment": _issue_comment,
    "pull_request_review_comment": _review_comment,
    "release": _release,
    "create": _create,
    "delete": _delete,
    "deployment_status": _deployment_status,
}


def build(event: str, payload: dict) -> tuple[str, str, dict] | None:
    """Convert an event into (feature, content, embed). Unsupported events and noise actions yield None."""
    handler = _HANDLERS.get(event)
    if handler is None:
        return None
    result = handler(payload)
    if result is None:
        return None
    feature, content, embed = result
    repo = payload.get("repository") or {}
    sender = payload.get("sender") or {}
    # author = actor avatar (native Discord webhook convention); the repo goes in the footer
    if sender.get("login"):
        embed["author"] = {
            "name": sender["login"],
            "url": sender.get("html_url"),
            "icon_url": sender.get("avatar_url"),
        }
    elif repo.get("full_name"):
        embed["author"] = {"name": repo["full_name"], "url": repo.get("html_url")}
    if repo.get("full_name"):
        embed["footer"] = {"text": f"GitHub · {repo['full_name']}"}
    return feature, content, embed
