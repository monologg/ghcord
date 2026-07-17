"""Discord HTTP interactions endpoint.

Receives slash commands without a gateway: Ed25519 signature verification
(fail-closed) → PING/PONG → /github subcommand dispatch. Discord tests the
verification with deliberately invalid signatures at endpoint registration and
periodically, so the 401 path must be exact.

subscribe calls external APIs, so it goes deferred (type 5) to dodge the 3-second
limit; unsubscribe/list only touch SQLite and respond immediately. Commands are
also recorded in the ledger (outcome ok/error — kept separate from the sent/failed
success-rate stats of webhook deliveries).
"""

import os
import re
import time

import httpx
import orjson
from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from app import ledger, reminders, subscriptions
from app.clients import discord_api
from app.config import DEFAULT_EVENTS
from app.identity import oauth, user_links
from app.interactions import actions, preview


router = APIRouter()

SIGNATURE_HEADER = "X-Signature-Ed25519"
TIMESTAMP_HEADER = "X-Signature-Timestamp"

# interaction payloads are a few KB — anything bigger is not Discord
MAX_BODY_BYTES = 1_000_000

REPO_PATTERN = re.compile(r"[\w.-]+/[\w.-]+")
# subscribe-family also accepts a bare owner — subscribes all its repos
TARGET_PATTERN = re.compile(r"[\w.-]+(/[\w.-]+)?")

# interaction types
PING = 1
APPLICATION_COMMAND = 2
MODAL_SUBMIT = 5

# response types
PONG = 1
CHANNEL_MESSAGE = 4
DEFERRED = 5
MODAL = 9

EPHEMERAL = 64  # command results are shown only to the invoker


def verify_signature(raw_body: bytes, signature: str, timestamp: str, public_key_hex: str) -> bool:
    try:
        VerifyKey(bytes.fromhex(public_key_hex)).verify(timestamp.encode() + raw_body, bytes.fromhex(signature))
        return True
    except (BadSignatureError, ValueError):
        return False


def ephemeral(content: str) -> JSONResponse:
    return JSONResponse({"type": CHANNEL_MESSAGE, "data": {"content": content, "flags": EPHEMERAL}})


