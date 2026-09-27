# 인수인계 — hermes-kit (2026-09-26, `8dc6a9d` 기준 · 테스트 84개 · CI 녹색)

다음 세션은 이 문서 → `docs/plans/2026-09-26-hermes-kit-installer.md`(계획서, §0 결정·§7 D1~D9·하단 "스파이크 결과") 순서로 읽고 시작한다.

## 1. 목표 한 줄
비개발자 수강생이 "VPS 결제 → compose 붙여넣기 → 디스코드 `/setup`"만으로, 매번 같은 결과의 Hermes를 20분 안에 갖게 한다. (LLM이 설치 후 컨테이너를 고치던 방식 폐기)

## 2. 위치

| 무엇 | 어디 |
|---|---|
| 키트 레포 (비공개) | `~/Documents/Github/hermes-kit` → GitHub `Wendy-Nam/hermes-kit` (private — 계획서에 서버 IP·채널 ID 등 포함) |
| 공개 스킬 레포 | `~/Documents/Github/hermes-skills-kr` → https://github.com/Wendy-Nam/hermes-skills-kr (public, MIT) |
| 테스트 봇 토큰 | `~/.hermes-kit-test.env` (권한 600, 채팅에 절대 출력 금지) |
| 테스트 환경 | 서아 님 VPS(`ssh vps` = 호스트 root)의 격리 compose 프로젝트 `hermes-kit-test` (`/docker/hermes-kit-test`, 메모리 2.5GB·CPU 1 상한, 운영 볼륨 미마운트) |
| 운영 서버 | `ssh hermes` = 운영 컨테이너 안(HOME=/opt/data). **읽기 전용 원칙**, 변경은 서아 님 승인 건만 |

**Phase 3 — 코드 부분 완료** (`fetch_packs.py`, `advanced/docker-compose.freellmapi.yml`)
- `fetch_packs.py`: `KIT_ACCESS_CODE`로 비공개 팩 레포를 받아 설치. **전부 best effort** — 네트워크 없음·코드 만료에도 부팅은 성공. **tarball 안의 심볼릭 링크/`../` 는 전체 중단**(안 그러면 다운로드 경로로 학생 `.env`를 덮을 수 있음), 임시 디렉터리 풀고 나서 옮김(중단된 다운로드가 반쪽 스킬 트리를 남기지 않게). `soul/`·`freellmapi/`는 **없을 때만** 복사
- `advanced/docker-compose.freellmapi.yml`: 두 번째 프로젝트로 붙여넣는 심화팩. **포트 미공개**(대시보드가 인터넷에 닿으면 안 됨), `ENCRYPTION_KEY`는 첫 기동에 볼륨에서 자동 생성
- **남음(서아 님 권한·준비물)**: Task 10 Step 1(레포 B 생성 + PAT), Task 11 스킬 큐레이션(개인 문맥 일반화), Task 12 Step 1/3/3b/4/5(freellmapi 체인·키 — 실서비스 필요)

**Phase 7 — Task 17/18/19 코드 완료** (`doctor.py`, `updates.py`, `backup.py`, `disconnect.py`)
- `/doctor`: LLM 없이 자가진단. 각 항목이 **원인과 조치**를 말함("Hostinger에서 재배포하세요") — 상태 코드만 찍으면 학생이 뭘 해야 할지 모름. **강사 복사본은 마스킹**(프로바이더 키 형태·Discord 스노우flake·이메일·IP·`KEY=value`)
- `updates.py`: 태그를 **숫자로** 비교(`0.21.10` > `0.21.9`). 파싱 불가하면 "모르겠다" — 잘못된 "최신입니다"가 침묵보다 나쁨
- `backup.py`: 주간 `no_agent` tarball. **`.env`·`auth.json`·세션은 깊이 상관없이 제외** — 백업이 평문 키 창고가 되면 안 됨. 실패 시 부분 아카이브 삭제
- `disconnect.py`(Task 19, `8dc6a9d`): 팩을 처음 적용할 때 **바꾸기 전 config 값을 한 번만 기록**(재적용이 원래 값을 덮지 않게), 해제 시 키 삭제 + 설정 원복을 함께 — 키만 지우면 `stt.provider: groq`인데 키 없는 반쪽 상태가 남는다. `plan()`으로 지울 목록을 먼저 보여 주고 확인받음. `.env` 쓰기는 `env_store.drop_env()`(원자적·0600·주석 보존)
- `/doctor`는 서버 소유자 또는 승인된 사용자만(`03576bb`) — 길드원이 반복 실행하면 키 검증이 학생 쿼터를 씀
- **남음**: Task 17 합격 기준(리허설에서 실제 확인), Task 20 스타터 크론

**Phase 2 `/setup` 플러그인** (`plugins/kit-setup/`) — 코드·테스트 완료, **수동 E2E 남음**
- `env_store.py`(원자적 600 쓰기·개행 주입 거부), `validators.py`(8종, 키는 헤더만), `packs.py`+`packs.json`/`kits.json`(로드시 전수 검증), `owner.py`(승인·초대링크·`PATCH /applications/@me`), `discord_ui.py`+`views.py`(모달·버튼)
- 계약: **팩의 키가 하나라도 검증 실패하면 아무것도 저장하지 않는다**(반쪽 설정은 나중에 못 고침). 키는 헤더로만, 응답·로그·메시지에 값이 안 나감
- `/setup`은 **길드 전용 등록 + 자체 `tree.sync(guild=)`**(S2 교훈), 서버 소유자만
- `PERMS=277028654080` 테스트로 고정 → 학생은 앱 만들고 토큰만 붙여넣음(인텐트·권한 체크박스 단계 삭제)
- 테스트 35개 통과(CI에서 실행). `views.py` 분리 → discord.py 없는 CI에서도 로직 테스트 가능
- **남음**: 실키 수동 확인(Task 6 Step 5), 테스트 봇 E2E 체크리스트(Task 9 Step 3) — 둘 다 서아 님 준비물 필요

**Phase 5 Task 14** — `docker-compose.yml` 작성 완료. 채울 값은 `DISCORD_BOT_TOKEN`·`KIT_ACCESS_CODE` 2칸뿐, 나머지 키는 `/setup`으로. **남음: 신규 VPS 리허설(Step 2) — S9 확인 겸 스톱워치**

## 3. 완료 (검증 근거 포함)

**Phase 0 스파이크** — S1 베이스 이미지 식별, S2 `/setup` 모달(길드 전용 명령), S3 주인 자동 승인, S4 재시작(s6, ~5초), S4b cont-init 환경, S5 rtk, S7 freellmapi 체인(REST만 가능), S8 라이선스, S10 private 풀 학습정책, 캐시 테스트. 결과는 계획서 하단 표.

