from app.clients.embeds import GRAY, GREEN, PURPLE, RED
from app.webhook.formatters import build


REPO = {
    "full_name": "monologg/ghcord",
    "html_url": "https://github.com/monologg/ghcord",
    "default_branch": "master",
}

SENDER = {
    "login": "monologg",
    "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
    "html_url": "https://github.com/monologg",
}


def make_push(branch: str = "master", commit_count: int = 1, deleted: bool = False) -> dict:
    return {
        "ref": f"refs/heads/{branch}",
        "deleted": deleted,
        "compare": "https://github.com/monologg/ghcord/compare/abc...def",
        "repository": REPO,
        "sender": SENDER,
        "commits": [
            {
                "id": f"{i:040x}",
                "url": f"https://github.com/monologg/ghcord/commit/{i:040x}",
                "message": f"Commit {i}\n\nbody detail",
                "author": {"name": "monologg"},
            }
            for i in range(commit_count)
        ],
    }


def make_pr(
    action: str,
    merged: bool = False,
    draft: bool = False,
    body: str | None = None,
    assignees: list[dict] | None = None,
) -> dict:
    return {
        "action": action,
        "number": 12,
        "pull_request": {
            "number": 12,
            "title": "Add relay",
            "html_url": "https://github.com/monologg/ghcord/pull/12",
            "merged": merged,
            "draft": draft,
            "body": body,
            "user": {"login": "monologg"},
            "base": {"ref": "master"},
            "head": {"ref": "feat/x"},
            "labels": [],
            "assignees": assignees or [],
        },
        "repository": REPO,
        "sender": SENDER,
    }


def test_push_formats_commits():
    feature, content, embed = build("push", make_push(commit_count=2))
    assert feature == "commits"
    assert "[2 new commits](https://github.com/monologg/ghcord/compare/abc...def)" in content
    assert "pushed to `master` by monologg" in content
    assert "title" not in embed  # headline moved into content (Slack parity)
    assert "Commit 0" in embed["description"]
    assert "body detail" not in embed["description"]  # commit message: first line only
    assert embed["author"]["name"] == "monologg"  # actor avatar (repo goes in the footer)
    assert embed["author"]["icon_url"] == SENDER["avatar_url"]
    assert embed["footer"]["text"] == "GitHub · monologg/ghcord"


def test_push_without_compare_url_is_plain_text():
    payload = make_push()
    payload["compare"] = None
    _, content, _ = build("push", payload)
    assert content == "1 new commit pushed to `master` by monologg"


def test_push_truncates_long_commit_list():
    _, _, embed = build("push", make_push(commit_count=13))
    assert "and 3 more" in embed["description"]


def test_push_tag_ref_ignored():
    payload = make_push()
    payload["ref"] = "refs/tags/v1.0.0"
    assert build("push", payload) is None


def test_push_branch_delete_ignored():
    assert build("push", make_push(deleted=True)) is None


def test_pr_opened():
    feature, content, embed = build("pull_request", make_pr("opened"))
    assert feature == "pulls"
    assert content == "Pull request opened by monologg"
    assert embed["title"] == "#12 Add relay"
    assert embed["color"] == GREEN
    assert embed["footer"]["text"] == "GitHub · monologg/ghcord"  # repo goes in the footer
    assert embed["author"] == {
        "name": "monologg",
        "url": SENDER["html_url"],
        "icon_url": SENDER["avatar_url"],
    }
    assert "monologg" in embed["description"]


def test_author_falls_back_to_repo_without_sender():
    payload = make_pr("opened")
    del payload["sender"]
    _, _, embed = build("pull_request", payload)
    assert embed["author"] == {"name": "monologg/ghcord", "url": REPO["html_url"]}


def test_pr_assignees_field():
    assignees = [
        {"login": "monologg", "html_url": "https://github.com/monologg"},
        {"login": "other", "html_url": "https://github.com/other"},
    ]
    _, _, embed = build("pull_request", make_pr("opened", assignees=assignees))
    assert embed["fields"] == [
        {
            "name": "Assignees",
            "value": "[monologg](https://github.com/monologg), [other](https://github.com/other)",
            "inline": True,
        }
    ]


def test_pr_without_assignees_has_no_fields():
    _, _, embed = build("pull_request", make_pr("opened"))
    assert "fields" not in embed


def test_pr_closed_omits_assignees():
    assignees = [{"login": "monologg", "html_url": "https://github.com/monologg"}]
    _, _, embed = build("pull_request", make_pr("closed", merged=True, assignees=assignees))
    assert "fields" not in embed


def test_pr_draft_opened():
    _, content, embed = build("pull_request", make_pr("opened", draft=True))
    assert content == "Draft pull request opened by monologg"
    assert embed["color"] == GRAY


def test_pr_opened_includes_body_preview():
    _, _, embed = build("pull_request", make_pr("opened", body="## Summary\n- adds the relay"))
    assert "## Summary\n- adds the relay" in embed["description"]
    assert "`master` ← `feat/x`" in embed["description"]  # existing branch line preserved


def test_pr_opened_without_body():
    _, _, embed = build("pull_request", make_pr("opened"))
    assert embed["description"] == "`master` ← `feat/x` — by monologg"


