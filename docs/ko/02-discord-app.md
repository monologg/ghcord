<!-- source: docs/02-discord-app.md -->

# 2단계 — Discord 애플리케이션 생성

> 이 문서는 [영어 원문](../02-discord-app.md)의 한국어 번역입니다.

Discord 쪽에는 봇 유저가 연결된 애플리케이션이 필요합니다. ghcord는 Discord와 순수 HTTPS(웹훅 + HTTP 인터랙션)로만 통신합니다 — 봇은 게이트웨이 연결을 열지 않고 message content intent(메시지 읽기 권한)도 요청하지 않으므로, 서버 안의 그 무엇도 읽을 수 없습니다.

## 1. 애플리케이션 생성

[Discord 개발자 포털](https://discord.com/developers/applications)에서:

1. **New Application** → 이름 입력 (예: `ghcord`). 아바타로 쓸 브랜드 이미지는 [`assets/png/`](../../assets/png/)에 있습니다.
2. **General Information**에서 두 값을 `.env`에 복사합니다:
   - **Application ID** → `DISCORD_APP_ID`
   - **Public Key** → `DISCORD_PUBLIC_KEY` (인터랙션 요청이 정말 Discord에서 온 것인지 검증하는 데 사용)

## 2. 봇 토큰

**Bot** 탭 → **Reset Token** → 복사 → `.env`의 `DISCORD_BOT_TOKEN`.

토큰은 한 번만 표시됩니다. 잃어버리면 다시 리셋하세요. ghcord가 토큰을 쓰는 곳은 정확히 두 가지입니다: 슬래시 커맨드 등록과 채널 웹훅 생성.

Bot 탭에 있는 김에:

- **Public Bot** — **끄세요**. 모르는 사람이 내 인스턴스를 초대할 수 있게 하고 싶은 게 아니라면요.
- **Privileged Gateway Intents**는 전부 끈 상태로 둡니다. ghcord는 게이트웨이를 아예 사용하지 않습니다.

## 3. 봇을 서버에 초대

**OAuth2 → URL Generator**:

- Scopes: `bot` + `applications.commands`
- Bot permissions: **Manage Webhooks** — 그 외에는 아무것도

생성된 URL을 열고, 서버를 선택하고, 승인합니다. `Manage Webhooks`는 봇의 유일한 권한입니다: ghcord는 구독된 각 채널에 웹훅을 만들어 알림을 전달하므로, 웹훅 관리 이상은 필요하지 않습니다.

## 4. 나중으로 미룰 것

포털의 두 항목은 아직 존재하지 않는 공개 HTTPS 주소에 의존합니다:

| 항목 | 위치 | 설정 시점 |
|---|---|---|
| **Interactions Endpoint URL** | General Information | [4단계](04-expose-https.md) — 저장하는 순간 Discord가 엔드포인트를 실시간 검증하므로 서버가 먼저 떠 있어야 합니다 |
| **OAuth Callback URL** (GitHub App 쪽, `/github signin`용) | GitHub App settings | [5단계](05-commands-and-signin.md) |

---

다음: [3단계 — 서버 실행](03-run-the-server.md)