def _finish_cmd(
    interaction: dict, sub: str, *, outcome: str, repo: str = "", detail: str = "", started: float
) -> None:
    delivery = interaction.get("id") or ""
    if delivery:
        ledger.finish(
            delivery,
            outcome=outcome,
            repo=repo or None,
            feature=f"cmd:{sub}",
            detail=detail or None,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    log = logger.error if outcome == "error" else logger.info
    log(
        "delivery={} event=cmd:{} repo={} outcome={} detail={}",
        delivery or "-",
        sub,
        repo or "-",
        outcome,
        detail or "-",
    )


@router.post("/interactions/discord")
async def receive(request: Request, background: BackgroundTasks) -> Response:
    # fail-closed: exposed without a key we would accept forged interactions, so reject
    public_key = os.environ.get("DISCORD_PUBLIC_KEY")
    if not public_key:
        logger.warning("Rejected interaction: DISCORD_PUBLIC_KEY not configured (fail-closed)")
        return PlainTextResponse("Interactions not configured", status_code=401)

    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body += chunk
        if len(raw_body) > MAX_BODY_BYTES:
            logger.warning("Rejected interaction: body exceeds {} bytes", MAX_BODY_BYTES)
            return PlainTextResponse("Payload too large", status_code=413)
    raw_body = bytes(raw_body)

    signature = request.headers.get(SIGNATURE_HEADER)
    timestamp = request.headers.get(TIMESTAMP_HEADER)
    if not signature or not timestamp or not verify_signature(raw_body, signature, timestamp, public_key):
        logger.warning("Rejected interaction: invalid signature (body {} bytes)", len(raw_body))
        return PlainTextResponse("Invalid signature", status_code=401)

    try:
        interaction = orjson.loads(raw_body)
    except orjson.JSONDecodeError:
        return PlainTextResponse("Bad JSON", status_code=400)

    if interaction.get("type") == PING:
        logger.info("Interactions ping received")
        return JSONResponse({"type": PONG})
    if interaction.get("type") == APPLICATION_COMMAND:
        return dispatch(interaction, background)
    if interaction.get("type") == MODAL_SUBMIT:
        return dispatch_modal(interaction, background)
    return PlainTextResponse("Unsupported interaction type", status_code=400)


def dispatch(interaction: dict, background: BackgroundTasks) -> JSONResponse:
    started = time.perf_counter()
    data = interaction.get("data") or {}
    node = next((o for o in data.get("options") or [] if o.get("type") in (1, 2)), {})
    if node.get("type") == 2:  # subcommand group (e.g. remind set)
        inner = next((o for o in node.get("options") or [] if o.get("type") == 1), {})
        sub = f"{node.get('name')}-{inner.get('name')}"
        sub_option = inner
    else:
        sub = node.get("name") or "?"
        sub_option = node
    opts = {o["name"]: o.get("value") for o in sub_option.get("options") or []}
    channel_id = str(interaction.get("channel_id") or "")
    logger.info("Command received: /github {} (channel={})", sub, channel_id)

    delivery = interaction.get("id") or ""
    if delivery:
        ledger.begin(delivery, f"cmd:{sub}")

    if sub == "subscribe":
        return _subscribe(interaction, sub, opts, channel_id, background, started)
    if sub == "unsubscribe":
        return _unsubscribe(interaction, sub, opts, channel_id, started)
    if sub == "list":
        return _list(interaction, sub, channel_id, started)
    if sub == "preview":
        return _preview_cmd(interaction, sub, opts, background, started)
    if sub == "open":
        return _open(interaction, sub, opts, started)
    if sub in ("close", "reopen"):
        return _set_state_cmd(interaction, sub, opts, background, started)
    if sub.startswith("remind-"):
        return _remind(interaction, sub, opts, channel_id, started)
    if sub in ("signin", "signout"):
        return _sign(interaction, sub, started)
    _finish_cmd(interaction, sub, outcome="ignored", detail="unknown subcommand", started=started)
    return ephemeral(f"`/github {sub}` is not a supported command")


def _actor_id(interaction: dict) -> str:
    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    return str(user.get("id") or "")


def _sign(interaction: dict, sub: str, started: float) -> JSONResponse:
    user_id = _actor_id(interaction)
    if not user_id:
        _finish_cmd(interaction, sub, outcome="error", detail="no actor id", started=started)
        return ephemeral("Could not read the invoking user")
    if sub == "signout":
        removed = user_links.unlink_discord(user_id)
        _finish_cmd(interaction, sub, outcome="ok" if removed else "ignored", started=started)
        if not removed:
            return ephemeral("No linked GitHub account — link one with `/github signin`")
        return ephemeral(f"🔓 Unlinked: `{'`, `'.join(removed)}` — DM alerts are now off")
    if not oauth.configured():
        _finish_cmd(interaction, sub, outcome="error", detail="oauth not configured", started=started)
        return ephemeral("GitHub OAuth is not configured — set GITHUB_CLIENT_ID/SECRET (docs/05)")
    state = user_links.create_state(user_id)
    _finish_cmd(interaction, sub, outcome="ok", detail="authorize link issued", started=started)
    return ephemeral(
        f"🔗 [Connect your GitHub account](<{oauth.authorize_url(state)}>)\n"
        "Complete within 10 minutes — the bot will DM you once linked"
    )


TIME_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
LOGIN_PATTERN = re.compile(r"[\w-]+")


def _remind(interaction: dict, sub: str, opts: dict, channel_id: str, started: float) -> JSONResponse:
    if sub == "remind-set":
        send_at = (opts.get("time") or "").strip()
        login = (opts.get("user") or "").strip()
        if not TIME_PATTERN.fullmatch(send_at):
            _finish_cmd(interaction, sub, outcome="error", detail="bad time", started=started)
            return ephemeral(f"Time must be `HH:MM` (24-hour, KST) — got `{send_at or 'nothing'}`")
        if not LOGIN_PATTERN.fullmatch(login):
            _finish_cmd(interaction, sub, outcome="error", detail="bad login", started=started)
            return ephemeral("Check the GitHub username")
        reminders.set_reminder(channel_id, login, send_at)
        _finish_cmd(interaction, sub, outcome="ok", detail=f"{send_at} {login}", started=started)
        return ephemeral(f"⏰ Pending review PRs for `{login}` will be posted here daily at `{send_at}` (KST)")
    if sub == "remind-off":
        removed = reminders.clear_reminder(channel_id)
        _finish_cmd(interaction, sub, outcome="ok" if removed else "ignored", started=started)
        return ephemeral("⏰ Reminder turned off" if removed else "No reminder in this channel")
    if sub == "remind-status":
        row = reminders.get_reminder(channel_id)
        _finish_cmd(interaction, sub, outcome="ok", started=started)
        if not row:
            return ephemeral("No reminder in this channel — start with `/github remind set`")
        return ephemeral(
            f"⏰ Daily at `{row['send_at']}` (KST) · `{row['github_login']}`"
            + (f" · last sent {row['last_sent_date']}" if row["last_sent_date"] else "")
        )
    _finish_cmd(interaction, sub, outcome="ignored", detail="unknown remind action", started=started)
    return ephemeral(f"`/github {sub.replace('-', ' ')}` is not a supported command")


def _open(interaction: dict, sub: str, opts: dict, started: float) -> JSONResponse:
    repo = (opts.get("repo") or "").strip().lower()
    if not REPO_PATTERN.fullmatch(repo):
        _finish_cmd(interaction, sub, outcome="error", repo=repo, detail="bad repo format", started=started)
        return ephemeral(f"Repo must be `owner/repo` — got `{repo or 'nothing'}`")
    _finish_cmd(interaction, sub, outcome="ok", repo=repo, detail="modal opened", started=started)
    # a modal must be the first response — no deferred. repo travels in custom_id.
    return JSONResponse(
        {
            "type": MODAL,
            "data": {
                "custom_id": f"open:{repo}",
                "title": f"New issue — {repo}"[:45],
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 4,
                                "custom_id": "title",
                                "label": "Title",
                                "style": 1,
                                "required": True,
                                "max_length": 256,
                            }
                        ],
                    },
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 4,
                                "custom_id": "body",
                                "label": "Body (optional)",
                                "style": 2,
                                "required": False,
                                "max_length": 4000,
                            }
                        ],
                    },
                ],
            },
        }
    )


