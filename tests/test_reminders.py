"""Pending-review reminders: storage + due decision + tick idempotency — no network."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app import reminders


KST = ZoneInfo("Asia/Seoul")


def at(hhmm: str, day: str = "2026-07-15") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=KST)


def test_set_get_clear_roundtrip():
    assert reminders.get_reminder("ch-1") is None
    reminders.set_reminder("ch-1", "monologg", "09:30")
    row = reminders.get_reminder("ch-1")
    assert row["github_login"] == "monologg"
    assert row["send_at"] == "09:30"
    # setting again replaces
    reminders.set_reminder("ch-1", "monologg", "18:00")
    assert reminders.get_reminder("ch-1")["send_at"] == "18:00"
    assert reminders.clear_reminder("ch-1") is True
    assert reminders.clear_reminder("ch-1") is False
    assert reminders.get_reminder("ch-1") is None


def test_due_only_after_send_time_and_once_per_day():
    reminders.set_reminder("ch-1", "monologg", "09:30")
    assert reminders.due_reminders(at("09:29")) == []
    due = reminders.due_reminders(at("09:31"))
    assert [r["channel_id"] for r in due] == ["ch-1"]
    reminders.mark_sent("ch-1", "2026-07-15")
    assert reminders.due_reminders(at("10:00")) == []  # no resend on the same day
    assert len(reminders.due_reminders(at("09:31", day="2026-07-16"))) == 1  # due again the next day


def test_reminder_embed_lists_prs_or_celebrates():
    prs = [{"title": "Fix bug", "html_url": "https://github.com/o/r/pull/1", "repo": "o/r"}]
    embed = reminders.reminder_embed("monologg", prs)
    assert "1 PR" in embed["title"]
    assert "Fix bug" in embed["description"]
    empty = reminders.reminder_embed("monologg", [])
    assert "No pending reviews" in empty["title"]


def test_tick_sends_due_and_marks(monkeypatch):
    sent = []

    async def fake_prs(login):
        return [{"title": "T", "html_url": "https://x/pull/1", "repo": "o/r"}]

    async def fake_deliver(channel_id, embed):
        sent.append(channel_id)

    monkeypatch.setattr(reminders, "review_requested_prs", fake_prs)
    monkeypatch.setattr(reminders, "_deliver", fake_deliver)
    reminders.set_reminder("ch-1", "monologg", "09:00")
    asyncio.run(reminders.tick(at("09:05")))
    assert sent == ["ch-1"]
    asyncio.run(reminders.tick(at("09:06")))
    assert sent == ["ch-1"]  # second tick on the same day is a no-op (idempotent)


def test_tick_failure_does_not_mark_sent(monkeypatch):
    async def failing_prs(login):
        raise RuntimeError("boom")

    monkeypatch.setattr(reminders, "review_requested_prs", failing_prs)
    reminders.set_reminder("ch-1", "monologg", "09:00")
    asyncio.run(reminders.tick(at("09:05")))
    # failed, so the next tick must retry it
    assert len(reminders.due_reminders(at("09:10"))) == 1
