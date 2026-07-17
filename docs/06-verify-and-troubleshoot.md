# Step 6 — Verify & troubleshoot

## End-to-end checklist

Run through these in order; each one exercises a different seam of the setup.

- [ ] `docker compose exec ghcord .venv/bin/python -m app.identity.verify_install` prints your App name, `selection=all`, and a repo count *(GitHub auth)*
- [ ] `curl -sI https://ghcord.example.com/` returns 200 *(exposure)*
- [ ] Unsigned POST to `/webhook/github` returns **401** *(fail-closed)*
- [ ] GitHub App → Advanced → Recent Deliveries: latest delivery shows **202** *(webhook wiring)*
- [ ] Open a test issue in a repo → embed arrives in the default channel, title links back to GitHub *(routing + formatting)*
- [ ] Push to the default branch → commits embed arrives *(branch filtering)*
- [ ] `/github subscribe repo:owner/repo` in a second channel → confirmation, and the next event lands in **both** channels *(commands + SQLite routing)*
- [ ] `/github list` shows the subscription *(state)*
- [ ] `/github signin` → authorize → confirmation DM arrives *(OAuth)*
- [ ] Ask someone to request your review on a PR (or @mention you in an issue) → DM alert arrives *(DM pipeline — note: events you trigger yourself never DM you)*
- [ ] Optional: put a deliberately wrong `webhook_url` in `config.toml`, trigger an event → alert appears in the `[ops]` channel → revert *(failure alerting)*

If all boxes tick, you're done. The rest of this page is for when one doesn't.

## Troubleshooting

### GitHub → server

**Recent Deliveries shows 401.**
The webhook secret in the App settings and `GITHUB_WEBHOOK_SECRET` in `.env` don't match (or `.env` wasn't reloaded — use `docker compose up -d --force-recreate`, not `restart`). 401 on *unsigned* requests is correct; 401 on real GitHub deliveries means secret mismatch.

**Recent Deliveries shows timeouts / "failed to connect".**
Your HTTPS exposure isn't reaching the container. Test the chain from outside in: `curl https://host/` → proxy/tunnel target → `curl http://127.0.0.1:8788/` on the host.

**Deliveries are 202 but nothing appears in Discord.**
202 means "received and verified", not "routed". Check `docker compose logs` for the delivery line: `outcome=skipped` means no route matched (no subscription and no matching `config.toml` entry, or the event type isn't in the channel's feature list — remember `reviews`/`comments`/`branches` are opt-in). `outcome=failed` means the Discord webhook rejected it — see the detail, and check the `[ops]` channel.

**Push events don't arrive for a feature branch.**
By design: `commits` defaults to the default branch only, matching the Slack app. Subscribe with `commits:*` (all branches) or a glob like `commits:release/*`.

### Discord → server

**Saving the Interactions Endpoint URL fails.**
Discord PINGs the URL and also probes it with an invalid signature the moment you save. Failure means the server isn't reachable at that URL, or `DISCORD_PUBLIC_KEY` is wrong/empty (check for a stray newline), or `.env` wasn't reloaded.

**`/github` doesn't appear in the command picker.**
Global commands take up to an hour to propagate — set `DISCORD_GUILD_ID` and re-run `scripts/register_commands.py` for instant guild registration while testing. Also: the command is hidden from members without **Manage Webhooks** permission by default, and the bot must have been invited with the `applications.commands` scope (re-invite with the step-2 URL if unsure).

**`/github subscribe` responds with an error.**
Two usual causes: `DISCORD_BOT_TOKEN` missing/stale in `.env`, or the bot lacks **Manage Webhooks** in that channel (channel-level permission overrides can deny what the server-level role grants).

**`/github open` / `close` / `reopen` responds 403.**
The App has `Issues: Read` but not `Read and write` — or you upgraded the permission but never approved it. Permission changes require re-approval: GitHub → Settings → Applications → Installed GitHub Apps → your app → approve the pending banner.

### DM alerts

**`/github signin` says it isn't configured.**
`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` are empty — see [step 5](05-commands-and-signin.md#2-github-signin--enable-personal-dm-alerts).

**Signed in, but no DMs arrive.**
In order of likelihood: (1) the event was triggered by you — self-triggered events are deliberately excluded; (2) your Discord privacy settings block DMs from server members ("Allow direct messages from server members"); (3) the GitHub account in the event isn't the one you linked — `/github signin` again to re-link. DM failures are logged (`dm=failed` in the ledger detail) but never alerted, since channel delivery is the primary path.

### Still stuck?

`docker compose logs -f ghcord` is the source of truth — every delivery and command gets one structured line (`delivery= event= repo= outcome=`). The `/status` endpoint (keep it access-restricted) shows recent deliveries, success rate, and error details.
