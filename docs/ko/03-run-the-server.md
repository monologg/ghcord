<!-- source: docs/03-run-the-server.md -->

# 3단계 — 서버 실행

> 이 문서는 [영어 원문](../03-run-the-server.md)의 한국어 번역입니다.

1·2단계에서 얻은 자격 증명이 있으면 서버를 띄울 수 있습니다. 코드 옆에 세 파일이 놓이며, 모두 gitignore되어 있습니다: `.env`(시크릿), `config.toml`(라우팅 기본값), 그리고 App의 `.pem` 키.

## 1. `.env`

```bash
git clone https://github.com/monologg/ghcord.git && cd ghcord
cp .env.example .env
```

지금까지 가진 값을 채워 넣습니다:

```dotenv
# 1단계에서 (GitHub App)
GITHUB_APP_ID=
GITHUB_WEBHOOK_SECRET=

# 2단계에서 (Discord 애플리케이션)
DISCORD_APP_ID=
DISCORD_PUBLIC_KEY=
DISCORD_BOT_TOKEN=
```

`GITHUB_APP_PRIVATE_KEY_PATH`는 비워 두세요 — `docker-compose.yml`이 마운트된 키의 컨테이너 내부 경로로 덮어씁니다. (Docker 없이 실행한다면 `.pem` 파일 경로를 지정하거나, 줄바꿈을 `\n`으로 이스케이프해서 `GITHUB_APP_PRIVATE_KEY`에 키를 인라인으로 넣으세요.)

`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`은 [5단계](05-commands-and-signin.md)까지 비워 둬도 됩니다.

## 2. `config.toml`

```bash
cp config.example.toml config.toml
```

`config.toml`은 **초기 기본값**입니다: "아직 아무도 `/github subscribe`를 실행하지 않았을 때 이벤트는 어디로 가는가?"에 대한 답이죠. 어떤 레포가 커맨드로 구독되고 나면 커맨드가 우선하며, 그 레포에 대해서는 이 파일이 무시됩니다.

최소한의 유용한 설정은 기본 채널 하나입니다. Discord에서: 채널 설정 → 연동(Integrations) → 웹훅(Webhooks) → 새 웹훅 → URL 복사:

```toml
[default]
webhook_url = "https://discord.com/api/webhooks/..."
```

GitHub App이 모든 레포를 커버하므로, 이 한 줄이 Slack의 "조직 전체 구독"에 해당합니다. 선택 항목들 (`config.example.toml`의 주석 참고):

- `[ops]` — 전달 실패 시 알림을 받는 **별도** 채널. 강력 추천합니다. 없으면 실패가 로그에만 남습니다.
- `[repos."owner/repo"]` — 레포별 채널/이벤트/브랜치/라벨 오버라이드.
- `[users]` — DM 알림용 GitHub 로그인 → Discord 유저 ID 매핑. 이건 수동 폴백이고, `/github signin`(5단계)이 더 나은 방법입니다.

## 3. 프라이빗 키 복사

1단계의 `.pem`을 compose 파일 옆에 놓습니다:

```bash
cp /path/to/your-app.private-key.pem ./ghcord.pem
chmod 600 ghcord.pem
```

## 4. 시작

```bash
docker compose up -d --build
```

compose 파일은 `config.toml`과 `ghcord.pem`을 읽기 전용으로 마운트하고, SQLite 상태(delivery ledger, 구독, 계정 연결)를 네임드 볼륨에 보관하므로 컨테이너를 다시 빌드해도 유지됩니다.

## 5. 로컬 확인

```bash
curl -s http://127.0.0.1:8788/    # → OK (헬스체크)

# 서명 없는 웹훅은 반드시 거부되어야 합니다 — fail-closed가 올바른 동작입니다:
curl -s -X POST http://127.0.0.1:8788/webhook/github -d '{}' \
  -o /dev/null -w '%{http_code}\n'   # → 401
```

두 번째 확인에서 401이 아닌 값이 나오면 멈추고 `.env`의 `GITHUB_WEBHOOK_SECRET`을 확인하세요 — 이 값이 없으면 서버는 모든 요청을 거부하며, 서명 없는 요청이 통과된다는 것은 `.env`가 아예 읽히지 않고 있다는 뜻입니다.

로그: `docker compose logs -f ghcord`.

> [!TIP]
> `.env`를 수정한 뒤에는 `docker compose up -d --force-recreate`로 재시작하세요 — 단순 `restart`는 `env_file`을 다시 읽지 않습니다. `config.toml` 수정은 재시작이 아예 필요 없지만(요청마다 다시 읽음), 파일의 inode를 교체하는 에디터(`sed -i`, 일부 atomic-save 에디터)는 조심하세요 — bind mount가 끊어집니다.

---

다음: [4단계 — HTTPS로 노출](04-expose-https.md)
