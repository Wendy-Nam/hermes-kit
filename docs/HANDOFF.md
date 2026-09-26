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

## 3. 완료 (검증 근거 포함)

**Phase 0 스파이크** — S1 베이스 이미지 식별, S2 `/setup` 모달(길드 전용 명령), S3 주인 자동 승인, S4 재시작(s6, ~5초), S4b cont-init 환경, S5 rtk, S7 freellmapi 체인(REST만 가능), S8 라이선스, S10 private 풀 학습정책, 캐시 테스트. 결과는 계획서 하단 표.

**Phase 1 이미지** (`Dockerfile`, `versions.env`, `rootfs/etc/cont-init.d/10-kit-seed`, `seed/`, `bin/merge_yaml.py`, `patches/`)
- 베이스 `nousresearch/hermes-agent:v2026.9.11`(다이제스트 고정, MIT, amd64+arm64)
- 보이스 패치 5종 + 코어 패치 7종(budget-caps는 업스트림용 import 폴백 추가, compression-fix는 source drift로 제외) — 빌드 시 앵커 불일치면 실패
- rtk 0.50.0(체크섬 검증) + rtk 공식 Hermes 플러그인(`rtk init --agent hermes`)
- 볼트 템플릿 work/personal + Dataview·Tasks·TaskNotes(버전 고정)
- 첫 부팅 시드: config **오버레이 병합**(공식 훅이 config를 먼저 만들기 때문), SOUL 교체, 번들 스킬 keep-list 14개로 정리, 볼트 생성
- 검증: `scripts/boot-test.sh`(새 볼륨 2회 부팅 → 시드·멱등) 통과, `scripts/secret-scan.sh`(심은 키·개인경로·/opt/data 오염 검출 확인 후) clean
- CI: `.github/workflows/build.yml` — 테스트→빌드→보이스 verify→비밀 스캔→부팅 테스트, **태그 푸시 때만** GHCR 게시

**공개 스킬 레포** — `youtube-summary`: 개인 의존 제거(경로·Apify 장부·proxynet), Apify 토큰 헤더 전송, `--fast` 400 폴백 버그 수정, 클릭 타임스탬프 링크(`[mm:ss]`·구간 → `youtu.be/ID?t=초`, `<>`로 디스코드 미리보기 방지), 한국어 출력 형식 문서, 테스트 9개, Hermes skills-guard **SAFE**, `hermes skills install Wendy-Nam/hermes-skills-kr/youtube-summary` 실설치 확인.

## 4. 진행 중 — youtube-summary 전면 리뷰 (서아 님 요청, 미완)
독립 리뷰어 에이전트를 돌리던 중 세션 종료. **다음 세션에서 리뷰를 다시 돌리고** 아래 자체 발견과 합쳐 수정할 것.
1. **(high) 프록시 자격증명 불일치**: `yt.py::_residential()`은 `.env`까지 읽어 True가 되는데, `fetch_transcript.py`는 `os.environ`만 읽음 → `.env`에만 Webshare를 넣으면 프록시 없이 요청해 IP 차단. 수정: yt.py가 `_env()`로 읽은 값을 하위 프로세스 env로 넘기기.
2. **(high) 자막 API 타임스탬프 형식**: `fetch_transcript.py --text-only --timestamps`는 `m:ss 텍스트`(대괄호 없음) → Gemini 텍스트 프롬프트("줄 앞 [mm:ss]")·링크 변환과 불일치. 수정: `[m:ss]` 출력.
3. **(medium) 긴 영상**: Apify 경로는 분을 100 이상으로 찍을 수 있음(`[100:05]`) → 링크 정규식 `\d{1,2}` 미매치. 수정: 시간 단위 포맷 또는 정규식 `\d{1,3}`.
4. **(medium) `yt.py` 인자**: URL 없이 실행하면 `sys.argv[1]` IndexError 트레이스백. 플래그가 URL보다 앞이면 오동작.
5. **(medium) `--raw`인데 Apify 실패 시** `gemini_video()` 요약을 출력 → "원문만" 계약 위반.
6. **(low)** `transcript_api()`는 `sys.executable`로 실행 → `youtube-transcript-api` 미설치면 조용히 실패(폴백은 됨). SKILL.md에 설치 안내 한 줄 필요. `_vid()` 실패 시 파일명 `yt-video.txt` 충돌.

## 5. 다음 할 일 (순서)
1. youtube-summary 리뷰 마무리(§4) → 푸시.
2. **Phase 1 마무리**: 키트 CI 녹색 확인(main 푸시 시 자동 실행) → **GHCR 공개 게시는 서아 님 확인 후** `v0.21.2-k1` 태그 푸시 → GitHub 패키지 설정에서 visibility **Public** 수동 전환.
3. 키트 반영: `seed/bundled-keep.txt`에서 `media/youtube-content` 제거 + 시드 훅에서 `hermes skills install Wendy-Nam/hermes-skills-kr/youtube-summary --yes`(부팅 시 네트워크 실패해도 계속) → boot-test 재실행.
4. **Phase 2 `/setup` 플러그인**(Task 5~9): `.env` 저장소·키 검증기·팩 정의·주인 등록+초대링크+`PATCH /applications/@me`(인텐트·권한 자동)·모달 UI. **명령은 반드시 길드 전용 등록**(S2 교훈).
5. 스파이크 잔여: S11(볼트 2개·채널별 프로필 — **테스트용 LLM 선택 대기**), S12(CLI OAuth 중계 — 서아 님 클릭 필요), S6(Composio 키), S9(Hostinger 화면).
6. 이후: Phase 4 Syncthing·대화 가져오기, Phase 5 compose(freellmapi는 별도 심화팩 compose), Phase 6 리허설·매뉴얼 v2, Phase 7 `/doctor`·업데이트 알림·백업.
7. 보류: 카톡·팀즈 스킬(서아 님 지시로 키트 이후), 텔레그램 `/setup`(v1.1, 미니앱 폼 안), 아침 브리핑·이메일 다이제스트(만족도 낮음), CLI 워커(2주 실측 후).

## 6. 함정 (이번에 실제로 밟은 것)
- 빌드 중 Hermes import가 `/opt/data`에 root 파일을 남기면 **모든 새 볼륨의 부팅이 깨짐** → 빌드 검증은 임시 HERMES_HOME에서, 가드로 차단 중.
- 공식 cont-init(01)이 config.yaml·.env·SOUL.md를 먼저 만듦 → "없을 때만 복사"는 영원히 no-op.
- cont-init 훅 shebang에 `with-contenv` 금지(execlineb 실패 전력). env는 `/run/s6/container_environment/` 파일로.
- 플러그인이 전역 트리에 추가한 슬래시 명령은 게이트웨이 safe-sync 스냅샷에서 누락(경합) → 길드 전용 + 자체 `tree.sync(guild=)`.
- skills-guard: 문서에 비밀파일 경로 문자열을 **글자 그대로** 쓰기만 해도 critical → `--force`로도 설치 불가. 테스트로 막아 둠.
- `hermes skills install <이름>`은 **남의 동명 스킬**을 잡음 → 항상 `owner/repo/skill` 전체 이름.
- rtk 절감 통계는 터미널 HOME(`/opt/data/home`)의 DB에 있음(`HOME=/opt/data/home rtk gain`). 운영 rtk는 9/20 이후 정상(500건·72%).
- freellmapi DB는 캐시 토큰을 저장하지 않음 → 캐시 지표는 Hermes `state.db`의 `session_model_usage`에서. 운영 캐시 적중 하락(9/24~)은 트래픽이 deepseek→kilo 무료 모델로 옮겨 간 탓(압축 무관).

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
