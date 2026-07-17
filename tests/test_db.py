"""Shared SQLite helpers — connect(schema) + utcnow()."""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from app import db


SCHEMA = """
CREATE TABLE IF NOT EXISTS a (id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS b (id TEXT PRIMARY KEY);
"""


def test_connect_applies_schema_and_row_factory():
    with closing(db.connect(SCHEMA)) as conn:
        # multi-statement schemas (subscriptions/user_links) must work too
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"a", "b"} <= tables
        assert conn.row_factory is sqlite3.Row


def test_connect_enables_wal():
    with closing(db.connect(SCHEMA)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_utcnow_is_utc_iso_with_milliseconds():
    now = db.utcnow()
    parsed = datetime.fromisoformat(now)
    assert parsed.tzinfo == timezone.utc
    assert (datetime.now(timezone.utc) - parsed).total_seconds() < 5
    # timespec="milliseconds" — exactly 3 fractional digits, so string ordering matches time ordering
    assert len(now.split(".")[1].split("+")[0]) == 3
