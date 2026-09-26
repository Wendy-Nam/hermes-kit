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
- **OmniRoute 키 이전(2026-09-26, 2단계 완료)**: freellmapi 활성 키 39개를 컨테이너 내부 복호화 → 호스트 파이프 → OmniRoute API로 이전(값 비출력). 결과: 공식 프로바이더 27(Cloudflare 포함) + OpenAI 호환 노드 11 = **38 연결, 일괄 테스트 37 통과**(speechify는 `/models` 없음 → 모델 ID 지정 검증 필요). Cloudflare는 freellmapi의 `accountId:token`을 서버 안에서 분리해 `cloudflare-ai` + `providerSpecificData.accountId`로 이전. 미이전: zhipu(호스트 미확인; OmniRoute glm/zai는 국제판 `api.z.ai`). 연결 이름 `fl-<platform>`. 스크립트 `/docker/omniroute/migrate/{fl_export.mjs,om_import.py,om_testall.py}`(600, 멱등 — 재실행 시 기존 이름 건너뜀). 함정: 노드 생성은 `apiType:"chat"` 필수(스키마상 optional인데 superRefine에서 요구), prefix `github`은 Copilot용 예약 → `github-models`, freellmapi 복호화 전 `initEncryptionKey()` 필요, ESM 스크립트는 `/app/server` 안에서 실행해야 `better-sqlite3` 해석. **freellmapi·Hermes 미변경.**
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
- **이전 다음 단계**: 2) freellmapi 키 복호화→호스트 파이프→OmniRoute import(값 비출력) + 프로바이더별 실호출 검증 3) 콤보(대화·보조·private·비전, unfiltered 제외) 4) Hermes 보조·위임 연결 전환(승인 후), freellmapi 1주 유지.
- 재평가 조건: OmniRoute가 thought_signature 왕복을 고친 안정 릴리스를 내면 같은 테스트(`scratchpad`의 `omnitest.py --loop`)로 재확인.
