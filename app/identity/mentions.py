"""Personal DM mention notifications.

Based on the GitHub login → Discord user ID mapping from /github signin links
(+config [users] fallback), sends review requests, review results, and
@mention events as bot DMs. Independent of channel routing — the DM goes out
even when the channel notification is filtered (same as Slack). Events the
user triggered themselves are excluded. Failures are log/ledger only — DMs
are a secondary path.
"""

import re

import httpx
from loguru import logger

from app import ledger
from app.clients import discord_api
from app.clients.embeds import GRAY, build_embed, preview_text
from app.identity import user_links


MENTION_PATTERN = re.compile(r"@([\w-]+)")


def _dm_embed(subject: dict, footer: str, body: str | None = None, url: str | None = None) -> dict:
    title = f"#{subject.get('number')} {subject.get('title') or ''}"
    return build_embed(title, url or subject.get("html_url"), GRAY, footer, preview_text(body))


def collect(event: str, payload: dict) -> dict[str, dict]:
    """DM-target GitHub login → embed from the event. The actor themselves is excluded."""
    out: dict[str, dict] = {}
    sender = (payload.get("sender") or {}).get("login")
    action = payload.get("action")

    def add(login: str | None, embed: dict) -> None:
        if login and login != sender and login not in out:
            out[login] = embed

    # assign does not DM — not in Slack real-time alerts either, and excessive in practice
    if event == "pull_request" and action == "review_requested":
        pr = payload.get("pull_request") or {}
        add((payload.get("requested_reviewer") or {}).get("login"), _dm_embed(pr, f"review requested by {sender}"))

    if event == "pull_request_review" and action == "submitted":
        pr = payload.get("pull_request") or {}
        review = payload.get("review") or {}
        state = (review.get("state") or "").replace("_", " ")
        add((pr.get("user") or {}).get("login"), _dm_embed(pr, f"review {state} by {sender}", review.get("body")))

    # Body @mentions — only new issue/PR bodies and new comments (avoid edit storms)
    text, subject, url = None, None, None
    if event in ("issues", "pull_request") and action == "opened":
        subject = payload.get("issue") or payload.get("pull_request") or {}
        text = subject.get("body")
    elif event in ("issue_comment", "pull_request_review_comment") and action == "created":
        subject = payload.get("issue") or payload.get("pull_request") or {}
        comment = payload.get("comment") or {}
        text, url = comment.get("body"), comment.get("html_url")
    if text and subject:
        for login in MENTION_PATTERN.findall(text):
            add(login, _dm_embed(subject, f"mentioned by {sender}", text, url))

    return out


def user_mapping(config: dict) -> dict[str, str]:
    combined = {str(k): str(v) for k, v in (config.get("users") or {}).items()}
    combined.update(user_links.mapping())  # /github signin links take precedence over the config fallback
    return combined


async def notify(config: dict, event: str, payload: dict, *, delivery: str) -> int:
    """Send DMs to mapped targets. Failures are swallowed — must not affect the main (channel) path."""
    mapping = user_mapping(config)
    if not mapping:
        return 0
    targets = [(login, mapping[login], embed) for login, embed in collect(event, payload).items() if login in mapping]
    if not targets:
        return 0
    sent = 0
    async with httpx.AsyncClient(timeout=10) as http:
        for login, user_id, embed in targets:
            dm_delivery = f"{delivery}-dm-{login}" if delivery else ""
            if dm_delivery:
                ledger.begin(dm_delivery, "dm")
            try:
                await discord_api.send_dm(http, user_id, embed)
            except (discord_api.DiscordAPIError, httpx.HTTPError) as exc:
                if dm_delivery:
                    ledger.finish(dm_delivery, outcome="failed", detail=str(exc)[:200])
                logger.error("delivery={} event=dm login={} outcome=failed detail={}", dm_delivery, login, exc)
                continue
            sent += 1
            if dm_delivery:
                ledger.finish(dm_delivery, outcome="sent", feature="dm", detail=embed["footer"]["text"])
            logger.info("delivery={} event=dm login={} outcome=sent", dm_delivery, login)
    return sent
