"""GitHub OAuth callback — completes the /github signin account link.

state is single-use with a 10-minute TTL (user_links), so even though the
endpoint itself is open, a forged link cannot succeed. The user token is used
only to confirm the login, then discarded.
"""

import os

import httpx
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from loguru import logger

from app.clients import discord_api
from app.clients.embeds import GREEN, build_embed
from app.identity import user_links


router = APIRouter()

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


class OAuthError(RuntimeError):
    pass


def authorize_url(state: str) -> str:
    return f"{AUTHORIZE_URL}?client_id={os.environ.get('GITHUB_CLIENT_ID')}&state={state}"


def configured() -> bool:
    return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))


async def exchange_code_for_login(http: httpx.AsyncClient, code: str) -> str:
    res = await http.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": os.environ.get("GITHUB_CLIENT_ID"),
            "client_secret": os.environ.get("GITHUB_CLIENT_SECRET"),
            "code": code,
        },
        headers={"Accept": "application/json"},
    )
    token = res.json().get("access_token") if res.is_success else None
    if not token:
        raise OAuthError(f"Code exchange failed: HTTP {res.status_code}")
    res = await http.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    if not res.is_success or not res.json().get("login"):
        raise OAuthError(f"User lookup failed: HTTP {res.status_code}")
    return res.json()["login"]


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><meta charset='utf-8'>"
        f"<title>ghcord</title><body style='font-family:sans-serif;text-align:center;padding-top:20vh'>"
        f"<h1>{title}</h1><p>{body}</p></body></html>",
        status_code=status_code,
    )


@router.get("/oauth/github/callback")
async def callback(code: str = "", state: str = "") -> HTMLResponse:
    discord_user_id = user_links.consume_state(state) if state else None
    if not discord_user_id or not code:
        logger.warning("OAuth callback rejected: invalid or expired state")
        return _page("Link failed", "This link is expired or invalid — run /github signin again in Discord", 400)

    async with httpx.AsyncClient(timeout=10) as http:
        try:
            login = await exchange_code_for_login(http, code)
        except (OAuthError, httpx.HTTPError) as exc:
            logger.error("OAuth exchange failed: {}", exc)
            return _page("Link failed", "GitHub authentication failed — try /github signin again", 400)
        user_links.link(login, discord_user_id)
        logger.info("event=signin login={} discord={} outcome=linked", login, discord_user_id)
        embed = build_embed(
            f"GitHub account linked — {login}",
            f"https://github.com/{login}",
            GREEN,
            "signin",
            "You'll now get DMs for review requests, reviews, and @mentions. Unlink with `/github signout`",
        )
        try:
            await discord_api.send_dm(http, discord_user_id, embed)
        except (discord_api.DiscordAPIError, httpx.HTTPError) as exc:
            logger.error("Signin confirmation DM failed: {}", exc)

    return _page("✅ Linked", f"<b>{login}</b> is now connected. Close this window and head back to Discord.")
