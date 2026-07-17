# ghcord Development Guide

ghcord is a self-hosted GitHub ↔ Discord integration server built on a GitHub App: GitHub webhooks come in, rich embeds go out to Discord channel webhooks, and `/github` slash commands manage subscriptions. Discord is reached over plain HTTPS only — no gateway connection, no message-content access.

## Commands

```bash
make setup       # uv sync --frozen + install pre-commit hooks
make test        # pytest with coverage (tests/)
make style       # ruff check --fix + ruff format
make quality     # ruff checks (no fixes) + uv lock --check — what CI runs

uv run pytest tests/test_webhook.py -k <name>   # single test file / case
docker compose up -d --build                     # run the server (port 8788)
uv run python scripts/register_commands.py       # (re)register the /github command tree
uv run python -m app.identity.verify_install     # check GitHub App auth without deploying
```

Python 3.13, dependencies pinned via `uv.lock` — always run through `uv run --frozen` / `make`, never bare `pip`.

## Architecture notes

Things you can't derive from reading the code alone:

- Domain-first layout under `app/`; shared modules stay at the top level. There is deliberately no `core/` directory.
- Routing precedence: a channel subscription created via `/github subscribe` (SQLite) wins over `config.toml` for that repo; `config.toml` is only the before-any-command bootstrap default.
- `/webhook/github` (HMAC-SHA256) and `/interactions/discord` (Ed25519) are **fail-closed**: unsigned or mis-signed requests get 401, and a missing secret rejects everything. Never weaken this verification.

## Conventions

- TDD: write a failing test first, then implement. Tests live in `tests/` (pytest + respx for HTTP mocking).
- Ruff is the only linter/formatter (line length 119); run `make style` before committing.
- Never commit secrets or local config: `.env`, `config.toml`, `*.pem` are gitignored.
- PRs are squash-merged.

## Documentation translations

English is the source of truth for all user-facing documentation. Korean translations mirror it:

- `README.md` → `README.ko.md`
- `docs/<file>.md` → `docs/ko/<file>.md` (same filenames)

Rules:

- When you edit `README.md` or any file under `docs/`, update the corresponding Korean file in the same change set.
- When you add or delete a doc, add or delete its Korean counterpart too.
- Every translated file starts with a `<!-- source: <path> -->` comment and a blockquote linking to the English original — keep both intact.
- Relative links inside `docs/ko/` point to Korean siblings; links to repo files outside `docs/` need one extra `../` compared to the English original.
- To check a pair for drift, compare the last commit that touched each file: if the English file is newer, the translation is stale.
