"""Discord embed building primitives shared across domains.

Split out of the webhook formatters — oauth, mentions, reminders,
and issue previews all build embeds with the same colors and helpers.
"""

from datetime import datetime, timezone


EMBED_TITLE_LIMIT = 256
BODY_PREVIEW_LIMIT = 500

# GitHub UI state colors
GREEN = 0x2DA44E  # open / created / success / approved
RED = 0xCF222E  # closed / deleted / failure / changes requested
PURPLE = 0x8250DF  # merged
GRAY = 0x768390  # neutral (push, comment, etc.)


def build_embed(title: str | None, url: str | None, color: int, footer: str, description: str | None = None) -> dict:
    embed = {
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": f"GitHub · {footer}" if footer else "GitHub"},
    }
    if title:
        embed["title"] = title[:EMBED_TITLE_LIMIT]
        embed["url"] = url
    if description:
        embed["description"] = description
    return embed


def preview_text(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) > BODY_PREVIEW_LIMIT:
        return text[:BODY_PREVIEW_LIMIT] + "…"
    return text or None
