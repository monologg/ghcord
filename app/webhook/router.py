"""GitHub App webhook receiver pipeline.

GitHub App (webhook POST) -> signature verification -> format + routing/filter + Discord send
-> delivery ledger + canonical log + failure alert + /status
"""

import os
import time
import tomllib
from functools import partial

import httpx
import orjson
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger

from app import ledger, subscriptions
from app.config import branch_allowed, labels_allowed, load_config, ops_webhook_url, resolve_route
from app.identity import mentions
from app.webhook.formatters import build
from app.webhook.security import SIGNATURE_HEADER, verify_signature


router = APIRouter()

# GitHub caps webhook payloads at 25MB — anything larger is not GitHub
MAX_BODY_BYTES = 25_000_000

# Same label-filter targets as the Slack official app (not applied to commits/branches)
LABEL_FILTERED_FEATURES = {"issues", "pulls", "comments", "reviews"}

ALERT_COLOR = 0xED4245  # Discord semantic red — intentionally not embeds.RED (GitHub palette)


def _subject_labels(payload: dict) -> list[str]:
    subject = payload.get("issue") or payload.get("pull_request") or {}
    return [label.get("name") for label in subject.get("labels") or [] if label.get("name")]


def _finish(
    message: str,
    status_code: int,
    *,
    delivery: str,
    started: float,
    outcome: str,
    event: str,
    repo: str = "",
    feature: str = "",
    detail: str = "",
) -> PlainTextResponse:
    """Single exit point for all delivery processing — ledger update + one canonical log line."""
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    if delivery:
        ledger.finish(
            delivery,
            outcome=outcome,
            repo=repo or None,
            feature=feature or None,
            detail=detail or None,
            duration_ms=duration_ms,
        )
    log = logger.error if outcome in ("failed", "error") else logger.info
    log(
        "delivery={} event={} repo={} feature={} outcome={} duration_ms={} detail={}",
        delivery or "-",
        event,
        repo or "-",
        feature or "-",
        outcome,
        duration_ms,
        detail or "-",
    )
    return PlainTextResponse(message, status_code=status_code)


async def _alert_ops(http: httpx.AsyncClient, ops_url: str, *, delivery: str, repo: str, feature: str, detail: str):
    """Alert the ops channel about a send failure. Failures of the alert itself are log-only — no recursion."""
    embed = {
        "title": "Discord delivery failed",
        "color": ALERT_COLOR,
        "description": f"repo `{repo}` · feature `{feature}`\ndelivery `{delivery}`\n{detail}",
        "footer": {"text": "ghcord ops"},
    }
    try:
        res = await http.post(ops_url, json={"embeds": [embed]})
        if not res.is_success:
            logger.error("Ops alert failed: HTTP {}", res.status_code)
    except httpx.HTTPError as exc:
        logger.error("Ops alert failed: {}", exc)


@router.api_route("/", methods=["GET", "HEAD"])
def healthcheck() -> PlainTextResponse:
    return PlainTextResponse("OK")


@router.get("/status")
def status(limit: int = 20) -> JSONResponse:
    limit = max(1, min(limit, 100))
    return JSONResponse({"deliveries": ledger.recent(limit), **ledger.stats()})


