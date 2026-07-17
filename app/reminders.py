"""Pending-review reminders.

Sends the list of "open PRs with review requested" once per day per channel at
the configured time (KST). No separate daemon — an in-process asyncio task ticks
every 60 seconds. Idempotent via last_sent_date, so restarts and delays never
double-send, and sends missed during downtime catch up after recovery. On a
failed send we don't mark, so the next tick retries.
"""

import asyncio
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from app import db, ledger, subscriptions
from app.clients import discord_api
from app.clients.embeds import GRAY, GREEN, build_embed
from app.clients.github_app import primary_installation_client


TZ = ZoneInfo("Asia/Seoul")
TICK_SECONDS = 60
LIST_LIMIT = 15

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    channel_id TEXT PRIMARY KEY,
    github_login TEXT NOT NULL,
    send_at TEXT NOT NULL,
    last_sent_date TEXT,
    created_at TEXT NOT NULL
)
"""


def _connect():
    return db.connect(_SCHEMA)


def set_reminder(channel_id: str, github_login: str, send_at: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO reminders (channel_id, github_login, send_at, created_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (channel_id) DO UPDATE SET github_login = excluded.github_login,"
            " send_at = excluded.send_at, last_sent_date = NULL",
            (channel_id, github_login, send_at, datetime.now(TZ).isoformat(timespec="seconds")),
        )


def clear_reminder(channel_id: str) -> bool:
    with closing(_connect()) as conn, conn:
        return conn.execute("DELETE FROM reminders WHERE channel_id = ?", (channel_id,)).rowcount > 0


def get_reminder(channel_id: str) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM reminders WHERE channel_id = ?", (channel_id,)).fetchone()
    return dict(row) if row else None


def due_reminders(now: datetime) -> list[dict]:
    today = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE send_at <= ? AND (last_sent_date IS NULL OR last_sent_date < ?)",
            (hhmm, today),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_sent(channel_id: str, date_str: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE reminders SET last_sent_date = ? WHERE channel_id = ?", (date_str, channel_id))


async def review_requested_prs(login: str) -> list[dict]:
    gh = await primary_installation_client()
    res = await gh.rest.search.async_issues_and_pull_requests(
        q=f"type:pr state:open review-requested:{login} archived:false"
    )
    items = res.parsed_data.items
    return [
        {
            "title": item.title,
            "html_url": item.html_url,
            "repo": "/".join((item.repository_url or "").rsplit("/", 2)[-2:]),
        }
        for item in items
    ]


def reminder_embed(login: str, prs: list[dict]) -> dict:
    if not prs:
        return build_embed(f"No pending reviews 🎉 — {login}", None, GREEN, "review reminder")
    lines = [f"- [{pr['title']}]({pr['html_url']}) · `{pr['repo']}`" for pr in prs[:LIST_LIMIT]]
    if len(prs) > LIST_LIMIT:
        lines.append(f"… and {len(prs) - LIST_LIMIT} more")
    count = len(prs)
    title = f"{count} PR{'s' if count > 1 else ''} waiting for review — {login}"
    return build_embed(title, None, GRAY, "review reminder", "\n".join(lines))


async def _deliver(channel_id: str, embed: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        url = subscriptions.webhook_url_for(channel_id)
        if not url:
            webhook_id, url = await discord_api.ensure_channel_webhook(http, channel_id)
            subscriptions.save_webhook(channel_id, webhook_id, url)
        res = await http.post(url, json={"embeds": [embed]})
        res.raise_for_status()


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(TZ)
    for row in due_reminders(now):
        channel_id, login = row["channel_id"], row["github_login"]
        delivery = f"reminder-{channel_id}-{now.date().isoformat()}"
        ledger.begin(delivery, "reminder")
        try:
            prs = await review_requested_prs(login)
            await _deliver(channel_id, reminder_embed(login, prs))
        except Exception as exc:  # don't mark on failure — the next tick retries
            ledger.finish(delivery, outcome="failed", detail=str(exc)[:200])
            logger.error("delivery={} event=reminder channel={} outcome=failed detail={}", delivery, channel_id, exc)
            continue
        mark_sent(channel_id, now.date().isoformat())
        ledger.finish(delivery, outcome="sent", feature="reminder", detail=f"{len(prs)} PRs for {login}")
        logger.info("delivery={} event=reminder channel={} outcome=sent prs={}", delivery, channel_id, len(prs))


async def scheduler() -> None:
    logger.info("Reminder scheduler started (tick={}s, tz={})", TICK_SECONDS, TZ)
    while True:
        try:
            await tick()
        except Exception as exc:
            logger.error("Reminder tick crashed: {}", exc)
        await asyncio.sleep(TICK_SECONDS)
