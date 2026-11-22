# CHANGELOG

학생용 [README](../README.md)는 현재 버전의 준비물·설치 순서·필수 키만 담습니다. 버전별 변경 내역은
여기에 있고, 각 버전의 상세 릴리스 노트는 `docs/*-release.md`에 남습니다.

이미지: `ghcr.io/wendy-nam/hermes-kit:0.23.3-kN`. 기수 배포 기준은
[설치 도우미 안내](instructor-install-guide.md)의 "강사·운영자 출시 기준"을 따릅니다.

## 0.23.3-k19 — 최신 업스트림 전면 업그레이드 + 보이스 경량 어댑터 + 추천 스킬 & OmniRoute/OMH 프리셋 + SSH 올인원 배포

- **전 컴포넌트 최신 업스트림 업그레이드**
  - **Hermes Agent `v0.23.3`**: Python 3.14 런타임 및 `hermes_yaml` 전환에 맞춘 `yaml` 호환 레이어 내장, 15종 코어 패치 전체 `v0.23.3` 대응 완료.
  - **OMH (`oh-my-hermes`) `v5.0.0`**: `v5.0.0`의 `pre_tool_call` 라우트 노트(`route_note`)와 키트의 라우트 강제·모델별 편향 보정(calibration) 훅이 충돌 없이 결합되도록 개선하고, 기존 설치를 보존하며 업그레이드하는 `bootstrap.py omh-upgrade` 추가.
  - **OmniRoute `v3.8.54-web`**: 최신 `3.8.54-web` 다이제스트 고정, RTK JSON envelope 어댑터 및 CommandCode Anthropic shim + 대시보드 키 경고 UI 패치 호환성 확보.
  - **RTK `v1.2.1`**: 최신 바이너리 체크섬 검증 적용.
- **디스코드 보이스룸 간편통화(`/call`) + 자동 따라가기(`voice_auto_follow`) 경량 런타임 어댑터**
  - 순정 Hermes 컨테이너의 코어 파일을 수정하지 않고도 플러그인 로드 시점에 런타임 몽키패치로 동작하는 [`plugins/kit-setup/voice_adapter.py`](../plugins/kit-setup/voice_adapter.py) 추가 (이미지 빌드 시점 [`patches/voice/`](../patches/voice/) 패치와도 100% 호환·중복 방지).
- **추천 스킬 번들 13종(`seed/recommended`) 추가 및 기본 불필요 스킬 정리 유지**
  - 기존 기본 스킬 정리(`seed/bundled-keep.txt` 13개만 유지) + `k-skill` 25종에 더해, 감사 완료된 추천 스킬 13종(`harness`, `orchestration`, `style-skill-creator`, `meeting-summary`, `meeting-minutes`, `workshop-prep`, `humanize-korean`, `image-prompt`, `bookforge`, 직무 `job` 선택 시 `company-interview-research`, `interview-grill`, `job-match`, `cover-letter-pdf`)을 체크섬 매니페스트(`kit-component/v1`)로 내장했습니다.
- **OmniRoute 가용 리소스 콤보 프리셋 + OMH 12개 카테고리 라우팅/보정 원클릭 연동**
  - [`plugins/kit-setup/omniroute_presets.py`](../plugins/kit-setup/omniroute_presets.py)를 통해 사용자의 OmniRoute에 실제로 연결된 무료 풀 및 구독 계정만 자동 감지하여 7종 추천 콤보(`hermes-chat`, `hermes-free`, `hermes-fast`, `hermes-coding`, `hermes-ultrabrain`, `hermes-writing`, `hermes-visual-engineering`)를 구성하고, OMH 12개 작업 카테고리 체인과 편향 보정 프롬프트를 한 번에 연결합니다 (Discord `/setup → 고급 설정 → OmniRoute 연결 → 추천 가용 리소스 콤보 + OMH 자동 셋업` 또는 `bootstrap.py omniroute-preset apply`).
- **원격 SSH 및 로컬 겸용 올인원 설치·마이그레이션 CLI ([`bin/hermes-kit-deploy.sh`](../bin/hermes-kit-deploy.sh))**
  - 로컬 VPS 또는 원격 SSH(`--ssh user@host`)에서 `install`, `migrate`, `preset`, `verify`를 한 번에 수행하며 기존 컨테이너 데이터와 설정을 안전하게 백업·보존합니다.
- **저장소 정리**: 루트에 잘못 커밋되어 있던 `costRules.ts` 및 미사용 프로토타입 `spikes/s2` 제거.

## 0.21.2-k18 — OMH가 없을 때 안내가 갈리는 것을 고쳤습니다

- **OMH 미설치 상태에서 `verify`가 잘못된 안내를 했습니다.** OMH가 없으면 검증 스크립트가
  예외로 끝나면서 종료 코드 1을 반환하는데, 호출부는 그 코드를 "1순위 경로에 살아있는
  연결이 없다"로 읽고 `providers.json`을 고치라고 했습니다. 원인이 다른 두 상태가 같은
  코드로 나가던 문제로, 이제 "OMH 미설치"는 별도 상태로 구분합니다. 실제 게이트웨이를
  띄워 실측하며 발견·수정했습니다.
