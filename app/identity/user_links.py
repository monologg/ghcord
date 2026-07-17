"""GitHub↔Discord account link storage.

Stores the OAuth result of /github signin. oauth_states holds the single-use
state (10-minute TTL) carried in the authorize link — deleted immediately once
consumed by the callback. config [users] is the bootstrap fallback; links
stored here take precedence.
"""

import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from app import db


STATE_TTL = timedelta(minutes=10)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_links (
    github_login TEXT PRIMARY KEY,
    discord_user_id TEXT NOT NULL,
    linked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    discord_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect():
    return db.connect(_SCHEMA)


def _utcnow() -> datetime:
    # datetime (not str, unlike db.utcnow) — consume_state does TTL arithmetic on it
    return datetime.now(timezone.utc)


def create_state(discord_user_id: str) -> str:
    state = secrets.token_urlsafe(32)
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO oauth_states (state, discord_user_id, created_at) VALUES (?, ?, ?)",
            (state, discord_user_id, _utcnow().isoformat()),
        )
    return state


def consume_state(state: str, *, now: datetime | None = None) -> str | None:
    """Single-use — deleted on return. None if expired (TTL)."""
    now = now or _utcnow()
    with closing(_connect()) as conn, conn:
        row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        if now - datetime.fromisoformat(row["created_at"]) > STATE_TTL:
            return None
        return row["discord_user_id"]


def link(github_login: str, discord_user_id: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_links (github_login, discord_user_id, linked_at) VALUES (?, ?, ?)",
            (github_login, discord_user_id, _utcnow().isoformat()),
        )


def unlink_discord(discord_user_id: str) -> list[str]:
    with closing(_connect()) as conn, conn:
        rows = conn.execute(
            "SELECT github_login FROM user_links WHERE discord_user_id = ? ORDER BY github_login",
            (discord_user_id,),
        ).fetchall()
        conn.execute("DELETE FROM user_links WHERE discord_user_id = ?", (discord_user_id,))
    return [row["github_login"] for row in rows]


def mapping() -> dict[str, str]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT github_login, discord_user_id FROM user_links").fetchall()
    return {row["github_login"]: row["discord_user_id"] for row in rows}