def dispatch_modal(interaction: dict, background: BackgroundTasks) -> JSONResponse:
    started = time.perf_counter()
    data = interaction.get("data") or {}
    custom_id = data.get("custom_id") or ""
    if not custom_id.startswith("open:"):
        return ephemeral("Unknown modal")
    repo_full = custom_id.removeprefix("open:")
    values = {
        field["custom_id"]: field.get("value")
        for row in data.get("components") or []
        for field in row.get("components") or []
    }
    delivery = interaction.get("id") or ""
    if delivery:
        ledger.begin(delivery, "cmd:open")
    background.add_task(
        _complete_open, interaction, repo_full, (values.get("title") or "").strip(), values.get("body"), started
    )
    return JSONResponse({"type": DEFERRED, "data": {"flags": EPHEMERAL}})


async def _complete_open(interaction: dict, repo_full: str, title: str, body: str | None, started: float) -> None:
    owner, repo = repo_full.split("/", 1)
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            embed = await actions.create_issue(owner, repo, title, body)
            _finish_cmd(interaction, "open", outcome="ok", repo=repo_full, detail=embed["title"], started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", embeds=[embed])
        except (actions.ActionError, httpx.HTTPError) as exc:
            _finish_cmd(interaction, "open", outcome="error", repo=repo_full, detail=str(exc), started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", content=f"⚠️ {exc}")


def _set_state_cmd(
    interaction: dict, sub: str, opts: dict, background: BackgroundTasks, started: float
) -> JSONResponse:
    url = (opts.get("url") or "").strip()
    parsed = preview.parse_url(url)
    if not parsed:
        _finish_cmd(interaction, sub, outcome="error", detail="unsupported url", started=started)
        return ephemeral(preview.USAGE)
    owner, repo, kind, number = parsed
    if kind == "pull":
        _finish_cmd(interaction, sub, outcome="error", detail="pr not supported", started=started)
        return ephemeral("Issues only — PRs are handled by the review/merge flow")
    reason = opts.get("reason") if sub == "close" else None
    background.add_task(_complete_set_state, interaction, sub, owner, repo, number, reason, started)
    return JSONResponse({"type": DEFERRED, "data": {"flags": EPHEMERAL}})


async def _complete_set_state(
    interaction: dict, sub: str, owner: str, repo: str, number: int, reason: str | None, started: float
) -> None:
    state = "closed" if sub == "close" else "open"
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            embed = await actions.set_issue_state(owner, repo, number, state=state, reason=reason)
            _finish_cmd(interaction, sub, outcome="ok", repo=f"{owner}/{repo}", detail=embed["title"], started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", embeds=[embed])
        except (actions.ActionError, httpx.HTTPError) as exc:
            _finish_cmd(interaction, sub, outcome="error", repo=f"{owner}/{repo}", detail=str(exc), started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", content=f"⚠️ {exc}")


def _preview_cmd(interaction: dict, sub: str, opts: dict, background: BackgroundTasks, started: float) -> JSONResponse:
    url = (opts.get("url") or "").strip()
    if not preview.parse_url(url):
        _finish_cmd(interaction, sub, outcome="error", detail="unsupported url", started=started)
        return ephemeral(preview.USAGE)
    # GitHub REST lookup runs outside the 3-second limit — deferred, then followup
    background.add_task(_complete_preview, interaction, sub, url, started)
    return JSONResponse({"type": DEFERRED, "data": {"flags": EPHEMERAL}})


async def _complete_preview(interaction: dict, sub: str, url: str, started: float) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            embed = await preview.fetch_embed(url)
            _finish_cmd(interaction, sub, outcome="ok", detail=embed["title"], started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", embeds=[embed])
        except (preview.PreviewError, httpx.HTTPError) as exc:
            _finish_cmd(interaction, sub, outcome="error", detail=str(exc), started=started)
            await discord_api.edit_original(http, interaction.get("token") or "", content=f"⚠️ {exc}")


def _subscribe(
    interaction: dict, sub: str, opts: dict, channel_id: str, background: BackgroundTasks, started: float
) -> JSONResponse:
    repo = (opts.get("repo") or "").strip().lower()
    features = (opts.get("features") or "").strip()
    label = (opts.get("label") or "").strip() or None
    if not TARGET_PATTERN.fullmatch(repo):
        _finish_cmd(interaction, sub, outcome="error", repo=repo, detail="bad repo format", started=started)
        return ephemeral(f"Use `owner/repo`, or `owner` for all its repos — got `{repo or 'nothing'}`")
    try:
        rest, _ = subscriptions.split_label_tokens(features)
        subscriptions.tokenize(rest)
    except ValueError as exc:
        _finish_cmd(interaction, sub, outcome="error", repo=repo, detail="bad feature token", started=started)
        return ephemeral(str(exc))

    # securing the webhook is an external API call, so deferred to dodge the 3-second limit — result via followup
    background.add_task(_complete_subscribe, interaction, sub, channel_id, repo, features, label, started)
    return JSONResponse({"type": DEFERRED, "data": {"flags": EPHEMERAL}})


async def _complete_subscribe(
    interaction: dict, sub: str, channel_id: str, repo: str, features: str, label: str | None, started: float
) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            if not subscriptions.webhook_url_for(channel_id):
                webhook_id, url = await discord_api.ensure_channel_webhook(http, channel_id)
                subscriptions.save_webhook(channel_id, webhook_id, url)
            # Slack semantics: merge into the existing subscription — not replace
            result = subscriptions.subscribe_merge(channel_id, repo, features, label)
            shown = " ".join(result["features"])
            target = f"`{repo}`" + (" (all repos)" if "/" not in repo else "")
            message = f"✅ Subscribed to {target} — features: `{shown}`" + (
                f" · label: `{result['label']}`" if result["label"] else ""
            )
            _finish_cmd(interaction, sub, outcome="ok", repo=repo, detail=shown, started=started)
        except (discord_api.DiscordAPIError, httpx.HTTPError) as exc:
            message = f"⚠️ Failed to subscribe to `{repo}`: {exc}"
            _finish_cmd(interaction, sub, outcome="error", repo=repo, detail=str(exc), started=started)
        await discord_api.edit_original(http, interaction.get("token") or "", message)


def _unsubscribe(interaction: dict, sub: str, opts: dict, channel_id: str, started: float) -> JSONResponse:
    repo = (opts.get("repo") or "").strip().lower()
    features = (opts.get("features") or "").strip()
    if features:
        # partial unsubscribe (Slack semantics): remove only the given features/`+label`
        try:
            outcome = subscriptions.unsubscribe_features(channel_id, repo, features)
        except ValueError as exc:
            _finish_cmd(interaction, sub, outcome="error", repo=repo, detail="bad feature token", started=started)
            return ephemeral(str(exc))
        if outcome == "missing":
            _finish_cmd(interaction, sub, outcome="ignored", repo=repo, detail="no such subscription", started=started)
            return ephemeral(f"`{repo}` is not subscribed in this channel — check with `/github list`")
        _finish_cmd(interaction, sub, outcome="ok", repo=repo, detail=f"-{features} ({outcome})", started=started)
        if outcome == "removed":
            return ephemeral(f"🗑️ `{repo}` — no features left, subscription removed")
        row = next(r for r in subscriptions.for_channel(channel_id) if r["repo"] == repo)
        return ephemeral(f"➖ Removed `{features}` from `{repo}` — remaining features: `{' '.join(row['features'])}`")
    if subscriptions.remove(channel_id, repo):
        _finish_cmd(interaction, sub, outcome="ok", repo=repo, started=started)
        return ephemeral(f"🗑️ Unsubscribed from `{repo}`")
    _finish_cmd(interaction, sub, outcome="ignored", repo=repo, detail="no such subscription", started=started)
    return ephemeral(f"`{repo}` is not subscribed in this channel — check with `/github list`")


def _list(interaction: dict, sub: str, channel_id: str, started: float) -> JSONResponse:
    rows = subscriptions.for_channel(channel_id)
    _finish_cmd(interaction, sub, outcome="ok", detail=f"{len(rows)} subscriptions", started=started)
    if not rows:
        return ephemeral("No subscriptions in this channel — start with `/github subscribe owner/repo`")
    lines = [
        f"- `{row['repo']}`{' (all repos)' if '/' not in row['repo'] else ''}"
        f" — {' '.join(row['features']) or ' '.join(DEFAULT_EVENTS)}"
        + (f" · label: `{row['label']}`" if row["label"] else "")
        for row in rows
    ]
    return ephemeral("**Subscriptions in this channel**\n" + "\n".join(lines))