**Phase 1 이미지** (`Dockerfile`, `versions.env`, `rootfs/etc/cont-init.d/10-kit-seed`, `seed/`, `bin/merge_yaml.py`, `patches/`)
- 베이스 `nousresearch/hermes-agent:v2026.9.11`(다이제스트 고정, MIT, amd64+arm64)
- 보이스 패치 5종 + 코어 패치 7종(budget-caps는 업스트림용 import 폴백 추가, compression-fix는 source drift로 제외) — 빌드 시 앵커 불일치면 실패
- rtk 0.50.0(체크섬 검증) + rtk 공식 Hermes 플러그인(`rtk init --agent hermes`)
- 볼트 템플릿 work/personal + Dataview·Tasks·TaskNotes(버전 고정)
- 첫 부팅 시드: config **오버레이 병합**(공식 훅이 config를 먼저 만들기 때문), SOUL 교체, 번들 스킬 keep-list 13개로 정리, 볼트 생성, **공개 스킬 `youtube-summary` 설치**(D9, 네트워크 실패해도 부팅 계속)
- 검증: `scripts/boot-test.sh`(새 볼륨 2회 부팅 → 시드·멱등) 통과, `scripts/secret-scan.sh`(심은 키·개인경로·/opt/data 오염 검출 확인 후) clean
- CI: `.github/workflows/build.yml` — 테스트→빌드→보이스 verify→비밀 스캔→부팅 테스트, **태그 푸시 때만** GHCR 게시. **2026-09-26 `61abdc5` 기준 전 단계 녹색.**

**공개 스킬 레포** — `youtube-summary`: 개인 의존 제거(경로·Apify 장부·proxynet), Apify 토큰 헤더 전송, `--fast` 400 폴백 버그 수정, 클릭 타임스탬프 링크(`[mm:ss]`·구간 → `youtu.be/ID?t=초`, `<>`로 디스코드 미리보기 방지), 한국어 출력 형식 문서, Hermes skills-guard **SAFE**, `hermes skills install Wendy-Nam/hermes-skills-kr/youtube-summary` 실설치 확인(경로 = 평면 `/opt/data/skills/youtube-summary`), 전면 리뷰 반영(§4) 후 **테스트 21개 통과**(`a2cd19f`).

## 4. youtube-summary 리뷰 — **완료** (2026-09-26, `a2cd19f`)

독립 리뷰어 에이전트 + 자체 발견을 합쳐 전부 수정·푸시. **사용자에게 틀린 답을 주던 것들이었다**(에러가 아니라 조용히 잘못된 출력).

수정 내역
- **(high) 프록시 자격증명 전달 단절** — `yt.py::_residential()`은 `.env`를 읽는데 `fetch_transcript.py`는 `os.environ`만 봤다. `.env`에만 Webshare를 넣으면 프록시 없이 요청해 VPS IP로 차단. → `_child_env()`가 읽어 둔 값을 `env=`로 자식에 전달. `_residential()`은 `fetch_transcript.py`와 **같은 변수 목록**(`HTTPS_PROXY` 누락도 같이 해결).
- **(high) `--raw` 계약 위반** — 자막을 못 얻으면 `gemini_video()`로 넘어가 **요약을 출력**했다. "정확한 인용용 원문만"을 요청한 사용자에게 생성된 요약이 인용으로 제공되는 최악의 케이스. → `--raw`는 절대 요약으로 대체하지 않고 exit 1 + 사유 출력. `--raw --no-apify` 무음 실패(0바이트)도 해결.
- **(high) 자막 타임스탬프 형식 불일치** — 자막 API는 `0:05`(대괄호 없음), Apify는 `[00:05]`, Gemini 프롬프트는 "줄 앞 `[mm:ss]`"라 주장. → `format_tag()`/`_stamp()` 하나로 3경로 통일, 분 0 패딩, 1시간 넘으면 `[h:mm:ss]`(→ `[100:05]` 소멸), 링크 정규식 `_TS`는 3자리 분 허용.
- **(medium) 인자 파싱** — URL 없으면 `IndexError` 트레이스백, 플래그가 URL 앞이면 플래그를 URL로 인식. → `_parse()` + 사용법 오류(exit 2). `--prompt` 뒤 값이 URL로 잡히던 것까지 테스트로 막음.
- **(medium) 파일명 충돌** — URL에서 ID를 못 뽑으면 **전부** `yt-video.txt` → 서로 다른 영상의 자막이 서로 덮어씀. → URL 해시 폴백.
- **(low)** `youtube-transcript-api` 미설치 시 조용히 실패 → stderr 알림 + SKILL.md 설치 안내. `.env`/자막 파일 미닫음(ResourceWarning) → `with` 블록.
- yt.py가 **import 시점에 폴백 체인 전체를 실행**해 단위 테스트가 불가능했다 → `main()` + `__main__` 가드.
- 테스트 9 → **21개**. 각 수정에 회귀 테스트. skills-guard SAFE 유지.

## 5. 다음 할 일 (순서)
1. **GHCR 공개 게시(서아 님 확인 후)**: `v0.21.2-k1` 태그 푸시 → GitHub 패키지 설정에서 visibility **Public** 수동 전환. 키트 CI는 **녹색 확인 완료**.
2. **레포 B 생성**(Task 10 Step 1) — private 레포 + fine-grained PAT(Contents Read-only, 만료 = 기수 종료일). `fetch_packs.py`가 기다리는 대상.
3. **Phase 2/7 수동 E2E** — 테스트 봇으로 `/setup`·`/doctor` 체크리스트, 실키 검증, 백업 크론 1회 실행.
4. **Task 14 Step 2 리허설** — 깨끗한 VPS에 compose 붙여넣고 20분 스톱워치. 이때 `/doctor` 합격 기준도 함께 확인.
5. **Task 11 스킬 큐레이션** — 개인 스킬을 일반화해서 레포 B로. "SAN"·개인 경로·채널 ID 0건이 기준.
6. **Task 20 스타터 크론**.
7. 이후: Phase 4 Syncthing·대화 가져오기, Phase 6 리허설·매뉴얼 v2, Task 12b CLI 워커 팩(고급), Task 12c 메신저 팩.
8. 보류: 텔레그램 `/setup`(v1.1), 아침 브리핑·이메일 다이제스트(만족도 낮음), CLI 워커(2주 실측 후).

