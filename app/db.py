"""Shared SQLite access for the single GHCORD_DB file.

Every store (ledger, subscriptions, reminders, user_links) lives in one SQLite
file — one backup/volume management point. Single-worker assumption (same as
the dedupe premise in webhook/router.py), so a short per-call connection is
enough. Each module owns its schema and passes it here.
"""

import os
import sqlite3
from datetime import datetime, timezone


def connect(schema: str) -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ.get("GHCORD_DB", "ghcord.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(schema)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
