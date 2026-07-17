# Step 5 — Register commands & sign in

Two last wiring tasks: push the `/github` command tree to Discord, and (optionally but recommended) set up the OAuth flow that powers personal DM alerts.

## 1. Register the slash commands

```bash
docker compose exec ghcord .venv/bin/python scripts/register_commands.py
```

(Running from a host checkout works too: `uv run python scripts/register_commands.py`.)

The script authenticates with `DISCORD_BOT_TOKEN` and registers the full command tree via a single idempotent `PUT` — safe to re-run any time (it replaces the whole tree, so also re-run it after pulling a version that changes commands).

- **Global registration** (the default) can take up to an hour to propagate.
- For instant propagation while testing, set `DISCORD_GUILD_ID=<your server id>` in `.env`, restart (`docker compose up -d`), and re-run — guild commands appear immediately. (Right-click your server name → Copy Server ID, with Developer Mode enabled.)

By default the `/github` command is only visible to members with **Manage Webhooks** permission — random members can't rewire your notifications. Adjust under Server Settings → Integrations if you want different visibility.

First test, in any channel:

```
/github subscribe repo:owner/repo
```

<!-- SCREENSHOT: the ephemeral confirmation after a successful subscribe -->

Then trigger an event on that repo (open a test issue) and watch the embed arrive.

## 2. `/github signin` — enable personal DM alerts

DM alerts ("you were requested for review", "your PR was reviewed", "you were @mentioned") need to know which Discord user is which GitHub user. `/github signin` links accounts through GitHub OAuth — the same flow the official Slack app uses.

Your GitHub App doubles as the OAuth app; you just need to enable its client credentials:

1. **Callback URL**: GitHub App settings → General → *Identifying and authorizing users* → Callback URL:
   ```
   https://ghcord.example.com/oauth/github/callback
   ```
2. **Client ID**: shown on the same General page → `GITHUB_CLIENT_ID` in `.env`
3. **Client secret**: *Client secrets → Generate a new client secret* → `GITHUB_CLIENT_SECRET` in `.env`
4. Restart: `docker compose up -d --force-recreate`

Now any server member can run `/github signin`, click the authorize link, and get a confirmation DM. `/github signout` removes the link.

**What happens to the OAuth token:** ghcord uses it once, to ask GitHub "who is this?", then discards it. Only the GitHub login ↔ Discord user ID pair is stored. DM alerts are driven by the App's webhook events, not by user tokens.

> [!NOTE]
> If you skip this section, everything else still works — you just won't get DM alerts unless you map users manually in `config.toml`'s `[users]` table.

---

Next: [Step 6 — Verify & troubleshoot](06-verify-and-troubleshoot.md)
