---
name: verify
description: Recipe for running ghcord locally and verifying the webhook receive → Discord send flow end-to-end
---

# ghcord verification recipe

Exercise the real surface with the server (uvicorn) + a fake Discord receiver
(local HTTP server). Re-running unit tests is not verification — send signed
POSTs and observe responses/logs/ledger.

## Startup

```bash
# 1. Fake Discord receiver: tiny http.server that returns 204 on /ok and 500 on /bad for POSTs (write it in the scratchpad)
# 2. Server:
GHCORD_CONFIG=<tmp config.toml> GHCORD_DB=<tmp .db> GITHUB_WEBHOOK_SECRET=<secret> \
  uv run uvicorn app.main:app --port 8901
```

Point webhook_url in config.toml at the fake receiver. Same for `[ops]`.

## Sending a signed event

Put `sha256=` + HMAC-SHA256(secret, raw_body) over the exact body in
`x-hub-signature-256`; `x-github-event`/`x-github-delivery` headers are required.
Minimal push payload:
`ref`, `compare`, `repository.full_name/html_url/default_branch`, `commits[]` (id/url/message/author.name).
With empty commits the formatter returns None and the delivery is Ignored, so include at least one.

## Flows to check

- Normal push → `202 Sent`, embed arrives at the receiver
- Resend of the same delivery → `202 Duplicate ignored` (survives a server restart — ledger dedupe)
- Failing route (/bad) → `502` + alert embed in the ops channel
- Resend of the same delivery after fixing the config → `Sent`, attempts=2 in `/status`
- `GET /status` → deliveries/totals/success_rate JSON
- Logs: one canonical line per processing (`delivery= event= repo= feature= outcome= duration_ms=`)
