# Step 1 — Register a GitHub App

A GitHub App is what lets ghcord receive events from **all** your repositories through a single installation — no per-repo webhook setup, and new repositories are covered automatically. You create the App, so you decide exactly what it can see.

## 1. Create the App

Go to <https://github.com/settings/apps/new> (or, for an organization, `https://github.com/organizations/<org>/settings/apps/new`) and fill in:

| Field | Value |
|---|---|
| GitHub App name | Anything you like — App names are globally unique, so `ghcord` may be taken; `<yourname>-ghcord` works |
| Homepage URL | Your fork/instance URL, or this repository |
| Webhook → Active | ✅ |
| Webhook URL | `https://ghcord.invalid/webhook/github` — a **temporary placeholder**; you'll replace it with your real address in [step 4](04-expose-https.md) |
| Webhook secret | Generate one: `openssl rand -hex 32`. Save it — this becomes `GITHUB_WEBHOOK_SECRET` in `.env` |
| Where can this App be installed? | **Only on this account** |

## 2. Repository permissions

Under **Permissions & events → Repository permissions**. Each permission exists for a specific feature — nothing here is speculative:

| Permission | Level | Why ghcord needs it |
|---|---|---|
| Metadata | Read | Mandatory baseline for any App |
| Contents | Read | Push, branch create/delete, and release notifications |
| Issues | Read **and write** | Issue notifications; *write* enables `/github open`, `close`, `reopen`. Choose Read-only if you don't want issue actions from Discord |
| Pull requests | Read | PR, review, and review-comment notifications |
| Actions | Read | Workflow-run notifications |
| Deployments | Read | Deployment-status notifications |
| Discussions | Read | Discussion notifications |

Leave every **Organization** and **Account** permission at *No access*.

## 3. Subscribe to events

The event checkboxes only appear after the matching permission above is set. Check all 12:

- [ ] Push
- [ ] Create (branch/tag)
- [ ] Delete (branch/tag)
- [ ] Release
- [ ] Issues
- [ ] Issue comment
- [ ] Pull request
- [ ] Pull request review
- [ ] Pull request review comment
- [ ] Workflow run
- [ ] Deployment status
- [ ] Discussion

Checking an event here only means ghcord *receives* it — which events actually reach a Discord channel is decided later, per channel, via `/github subscribe`.

## 4. Collect the credentials

After creating the App, from **App settings → General**:

1. **App ID** (under *About*) → `GITHUB_APP_ID` in `.env`
2. **Private key**: *Private keys → Generate a private key* — downloads a `.pem` file. You'll mount it into the container in [step 3](03-run-the-server.md). Keep it outside the repository, or rely on `.gitignore`'s `*.pem` rule — but outside is the safer habit.

## 5. Install the App

App settings → **Install App** → your account → **All repositories**.

This single click is the point of the whole design: one installation covers every repository you have and every one you create later. There is no per-repo approval dance.

## 6. Sanity check

You can verify authentication before the server is even deployed (requires the `.env` values from above):

```bash
uv run python -m app.identity.verify_install
```

Expected output: your App's name, `selection=all`, and the repository count. Webhook delivery can't be verified yet — the URL is still a placeholder. That happens in [step 4](04-expose-https.md).

---

Next: [Step 2 — Create a Discord application](02-discord-app.md)
