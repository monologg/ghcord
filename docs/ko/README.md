<!-- source: docs/README.md -->

# 설치 가이드

> 이 문서는 [영어 원문](../README.md)의 한국어 번역입니다.

이 가이드는 아무것도 없는 상태에서 동작하는 ghcord 인스턴스까지 안내합니다: GitHub 이벤트가 Discord 채널에 도착하고, 슬래시 커맨드가 동작하고, 개인 DM 알림까지 연결된 상태 말이죠. **약 30분**을 예상하세요. 여기서 다루는 모든 자격 증명은 직접 만드는 것이며, 그 무엇도 내 서버 밖으로 나가지 않습니다.

## 시작하기 전에

다음을 준비하세요:

- [ ] **Docker**를 실행할 수 있는 호스트 (또는 Python 3.13+ 직접 실행)
- [ ] HTTPS 엔드포인트 하나를 공개적으로 노출할 방법 — 리버스 프록시 뒤의 도메인, 또는 터널(Cloudflare Tunnel, Tailscale Funnel, ngrok, ...). GitHub과 Discord 모두 HTTPS를 요구합니다.
- [ ] 사용자 계정 또는 조직에 **GitHub App을 만들 수 있는 권한**
- [ ] 봇을 추가할 Discord 서버의 **서버 관리(Manage Server)** 권한

## 여섯 단계

| 단계 | 하는 일 | 얻는 것 |
|---|---|---|
| [1. GitHub App 등록](01-github-app.md) | 필요한 권한 & 이벤트 체크, 웹훅 시크릿 설정, 계정에 설치 | App ID, 프라이빗 키(`.pem`), 웹훅 시크릿 |
| [2. Discord 애플리케이션 생성](02-discord-app.md) | 앱 + 봇 생성, 서버에 초대 | Application ID, 퍼블릭 키, 봇 토큰 |
| [3. 서버 실행](03-run-the-server.md) | `.env`와 `config.toml` 채우고 `docker compose up` | 로컬에서 동작하며 서명 없는 요청을 거부하는 ghcord |
| [4. HTTPS로 노출](04-expose-https.md) | 도메인/터널 뒤에 서버 배치, GitHub과 Discord를 연결 | 라이브 웹훅 + 인터랙션 엔드포인트 |
| [5. 커맨드 등록 & 로그인](05-commands-and-signin.md) | `/github` 커맨드 트리 등록, DM 알림용 OAuth 설정 | 동작하는 슬래시 커맨드, 연결된 GitHub 계정 |
| [6. 검증 & 트러블슈팅](06-verify-and-troubleshoot.md) | 엔드투엔드 체크리스트 | 전부 동작한다는 확신 |

1단계와 2단계는 서로 독립적이라 순서는 상관없습니다. 4단계는 3단계가, 5단계는 4단계가 선행되어야 합니다.

## 전체 구조

```
GitHub ──webhook──▶ POST /webhook/github ─┐
                    (HMAC verified)        │   ghcord ──▶ Discord channel webhooks (embeds)
Discord ─commands─▶ POST /interactions/discord ─┘        ──▶ Discord DMs (personal alerts)
                    (Ed25519 verified)
```

GitHub App 설치 한 번이면 나중에 만들 레포까지 포함해 계정의 **모든 레포**가 커버됩니다. 어떤 레포의 이벤트가 어떤 채널로 갈지는 Discord 슬래시 커맨드(`/github subscribe ...`)가 결정하고, `config.toml`은 아직 아무 커맨드도 실행하지 않았을 때의 초기 기본값을 제공합니다.

## Credentials

서버가 읽는 모든 값을 한곳에 모았습니다. 자세한 내용은 각 단계 문서에 있습니다.

| 변수 | 출처 | 단계 |
|---|---|---|
| `GITHUB_APP_ID` | App settings → General → App ID | 1 |
| `GITHUB_APP_PRIVATE_KEY_PATH` | App settings → Private keys → Generate | 1 |
| `GITHUB_WEBHOOK_SECRET` | 직접 생성 (`openssl rand -hex 32`) | 1 |
| `DISCORD_APP_ID` | Developer portal → General Information | 2 |
| `DISCORD_PUBLIC_KEY` | Developer portal → General Information | 2 |
| `DISCORD_BOT_TOKEN` | Developer portal → Bot → Reset Token | 2 |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | App settings → General → Client secrets | 5 (선택, `/github signin`용) |
| `DISCORD_GUILD_ID` | 선택 — 커맨드를 길드 단위로 등록해 즉시 반영 (개발용) | 5 |

> [!WARNING]
> 이 값들은 절대 커밋하지 마세요. 레포의 `.gitignore`가 이미 `.env`, `config.toml`, `*.pem`을 제외하고 있습니다 — 그대로 유지하세요.
