"""Channel subscription storage + feature token parsing.

Uses the same SQLite file as the ledger (GHCORD_DB) — one backup/volume
management point. Repos with command-managed subscriptions take precedence
over config.toml (the config file is a bootstrap default). The feature
vocabulary stores the Slack official app's tokens verbatim and parses on read.
"""

import json
import re
from contextlib import closing

from loguru import logger

from app import db
from app.config import DEFAULT_EVENTS, Route


# The Slack official app's default 5 + opt-ins
BASE_FEATURES = frozenset(
    {
        "issues",
        "pulls",
        "commits",
        "releases",
        "deployments",
        "reviews",
        "comments",
        "branches",
        "workflows",
        "discussions",
    }
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    channel_id TEXT NOT NULL,
    repo TEXT NOT NULL,
    features TEXT NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, repo)
);
CREATE TABLE IF NOT EXISTS channel_webhooks (
    channel_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    webhook_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect():
    return db.connect(_SCHEMA)


LABEL_TOKEN = re.compile(r'\+label:"([^"]+)"')


def split_label_tokens(raw: str) -> tuple[str, list[str]]:
    """Split `+label:"..."` tokens out of the features string (Slack syntax)."""
    labels = LABEL_TOKEN.findall(raw)
    rest = LABEL_TOKEN.sub("", raw)
    if "+label" in rest:
        raise ValueError('Label filter must be `+label:"label name"` (quotes required)')
    return rest, labels


def tokenize(raw: str) -> tuple[set[str], list[str]]:
    """Whitespace-separated tokens → (events, branch patterns). Empty input gives empty results — no defaults."""
    events: set[str] = set()
    branches: list[str] = []
    invalid: list[str] = []
    for token in raw.split():
        pattern = token.removeprefix("commits:")
        if token in BASE_FEATURES:
            events.add(token)
        elif token != pattern and pattern:
            events.add("commits")
            branches.append(pattern)
        else:
            invalid.append(token)
    if invalid:
        raise ValueError(
            f"Unknown feature: {' '.join(invalid)}\n"
            f'Available: {" ".join(sorted(BASE_FEATURES))}, `commits:<branch-glob>`, `+label:"name"`'
        )
    return events, branches


def parse_features(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Whitespace-separated tokens → (events, branch patterns). Unspecified means the same default 5 as Slack."""
    if not raw.split():
        return tuple(sorted(DEFAULT_EVENTS)), ()
    events, branches = tokenize(raw)
    return tuple(sorted(events)), tuple(branches)


def _tokens_of(events: set[str], branches: list[str]) -> list[str]:
    """(events, patterns) → token list for storage. With patterns, commits:pattern replaces plain commits."""
    tokens = sorted(events - {"commits"} if branches else events)
    return tokens + [f"commits:{p}" for p in branches]


def subscribe_merge(channel_id: str, repo: str, features_raw: str, label_opt: str | None) -> dict:
    """Slack semantics: new = default 5 ∪ specified; existing adds specified. Patterns/label replaced when given."""
    rest, label_tokens = split_label_tokens(features_raw or "")
    add_events, add_branches = tokenize(rest)
    label = (label_tokens[-1] if label_tokens else None) or label_opt

    existing = next((r for r in for_channel(channel_id) if r["repo"] == repo.lower()), None)
    if existing:
        cur_events, cur_branches = tokenize(" ".join(existing["features"]))
        events = cur_events | add_events
        branches = add_branches or cur_branches
        label = label or existing["label"]
    else:
        events = set(DEFAULT_EVENTS) | add_events
        branches = add_branches

    tokens = _tokens_of(events, branches)
    upsert(channel_id, repo, tokens, label)
    return {"features": tokens, "label": label}


def unsubscribe_features(channel_id: str, repo: str, features_raw: str) -> str:
    """Remove only the given features/`+label`. Returns: updated | removed (all gone) | missing (no subscription)."""
    existing = next((r for r in for_channel(channel_id) if r["repo"] == repo.lower()), None)
    if existing is None:
        return "missing"
    rest, label_tokens = split_label_tokens(features_raw or "")
    rem_events, rem_branches = tokenize(rest)

    cur_events, cur_branches = tokenize(" ".join(existing["features"]))
    events = cur_events - rem_events
    branches = [] if "commits" in rem_events else [p for p in cur_branches if p not in rem_branches]
    if branches and "commits" not in events:
        branches = []
    label = None if label_tokens else existing["label"]

    if not events:
        remove(channel_id, repo)
        return "removed"
    upsert(channel_id, repo, _tokens_of(events, branches), label)
    return "updated"


def upsert(channel_id: str, repo: str, features: list[str], label: str | None) -> None:
    now = db.utcnow()
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO subscriptions (channel_id, repo, features, label, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (channel_id, repo)"
            " DO UPDATE SET features = excluded.features, label = excluded.label, updated_at = excluded.updated_at",
            (channel_id, repo.lower(), json.dumps(features), label, now, now),
        )


def remove(channel_id: str, repo: str) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute("DELETE FROM subscriptions WHERE channel_id = ? AND repo = ?", (channel_id, repo.lower()))
        return cur.rowcount > 0


def for_channel(channel_id: str) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT repo, features, label FROM subscriptions WHERE channel_id = ? ORDER BY repo", (channel_id,)
        ).fetchall()
    return [{"repo": r["repo"], "features": json.loads(r["features"]), "label": r["label"]} for r in rows]


def routes_for(repo: str) -> list[Route]:
    """Routes for the channels subscribed to this repo (exact match or the whole owner).

    An owner subscription covers every repo under that owner. If the
    same channel subscribes to both the repo and the owner, only the more
    specific repo subscription is used — Slack double-sends in this case, but
    that is closer to a defect (see the integrations/slack#391 reply).
    """
    full = repo.lower()
    owner = full.split("/", 1)[0]
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT s.channel_id, s.repo, s.features, s.label, w.webhook_url"
            " FROM subscriptions s LEFT JOIN channel_webhooks w ON w.channel_id = s.channel_id"
            " WHERE s.repo IN (?, ?)"
            " ORDER BY s.channel_id, CASE WHEN s.repo = ? THEN 0 ELSE 1 END",
            (full, owner, full),
        ).fetchall()
    routes = []
    seen_channels: set[str] = set()
    for row in rows:
        if row["channel_id"] in seen_channels:
            continue
        seen_channels.add(row["channel_id"])
        if not row["webhook_url"]:
            # subscribe stores the subscription only after securing a webhook, so absent in the normal flow
            logger.warning("Subscription without webhook: channel={} repo={}", row["channel_id"], repo)
            continue
        events, branches = parse_features(" ".join(json.loads(row["features"])))
        routes.append(
            Route(
                webhook_url=row["webhook_url"],
                events=frozenset(events),
                branches=branches,
                labels=(row["label"],) if row["label"] else (),
            )
        )
    return routes


def webhook_url_for(channel_id: str) -> str | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT webhook_url FROM channel_webhooks WHERE channel_id = ?", (channel_id,)).fetchone()
    return row["webhook_url"] if row else None


def save_webhook(channel_id: str, webhook_id: str, webhook_url: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO channel_webhooks (channel_id, webhook_id, webhook_url, created_at)"
            " VALUES (?, ?, ?, ?)",
            (channel_id, webhook_id, webhook_url, db.utcnow()),
        )
