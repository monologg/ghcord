# Step 2 — Create a Discord application

The Discord side needs an application with a bot user. ghcord talks to Discord over plain HTTPS (webhooks + HTTP interactions) — the bot never opens a gateway connection and never requests the message-content intent, so it cannot read anything in your server.

## 1. Create the application

In the [Discord developer portal](https://discord.com/developers/applications):

1. **New Application** → name it (e.g. `ghcord`). Brand images are available under [`assets/png/`](../assets/png/) if you want the avatar.
2. From **General Information**, copy two values into `.env`:
   - **Application ID** → `DISCORD_APP_ID`
   - **Public Key** → `DISCORD_PUBLIC_KEY` (used to verify that interaction requests really come from Discord)

## 2. Bot token

**Bot** tab → **Reset Token** → copy it → `DISCORD_BOT_TOKEN` in `.env`.

The token is shown only once; if you lose it, reset again. ghcord uses it for exactly two things: registering slash commands and creating channel webhooks.

While you're on the Bot tab:

- **Public Bot** — turn **off**, unless you want strangers to be able to invite your instance.
- Leave all **Privileged Gateway Intents** off. ghcord doesn't use the gateway at all.

## 3. Invite the bot to your server

**OAuth2 → URL Generator**:

- Scopes: `bot` + `applications.commands`
- Bot permissions: **Manage Webhooks** — nothing else

Open the generated URL, pick your server, authorize. `Manage Webhooks` is the bot's only permission: ghcord delivers notifications by creating a webhook in each subscribed channel, so it needs to manage webhooks and nothing more.

## 4. What to leave for later

Two portal fields depend on your public HTTPS address, which doesn't exist yet:

| Field | Where | Set in |
|---|---|---|
| **Interactions Endpoint URL** | General Information | [Step 4](04-expose-https.md) — Discord validates the endpoint live when you save it, so the server must be up first |
| **OAuth Callback URL** (GitHub App side, for `/github signin`) | GitHub App settings | [Step 5](05-commands-and-signin.md) |

---

Next: [Step 3 — Run the server](03-run-the-server.md)