## 6. 함정 (이번에 실제로 밟은 것)
- 빌드 중 Hermes import가 `/opt/data`에 root 파일을 남기면 **모든 새 볼륨의 부팅이 깨짐** → 빌드 검증은 임시 HERMES_HOME에서, 가드로 차단 중.
- 공식 cont-init(01)이 config.yaml·.env·SOUL.md를 먼저 만듦 → "없을 때만 복사"는 영원히 no-op.
- cont-init 훅 shebang에 `with-contenv` 금지(execlineb 실패 전력). env는 `/run/s6/container_environment/` 파일로.
- 플러그인이 전역 트리에 추가한 슬래시 명령은 게이트웨이 safe-sync 스냅샷에서 누락(경합) → 길드 전용 + 자체 `tree.sync(guild=)`.
- skills-guard: 문서에 비밀파일 경로 문자열을 **글자 그대로** 쓰기만 해도 critical → `--force`로도 설치 불가. 테스트로 막아 둠.
- `hermes skills install <이름>`은 **남의 동명 스킬**을 잡음 → 항상 `owner/repo/skill` 전체 이름.
- rtk 절감 통계는 터미널 HOME(`/opt/data/home`)의 DB에 있음(`HOME=/opt/data/home rtk gain`). 운영 rtk는 9/20 이후 정상(500건·72%).
- freellmapi DB는 캐시 토큰을 저장하지 않음 → 캐시 지표는 Hermes `state.db`의 `session_model_usage`에서. 운영 캐시 적중 하락(9/24~)은 트래픽이 deepseek→kilo 무료 모델로 옮겨 간 탓(압축 무관).
- **`.gitignore`의 `*.env`가 `versions.env`까지 삼켰다** → CI가 매번 `./versions.env: No such file or directory`로 8초 만에 실패. 되돌리려면 `!versions.env`이 필요한데, **주석은 반드시 별도 줄에** — gitignore에서 줄 끝 `#`는 주석이 아니라 패턴의 일부라 `!versions.env   # 메모`는 아무것도 예외 처리하지 않는다(조용히).
- 스크립트를 import해서 단위 테스트하려고 하면, 그게 불가능한 이유(import 시점 부수효과)를 먼저 확인할 것 — `yt.py`가 폴백 체인 전체를 최상위에서 실행해서 테스트가 불가능했다.
- macOS에서 `~/Documents` 아래 폴더가 쓰기는 되는데 읽기가 EPERM이 될 수 있음(TCC). 읽기가 막히면 GitHub에서 클론해 작업 후 푸시 — 원본 폴더 상태는 건드리지 않는다.
- **비밀 스캔은 마스킹 테스트까지 잡는다**(2026-09-26 실제 적중). `/doctor` 마스킹 테스트에 서아 님 채널 ID·서버 IP·키 형태 문자열을 리터럴로 넣었다가 CI가 실패. 이런 값은 **런타임에 조립**하고 IP는 TEST-NET-3(`203.0.113.x`)을 쓴다. "가린다"를 테스트하면서 정작 진짜 값을 커밋하기 쉬운 자리.
- **엔트리포인트를 실행하지 않는 테스트는 구멍이다**(`03576bb`): `backup.py`의 `__main__`이 `import os` 누락으로 **매번 NameError** — 주간 백업이 한 번도 돈 적 없는데 테스트 67개는 전부 통과했다(모두 `build()`를 직접 호출). 이제 `Entrypoints` 테스트가 크론처럼 스크립트를 실행한다.
- **"적용됨"을 무조건 찍지 말 것**(`51c94c1`): `hermes config set`을 `check=False`로 돌리고 초록 체크를 항상 출력하던 것 — 학생은 성공으로 읽고 다시 `/setup`을 안 한다. 반환 코드 확인 + 실패 항목 명시. 재시작 실패 시 `.kit-pending-greeting`이 남아 **엉뚱한 재시작 때 "준비 끝"**을 보내던 것도 수정.
- `(?i)` 인라인 플래그는 **패턴 맨 앞에만** 올 수 있다. 중간에 두면 `TypeError`로 정규식 컴파일 자체가 실패한다(무시되는 게 아니다).
- `discord` 모듈을 상속하는 클래스는 모듈 최상위에 둘 수 없다 — `discord.py`가 없는 환경(CI)에서 import가 죽는다. SDK에 묶인 위젯은 별도 모듈로 빼고 게이트웨이 안에서만 import.

