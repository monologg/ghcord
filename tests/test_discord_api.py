"""Bot REST: channel webhook create/reuse — brand avatar set at creation."""

import asyncio
import json

import httpx
import pytest
import respx
from httpx import Response

from app.clients import discord_api


API = discord_api.API


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_APP_ID", "123")


def ensure(channel_id="ch-1"):
    async def run():
        async with httpx.AsyncClient() as http:
            return await discord_api.ensure_channel_webhook(http, channel_id)

    return asyncio.run(run())


@respx.mock
def test_create_webhook_sets_name_and_brand_avatar():
    respx.get(f"{API}/channels/ch-1/webhooks").mock(return_value=Response(200, json=[]))
    post = respx.post(f"{API}/channels/ch-1/webhooks").mock(
        return_value=Response(200, json={"id": "wh-1", "token": "tk"})
    )
    webhook_id, url = ensure()
    assert webhook_id == "wh-1"
    assert url.endswith("/webhooks/wh-1/tk")
    payload = json.loads(post.calls.last.request.content)
    assert payload["name"] == "ghcord"
    # bake the avatar in at creation so the notification sender doesn't show the default Discord logo
    assert payload["avatar"].startswith("data:image/png;base64,")


@respx.mock
def test_reuses_existing_own_webhook_without_creating():
    respx.get(f"{API}/channels/ch-1/webhooks").mock(
        return_value=Response(200, json=[{"id": "wh-old", "token": "tk", "application_id": "123"}])
    )
    post = respx.post(f"{API}/channels/ch-1/webhooks").mock(return_value=Response(200, json={}))
    webhook_id, url = ensure()
    assert webhook_id == "wh-old"
    assert not post.called
