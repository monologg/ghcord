"""Register the /github command tree with Discord.

Names match the Slack official app (/github subscribe ...) — muscle-memory compatible.

Global registration takes up to 1 hour to propagate — set DISCORD_GUILD_ID to
register as guild commands for instant effect (development). Idempotent: PUT,
so re-running replaces the whole set.

    uv run python scripts/register_commands.py
"""

import os
import sys

import httpx


STRING_OPTION = 3
SUBCOMMAND = 1
SUBCOMMAND_GROUP = 2
MANAGE_WEBHOOKS = str(1 << 29)  # only channel-webhook managers may change subscriptions

GH_COMMAND = {
    "name": "github",
    "description": "Manage GitHub notifications (ghcord)",
    "default_member_permissions": MANAGE_WEBHOOKS,
    "options": [
        {
            "type": SUBCOMMAND,
            "name": "subscribe",
            "description": "Subscribe this channel to a repository (or every repo of an owner)",
            "options": [
                {
                    "type": STRING_OPTION,
                    "name": "repo",
                    "description": "owner/repo, or owner for all its repos",
                    "required": True,
                },
                {
                    "type": STRING_OPTION,
                    "name": "features",
                    "description": 'Tokens to add — reviews comments commits:main +label:"bug" ...',
                },
                {
                    "type": STRING_OPTION,
                    "name": "label",
                    "description": "Only issues/PRs with this label (+label filter)",
                },
            ],
        },
        {
            "type": SUBCOMMAND,
            "name": "unsubscribe",
            "description": "Unsubscribe this channel from a repo (partial if features given)",
            "options": [
                {"type": STRING_OPTION, "name": "repo", "description": "owner/repo", "required": True},
                {
                    "type": STRING_OPTION,
                    "name": "features",
                    "description": 'Tokens to remove — pulls reviews +label:"bug" ... Omit to unsubscribe fully',
                },
            ],
        },
        {"type": SUBCOMMAND, "name": "list", "description": "Subscriptions in this channel"},
        {
            "type": SUBCOMMAND,
            "name": "preview",
            "description": "Preview a GitHub link (PR/issue)",
            "options": [
                {"type": STRING_OPTION, "name": "url", "description": "GitHub URL", "required": True},
            ],
        },
        {
            "type": SUBCOMMAND,
            "name": "open",
            "description": "Open an issue (via modal)",
            "options": [
                {"type": STRING_OPTION, "name": "repo", "description": "owner/repo", "required": True},
            ],
        },
        {
            "type": SUBCOMMAND,
            "name": "close",
            "description": "Close an issue",
            "options": [
                {"type": STRING_OPTION, "name": "url", "description": "Issue URL", "required": True},
                {
                    "type": STRING_OPTION,
                    "name": "reason",
                    "description": "Reason for closing",
                    "choices": [
                        {"name": "completed", "value": "completed"},
                        {"name": "not planned", "value": "not_planned"},
                    ],
                },
            ],
        },
        {
            "type": SUBCOMMAND,
            "name": "reopen",
            "description": "Reopen an issue",
            "options": [
                {"type": STRING_OPTION, "name": "url", "description": "Issue URL", "required": True},
            ],
        },
        {"type": SUBCOMMAND, "name": "signin", "description": "Connect your GitHub account — enables DM alerts"},
        {"type": SUBCOMMAND, "name": "signout", "description": "Disconnect your GitHub account"},
        {
            "type": SUBCOMMAND_GROUP,
            "name": "remind",
            "description": "Pending-review reminders",
            "options": [
                {
                    "type": SUBCOMMAND,
                    "name": "set",
                    "description": "Post pending review PRs to this channel daily at a given time",
                    "options": [
                        {
                            "type": STRING_OPTION,
                            "name": "time",
                            "description": "HH:MM (24-hour, KST)",
                            "required": True,
                        },
                        {"type": STRING_OPTION, "name": "user", "description": "GitHub username", "required": True},
                    ],
                },
                {"type": SUBCOMMAND, "name": "off", "description": "Turn off this channel's reminder"},
                {"type": SUBCOMMAND, "name": "status", "description": "Show this channel's reminder settings"},
            ],
        },
    ],
}


def main() -> None:
    app_id = os.environ.get("DISCORD_APP_ID")
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not app_id or not token:
        sys.exit("DISCORD_APP_ID and DISCORD_BOT_TOKEN must be set")

    guild = os.environ.get("DISCORD_GUILD_ID")
    scope = f"guilds/{guild}/commands" if guild else "commands"
    res = httpx.put(
        f"https://discord.com/api/v10/applications/{app_id}/{scope}",
        headers={"Authorization": f"Bot {token}"},
        json=[GH_COMMAND],
        timeout=10,
    )
    res.raise_for_status()
    registered = ", ".join(f"/{c['name']}" for c in res.json())
    print(f"Registered ({'guild ' + guild if guild else 'global'}): {registered}")


if __name__ == "__main__":
    main()