## 7. 운영 서버에 한 변경 (전부)
- `/opt/data/skills/media/youtube-content/scripts/gemini_video.py`: `--fast` 400 폴백 2줄 추가(서아 님 승인). 롤백: 같은 폴더 `gemini_video.py.bak-20260926-064043-fast400`으로 되돌리기.
- **OmniRoute 병행 배포(2026-09-26, 서아 님 승인)**: 호스트 `/docker/omniroute`(compose 프로젝트 `omniroute`), 이미지 `diegosouzapw/omniroute:3.8.50@sha256:085c57ad…`, 메모리 2GB 상한, `REQUIRE_API_KEY=true`, 포트 `127.0.0.1:20128`만(대시보드는 `ssh -L 20128:127.0.0.1:20128 vps`), 네트워크 `hermes-agent-ywj7_default`(Hermes에서 `http://omniroute:20128`). 비밀값은 `/docker/omniroute/.env`(600). **Hermes·freellmapi 설정은 미변경.** 롤백: `cd /docker/omniroute && docker compose down -v`.
- **OmniRoute 키 이전(2026-09-26, 2단계 완료)**: freellmapi 활성 키 39개를 컨테이너 내부 복호화 → 호스트 파이프 → OmniRoute API로 이전(값 비출력). 결과: 공식 프로바이더 27(Cloudflare 포함) + OpenAI 호환 노드 11 = **38 연결, 일괄 테스트 37 통과**(speechify는 `/models` 없음 → 모델 ID 지정 검증 필요). Cloudflare는 freellmapi의 `accountId:token`을 서버 안에서 분리해 `cloudflare-ai` + `providerSpecificData.accountId`로 이전. **추가 이전(같은 날)**: freellmapi에서 꺼져 있던 키도 전부(키 자체는 healthy — 9/23 점검의 '만성 실패'는 Hermes 요청 크기 탓이 큼, 나머지는 수동 off) + 커스텀 **Nous API 키 → `nous-research`**(**정정**: `/models`만 통과하고 채팅은 401 — freellmapi의 '커스텀 401 ×152/7일'이 이 키. Hermes `.env`의 `NOUS_API_KEY`도 채팅 401. Hermes는 Nous를 **OAuth 로그인**으로 씀 → Nous는 Hermes 직접 호출 유지, OmniRoute 연결은 비활성) + zhipu(대시보드 표기는 Z.ai지만 실제 호출 주소가 `open.bigmodel.cn` → 그 주소로 노드). **합계 51 연결, 48 검증 통과.** 실패: `ovh`·`aihorde`(freellmapi에서 '키 불필요' 익명 서비스 — 삭제 권장, 서아 님 확인 대기), `speechify`(`/models` 없음). 미이전: `router9`(주소 기록 없음; OmniRoute `9router`는 로컬 npm 프록시로 다른 것). 익스포트 전체 대상은 `EXPORT_ALL=1`. 이전 전 원래 미이전 항목: zhipu(호스트 미확인; OmniRoute glm/zai는 국제판 `api.z.ai`). 연결 이름 `fl-<platform>`. 스크립트 `/docker/omniroute/migrate/{fl_export.mjs,om_import.py,om_testall.py}`(600, 멱등 — 재실행 시 기존 이름 건너뜀). 함정: 노드 생성은 `apiType:"chat"` 필수(스키마상 optional인데 superRefine에서 요구), prefix `github`은 Copilot용 예약 → `github-models`, freellmapi 복호화 전 `initEncryptionKey()` 필요, ESM 스크립트는 `/app/server` 안에서 실행해야 `better-sqlite3` 해석. **freellmapi·Hermes 미변경.**
- **OmniRoute 3단계(A) 완료(2026-09-26, 서아 님 승인)** — Hermes는 여전히 freellmapi, 아래는 OmniRoute만:
  - 이미지 `next`(3.8.51 프리릴리스, 9/24) digest 고정 + 메모리 상한 3GB(2GB는 첫 동기화 때 1.9GB 도달). DB 마이그레이션 13개 적용 → 3.8.50 롤백은 `docker-compose.yml.bak-3850-20260926-123237` + `backups/data-pre-3851-20260926-123237.tgz` 둘 다 복원.
  - 스킬 주입 끔(`skillsEnabled`, 기본 켜짐), 의미 응답 캐시 끔(`semanticCacheEnabled`, temperature 0 요청에 '비슷한' 옛 답 반환). 메모리 추출·작업유형 라우팅·백그라운드 강등·시스템 프롬프트 주입은 원래 꺼져 있음 확인.
  - 모든 연결 `autoSync=true`(24시간마다 각 업체 `/models`에서 카탈로그 갱신, `MODEL_SYNC_INTERVAL_HOURS`) + 1회 동기화 58/62(실패 4개는 `/models` 미제공 → 내장 목록). `/v1/models` 전체 목록은 `catalog_build_timeout`(8천 개+) → 연결별 `GET /api/providers/<id>/models` 사용.
  - `fl-ovh`·`fl-aihorde` 삭제, Cline·Nous 연결 비활성. 서아 님이 대시보드에서 추가한 연결 14개(Claude·Antigravity×2·Copilot·웹세션 gemini/deepseek/zai·lmarena·Devin 등)는 **콤보에 넣지 않음**(구독·웹세션 계정의 자동화 사용 위험). **Codex는 아직 미연결.**
  - 콤보 13개 + 별칭 7개(`migrate/om_combos.py`, 설계는 §11) — 실호출 14/14 정상. `upstage/solar-pro4`는 Upstage `/models`에 없어 사용자 모델로 등록.
  - Hermes용 추론 키 `/docker/omniroute/hermes-api-key`(600, 출력 안 함). 스크립트 `migrate/{om_setup,om_combos,om_fix,om_fix2,om_models,om_calltest,om_api}.py`.
- 테스트 컨테이너 `hermes-kit-test`는 메모리 확보를 위해 정지 상태(`docker start hermes-kit-test`로 재개).
- 그 외 변경 없음(rtk 수정 제안은 불필요로 판명되어 미적용).

## 8. 테스트 환경 정리 (필요할 때)
```bash
ssh vps 'cd /docker/hermes-kit-test && docker compose down -v; docker volume rm -f kitboot-data; docker rmi hermes-kit:spike hermes-kit:dev'
```
테스트 봇 `/kitping`·`/kitowner`는 테스트 서버의 길드 명령으로 남아 있음(무해).

## 9. 서아 님 결정 대기
- S11 테스트용 LLM: freellmapi 무료 풀 연결(추천) vs OpenCode Go 키
- GHCR 이미지 공개 게시 시점
- 운영 freellmapi 체인 순서 조정(대화·위임은 캐싱 모델 우선) 적용 여부
- CLI 워커 2주 측정용 주간 리포트 크론 설치 여부

