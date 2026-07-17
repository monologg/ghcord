<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" width="128" alt="ghcord logo">
  </picture>
</p>

<h3 align="center">The missing "GitHub for Discord"</h3>

<p align="center">
  Self-hosted GitHub ↔ Discord integration server, built on a GitHub App.
</p>

<p align="center">
  <a href="docs/README.md"><b>Setup Guide</b></a>
  &nbsp;·&nbsp;
  <a href="#commands">Commands</a>
  &nbsp;·&nbsp;
  <a href="#how-it-compares">How it compares</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://github.com/monologg/ghcord/actions/workflows/test.yml"><img src="https://github.com/monologg/ghcord/actions/workflows/test.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="https://codecov.io/gh/monologg/ghcord"><img src="https://codecov.io/gh/monologg/ghcord/graph/badge.svg" alt="Coverage"></a>
</p>

<p align="center">
  <img src="assets/screenshots/hero-channel.png" width="640" alt="ghcord notifications in a Discord channel — a PR opened, merged, and pushed">
</p>

## Why ghcord

GitHub ships a full-featured official app for Slack. For Discord, all you get is the built-in webhook: one-way, unfiltered, per-repo. ghcord closes that gap with a small server you host yourself.

- **One install, every repo** — a single GitHub App installation covers every repository you own, including ones you create later. No per-repo webhooks; slash commands manage the rest.
- **Your credentials stay yours** — you issue the GitHub App, its private key, and the bot token. Nothing goes through anyone else's server, and every inbound request is verified fail-closed.
- **It can't read your messages** — ghcord talks to Discord over plain HTTP interactions: no gateway connection, no message-content access, even in principle.

## Features

- **Slack-compatible subscriptions** — `/github subscribe owner/repo reviews comments`, incremental add/remove, owner-wide subscribe
- **Filters** — branch globs, label filters, per-channel event selection
- **Rich embeds for 12 event types** — issues, PRs, reviews, comments, pushes, releases, and more
- **Personal DM alerts** — review requests, review results, @mentions
- **Issue actions & link previews from chat** — `/github open · close · reopen · preview`
- **Daily review reminders** — your pending review queue, posted on schedule

<p align="center">
  <img src="assets/screenshots/subscribe-command.png" width="720" alt="/github subscribe and its ephemeral confirmation response">
</p>

## How it compares

| | Discord built-in webhook | GitHub for Slack | ghcord |
|---|:---:|:---:|:---:|
| Event notifications | ✅ fixed format | ✅ | ✅ rich embeds |
| Choose events per channel | limited | ✅ | ✅ |
| Branch / label filters | ❌ | ✅ | ✅ |
| Account-wide subscribe (incl. future repos) | ❌ per-repo setup | ✅ | ✅ |
| Manage subscriptions via slash commands | ❌ | ✅ | ✅ |
| Personal DM alerts (reviews, mentions) | ❌ | ✅ | ✅ |
| Open / close issues from chat | ❌ | ✅ | ✅ |
| Scheduled review reminders | ❌ | ✅ | ✅ |
| Automatic link unfurling | ❌ | ✅ | ➖ on-demand `/github preview` |
| Thread grouping per issue/PR | ❌ | ✅ | ❌ deliberately skipped |
| Hosting | none | hosted by GitHub | self-hosted |

The two ❌/➖ rows are deliberate: both would require a persistent gateway connection or message-content access, which ghcord's design forbids — every predecessor bot that depended on a gateway connection eventually died of the maintenance burden.

## Commands

```
/github subscribe   repo:<owner/repo | owner> [features] [label]
/github unsubscribe repo:<owner/repo | owner> [features]
/github list
/github preview     url:<GitHub URL>
/github open        repo:<owner/repo>
/github close       url:<issue URL> [reason]
/github reopen      url:<issue URL>
/github signin · signout
/github remind      set time:<HH:MM> user:<login> · off · status
```

Feature tokens follow the GitHub-for-Slack vocabulary:

- **Defaults**: `issues`, `pulls`, `commits`, `releases`, `deployments`
- **Opt-in**: `reviews`, `comments`, `branches`, `commits:<branch-glob>`

<p align="center">
  <img src="assets/screenshots/command-picker.png" width="720" alt="The /github command tree in Discord's command picker">
</p>

## Getting started

You self-host ghcord — there is no hosted instance to invite. Setting up takes roughly **30 minutes** the first time. You'll need:

- A host that can run Docker (any small box works — ghcord runs comfortably under 256 MB of RAM)
- A public HTTPS endpoint for it (a domain behind a reverse proxy, or a tunnel such as Cloudflare Tunnel / Tailscale Funnel)
- Permission to create a GitHub App on your account or org
- **Manage Server** permission on your Discord server

The server half is three commands:

```bash
git clone https://github.com/monologg/ghcord.git && cd ghcord
cp .env.example .env && cp config.example.toml config.toml   # fill in as you go
docker compose up -d --build
```

Filling in those blanks — the GitHub App, the Discord app, the HTTPS endpoint — is what the [setup guide](docs/README.md) walks through, in six steps:

1. [Register a GitHub App](docs/01-github-app.md) — permissions & events checklist, webhook secret
2. [Create a Discord application](docs/02-discord-app.md) — bot token, public key, invite URL
3. [Run the server](docs/03-run-the-server.md) — `.env`, `config.toml`, `docker compose up`
4. [Expose it over HTTPS](docs/04-expose-https.md) — webhook URL, interactions endpoint
5. [Register commands & sign in](docs/05-commands-and-signin.md) — slash commands, OAuth for DM alerts
6. [Verify & troubleshoot](docs/06-verify-and-troubleshoot.md) — end-to-end checklist

## License

[MIT](LICENSE). Issues and pull requests are welcome.

ghcord is an independent project, not affiliated with or endorsed by GitHub, Inc. or Discord Inc.
