<!-- source: docs/01-github-app.md -->

# 1단계 — GitHub App 등록

> 이 문서는 [영어 원문](../01-github-app.md)의 한국어 번역입니다.

GitHub App은 단 한 번의 설치로 ghcord가 **모든** 레포의 이벤트를 받을 수 있게 해주는 장치입니다 — 레포별 웹훅 설정이 필요 없고, 새로 만드는 레포도 자동으로 커버됩니다. App은 직접 만드는 것이므로, 무엇을 볼 수 있는지도 직접 결정합니다.

## 1. App 생성

<https://github.com/settings/apps/new> (조직이라면 `https://github.com/organizations/<org>/settings/apps/new`)에서 다음을 입력합니다:

| 항목 | 값 |
|---|---|
| GitHub App name | 아무거나 — App 이름은 전역에서 유일해야 하므로 `ghcord`는 이미 사용 중일 수 있습니다. `<yourname>-ghcord` 같은 이름이 무난합니다 |
| Homepage URL | 내 포크/인스턴스 URL, 또는 이 저장소 |
| Webhook → Active | ✅ |
| Webhook URL | `https://ghcord.invalid/webhook/github` — **임시 값**입니다. [4단계](04-expose-https.md)에서 실제 주소로 교체합니다 |
| Webhook secret | 직접 생성: `openssl rand -hex 32`. 저장해 두세요 — `.env`의 `GITHUB_WEBHOOK_SECRET`이 됩니다 |
| Where can this App be installed? | **Only on this account** |

## 2. 레포지토리 권한

**Permissions & events → Repository permissions**에서 설정합니다. 각 권한은 특정 기능을 위해 존재하며, 만일을 위해 미리 요구하는 권한은 하나도 없습니다:

| 권한 | 수준 | ghcord가 필요한 이유 |
|---|---|---|
| Metadata | Read | 모든 App의 필수 기본값 |
| Contents | Read | 푸시, 브랜치 생성/삭제, 릴리스 알림 |
| Issues | Read **and write** | 이슈 알림. *write*는 `/github open`, `close`, `reopen`을 가능하게 합니다. Discord에서 이슈를 조작하고 싶지 않다면 Read-only를 선택하세요 |
| Pull requests | Read | PR, 리뷰, 리뷰 코멘트 알림 |
| Actions | Read | 워크플로우 실행 알림 |
| Deployments | Read | 배포 상태 알림 |
| Discussions | Read | 디스커션 알림 |

**Organization**과 **Account** 권한은 전부 *No access*로 둡니다.

## 3. 이벤트 구독

이벤트 체크박스는 위에서 해당 권한을 설정해야 나타납니다. 12개를 모두 체크하세요:

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

여기서 이벤트를 체크하는 것은 ghcord가 그 이벤트를 *수신*한다는 의미일 뿐입니다 — 어떤 이벤트가 실제로 어느 Discord 채널에 도달할지는 나중에 채널별로 `/github subscribe`가 결정합니다.

## 4. 자격 증명 수집

App을 만든 뒤 **App settings → General**에서:

1. **App ID** (*About* 아래) → `.env`의 `GITHUB_APP_ID`
2. **프라이빗 키**: *Private keys → Generate a private key* — `.pem` 파일이 다운로드됩니다. [3단계](03-run-the-server.md)에서 컨테이너에 마운트합니다. 레포 밖에 보관하거나 `.gitignore`의 `*.pem` 규칙에 의존하세요 — 밖에 두는 편이 더 안전한 습관입니다.

## 5. App 설치

App settings → **Install App** → 내 계정 → **All repositories**.

이 클릭 한 번이 전체 설계의 핵심입니다: 설치 한 번으로 지금 있는 레포와 앞으로 만들 레포가 전부 커버됩니다. 레포마다 승인을 반복할 필요가 없습니다.

## 6. 동작 확인

서버를 배포하기 전에도 인증이 되는지 확인할 수 있습니다 (위의 `.env` 값 필요):

```bash
uv run python -m app.identity.verify_install
```

기대 출력: App 이름, `selection=all`, 레포 개수. 웹훅 전달은 아직 확인할 수 없습니다 — URL이 여전히 임시 값이기 때문입니다. 그건 [4단계](04-expose-https.md)에서 합니다.

---

다음: [2단계 — Discord 애플리케이션 생성](02-discord-app.md)