## 10. OmniRoute 평가 (2026-09-26) — 키트는 freellmapi 유지
격리 테스트 네트워크에서 Hermes 실제 도구 스키마(25개 ≈1.1만 토큰, 전체 45개 ≈2.1만 토큰)로 Gemini 직접 vs OmniRoute 비교.
- 단일 요청: OmniRoute 3.8.50·`main`(9/21) 모두 25/45개 도구 정상(200 + 도구 호출). "도구 많으면 끊김"은 **재현 안 됨**.
- **여러 턴 도구 루프: OmniRoute 경유 시 Gemini thought_signature(`extra_content`)가 클라이언트로 오지 않고, 모델이 이미 읽은 파일을 반복 호출** — 직접 호출은 2~3턴에 답변 완료. 이슈 #14811(Hermes+OmniRoute 400·토큰 과다)과 같은 증상. 안정판 최신이 여전히 3.8.50(8/26).
- 그 외: 키 1개일 때 OmniRoute 자체 쿨다운이 구글 실제 한도보다 길게 잠금, 카탈로그에 `gemini-3.5-flash` 없음, Docker 이미지의 CLI는 `tsx` 누락으로 실행 불가(설정은 HTTP API로), 대기 메모리 490~640MB(freellmapi 101MB).
- CLI·구독 쿼타 기능은 TLS/클라이언트 지문 위장 기반(`docs/security/STEALTH_GUIDE.md`) + 자체 정지 감지 기능 존재 → 수강생 키트 제외.
- 서아 님 freellmapi 프리미엄은 평생 플랜·활성(live 카탈로그). 운영 개선 후보: 죽은 커스텀 키(401 ×152/7일) 교체, 구글 키 모델 범위 2.5→3.x, private 풀에서 xkiro 제외, 대화 체인 캐싱 모델 우선 — **전부 서아 님 승인 대기**.
- **freellmapi도 같은 조건으로 테스트(2026-09-26)**: 운영과 같은 이미지(`freellmapi:hermes-v0.12.0`) 새 인스턴스 + 같은 Gemini 키 + Hermes 도구 25개 → **첫 요청부터 400**. 원인: Hermes `delegate_task.routing.reasoning_effort`의 `anyOf[1] = {"type":"boolean","enum":[false]}` — Gemini 네이티브 API는 문자열 enum만 허용, freellmapi Google 어댑터가 스키마를 정리하지 않고 전송(`...any_of[1].enum[0] (TYPE_STRING), false`). OmniRoute·구글 OpenAI 호환 엔드포인트는 통과. 운영에서 안 보인 이유: 구글 키 모델 범위가 폐지된 2.5로 묶여 Gemini로 거의 안 감 → **모델 범위를 3.x로 넓히기 전에 이 버그부터 패치할 것**.
- 결론 유지(키트 = freellmapi, Gemini는 Hermes에서 직접 호출). 후속: freellmapi 스키마 정리 패치(격리 검증 → 운영은 승인 후), freellmapi·Hermes 업스트림 이슈(공개 게시라 문안 승인 후).
- **방향 전환(서아 님 결정, 2026-09-26): 운영은 OmniRoute로 이전** — 이유는 정확도가 아니라 유지보수 부담(체인 수동 조절, session-sticky/turn-router, freellmapi 패치 5개, CLI 보조툴 관리)을 한 도구로 통합. 두 라우터의 결함은 모두 **Gemini 전용**이므로 **Gemini는 Hermes가 직접 호출**하고 나머지를 OmniRoute로 → 패치 불필요.
- 검증: OmniRoute 3.8.50 + Command Code `cmd/deepseek/deepseek-v4-flash`, Hermes 도구 25·45개 여러 턴 → **둘 다 2턴에 완료**. 키 없는 `oc/*`는 불가(OpenCode 무료 티어는 OpenCode 밖에서 403, deepseek-free는 unavailable) — "키 없이 바로 작동" 광고와 다름.
- **OmniRoute 압축 방침**: Hermes rtk 플러그인 유지(메인 두뇌·Gemini는 OmniRoute를 거치지 않으므로 OmniRoute RTK로 대체 불가). OmniRoute 압축은 기본값(session-dedup → lite)으로 시작 → 전환 후 캐시 2회 호출 테스트로 확인. **Caveman은 대화 콤보에서 끔**(답변을 약 75% 줄여 한국어 응답 품질 저하 우려), 보조 작업 콤보에만 선택.
- **CLI 계정 프로바이더(Cline·Antigravity·Antigravity CLI)**: OmniRoute가 스스로 '프록시 사용 미승인, 장시간 자율 에이전트 사용 비권장, 계정 제한·차단 가능' 경고를 띄움. 코드 확인: Antigravity executor가 공식 클라이언트 프로필로 헤더·User-Agent를 만들고 '비공식 트래픽을 드러내는 프록시/지문 헤더 제거'(`scrubProxyAndFingerprintHeaders`). Hermes는 경고가 말하는 바로 그 사용 방식 → **연결 비권장**, 쓰더라도 보조 계정·저용량 보조 콤보만. 탐지 우회 설정은 손대지 않음. CLI 워커 은퇴는 API 키 콤보로 가능.
- **이전 다음 단계**: 2) freellmapi 키 복호화→호스트 파이프→OmniRoute import(값 비출력) + 프로바이더별 실호출 검증 3) 콤보(대화·보조·private·비전, unfiltered 제외) 4) Hermes 보조·위임 연결 전환(승인 후), freellmapi 1주 유지.
- 재평가 조건: OmniRoute가 thought_signature 왕복을 고친 안정 릴리스를 내면 같은 테스트(`scratchpad`의 `omnitest.py --loop`)로 재확인.

## 11. freellmapi 설계 → OmniRoute 대응 (2026-09-26 운영 전수 조사)
| 원래 설계 | OmniRoute |
|---|---|
| 용도별 프로필(`auto:fast/private/ops-fast/compress/vision/coding/coding-worker/public/commandcode/ultrabrain/writing/visual-engineering`) | 같은 순서의 콤보 `hermes-<이름>`(콤보 이름에 `:` 불가). 메인 모델명 `solar-pro4`는 **같은 이름 콤보** → 크론·omh의 `solar-pro4`는 그대로 |
| private 풀 = 학습 안 하는 곳(Mistral 학습 끔, Cloudflare) | `hermes-private` + `allowedProviders: [mistral, cloudflare-ai]`, xkiro 제외 |
| 세션 고정 `X-Session-Id`(session-sticky) | OmniRoute가 헤더를 기본 인식 + 콤보 세션 고정 기본 켜짐. 플러그인 게이트에 omniroute 추가(전환 스크립트) |
| 난이도 상향 → `auto:commandcode`(7일 105회) | `hermes-commandcode`. 모델명만 바꾸는 방식이라 **메인과 같은 단계에서만** 전환 |
| 무손실 압축(9/23 standard→lossless) | 전역 압축 끔으로 시작(Hermes rtk·tool_output 상한이 이미 있음). 전환 후 캐시 2회 테스트 뒤 대화 콤보만 `lite` 검토 |
| 컨텍스트 핸드오프 끔(Hermes는 매 턴 전체 이력 재전송) | `context-relay` 전략 안 씀(모든 콤보 `priority`) |
| E6-3 예비 모델(qwen3.8-max:free, cf gpt-oss-120b ×0.7) | 콤보 맨 뒤 |
| 키별 모델 범위(OpenRouter `:free`만 등) | 콤보에 명시한 모델만. Gemini 계열은 단발 콤보(vision·ops-fast)에만 — 여러 턴 도구 루프에서 서명 유실 |
| 폴백 예산 9초·첫 토큰 제한·끊김 취소 패치(로컬 커밋 21개) | OmniRoute 기본값(재시도 1, 2초 간격). 문제 보이면 콤보 `timeoutMs`·`targetTimeoutMs` |
| 직접 폴백(nous OAuth, gemini) | **유지** — OmniRoute 장애 시에도 Hermes가 답함 |
| `context_lengths` solar-pro4 131072 | 콤보 `context_length` + Hermes 키를 OmniRoute 주소로 추가 |
| 피크 시간 보정·작업유형 가중치·탐색 끔 | 옮기지 않음(상태·쿼터 점수로 대체) |
| unfiltered 풀 | 옮기지 않음(결정됨, 사용처 없음) |