@router.post("/webhook/github")
async def receive(request: Request) -> PlainTextResponse:
    started = time.perf_counter()

    # fail-closed: exposure without a configured secret would accept forged payloads, so reject
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if not secret:
        logger.warning("Rejected POST: GITHUB_WEBHOOK_SECRET not configured (fail-closed)")
        return PlainTextResponse("Webhook secret not configured", status_code=401)

    # The body is buffered in memory before auth, so cap the size first (re-checked in the stream for chunked)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        logger.warning("Rejected POST: Content-Length {} exceeds limit", content_length)
        return PlainTextResponse("Payload too large", status_code=413)

    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body += chunk
        if len(raw_body) > MAX_BODY_BYTES:
            logger.warning("Rejected POST: body exceeds {} bytes", MAX_BODY_BYTES)
            return PlainTextResponse("Payload too large", status_code=413)
    raw_body = bytes(raw_body)

    signature = request.headers.get(SIGNATURE_HEADER)
    if not verify_signature(raw_body, signature or "", secret):
        # Never log the signature value itself — record only its presence, to diagnose a missing header
        if signature is None:
            logger.warning("Rejected POST: {} header missing (body {} bytes)", SIGNATURE_HEADER, len(raw_body))
        else:
            logger.warning("Rejected POST: invalid signature (body {} bytes)", len(raw_body))
        return PlainTextResponse("Invalid signature", status_code=401)

    event = request.headers.get("x-github-event", "unknown")
    delivery = request.headers.get("x-github-delivery", "")

    if event == "ping":
        logger.info("Ping received (delivery={})", delivery)
        return PlainTextResponse("Pong", status_code=202)

    # persist-before-accept: an authenticated delivery is recorded before processing.
    # Re-receiving a delivery that ended successfully is a GitHub duplicate send — suppressed even after restart.
    # Manual Redeliver gets a new delivery ID, so it is not suppressed.
    if delivery and not ledger.begin(delivery, event):
        logger.info("Duplicate suppressed: event={} delivery={}", event, delivery)
        return PlainTextResponse("Duplicate ignored", status_code=202)

    done = partial(_finish, delivery=delivery, started=started, event=event)

    try:
        payload = orjson.loads(raw_body)
    except orjson.JSONDecodeError:
        return done("Bad JSON", 400, outcome="error", detail="body is not valid JSON")

    repo_name = (payload.get("repository") or {}).get("full_name") or "?"

    # Config file problems are not swallowed silently — they must show as failures in Recent Deliveries to get fixed
    try:
        config = load_config()
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return done("Config error", 500, outcome="error", repo=repo_name, detail=f"config load failed: {exc}")

    # Personal DM notifications — independent of channel routing, so decided before build/filters.
    # Failures are swallowed internally.
    try:
        await mentions.notify(config, event, payload, delivery=delivery)
    except Exception as exc:
        logger.error("DM notify crashed: {}", exc)

    result = build(event, payload)
    if result is None:
        return done(
            "Ignored",
            202,
            outcome="ignored",
            repo=repo_name,
            detail=f"no formatter for action={payload.get('action')}",
        )
    feature, content, embed = result

    # Fan out to channels with command-managed subscriptions (SQLite) if any, else config.toml
    routes = subscriptions.routes_for(repo_name)
    if not routes:
        route = resolve_route(config, repo_name)
        routes = [route] if route else []
    if not routes:
        return done(
            "Unrouted",
            202,
            outcome="unrouted",
            repo=repo_name,
            feature=feature,
            detail="no channel (no default webhook_url)",
        )

    matching = []
    skip_reasons: list[str] = []
    for route in routes:
        if feature not in route.events:
            skip_reasons.append("feature not subscribed")
            continue
        if feature == "commits":
            branch = (payload.get("ref") or "").removeprefix("refs/heads/")
            default_branch = (payload.get("repository") or {}).get("default_branch") or ""
            if not branch_allowed(route, branch, default_branch):
                skip_reasons.append(f"branch={branch} filtered")
                continue
        if feature in LABEL_FILTERED_FEATURES and not labels_allowed(route, _subject_labels(payload)):
            skip_reasons.append("labels filtered")
            continue
        matching.append(route)

    if not matching:
        detail = "; ".join(dict.fromkeys(skip_reasons))
        return done("Ignored", 202, outcome="ignored", repo=repo_name, feature=feature, detail=detail)

    failures: list[str] = []
    async with httpx.AsyncClient(timeout=10) as http:
        for route in matching:
            try:
                res = await http.post(route.webhook_url, json={"content": content, "embeds": [embed]})
                failure = None if res.is_success else f"HTTP {res.status_code} {res.text[:200]}"
            except httpx.HTTPError as exc:
                failure = f"{type(exc).__name__}: {exc}"
            if not failure:
                continue
            failures.append(failure)
            ops_url = ops_webhook_url(config)
            if ops_url == route.webhook_url:
                # The ops channel's own failure goes to a separate path (logs) — don't alert a dead channel again
                logger.error("Ops channel itself failed — alert suppressed")
            elif ops_url:
                await _alert_ops(http, ops_url, delivery=delivery, repo=repo_name, feature=feature, detail=failure)

    if failures:
        # Any single failure = failed — allow GitHub redelivery (duplicates to successful channels accepted)
        return done(
            "Discord error", 502, outcome="failed", repo=repo_name, feature=feature, detail="; ".join(failures)
        )
    return done("Sent", 202, outcome="sent", repo=repo_name, feature=feature, detail=embed.get("title") or content)
