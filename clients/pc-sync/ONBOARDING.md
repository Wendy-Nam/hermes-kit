# hermes-kit 온보딩 (clients/pc-sync)

이 문서는 "Hermes 에이전트를 개인 VPS에서 쓰고 PC 옵시디언으로 노트를 본다"까지
끝나는 전체 경로를 한 번에 설명합니다. 이 폴더(`clients/pc-sync`)는 그 경로의 **PC 쪽 구간만**
자동화합니다. 서버 설정은 hermes-kit이 소유합니다.

- 서버·봇·모델·키: <https://github.com/Wendy-Nam/hermes-kit> (README의 "수강생 설치 순서")
- 강사가 학생을 데려가는 절차: hermes-kit의 `docs/instructor-install-guide.md`

## 1. 전체 그림

```
Discord (학생)                VPS (4GB 이상)                     PC
  /setup  ──────────────▶  hermes 컨테이너 ──▶ syncthing 컨테이너
  /doctor                     (봇·에이전트)        (볼트 2개 공유) ◀──▶ Syncthing ──▶ Obsidian
  /invite                        │                                    ▲
                                 └────────────────────────────────────┘
                                        SSH (수동, 1회 페어링)
```

- `hermes` 컨테이너: Discord 봇과 에이전트. 데이터는 `/opt/data`
- `syncthing` 컨테이너: 볼트를 PC와 공유. `/var/syncthing/vaults/{work,personal}`
- `swap-init`·`syncthing-init`: 한 번 설정하고 끝나는 컨테이너. **종료(0)가 정상**
- 공유되는 것은 **볼트 2개뿐**입니다. `.env`, 인증 파일, 전체 데이터는 공유되지 않습니다.

## 2. 책임 경계

| 하는 일 | 주체 |
|---|---|
| 모델·API 키 입력과 검증 | hermes-kit `/setup` (Discord 모달) |
| OMH·역할 프로필 설치 | hermes-kit `/setup` |
| 볼트(work·personal) 생성 | hermes-kit `/setup` |
| Syncthing 서버 컨테이너 | hermes-kit Compose |
| PC Syncthing 설치·자동 실행 등록 | **이 스킬** |
| PC↔서버 볼트 페어링(공유 등록) | **이 스킬** (키트도 같은 값을 씁니다) |
| Obsidian 설치·볼트 열기 | **이 스킬** |
| 실제 파일이 왕복하는지 검증 | **이 스킬** (`02-verify.sh`) |

> 이전 버전은 이 스킬이 PC에서 SSH로 서버 `config.yaml`·프로필·크론·OMH까지
> 덮어썼습니다. 그 결과 hermes-kit `/setup`과 **같은 파일에 두 개가 쓰는** 일이
> 생겼습니다(2026-09-28 크론 덮어쓰기와 같은 형태). 서버 쪽은 전부 kit에 넘겼습니다.

## 3. 전체 순서

### 0단계 — 준비물

| 준비물 | 내용 |
|---|---|
| VPS | Docker 사용 가능, RAM 4GB 이상, 디스크 여유 6GB 이상. 7GB 미만이면 Compose가 스왑 2GB를 자동 생성 |
| Discord | 본인 계정 + **본인이 소유한 서버** 하나 |
| 대화 모델 | ChatGPT 구독(로그인) 또는 API 제공자 키 중 하나 |
| Gemini 키 | 영상 요약용 무료 키 (`/setup`에서 입력) |
| 선택 | 음성(Groq)·차단 우회(Webshare)·SNS 수집(Apify)·Composio — 당일 없어도 됨 |

키와 봇 토큰은 **본인이 입력하고, 강사에게도 보내지 않습니다.**

### 1단계 — VPS에 hermes-kit 배포

Hostinger Docker Manager의 Compose 프로젝트에 hermes-kit의 `docker-compose.yml`을
붙여넣고, 환경변수 `DISCORD_BOT_TOKEN`만 입력해 배포합니다.

확인 지점: `hermes`·`syncthing`은 실행 중, `swap-init`·`syncthing-init`은 종료(0).
로그에 `[kit] 봇 초대:` 링크가 보입니다.

### 2단계 — 봇 초대와 `/setup`

1. 로그의 초대 링크로 **본인 서버**에 봇을 초대합니다.
   - 로그를 못 찾은 경우(k16~): 이미 초대했다면 Discord에서 `/invite`.
     아직 초대하지 못했다면 `/invite`가 Developer Portal의 URL Generator 절차를 안내합니다.
2. **서버 소유자 계정**으로 `/setup`을 실행하고, 화면의 번호대로 진행합니다.
   1. 대화 모델 연결(권장 ChatGPT 로그인 또는 API 키)
   2. Gemini 키
   3. 직무 선택
   4. 권장 설정 적용(재시작) — OMH와 역할 프로필
3. `/doctor`로 확인하고 실제 질문 하나를 해봅니다.

여기까지가 hermes-kit의 영역입니다. **이 스킬의 스크립트는 이 과정을 대신하지 않습니다.**

