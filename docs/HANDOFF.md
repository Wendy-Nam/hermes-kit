# 인수인계 — hermes-kit (2026-09-26)

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
1. **GHCR 공개 게시(서아 님 확인 후)**: `v0.21.2-k1` 태그 푸시 → GitHub 패키지 설정에서 visibility **Public** 수동 전환. 키트 CI는 **녹색 확인 완료**(`61abdc5`, 전 단계 success).
2. **Phase 2 `/setup` 플러그인**(Task 5~9): `.env` 저장소·키 검증기·팩 정의·주인 등록+초대링크+`PATCH /applications/@me`(인텐트·권한 자동)·모달 UI. **명령은 반드시 길드 전용 등록**(S2 교훈).
3. 스파이크 잔여: S11(볼트 2개·채널별 프로필 — **테스트용 LLM 선택 대기**), S12(CLI OAuth 중계 — 서아 님 클릭 필요), S6(Composio 키), S9(Hostinger 화면).
4. 이후: Phase 4 Syncthing·대화 가져오기, Phase 5 compose(freellmapi는 별도 심화팩 compose), Phase 6 리허설·매뉴얼 v2, Phase 7 `/doctor`·업데이트 알림·백업.
5. 보류: 카톡·팀즈 스킬(서아 님 지시로 키트 이후), 텔레그램 `/setup`(v1.1, 미니앱 폼 안), 아침 브리핑·이메일 다이제스트(만족도 낮음), CLI 워커(2주 실측 후).

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

## 7. 운영 서버에 한 변경 (전부)
- `/opt/data/skills/media/youtube-content/scripts/gemini_video.py`: `--fast` 400 폴백 2줄 추가(서아 님 승인). 롤백: 같은 폴더 `gemini_video.py.bak-20260926-064043-fast400`으로 되돌리기.
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
