<!-- source: docs/04-expose-https.md -->

# 4단계 — HTTPS로 노출

> 이 문서는 [영어 원문](../04-expose-https.md)의 한국어 번역입니다.

GitHub은 내 서버로 웹훅을 POST해야 하고, Discord는 인터랙션을 POST해야 합니다. 둘 다 **공개 HTTPS** 엔드포인트를 요구합니다 — 평문 HTTP는 어느 쪽도 받아주지 않습니다. 이 문서는 예시 호스트명으로 `ghcord.example.com`을 사용합니다. 전부 본인 호스트명으로 바꿔 읽으세요.

## 1. 서버를 호스트명 뒤에 배치

흔히 쓰는 방법 중 무엇이든 됩니다 — ghcord는 포트 `8788`의 단일 HTTP 서비스입니다:

- **터널** (Cloudflare Tunnel, Tailscale Funnel, ngrok, ...) — 호스트에 공인 IP가 없다면 가장 쉽습니다. TLS도 알아서 처리됩니다. 터널의 ingress를 `http://<host-lan-ip>:8788`로 향하게 하세요.
- **리버스 프록시** (Caddy, nginx, Traefik) — 공인 IP가 있는 머신에서 `https://ghcord.example.com`을 `127.0.0.1:8788`로 프록시.

ghcord는 어느 쪽이든 상관하지 않습니다. 요청이 컨테이너에 도달하기만 하면 됩니다.

바깥에서 확인:

```bash
curl -sI https://ghcord.example.com/          # → 200
curl -s -X POST https://ghcord.example.com/webhook/github -d '{}' \
  -o /dev/null -w '%{http_code}\n'            # → 401 (fail-closed, 정상)
```

## 2. GitHub 연결

GitHub App settings → **Webhook URL** → 임시 값을 교체:

```
https://ghcord.example.com/webhook/github
```

전달 확인: App settings → **Advanced → Recent Deliveries** → 아무 전달이나 재전송 (또는 아무 레포에 푸시해서 새로 발생시키기). **202**가 표시되어야 하고, `docker compose logs`에 `outcome=sent`로 끝나는 줄이 보여야 합니다 (매칭되는 라우트가 없으면 `outcome=skipped`).

## 3. Discord 연결

개발자 포털 → 내 앱 → **General Information → Interactions Endpoint URL**:

```
https://ghcord.example.com/interactions/discord
```

저장하는 순간 Discord가 엔드포인트로 PING과 함께 고의로 잘못된 서명을 보냅니다. PING이 성공하고 잘못된 서명이 거부되어야만 URL이 승인됩니다. 저장이 실패하면 서버에 도달할 수 없거나 `DISCORD_PUBLIC_KEY`가 틀렸거나 비어 있는 것입니다.

## 4. 노출 범위에 대한 노트

두 공개 엔드포인트 모두 모든 요청을 암호학적으로 인증하며 fail-closed로 동작합니다:

- `/webhook/github` — 웹훅 시크릿에 대한 HMAC-SHA256 서명. 서명이 없거나 잘못되면 401.
- `/interactions/discord` — Discord 퍼블릭 키에 대한 Ed25519 서명. 같은 정책.

한 엔드포인트는 별도의 주의가 필요합니다: **`GET /status`**는 레포 이름과 최근 전달 내역이 담긴 비인증 상태 페이지입니다. private 레포가 있다면 프록시/터널 계층에서 제한하거나(IP 허용 목록, 또는 Cloudflare Access 같은 접근 제어 제품) 아예 공개 라우팅하지 마세요. FastAPI의 자동 문서 엔드포인트(`/docs`, `/redoc`, `/openapi.json`)는 코드에서 비활성화되어 있습니다.

---

다음: [5단계 — 커맨드 등록 & 로그인](05-commands-and-signin.md)
