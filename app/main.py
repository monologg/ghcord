"""ghcord FastAPI app — app creation, router mounting, and lifespan only.

Domain packages: webhook/ (receive pipeline·formatters·signature verification),
interactions/ (Discord slash commands), identity/ (OAuth·user links·DM mentions),
clients/ (Discord·GitHub API·embed building). Shared modules stay top-level:
config, db, ledger, subscriptions, reminders.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import reminders
from app.identity import oauth
from app.interactions import router as interactions
from app.webhook import router as webhook


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Reminder scheduler — in-process task, no separate daemon
    task = asyncio.create_task(reminders.scheduler())
    yield
    task.cancel()


# Minimize the public deployment surface — do not expose auto docs/schema endpoints
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(webhook.router)
app.include_router(interactions.router)
app.include_router(oauth.router)
