"""TOML routing config.

The config file is the only state in stage 1 — SQLite arrives in stage 2 (doc 02).
Uses stdlib tomllib only, to keep the dependency tree from growing.

The event vocabulary follows the official Slack app: issues / pulls / commits /
releases / deployments (the default 5) + reviews / comments / branches (opt-in).
"""

import fnmatch
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


# Repo root anchor — resolve file paths from here instead of counting parents in leaf modules,
# which silently breaks when a file moves deeper (bitten during a package restructure)
BASE_DIR = Path(__file__).resolve().parents[1]

# Same as the official Slack app's 5 default subscriptions (doc 02 A1)
DEFAULT_EVENTS = ("issues", "pulls", "commits", "releases", "deployments")


@dataclass(frozen=True)
class Route:
    webhook_url: str
    events: frozenset[str]
    branches: tuple[str, ...]  # empty = default branch only (same as Slack's default behavior)
    labels: tuple[str, ...]  # empty = no label filter


def load_config() -> dict:
    path = os.environ.get("GHCORD_CONFIG", "config.toml")
    with open(path, "rb") as f:
        return tomllib.load(f)


def ops_webhook_url(config: dict) -> str | None:
    """[ops] channel — delivery-failure alerts only. Not a routing target."""
    return (config.get("ops") or {}).get("webhook_url") or None


def resolve_route(config: dict, repo_full_name: str) -> Route | None:
    default = config.get("default") or {}
    repo = (config.get("repos") or {}).get(repo_full_name) or {}
    webhook_url = repo.get("webhook_url") or default.get("webhook_url")
    if not webhook_url:
        return None
    events = repo.get("events") or default.get("events") or DEFAULT_EVENTS
    branches = repo.get("branches") or default.get("branches") or ()
    labels = repo.get("labels") or default.get("labels") or ()
    return Route(
        webhook_url=webhook_url,
        events=frozenset(events),
        branches=tuple(branches),
        labels=tuple(labels),
    )


def branch_allowed(route: Route, branch: str, default_branch: str) -> bool:
    if not route.branches:
        return branch == default_branch
    return any(fnmatch.fnmatch(branch, pattern) for pattern in route.branches)


def labels_allowed(route: Route, labels: list[str]) -> bool:
    if not route.labels:
        return True
    return bool(set(labels) & set(route.labels))
