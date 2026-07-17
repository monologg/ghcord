"""Delivery ledger — persist-before-accept.

A delivery that passes signature verification is recorded before processing
(begin), and however processing ends, the result is kept (finish). Deliveries
whose outcome stayed 'received' after a crash and 'failed' deliveries pass
GitHub redelivery — the ledger is the single source of dedupe, so duplicate
suppression survives restarts.

stdlib sqlite3 only (connection details in app.db).
"""

from contextlib import closing

from app import db


# Re-receiving a delivery that ended with these outcomes is a GitHub duplicate send (202 already returned)
_TERMINAL_OUTCOMES = frozenset({"sent", "ignored", "unrouted"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    repo TEXT,
    feature TEXT,
    outcome TEXT NOT NULL DEFAULT 'received',
    detail TEXT,
    duration_ms REAL,
    attempts INTEGER NOT NULL DEFAULT 1,
    received_at TEXT NOT NULL,
    completed_at TEXT
)
"""


def _connect():
    return db.connect(_SCHEMA)


def begin(delivery_id: str, event: str) -> bool:
    """Persist immediately on receipt. False means an already-processed successful duplicate — do not process."""
    with closing(_connect()) as conn, conn:
        row = conn.execute("SELECT outcome FROM deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO deliveries (delivery_id, event, received_at) VALUES (?, ?, ?)",
                (delivery_id, event, db.utcnow()),
            )
            return True
        if row["outcome"] in _TERMINAL_OUTCOMES:
            return False
        # Retry ledger: re-receipt in failed/received state is recorded as a new attempt
        conn.execute(
            "UPDATE deliveries SET attempts = attempts + 1, outcome = 'received',"
            " completed_at = NULL, duration_ms = NULL WHERE delivery_id = ?",
            (delivery_id,),
        )
        return True


def finish(
    delivery_id: str,
    *,
    outcome: str,
    repo: str | None = None,
    feature: str | None = None,
    detail: str | None = None,
    duration_ms: float | None = None,
) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE deliveries SET outcome = ?, repo = COALESCE(?, repo), feature = COALESCE(?, feature),"
            " detail = ?, duration_ms = ?, completed_at = ? WHERE delivery_id = ?",
            (outcome, repo, feature, detail, duration_ms, db.utcnow(), delivery_id),
        )


def recent(limit: int = 20) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM deliveries ORDER BY received_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def stats() -> dict:
    """Totals per outcome + success rate (sent / (sent + failed)) — counts only attempted sends."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT outcome, COUNT(*) AS n FROM deliveries GROUP BY outcome").fetchall()
    totals = {row["outcome"]: row["n"] for row in rows}
    attempted = totals.get("sent", 0) + totals.get("failed", 0)
    success_rate = totals.get("sent", 0) / attempted if attempted else None
    return {"totals": totals, "success_rate": success_rate}