- `verify`의 종료 코드 구분을 회귀 테스트로 고정했습니다.

## 0.21.2-k17 — 저장소 하나, 차단 우회는 키 하나

`hermes-vps-setup`과 `omh-omniroute-setup`을 이 저장소에 편입했습니다. 학생이 설치할
패키지는 이제 이 저장소 하나입니다. 상세 판단 근거는
[저장소 통합 문서](2026-10-03-repo-consolidation.md)를 보세요.

- **OMH 라우팅 폴백이 키트에 들어왔습니다.** 구독 계정은 사용 한도가 소진돼도
  `isActive: true`로 남습니다. OmniRoute는 이런 계정을 사전 필터에서 빼고 429로 응답하는데,
  기존 판정은 이를 살아 있는 경로로 보아 **1순위에 턴을 쓰고 폴백하지 못한 채 끝냈습니다.**
  이제 [patches/omh-routing](patches/omh-routing)의 패치가 라우팅 시점에 한도를 읽어
  다음 후보로 넘어갑니다. 100%로 확정된 판정만 소진으로 봅니다.
- **OMH 업데이트로 패치가 사라지지 않습니다.** OMH는 패치된 파일의 자체 사본을 함께
  배포하므로 `omh update`가 원본을 되돌립니다. 이제 키트가 부팅할 때마다와 OMH 설치 직후에
  자동으로 다시 적용합니다. 원본은 `.kit-omh-routing-backups`에 한 번만 보관합니다.
- **학생이 직접 고친 `providers.json`은 건드리지 않습니다.** 이 파일은 그 사람이 실제로
  가진 연결 목록입니다. 기본 템플릿과 같을 때만 키트가 씁니다.
- **이미 켜진 호스트에 붙일 수 있습니다.** `docker exec <컨테이너> python3
  /opt/data/plugins/kit-setup/bootstrap.py omh-routing [status|apply|verify|rollback]`.
  이미 실행 중인 OmniRoute는 재사용하고, 이미지 재배포는 필요 없습니다.
- **`/doctor`에 `OMH 라우팅 폴백` 항목**이 생겼습니다. 복원되었는지 바로 봅니다.
- **PC 노트 동기화가 `clients/pc-sync`로 들어왔습니다.** 동작과 안전 규칙은 그대로이며,
  이제 이미지 빌드 CI에서 문법 검사와 개인정보 스캔을 함께 받습니다.
- **CommandCode Anthropic shim과 대시보드 키 경고 패치**는 게시 이미지를 건드리지 않도록
  [advanced/omniroute-patches](advanced/omniroute-patches)의 선택형 오버레이로
  제공합니다. `KIT_OMNIROUTE_IMAGE`로 지정해 opting in 합니다.

- **차단 우회(Webshare)는 API 키 하나만 넣으면 됩니다.** 예전엔 프록시 Username과
  Password를 따로 물어봤는데, 학생들이 Webshare 대시보드 **로그인 정보**를 그 칸에
  붙여넣는 일이 반복돼 두 칸 모두 "로그인 정보 아님"을 경고해야 했습니다. API 키 하나로
  프록시 인증정보를 조회해 자동으로 채웁니다. 로그인 이메일이 프록시 인증정보가 될 수
  없으므로, 잘못 넣을 여지 자체가 없어집니다. 키가 맞아도 프록시가 죽어 있으면
  저장하지 않습니다(원티드 접속으로 확인).
- **OpenCode Go 발급처 주소가 실제와 달랐습니다.** `opencode.ai/go`는 키 발급 페이지가
  아니라 안내 문서였습니다. `/zen/go`가 실제 Go 플랜 경로입니다(모델 카탈로그도 다릅니다).
- **README 키 목록을 코드와 대조해 고쳤습니다.** Webshare 2개 → API 키 1개,
  대화 모델이 "아래 해당 키"로 되어 있던 부분을 실제 지원 제공자 4개로 명시.
- 상세: [저장소 통합 문서](2026-10-03-repo-consolidation.md)

## 0.21.2-k16 — 막히는 두 지점을 없앱니다

- **봇 초대 링크 복구.** 링크가 첫 부팅 로그의 `[kit] 봇 초대:` 한 줄에만 있던 것을 데이터 볼륨(`/opt/data/.kit-invite-url`, 0600)에 저장하고, 서버 소유자가 **`/invite`** 로 다시 봅니다(ephemeral). 아직 초대하지 못한 경우에는 Developer Portal의 URL Generator 절차를 대신 알려 줍니다(클라이언트 ID를 지어내지 않습니다). 컨테이너에서 `python /opt/data/plugins/kit-setup/owner.py` 로도 같은 링크가 나오고, `/doctor` 에 **봇 초대 링크** 항목이 생겼습니다.
- **고급 설정에 선택 기능 안내.** `/setup → 고급 설정` 첫 메시지에 기능별 설명·필요 키·발급 URL·현재 켜짐 여부가 나옵니다(키 값은 표시하지 않음). PC 노트 줄은 Syncthing 설정의 장치 수를 읽되 "아직 PC 없음 / 연결된 장치 N대"로만 말합니다.
- 상세: [k16 릴리스 노트](2026-09-28-k16-release.md)