### 3단계 — 이 스킬로 PC 동기화 (clients/pc-sync)

```sh
bash scripts/00-preflight.sh     # 키트 배포·볼트·Syncthing 응답 확인
bash scripts/01-pc-sync.sh       # PC Syncthing·Obsidian 설치 + 볼트 2개 페어링
bash scripts/02-verify.sh        # 실제 파일 왕복 확인
```

2단계는 기존 Syncthing 설치가 있으면 재사용하고, 없을 때만 portable 설치와
로그인 시 자동 실행 등록(launchd / 시작 프로그램)을 합니다.

## 4. 볼트 구조

| | 서버 | PC(기본) |
|---|---|---|
| 업무 | `/var/syncthing/vaults/work` | `~/HermesVaults/work` |
| 개인 | `/var/syncthing/vaults/personal` | `~/HermesVaults/personal` |

Syncthing 폴더 ID는 `hermes-work`, `hermes-personal`입니다. 이 값은 hermes-kit의
`syncthing_setup.FOLDERS`와 **반드시 같아야 합니다.** 어긋나면 공유 설정만 성공하고
파일은 조용히 오가지 않습니다. 두 저장소는 같은 값을 기계적으로 유지해야 합니다.

PC 위치를 바꾸려면 `setup.env.example`을 `setup.env`로 복사해 `LOCAL_VAULT_ROOT`을
지정하세요(없어도 동작합니다).

## 5. 무엇이 확인된 것이고 무엇이 아닌가

`pair_device()`와 이 스킬의 등록 단계는 **공유 설정이 저장되었다**는 뜻입니다.
PC가 수락했는지, 파일이 도착했는지는 증명하지 않습니다.

- 키트: 공유 설정 저장까지. `/setup → 고급 설정`의 **선택 기능 안내**가 세는
  "연결된 장치 N대"도 Syncthing 설정만 센 값입니다.
- 이 스킬: `02-verify.sh`가 서버에 실제 파일을 써서 **PC에 도착할 때까지** 기다립니다.

지금까지 실제로 확인한 것: mock Syncthing 대상 등록·재실행·자기 ID 거부·두 번째 기기 추가.
**실제 학생 Windows/macOS에서의 완주 실행은 별도 확인 항목입니다.**

## 6. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| "컨테이너를 찾지 못했습니다" | hermes-kit을 아직 배포하지 않았습니다 |
| "Syncthing이 응답하지 않습니다" | `docker logs`로 syncthing 서비스 확인 |
| kit-setup이 없습니다 | k11 이전 이미지입니다. k11 이상으로 재배포 |
| 공유는 됐는데 파일이 안 옵니다 | `02-verify.sh`가 짚어 준 Syncthing 화면의 "업로드 대기" 항목 |
| 폴더 ID 충돌 중단 | 같은 ID가 다른 경로에 쓰이고 있습니다. 기존 설정을 확인하세요 |
| 4GB에서 봇이 재시작 | `swap-init` 로그. 스왑이 안 켜졌다면 호스트에서 수동 생성 |
| 첫 동기화가 느림 | 1~2분이면 정상입니다. "안 된다"가 아니라 아직 전송 중입니다 |

## 7. 안전 규칙

1. **API 키를 이 스킬로 받지 않습니다.** 키 입력은 `/setup`이 담당합니다.
2. **서버 설정을 직접 고치지 않습니다.** `config.yaml`, `cron/jobs.json`, 프로필,
   OMH는 hermes-kit의 영역입니다.
3. **컨테이너 재시작은 서비스 중단입니다.** 이 스킬은 재시작하지 않습니다.
4. 스크립트가 실패하면 **고쳐서 재실행**합니다. 모두 멱등입니다. 수동 ssh로 우회하지
   않습니다. 그 전에 `setup.env`와 `SSH_ALIAS`만 확인하세요.

## 8. 데이터와 삭제

- 동기화는 **양방향**입니다. PC에서 지운 파일은 서버에서도 지워집니다.
- 서버를 지우면 볼트도 함께 사라집니다. 키트가 등록한 주간 백업과 별도로,
  PC 동기화가 곧 서버 밖 사본입니다.
- 개인 볼트에 둔 대화는 연결한 PC와 서버 사이에서만 오갑니다. 본인 기기인지
  확인하고 연결하세요.
- 옵시디언을 켜 두면 `workspace` 파일이 계속 바뀌어 충돌합니다. `.stignore`는
  `01-pc-sync.sh`가 생성합니다.

## 9. 되돌리기

- 동기화 해제: PC Syncthing에서 해당 기기의 폴더 공유를 해제합니다. 이 가이드는
  기기나 파일을 삭제하지 않습니다.
- 볼트 정리: 서버 볼트의 파일을 지우면 PC에도 반영됩니다. 지우기 전에 확인하세요.
- 이 스킬을 없애려면 PC의 Syncthing 공유 해제 후 폴더를 삭제하세요. 서버는 그대로입니다.
