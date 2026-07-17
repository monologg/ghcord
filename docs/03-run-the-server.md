# Step 3 — Run the server

With the credentials from steps 1 and 2 in hand, you can bring the server up. Three files live next to the code, all gitignored: `.env` (secrets), `config.toml` (routing defaults), and the App's `.pem` key.

## 1. `.env`

```bash
git clone https://github.com/monologg/ghcord.git && cd ghcord
cp .env.example .env
```

Fill in what you have so far:

```dotenv
# From step 1 (GitHub App)
GITHUB_APP_ID=
GITHUB_WEBHOOK_SECRET=

# From step 2 (Discord application)
DISCORD_APP_ID=
DISCORD_PUBLIC_KEY=
DISCORD_BOT_TOKEN=
```

Leave `GITHUB_APP_PRIVATE_KEY_PATH` empty — `docker-compose.yml` overrides it with the in-container path of the mounted key. (Running without Docker? Point it at your `.pem` file, or put the key inline in `GITHUB_APP_PRIVATE_KEY` with newlines escaped as `\n`.)

`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` can stay empty until [step 5](05-commands-and-signin.md).

## 2. `config.toml`

```bash
cp config.example.toml config.toml
```

`config.toml` is the **bootstrap default**: it answers "where do events go before anyone has run `/github subscribe`?" Once a repo is subscribed via command, the command wins and the file is ignored for that repo.

The minimum useful config is a single default channel. In Discord: channel settings → Integrations → Webhooks → New Webhook → Copy URL:

```toml
[default]
webhook_url = "https://discord.com/api/webhooks/..."
```

Because the GitHub App covers all your repositories, this one line is the equivalent of Slack's "subscribe the whole org". Optional extras (see comments in `config.example.toml`):

- `[ops]` — a **separate** channel that receives an alert when a delivery fails. Strongly recommended; without it, failures only go to logs.
- `[repos."owner/repo"]` — per-repo channel/event/branch/label overrides.
- `[users]` — GitHub login → Discord user ID mapping for DM alerts. This is the manual fallback; `/github signin` (step 5) is the better path.

## 3. Copy the private key

Place the `.pem` from step 1 next to the compose file:

```bash
cp /path/to/your-app.private-key.pem ./ghcord.pem
chmod 600 ghcord.pem
```

## 4. Start

```bash
docker compose up -d --build
```

The compose file mounts `config.toml` and `ghcord.pem` read-only and keeps the SQLite state (delivery ledger, subscriptions, account links) in a named volume, so it survives container rebuilds.

## 5. Verify locally

```bash
curl -s http://127.0.0.1:8788/    # → OK (healthcheck)

# Unsigned webhook must be REJECTED — fail-closed is correct behavior:
curl -s -X POST http://127.0.0.1:8788/webhook/github -d '{}' \
  -o /dev/null -w '%{http_code}\n'   # → 401
```

If the second check returns anything other than 401, stop and check `GITHUB_WEBHOOK_SECRET` in `.env` — the server refuses everything when it's missing, and accepting unsigned posts would mean it isn't being read at all.

Logs: `docker compose logs -f ghcord`.

> [!TIP]
> After editing `.env`, restart with `docker compose up -d --force-recreate` — a plain `restart` does not re-read `env_file`. Edits to `config.toml` need no restart at all (it's re-read per request), but beware editors that replace the file's inode (`sed -i`, some atomic-save editors) — that breaks the bind mount.

---

Next: [Step 4 — Expose it over HTTPS](04-expose-https.md)