## 0.21.2-k15 — 점검에서 나온 실제 결함 수정

- OmniRoute 비밀번호를 비우면 Compose가 기동을 거부합니다(조용히 빈 대시보드가 뜨던 문제).
- 4GB 보호(스왑) 준비 순서를 기다리게 정리, 스왑 실패 로그를 실제 동작과 일치시킵니다.
- API 키 입력 경로에서 저장 실패를 숨기던 문제를 고쳤습니다.
- OmniRoute 문서에 빠뜨리기 쉬웠던 마지막 단계(적용하기 재시작)를 넣었습니다.
- 상세: [k15 릴리스 노트](2026-09-28-k15-release.md)

## 0.21.2-k14 — OmniRoute를 SSH 없이

- 대시보드를 15분 임시 링크로 엽니다(Cloudflare 터널). 모델을 목록에서 고릅니다.
- 상세: [k14 릴리스 노트](2026-09-28-k14-release.md)

## 0.21.2-k13 — 4GB VPS 보호 + OmniRoute 모드

- 메모리 7GB 미만이면 Compose가 2GB 스왑을 한 번 만듭니다. 역할 작업 동시 실행을 1개로 제한합니다.
- 대시보드에서 직접 연결한 계정으로 대화·강한 작업 모델 콤보를 만드는 **OmniRoute 모드**를 추가했습니다(직접 연결 모델이 대체 경로로 남음).
- 상세: [k13 릴리스 노트](2026-09-28-k13-release.md)

## 0.21.2-k12 — 4단계 설정 마법사 + 역할 프로필

- `/setup`이 버튼 15개 대신 번호가 붙은 4단계(대화 모델 연결 → Gemini 키 → 직무 선택 → 권장 설정 적용)로 시작합니다.
- 조사 `research`·코딩 `coder`·콘텐츠 `creator` 역할 프로필이 함께 설치됩니다.
- 상세: [k12 릴리스 노트](2026-09-28-k12-release.md)

## 0.21.2-k11 — ⚠️ k4~k10은 `/setup`, `/doctor`가 뜨지 않았습니다

- **k4~k10을 받은 학생은 k11 이상으로 반드시 재배포해야 합니다.** 플러그인을 패키지로 로드하면서 같은 폴더 모듈을 직접 import하던 문제로 명령이 등록되지 않았습니다.
- 상세: [k11 릴리스 노트](2026-09-28-k11-release.md)

## 0.21.2-k10 — 설치를 단순하게

- **보조 모델은 선택.** 대화 모델 하나 + Gemini 키면 설치가 끝납니다. 보조 모델이 없으면 하위 작업도 대화 모델이 처리합니다.
- 비공개 팩 입력란(`KIT_ACCESS_CODE`·`KIT_PACKS_REF`)을 제거했습니다. Compose 환경변수는 `DISCORD_BOT_TOKEN` 하나입니다.
- 상세: [k10 릴리스 노트](2026-09-28-k10-release.md)

## 0.21.2-k9 — 강사 서버 수정을 학생에게 이식

- 터미널 실패 안내 중복 제거, 프로세스 도구 이름 안내 수정(`process` → `process_manage`).
- 상세: [k9 릴리스 노트](2026-09-28-k9-release.md)

## 0.21.2-k8 — 위임 경로 미정 시 되돌리기

- 경로를 정하지 않은 위임은 한 턴에 한 번 되돌려 `omh_delegate_route`로 작업 종류를 먼저 정하게 합니다. 동시에 여러 대화가 경로를 섞지 않습니다.
- 상세: [k8 릴리스 노트](2026-09-28-k8-release.md)

## 0.21.2-k7 — OMH 경로를 업스트림 기준으로 재구현

- k6은 존재하지 않는 `delegate_task(routing=...)`에 의존해 게시되지 않았습니다. k7은 업스트림 OMH 자체 라우팅 위에서 다시 구현했습니다.
- 상세: [k7 릴리스 노트](2026-09-27-k7-release.md)

## 0.21.2-k6 — OMH 선택 강화

- 작업 분류별로 모델 하나 또는 OmniRoute 콤보 하나와 추론 강도를 정하고, 저장 전에 실제 응답을 확인합니다.
- 상세: [k6 릴리스 노트](2026-09-27-k6-release.md)

## 0.21.2-k5 — 부분 답변을 성공으로 기록하지 않음

- 크론이 실행 한도에 걸려 부분 답변만 만든 경우 성공으로 기록하지 않고 실패 기록을 보존합니다.
- 상세: [k5 릴리스 노트](2026-09-27-k5-release.md)

## 0.21.2-k4 — 스킬 재사용

- 같은 대화에서 이미 읽은 스킬을 재조회하지 않습니다. 내용 압축·변경 시에만 다시 읽습니다.
- 상세: [k4 릴리스 노트](2026-09-27-k4-release.md)