# Setup guide

This guide takes you from nothing to a working ghcord instance: GitHub events landing in your Discord channels, slash commands working, and personal DM alerts wired up. Budget **about 30 minutes**. Every credential involved is one you create yourself, and none of them leave your server.

## Before you start

Make sure you have:

- [ ] A host that can run **Docker** (or Python 3.13+ directly)
- [ ] A way to expose one HTTPS endpoint publicly — a domain behind a reverse proxy, or a tunnel (Cloudflare Tunnel, Tailscale Funnel, ngrok, ...). GitHub and Discord both require HTTPS.
- [ ] Permission to **create a GitHub App** on your user account or organization
- [ ] **Manage Server** permission on the Discord server where the bot will live

## The six steps

| Step | What you do | What you come away with |
|---|---|---|
| [1. Register a GitHub App](01-github-app.md) | Check the right permissions & events, set a webhook secret, install it on your account | App ID, private key (`.pem`), webhook secret |
| [2. Create a Discord application](02-discord-app.md) | Create the app + bot, invite it to your server | Application ID, public key, bot token |
| [3. Run the server](03-run-the-server.md) | Fill in `.env` and `config.toml`, `docker compose up` | ghcord running locally, rejecting unsigned requests |
| [4. Expose it over HTTPS](04-expose-https.md) | Put the server behind your domain/tunnel, point GitHub and Discord at it | Live webhook + interactions endpoint |
| [5. Register commands & sign in](05-commands-and-signin.md) | Push the `/github` command tree, set up OAuth for DM alerts | Working slash commands, linked GitHub account |
| [6. Verify & troubleshoot](06-verify-and-troubleshoot.md) | End-to-end checklist | Confidence it all works |

Steps 1 and 2 are independent — do them in either order. Step 4 needs 3. Step 5 needs 4.

## How the pieces fit

```
GitHub ──webhook──▶ POST /webhook/github ─┐
                    (HMAC verified)        │   ghcord ──▶ Discord channel webhooks (embeds)
Discord ─commands─▶ POST /interactions/discord ─┘        ──▶ Discord DMs (personal alerts)
                    (Ed25519 verified)
```

One GitHub App installation covers **all repositories** on your account, including ones you create later. Discord slash commands (`/github subscribe ...`) decide which repo's events go to which channel; `config.toml` provides the bootstrap defaults before any command has been used.

## Credentials cheat sheet

Everything the server reads, in one place. Details are in the step pages.

| Variable | From | Step |
|---|---|---|
| `GITHUB_APP_ID` | App settings → General → App ID | 1 |
| `GITHUB_APP_PRIVATE_KEY_PATH` | App settings → Private keys → Generate | 1 |
| `GITHUB_WEBHOOK_SECRET` | You generate it (`openssl rand -hex 32`) | 1 |
| `DISCORD_APP_ID` | Developer portal → General Information | 2 |
| `DISCORD_PUBLIC_KEY` | Developer portal → General Information | 2 |
| `DISCORD_BOT_TOKEN` | Developer portal → Bot → Reset Token | 2 |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | App settings → General → Client secrets | 5 (optional, for `/github signin`) |
| `DISCORD_GUILD_ID` | Optional — registers commands per-guild for instant propagation (dev) | 5 |

> [!WARNING]
> Never commit any of these. The repo's `.gitignore` already excludes `.env`, `config.toml`, and `*.pem` — keep it that way.