**omh 활용도**: 위임 카테고리 체인(`.omh/routing/model-chains.json`, 12개)이 `auto:*` 프로필을 가리키지만 실제 위임 경로 기록은 9/4 이후 20건, **최근 7일 0건**. 전환 스크립트가 `model-providers.json`(21개)·`model-chains.json`(20단계)을 함께 바꿈.

**B단계(Hermes 전환, 미실행 — 승인 필요)**: `/docker/omniroute/migrate/hermes_to_omniroute.py --scope aux|all [--apply]`
- `aux`: 설정 7개의 보조·위임·폴백(35경로) + 크론 17개 + omh 경로 + 모든 `.env`에 `OMNIROUTE_API_KEY`. 메인 대화는 freellmapi 유지.
- `all`: + 메인 모델 6개(work는 Nous 직접이라 제외) + session-sticky 2파일.
- 파일마다 `.bak-omniroute-<ts>` 백업, 적용 후 `docker restart hermes-agent-ywj7-hermes-agent-1`. 롤백 = 백업 복사 + 재시작.
- 확인할 것: coder 프로필 `api_mode: codex_responses`가 OmniRoute `/v1/responses`로 도는지, 전환 후 캐시 적중률(Hermes 세션 DB `cached_input_tokens`).

## 12. 최대 풀 + 실검증 + Hermes 1단계 전환 (2026-09-27)
- **풀 생성기** `/docker/omniroute/migrate/om_pool.py plan → probe → apply`: 콤보 = 고정 머리(검증된 기존 설계) → 구독·웹 계정(호출량 적고 개인정보 아닌 콤보만) → **freellmapi 프리미엄 카탈로그**(성능·속도 순위, 도구·비전 지원, 컨텍스트, 무료 여부)로 정렬한 무료 풀 → E6-3 예비. **모든 모델을 Hermes 실제 도구 25개로 시험해 통과한 것만** 넣음(머리 포함 — 정중한 거절도 200이라 폴백이 안 걸리므로). 결과: 230개 시험, 67개 통과, 콤보당 13~23개.
- 시험 방식 함정: 동시 16개로 몰면 업체가 403/429 → OmniRoute가 모델 잠금 → 연쇄 실패(1차 39/215). 업체별 순차·1.5초 간격·일시 오류 20초 후 재시도로 해결. `probe.json`은 통과한 (모델, 종류)만 재사용.
- 학습·공개 위험 경로(kilo 무료 = 학습용 기록, lmarena = 공개)는 `hermes-public`에만. private은 Mistral·Cloudflare 잠금 유지.
- **작동 안 하는 연결(자동 제외)**: auggie·devin-cli(컨테이너에 CLI 필요), zai-web(Playwright Chromium 필요), Copilot(모델마다 '이 연동에서 사용 불가' — 요금제), opencode 계정(카탈로그/무료 티어 거부), gemini-web 비전, lmarena(403/429 잦음), huggingface(월 무료 크레딧 소진 402), electronhub(잔액 소진, 주간 충전), kilo(OmniRoute kilo-gateway는 **실제 Kilo 계정 키 필수** — freellmapi는 키 없이 익명 호출), command-code의 claude-*(Anthropic Messages 형식 필요). Claude 계정(sonnet-5, opus-5)·Antigravity 2개(Claude)·deepseek-web은 통과.
- **3.8.51 변경**: `xkiro`가 기본 프로바이더가 되어 같은 prefix 노드를 가림 → 키를 기본 프로바이더로 옮기고 노드 삭제. **별칭은 모든 prefix의 모델 부분에 걸림**(예: `claude-sonnet-5` 별칭이 `claude/claude-sonnet-5`를 command-code로 가로챔) → 별칭은 `deepseek-v4.1-flash`만 남기고, omh 옛 이름은 전환 스크립트가 콤보 이름으로 바꿈.
- **콤보 인수 테스트**(`om_suite.py`): 여러 턴 도구 루프 11/11(2턴 완료, 반복 호출 없음), 6~11만 토큰 입력 5/5, 스트리밍+도구 3/3, `/v1/responses` 2/2, 캐시: command-code·experiential 두 번째 호출 99% 캐시(Upstage는 캐시 정보 없음). 폴백 실동작 확인(앞 모델 403 → 다음 모델).
- **Hermes 1단계 적용(2026-09-26 16:38 UTC, 서아 님 승인)**: `hermes_to_omniroute.py --scope aux --apply` — 설정 7개의 보조·위임·폴백 35경로, 크론 17개, omh 경로(21+20), `.env` 8개에 `OMNIROUTE_API_KEY`. 백업 `*.bak-omniroute-20260926-163857`. 재시작 후 E2E(`hermes -z … --provider omniroute -m solar-pro4`, `hermes` 사용자) → read_file 사용 후 한국어 답변, 제목 생성은 `hermes-ops-fast`. 8분간 콤보 43건 전부 200, Hermes 오류 없음.
- **2단계(메인 6개 프로필 + session-sticky) 미적용** — 운영 배포 권한 확인 대기. 명령: `python3 /docker/omniroute/migrate/hermes_to_omniroute.py --scope all --apply && docker restart hermes-agent-ywj7-hermes-agent-1`.
- 롤백(1단계): 각 파일 옆 `.bak-omniroute-20260926-163857`을 원래 이름으로 복사 → Hermes 재시작. freellmapi는 그대로 살아 있음.

## 13. freellmapi 처리·주간 갱신·키트 전환·압축 계층 (2026-09-27)
- **2단계(메인 대화 6개 프로필 + session-sticky) 여전히 미적용** — 운영 배포 권한 검사가 두 번 막음(서아 님 "나머지 다 해줘" 이후에도). 서아 님이 직접 실행:
  `ssh vps 'python3 /docker/omniroute/migrate/hermes_to_omniroute.py --scope all --apply && docker restart hermes-agent-ywj7-hermes-agent-1'`
