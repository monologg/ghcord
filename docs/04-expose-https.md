# Step 4 — Expose it over HTTPS

GitHub needs to POST webhooks to your server, and Discord needs to POST interactions. Both require a **public HTTPS** endpoint — plain HTTP won't be accepted by either. This page uses `ghcord.example.com` as the placeholder; substitute your own hostname throughout.

## 1. Put the server behind your hostname

Any of the usual mechanisms works — ghcord is a single HTTP service on port `8788`:

- **Tunnel** (Cloudflare Tunnel, Tailscale Funnel, ngrok, ...) — easiest if your host has no public IP; TLS is handled for you. Point the tunnel's ingress at `http://<host-lan-ip>:8788`.
- **Reverse proxy** (Caddy, nginx, Traefik) on a machine with a public IP — proxy `https://ghcord.example.com` to `127.0.0.1:8788`.

ghcord doesn't care which; it just needs requests to arrive at the container.

Then verify from outside:

```bash
curl -sI https://ghcord.example.com/          # → 200
curl -s -X POST https://ghcord.example.com/webhook/github -d '{}' \
  -o /dev/null -w '%{http_code}\n'            # → 401 (fail-closed, correct)
```

## 2. Point GitHub at it

GitHub App settings → **Webhook URL** → replace the placeholder:

```
https://ghcord.example.com/webhook/github
```

Then confirm delivery: App settings → **Advanced → Recent Deliveries** → redeliver any delivery (or trigger one — push to any repo). It should show **202**, and `docker compose logs` should show a line ending in `outcome=sent` (or `outcome=skipped` if no route matched).

## 3. Point Discord at it

Developer portal → your app → **General Information → Interactions Endpoint URL**:

```
https://ghcord.example.com/interactions/discord
```

When you save, Discord immediately sends a PING **and** a deliberately invalid signature to the endpoint; it only accepts the URL if the PING succeeds and the invalid signature is rejected. If the save fails, the server isn't reachable or `DISCORD_PUBLIC_KEY` is wrong/missing.

## 4. A note on the exposed surface

Both public endpoints authenticate every request cryptographically and fail closed:

- `/webhook/github` — HMAC-SHA256 signature against your webhook secret; anything unsigned or mis-signed gets 401.
- `/interactions/discord` — Ed25519 signature against the Discord public key; same policy.

One endpoint deserves extra care: **`GET /status`** is an unauthenticated status page that includes repository names and recent delivery details. If your repos are private, restrict it at the proxy/tunnel layer (IP allowlist, or an access product like Cloudflare Access) or simply don't route it publicly. FastAPI's auto-docs endpoints (`/docs`, `/redoc`, `/openapi.json`) are disabled in code.

---

Next: [Step 5 — Register commands & sign in](05-commands-and-signin.md)
