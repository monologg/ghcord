<!-- source: docs/05-commands-and-signin.md -->

# 5단계 — 커맨드 등록 & 로그인

> 이 문서는 [영어 원문](../05-commands-and-signin.md)의 한국어 번역입니다.

마지막 연결 작업 두 가지입니다: `/github` 커맨드 트리를 Discord에 등록하고, (선택이지만 권장) 개인 DM 알림을 구동하는 OAuth 플로우를 설정합니다.

## 1. 슬래시 커맨드 등록

```bash
docker compose exec ghcord .venv/bin/python scripts/register_commands.py
```

(컨테이너 밖에서, 호스트에 클론해 둔 레포에서 직접 실행해도 됩니다: `uv run python scripts/register_commands.py`.)

이 스크립트는 `DISCORD_BOT_TOKEN`으로 인증한 뒤, 멱등한 `PUT` 한 번으로 전체 커맨드 트리를 등록합니다 — 언제든 다시 실행해도 안전합니다 (트리 전체를 교체하므로, 커맨드가 바뀐 버전으로 업데이트한 뒤에도 다시 실행하세요).

- **전역 등록**(기본값)은 반영에 최대 1시간이 걸릴 수 있습니다.
- 테스트 중 즉시 반영이 필요하면 `.env`에 `DISCORD_GUILD_ID=<서버 ID>`를 설정하고, 재시작(`docker compose up -d`) 후 다시 실행하세요 — 길드 커맨드는 즉시 나타납니다. (개발자 모드를 켠 상태에서 서버 이름 우클릭 → 서버 ID 복사하기.)

기본적으로 `/github` 커맨드는 **웹훅 관리(Manage Webhooks)** 권한이 있는 멤버에게만 보입니다 — 아무 멤버나 알림 설정을 바꿀 수 없다는 뜻입니다. 다르게 보이길 원하면 서버 설정 → 연동에서 조정하세요.

첫 테스트, 아무 채널에서:

```
/github subscribe repo:owner/repo
```

<img src="../../assets/screenshots/subscribe-command.png" width="720" alt="/github subscribe 실행과 ephemeral 확인 응답">

그다음 그 레포에서 이벤트를 발생시키고 (테스트 이슈 열기) 임베드가 도착하는지 지켜보세요.

## 2. `/github signin` — 개인 DM 알림 활성화

DM 알림("리뷰 요청을 받았습니다", "PR이 리뷰되었습니다", "@멘션되었습니다")은 어느 Discord 유저가 어느 GitHub 유저인지 알아야 합니다. `/github signin`은 GitHub OAuth로 계정을 연결합니다 — 공식 Slack 앱이 쓰는 것과 같은 플로우입니다.

만들어 둔 GitHub App이 OAuth 앱을 겸합니다. 클라이언트 자격 증명만 활성화하면 됩니다:

1. **Callback URL**: GitHub App settings → General → *Identifying and authorizing users* → Callback URL:
   ```
   https://ghcord.example.com/oauth/github/callback
   ```
2. **Client ID**: 같은 General 페이지에 표시 → `.env`의 `GITHUB_CLIENT_ID`
3. **Client secret**: *Client secrets → Generate a new client secret* → `.env`의 `GITHUB_CLIENT_SECRET`
4. 재시작: `docker compose up -d --force-recreate`

이제 서버의 아무 멤버나 `/github signin`을 실행하고, 승인 링크를 클릭하면 확인 DM을 받습니다. `/github signout`은 연결을 해제합니다.

**OAuth 토큰은 어떻게 되나:** ghcord는 토큰을 GitHub에 "이 사람 누구야?"라고 한 번 묻는 데만 쓰고 버립니다. 저장되는 것은 GitHub 로그인 ↔ Discord 유저 ID 쌍뿐입니다. DM 알림은 유저 토큰이 아니라 App의 웹훅 이벤트로 구동됩니다.

> [!NOTE]
> 이 섹션을 건너뛰어도 나머지는 전부 동작합니다 — `config.toml`의 `[users]` 테이블로 수동 매핑하지 않는 한 DM 알림만 못 받을 뿐입니다.

---

다음: [6단계 — 검증 & 트러블슈팅](06-verify-and-troubleshoot.md)
