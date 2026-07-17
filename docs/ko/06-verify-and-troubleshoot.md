<!-- source: docs/06-verify-and-troubleshoot.md -->

# 6단계 — 검증 & 트러블슈팅

> 이 문서는 [영어 원문](../06-verify-and-troubleshoot.md)의 한국어 번역입니다.

## 엔드투엔드 체크리스트

순서대로 진행하세요. 각 항목이 설정의 서로 다른 연결 지점을 검증합니다.

- [ ] `docker compose exec ghcord .venv/bin/python -m app.identity.verify_install`이 App 이름, `selection=all`, 레포 개수를 출력 *(GitHub 인증)*
- [ ] `curl -sI https://ghcord.example.com/`이 200 반환 *(노출)*
- [ ] `/webhook/github`에 서명 없는 POST가 **401** 반환 *(fail-closed)*
- [ ] GitHub App → Advanced → Recent Deliveries: 최신 전달이 **202** *(웹훅 연결)*
- [ ] 레포에 테스트 이슈 열기 → 기본 채널에 임베드 도착, 제목이 GitHub으로 링크됨 *(라우팅 + 포매팅)*
- [ ] 기본 브랜치에 푸시 → 커밋 임베드 도착 *(브랜치 필터링)*
- [ ] 두 번째 채널에서 `/github subscribe repo:owner/repo` → 확인 응답, 이후 이벤트가 **두** 채널 모두에 도착 *(커맨드 + SQLite 라우팅)*
- [ ] `/github list`에 구독 표시 *(상태)*
- [ ] `/github signin` → 승인 → 확인 DM 도착 *(OAuth)*
- [ ] 다른 사람에게 내 리뷰를 요청해 달라고 하기 (또는 이슈에서 나를 @멘션) → DM 알림 도착 *(DM 파이프라인 — 주의: 내가 직접 발생시킨 이벤트는 나에게 DM을 보내지 않습니다)*
- [ ] 선택: `config.toml`에 일부러 틀린 `webhook_url`을 넣고 이벤트 발생 → `[ops]` 채널에 알림 → 원상 복구 *(실패 알림)*

모든 항목이 체크되면 끝입니다. 이 페이지의 나머지는 하나라도 체크되지 않을 때를 위한 것입니다.

## 트러블슈팅

### GitHub → 서버

**Recent Deliveries에 401이 표시된다.**
App 설정의 웹훅 시크릿과 `.env`의 `GITHUB_WEBHOOK_SECRET`이 일치하지 않습니다 (또는 `.env`가 다시 로드되지 않았습니다 — `restart`가 아니라 `docker compose up -d --force-recreate`를 쓰세요). *서명 없는* 요청의 401은 정상이고, 실제 GitHub 전달의 401은 시크릿 불일치입니다.

**Recent Deliveries에 타임아웃 / "failed to connect"가 표시된다.**
HTTPS 노출이 컨테이너까지 닿지 않고 있습니다. 바깥에서 안쪽으로 체인을 테스트하세요: `curl https://host/` → 프록시/터널 타깃 → 호스트에서 `curl http://127.0.0.1:8788/`.

**전달은 202인데 Discord에 아무것도 나타나지 않는다.**
202는 "수신하고 검증했다"이지 "라우팅했다"가 아닙니다. `docker compose logs`에서 해당 전달의 줄을 확인하세요: `outcome=skipped`는 매칭된 라우트가 없다는 뜻입니다 (구독도 없고 매칭되는 `config.toml` 항목도 없거나, 이벤트 타입이 채널이 구독한 `features` 목록에 없음 — `reviews`/`comments`/`branches`는 옵트인임을 기억하세요). `outcome=failed`는 Discord 웹훅이 거부했다는 뜻입니다 — 상세 내용을 보고 `[ops]` 채널을 확인하세요.

**피처 브랜치의 푸시 이벤트가 도착하지 않는다.**
의도된 동작입니다: `commits`는 Slack 앱과 동일하게 기본 브랜치만 대상으로 합니다. `commits:*`(모든 브랜치) 또는 `commits:release/*` 같은 glob으로 구독하세요.

### Discord → 서버

**Interactions Endpoint URL 저장이 실패한다.**
저장하는 순간 Discord가 URL에 PING을 보내고, 고의로 잘못된 서명을 보내 거부하는지도 확인합니다. 실패한다면 그 URL로 서버에 도달할 수 없거나, `DISCORD_PUBLIC_KEY`가 틀렸거나 비어 있거나(줄바꿈이 섞여 들어갔는지 확인), `.env`가 다시 로드되지 않은 것입니다.

**커맨드 선택기에 `/github`이 나타나지 않는다.**
전역 커맨드는 반영에 최대 1시간이 걸립니다 — 테스트 중에는 `DISCORD_GUILD_ID`를 설정하고 `scripts/register_commands.py`를 다시 실행해 길드 등록으로 즉시 반영하세요. 그리고: 커맨드는 기본적으로 **웹훅 관리(Manage Webhooks)** 권한이 없는 멤버에게는 숨겨지며, 봇이 `applications.commands` 스코프로 초대되어 있어야 합니다 (불확실하면 2단계의 URL로 다시 초대).

**`/github subscribe`가 에러로 응답한다.**
흔한 원인 둘: `.env`의 `DISCORD_BOT_TOKEN`이 없거나 오래됐거나, 봇에게 그 채널의 **웹훅 관리** 권한이 없는 경우입니다 (채널 수준 권한 오버라이드가 서버 수준 역할이 부여한 권한을 거부할 수 있습니다).

**`/github open` / `close` / `reopen`이 403으로 응답한다.**
App의 권한이 `Issues: Read`이고 `Read and write`가 아니거나 — 권한을 올렸지만 승인하지 않은 경우입니다. 권한 변경은 재승인이 필요합니다: GitHub → Settings → Applications → Installed GitHub Apps → 내 앱 → 대기 중인 배너 승인.

### DM 알림

**`/github signin`이 설정되지 않았다고 한다.**
`GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`이 비어 있습니다 — [5단계](05-commands-and-signin.md#2-github-signin--개인-dm-알림-활성화)를 보세요.

**로그인했는데 DM이 오지 않는다.**
가능성 순으로: (1) 그 이벤트를 내가 발생시킨 경우 — 스스로 발생시킨 이벤트는 의도적으로 제외됩니다; (2) Discord 개인정보 설정이 서버 멤버의 DM을 차단하는 경우 ("서버 멤버가 보내는 다이렉트 메시지 허용"); (3) 이벤트의 GitHub 계정이 연결한 계정과 다른 경우 — `/github signin`으로 다시 연결하세요. DM 실패는 로그에 남지만(delivery ledger 상세의 `dm=failed`) 별도 알림은 없습니다. 채널 전달이 기본 경로이기 때문입니다.

### 그래도 안 되면?

문제를 추적할 때는 `docker compose logs -f ghcord`를 가장 먼저 보세요 — 모든 전달과 커맨드는 구조화된 로그 한 줄(`delivery= event= repo= outcome=`)을 남깁니다. `/status` 엔드포인트(접근 제한 유지 필수)는 최근 전달 내역, 성공률, 에러 상세를 보여줍니다.