def test_pr_body_preview_truncated():
    _, _, embed = build("pull_request", make_pr("opened", body="x" * 600))
    assert embed["description"].endswith("…")
    assert "x" * 500 in embed["description"]
    assert "x" * 501 not in embed["description"]


def test_pr_closed_omits_body():
    _, _, embed = build("pull_request", make_pr("closed", merged=True, body="## Summary\n- adds the relay"))
    assert "Summary" not in embed["description"]


def test_pr_merged_is_purple():
    _, content, embed = build("pull_request", make_pr("closed", merged=True))
    assert embed["color"] == PURPLE
    assert content == "Pull request merged by monologg"


def test_pr_closed_unmerged_is_red():
    _, content, embed = build("pull_request", make_pr("closed"))
    assert embed["color"] == RED
    assert content == "Pull request closed by monologg"


def test_pr_synchronize_is_noise():
    assert build("pull_request", make_pr("synchronize")) is None


def test_issue_opened_includes_body_preview():
    payload = {
        "action": "opened",
        "issue": {
            "number": 5,
            "title": "Bug report",
            "html_url": "https://github.com/monologg/ghcord/issues/5",
            "body": "x" * 600,
            "user": {"login": "monologg"},
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "other", "html_url": "https://github.com/other"}],
        },
        "repository": REPO,
        "sender": SENDER,
    }
    feature, content, embed = build("issues", payload)
    assert feature == "issues"
    assert content == "Issue opened by monologg"
    assert embed["fields"][0]["name"] == "Assignees"
    assert "[other](https://github.com/other)" in embed["fields"][0]["value"]
    assert embed["title"] == "#5 Bug report"
    assert embed["color"] == GREEN
    assert len(embed["description"]) <= 501  # 500 + ellipsis
    assert embed["description"].endswith("…")


def test_issue_labeled_is_noise():
    assert build("issues", {"action": "labeled", "issue": {}, "repository": REPO}) is None


def test_review_approved():
    payload = {
        "action": "submitted",
        "review": {
            "state": "approved",
            "body": "LGTM",
            "html_url": "https://github.com/monologg/ghcord/pull/12#review-1",
            "user": {"login": "reviewer"},
        },
        "pull_request": {"number": 12, "title": "Add relay", "labels": []},
        "repository": REPO,
        "sender": {"login": "reviewer"},
    }
    feature, content, embed = build("pull_request_review", payload)
    assert feature == "reviews"
    assert embed["color"] == GREEN
    assert content == "Review approved by reviewer"


def test_review_empty_commented_is_noise():
    payload = {
        "action": "submitted",
        "review": {"state": "commented", "body": None, "user": {"login": "r"}},
        "pull_request": {"number": 12, "title": "Add relay"},
        "repository": REPO,
    }
    assert build("pull_request_review", payload) is None


def test_issue_comment_created():
    payload = {
        "action": "created",
        "issue": {"number": 5, "title": "Bug report", "labels": []},
        "comment": {
            "body": "same here",
            "html_url": "https://github.com/monologg/ghcord/issues/5#comment-1",
            "user": {"login": "someone"},
        },
        "repository": REPO,
        "sender": {"login": "someone"},
    }
    feature, content, embed = build("issue_comment", payload)
    assert feature == "comments"
    assert content == "New comment by someone"
    assert "#5" in embed["title"]
    assert embed["description"] == "same here"


def test_release_published():
    payload = {
        "action": "published",
        "release": {
            "tag_name": "v0.1.0",
            "name": "First release",
            "body": "changelog",
            "html_url": "https://github.com/monologg/ghcord/releases/v0.1.0",
        },
        "repository": REPO,
        "sender": SENDER,
    }
    feature, content, embed = build("release", payload)
    assert feature == "releases"
    assert content == "Release published by monologg"
    assert "v0.1.0" in embed["title"]
    assert embed["color"] == GREEN


def test_release_created_is_noise():
    assert build("release", {"action": "created", "release": {}, "repository": REPO}) is None


def test_branch_created():
    payload = {"ref_type": "branch", "ref": "feat/x", "repository": REPO, "sender": SENDER}
    feature, content, embed = build("create", payload)
    assert feature == "branches"
    assert content == "Branch created by monologg"
    assert "feat/x" in embed["title"]
    assert embed["color"] == GREEN


def test_branch_deleted():
    payload = {"ref_type": "branch", "ref": "feat/x", "repository": REPO, "sender": SENDER}
    feature, content, embed = build("delete", payload)
    assert feature == "branches"
    assert content == "Branch deleted by monologg"
    assert embed["color"] == RED


def test_deployment_success():
    payload = {
        "deployment_status": {"state": "success", "target_url": "https://ci.example/1"},
        "deployment": {"environment": "production"},
        "repository": REPO,
        "sender": SENDER,
    }
    feature, content, embed = build("deployment_status", payload)
    assert feature == "deployments"
    assert content == "Deployment success by monologg"
    assert "production" in embed["title"]
    assert embed["color"] == GREEN


def test_deployment_pending_is_noise():
    payload = {
        "deployment_status": {"state": "pending"},
        "deployment": {"environment": "production"},
        "repository": REPO,
    }
    assert build("deployment_status", payload) is None


def test_unknown_event_returns_none():
    assert build("workflow_run", {"repository": REPO}) is None


def test_neutral_push_color_is_gray():
    _, _, embed = build("push", make_push())
    assert embed["color"] == GRAY