- **freellmapi = 평소 정지, 주 1회만 기동("CLI처럼")**: OmniRoute 컨테이너에 합치지 않음(이미지 직접 수정 = 줄이려던 유지보수 부담). freellmapi는 부팅 10초 후 카탈로그를 받고 `catalog_last_sync_ms`를 찍음(`services/catalog-sync.ts`, 12시간 주기) → `ops/omniroute/om_refresh.sh`가 기동 → 동기화 확인 → `fl_catalog.json` 추출 → **24시간 요청이 0건일 때만** 정지 → 모델 목록 갱신 → 전체 재시험 → 콤보 적용(콤보당 통과 3개 미만이면 기존 유지) → 도구 루프 스모크. 배포(미실행, 권한 필요): `ops/omniroute/*`를 `/docker/omniroute/migrate/`로 복사 + 호스트 크론 `20 4 * * 1 /docker/omniroute/migrate/om_refresh.sh >> /docker/omniroute/refresh.log 2>&1`.
- `ops/omniroute/`에 운영 검증 도구를 버전 관리로 옮김(`om_pool`·`om_suite`·`om_setup`·`om_models`·`om_calltest`·`hermes_to_omniroute`·`fl_catalog.mjs`·`fl_state.mjs`·`om_refresh.sh`). 비밀값 없음 — 키는 서버 파일(`/docker/omniroute/.env`, `hermes-api-key`)에서만 읽음.
- **키트 전환**: 심화팩 freellmapi → OmniRoute(`advanced/docker-compose.omniroute.yml`, 수강생 입력은 `KIT_OMNIROUTE_PASSWORD` 하나, 서명 비밀값은 첫 기동 때 볼륨에 생성, `/healthz`), `/doctor` 점검 대상·팩 복사 대상(`omniroute/`) 변경, 테스트 통과. 설계 문서 Task 12·D7 재작성, D10(압축 계층) 추가. 수강생 기본에서 구독·웹 세션·CLI 계정 프로바이더와 kilo·lmarena 제외. 프리미엄 카탈로그 원본은 팩에 넣지 않음(라이선스 재배포 여부 미확인).
- **압축 계층(운영·키트 공통, §D10)**: 셸 출력 = rtk 플러그인, 도구 결과 = Hermes `tool_output`/`tool_budget`, 대화 길이 = Hermes 압축(`hermes-compress`), OmniRoute는 압축 전역 off·Caveman off(라우팅·세션 고정·캐시 보존만). 전환으로 freellmapi `lossless` 압축(dedup·toolfilter·jsoncompact)이 빠짐 — toolfilter는 Hermes `tool_output`과 중복이라 손실 작음. 1주 뒤 Hermes `session_model_usage`로 입력 토큰 추이 비교.
- 선택: OmniRoute `-web` 이미지(`next-web`)면 Chromium이 들어 있어 zai-web·gemini-web 등 웹 세션 프로바이더가 동작(약 +300MB).

## 14. 메인 전환 완료 · omh 수정 · 연결 되살리기 (2026-09-27)
- **메인 전환(서아 님 직접 실행)** 확인: 기본 설정으로 `hermes -z` → `omniroute/solar-pro4`, coder 프로필 → `hermes-coding`, 도구 사용·성공. 중국어 답변 1회는 solar-pro4 일회성(OmniRoute·freellmapi 각 2회 재시험 모두 한국어). 전환 후 freellmapi 요청은 비교 시험 4건뿐.
- **omh 버그 2개(전환 스크립트 탓) 수정**: ① `model-chains.json`만 `hermes-*`로 바뀌고 `model-providers.json` 키가 옛 `auto:*` → 새 이름 11개 추가 ② omh는 모델 이름 토큰 `^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$` 위반 시 **파일 전체 무시** — `cloudflare-ai/@cf/...`의 `@` 때문에 1단계 이후 omh 위임 경로가 꺼져 있었음 → `hermes-fast`로 교체. omh 로더로 검증(경로 35, 카테고리 12 applied), `deep` 위임 E2E 성공. 스크립트는 비토큰 모델이면 쓰기 전에 중단.
- **OmniRoute 이미지 `next-web`**(서아 님 실행, 같은 3.8.51 + Chromium/Playwright, 메모리 상한 4g). 롤백 `docker-compose.yml.bak-pre-web`(DB 변경 없음).
- **웹 쿠키 프로바이더**: 공식 문서상 **도구 호출 미지원**. `next-web`에서도 zai-web(502·시간 초과)·lmarena(403/429) 실패. deepseek-web만 여러 턴 도구 루프 통과. 쿠키 추출은 서아 님이 직접(DevTools → Network → 채팅 요청의 Request Headers `Cookie` 전체 복사, Cookie 저장소 값 금지 — OmniRoute WEB-COOKIE-GUIDE).
- **연결 되살리기(서아 님 요청)**: Cline·Nous 재활성(`:free`만 사용), aihorde는 공식 익명 키(`0000000000`), kilo·ovh는 **키 없는 OpenAI 호환 노드**(`kilo-anon`, `ovh-anon`) — 기본 프로바이더는 키 필수인데 잘못된 키면 업체가 거부. 작동: Cline `nemotron-3-ultra:free`(여러 턴 통과), kilo 익명 7개, ovh 익명 4개(느림), aihorde. **Nous는 두 키 모두 채팅 401 → 서아 님이 Nous 포털에서 새 API 키 발급 후 대시보드에서 `hermes-nous` 연결 키 교체**(주간 갱신이 자동으로 `:free` 5개를 넣음). kilo·lmarena·aihorde는 `hermes-public`만(학습·공개·자원봉사 워커가 프롬프트 열람).
- 구독 계정 여러 턴 도구 루프: claude-sonnet-5 · antigravity claude-sonnet-4-6 · deepseek-web · cline nemotron 모두 통과. 최종 콤보 14~30개(통과 79/252). 대표 콤보 4개 루프 통과.
- **Codex**: OmniRoute는 기기 인증을 **브라우저가 수행**(서버 IP는 auth.openai.com 차단) → 서아 님이 대시보드에서 직접 로그인. 로그인 후 `om_pool.py`에 codex 모델을 구독 계층으로 추가·시험.
- **Codex 연결(2026-09-27, 서아 님 대시보드 로그인, 계정 hanzoom2000)**: 46개 모델. `gpt-6-astra`·`gpt-6-sol`·`gpt-5.6-terra`·`gpt-6-luna` 도구 시험 통과(luna 비전 통과). 배치: ultrabrain 맨 앞 astra→sol, 성능 콤보(coding·commandcode·writing·visual-engineering) 구독 계층 맨 앞 sol→terra, 메인 폴백·비전에 luna. 여러 턴 루프 통과, 캐시 2회차 11,776/11,921(99%). 콤보 16~33개.
- **Nous**: 무료 티어는 OAuth 전용이라 API 키 발급 불가 → OmniRoute `nous-research`(키 전용) 사용 불가. 연결 비활성, 풀 후보에서 제거. Hermes의 Nous 직접 호출(OAuth)은 그대로(메인 폴백 첫 항목 `nous/upstage/solar-pro4:free`, work 프로필 메인).

