"""Discord bot REST calls — channel webhook provisioning + interaction followup.

One-shot REST only, no gateway (principle 2). The bot's sole permission is Manage Webhooks.
"""

import base64
import os
from functools import lru_cache

import httpx
from loguru import logger

from app.config import BASE_DIR


API = "https://discord.com/api/v10"
WEBHOOK_NAME = "ghcord"

# Avatar for the webhooks we create — without it, notifications show the default Discord logo
AVATAR_PATH = BASE_DIR / "assets" / "png" / "avatar-brand-512.png"


@lru_cache(maxsize=1)
def _avatar_data_uri() -> str | None:
    try:
        data = AVATAR_PATH.read_bytes()
    except OSError:
        logger.warning("Brand avatar not found at {} — webhook will use default", AVATAR_PATH)
        return None
    return "data:image/png;base64," + base64.b64encode(data).decode()


class DiscordAPIError(RuntimeError):
    pass


def _bot_headers() -> dict:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise DiscordAPIError("DISCORD_BOT_TOKEN is not set")
    return {"Authorization": f"Bot {token}"}


async def ensure_channel_webhook(http: httpx.AsyncClient, channel_id: str) -> tuple[str, str]:
    """Find the ghcord-owned webhook in the channel, creating one if missing. Returns (webhook_id, url)."""
    headers = _bot_headers()
    app_id = os.environ.get("DISCORD_APP_ID")

    res = await http.get(f"{API}/channels/{channel_id}/webhooks", headers=headers)
    if res.is_success:
        for hook in res.json():
            if str(hook.get("application_id")) == app_id and hook.get("token"):
                return hook["id"], f"{API}/webhooks/{hook['id']}/{hook['token']}"
    elif res.status_code == 403:
        raise DiscordAPIError("Failed to list webhooks — check the bot has the Manage Webhooks permission")
    else:
        raise DiscordAPIError(f"Failed to list webhooks: HTTP {res.status_code}")

    payload = {"name": WEBHOOK_NAME}
    if avatar := _avatar_data_uri():
        payload["avatar"] = avatar
    res = await http.post(f"{API}/channels/{channel_id}/webhooks", headers=headers, json=payload)
    if not res.is_success:
        raise DiscordAPIError(
            f"Failed to create webhook: HTTP {res.status_code} — check the bot's Manage Webhooks permission"
        )
    hook = res.json()
    return hook["id"], f"{API}/webhooks/{hook['id']}/{hook['token']}"


async def send_dm(http: httpx.AsyncClient, user_id: str, embed: dict) -> None:
    """Send a bot DM — DM channel creation is idempotent, so calling it every time without a cache is safe."""
    headers = _bot_headers()
    res = await http.post(f"{API}/users/@me/channels", headers=headers, json={"recipient_id": user_id})
    if not res.is_success:
        raise DiscordAPIError(f"Failed to open DM channel: HTTP {res.status_code}")
    channel_id = res.json()["id"]
    res = await http.post(f"{API}/channels/{channel_id}/messages", headers=headers, json={"embeds": [embed]})
    if not res.is_success:
        raise DiscordAPIError(f"Failed to send DM: HTTP {res.status_code} — check the user's DM privacy settings")


async def edit_original(
    http: httpx.AsyncClient, interaction_token: str, content: str | None = None, embeds: list[dict] | None = None
) -> None:
    """Fill in the body of a deferred response. Failures are only logged — it's just a user message."""
    app_id = os.environ.get("DISCORD_APP_ID")
    payload: dict = {}
    if content is not None:
        payload["content"] = content
    if embeds is not None:
        payload["embeds"] = embeds
    try:
        res = await http.patch(f"{API}/webhooks/{app_id}/{interaction_token}/messages/@original", json=payload)
        if not res.is_success:
            logger.error("Interaction followup failed: HTTP {}", res.status_code)
    except httpx.HTTPError as exc:
        logger.error("Interaction followup failed: {}", exc)