## 15. youtube-summary 라이브 적용 · freellmapi 잔재 정리 (2026-09-27)
- **youtube-summary**: 기본·`public` 프로필 둘 다 `hermes skills install Wendy-Nam/hermes-skills-kr/youtube-summary --category media --yes --force`(Hermes 스캐너가 API 키를 env에서 읽는 커뮤니티 스킬을 '주의'로 막음 — 우리 검토본이라 강제). turn-router 하드 트리거(`_shared/skill_retriever.py` 6줄·`skill_synonyms.yaml`)를 `youtube-summary`로, 옛 `youtube-content`는 `skills/.archive/youtube-content-20260927-023347`(두 프로필). 디스코드 시뮬레이션에서 L1 자동 로드 확인, 스크립트 직접 실행 → Gemini 영상 분석 + 클릭 타임스탬프 링크. `hermes -z`(CLI)는 turn-router가 비사용자 트래픽으로 건너뛰므로 스킬 트리거 시험에 못 씀.
- **키트 버그**: 첫 부팅 설치가 `--yes`만이라 스캐너에 막혀도 조용히 넘어가고 있었음 → `--category media --yes --force` + 설치 후 파일 확인, 부팅 시험이 `skills/media/youtube-summary/SKILL.md` 존재를 검사(CI 녹색 `7dd9817`). 공개 레포 README도 `--force` 안내 필요(공개 게시라 서아 님 확인 후).
- **freellmapi 잔재 16파일 → OmniRoute**(`ops/omniroute/hermes_leftovers.py`, `.bak-omniroute-leftovers-*`): hermes-self 자율 작업 경로, 셀카 선톡(비전), 메모리 압축(`hermes-private`), 자기개선 evo 2종, `llm_oneshot`(옛 `auto:*` 이름을 콤보로 자동 변환), 헬스 모니터(`/healthz`), 공개 모델 실행기, self-arch-audit, CONTRACT.md, 스킬 문서 5개(`/v1/models` 대신 콤보 이름 쓰라는 안내 포함). freellmapi 전용 도구 3개 → `_quarantine/freellmapi-tools-*`. `bin/ua-refresh.sh`는 파일 스스로 '레거시·수동 전용'이라 미변경. 검증: 컴파일, `llm_oneshot --model auto:private` → `hermes-private` 응답, 재시작 오류 없음.
- **겹침 없이 남긴 것**: turn-router(스킬·규칙 주입 — OmniRoute 스킬 주입은 끔), rtk-rewrite(셸 출력 — OmniRoute RTK 끔), session-sticky의 `X-Session-Id`(OmniRoute가 그대로 세션 고정에 씀), 에스컬레이션(메인 모델 이름에 `solar`가 있을 때만 동작), Hermes 패치 aux-route-attribution·aux-configured-routes-only(무해·일반). **freellmapi 은퇴 후 삭제**: 설정의 `providers.freellmapi`·`context_lengths`의 freellmapi 키·`.env`의 `FREELLMAPI_API_KEY`·session-sticky의 freellmapi 분기.
- 캐시(7일, Hermes `session_model_usage`, 적중 = 캐시/(입력+캐시)): 메인 solar-pro4 56%(1,803회, 약 7천만 토큰), fast·deepseek 계열 92~94%.

## 16. 대화 모델·채널·무료 풀·omh 추천 모델 (2026-09-27)
- **대화**(서아 님 실행 `hermes_chat.py`): 기본 프로필 메인 `hermes-chat`(Codex gpt-6-luna → Cline 무료 DeepSeek V4.1 Flash → Command Code → Upstage solar-pro4 → 구독·무료), RP 채널만 `discord.channel_overrides`로 `solar-pro4`, 압축 prune 4만·threshold 8만, `agent.service_tier` 제거. 요약 채널은 채널 지정 없이 `public` 프로필 메인(무료 `hermes-public`).
- **요약 채널 사고**: `hermes-public` 맨 앞 codestral이 형식을 되묻고, 스킬을 도구 목록에서 찾다 포기, `public` SOUL의 "서아가 … 던지는"을 자기 이름으로 씀 → SOUL에서 이름 제거·옛 `youtube-content`→`youtube-summary`·"형식 되묻지 말 것", `hermes-public` 맨 앞을 무료 대화 모델(experiential gpt-5.6-luna, NVIDIA/Cline nemotron-3-ultra)로. 같은 프로필에서 요약 E2E 확인.
- **Cline = 무료만**: 유료 id는 크레딧 없음 402 → OmniRoute가 **Cline 연결 전체를 몇 분 잠가 무료까지 막음** → 유료 id는 절대 콤보에 넣지 않음. 무료 목록은 `api.cline.bot/api/v1/models`(공개, 458개 중 `:free` 17개) + DeepSeek V4/V4.1 Flash(접미사 없지만 잔액 음수에서 응답 = 무료). OmniRoute 내장 Cline 목록(13개)에 없는 id도 그대로 전달되므로 풀 생성기 `UNLISTED_OK`에 포함. Cline 연결 `서아 남`은 토큰 만료(재로그인 필요), `Seoa Nahm`이 동작(잔액 -$0.04). Kimi K3 무료는 unorouter에만 있으나 2턴째 429 → omh에는 sail Kimi K3(무료, 루프 통과).
- **`hermes-free`**(무료 전용 콤보) 생성 — 현재 omh는 쓰지 않음(아래), 필요 시 수동/위임 기본값용.
- **omh 모델별 보정**: `omh_delegate_route`는 `routing.model`(전송 모델 이름)로 계열을 판별해 보정 문구(`child_context_append`)를 고름 → 콤보 이름(`hermes-*`)은 `unknown`. 그래서 omh 카테고리를 **omh 기본 추천 순서 + 실제 OmniRoute 모델**로 재구성(`ops/omniroute/omh_chains.py`): kimi-k3=sail(무료), deepseek-flash=Cline V4.1(무료), glm-5.3/flash=sail(무료), gemini-3.1-pro=agy Pro(Antigravity 서명 캐시로 루프 정상), gpt-6-*=Codex, claude-fable-5-1·opus-5-5=Claude Opus 5(Fable은 요금제 밖 429, Opus 5.5는 400), qwen3-coder=Command Code Qwen 3.8 Max(xkiro 무료 403). writing·artistry는 Gemini 맨 앞(서아 님). 전 모델 여러 턴 루프 통과, omh 로더 applied, 계열 판별 전부 정상(보정 문구 0자인 계열은 omh에 문구가 없는 것). writing 위임 E2E → `agy/gemini-3.1-pro-high`.
