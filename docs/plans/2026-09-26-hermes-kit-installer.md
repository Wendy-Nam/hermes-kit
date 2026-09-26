# Hermes Kit 인스톨러 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비개발자 수강생이 "VPS 결제 → compose 붙여넣기 → 디스코드 `/setup`" 만으로 서아 님 서버와 같은 품질의 Hermes를 20분 안에, 매번 같은 결과로 갖게 한다.

**Architecture:** 설치 후 LLM이 컨테이너를 고치던 방식을 버리고, 변하지 않는 것은 **공개 파생 이미지**(Hermes v0.21.2 + 보이스 패치 + rtk + 공개 플러그인 + 기본 config)에 굽는다. 사람마다 다른 것(키)은 디스코드 `/setup` 모달로 받아 LLM을 거치지 않고 검증·저장한다. 서아 님 노하우(큐레이션 스킬·SOUL·freellmapi 체인·구직 키트)는 **비공개 팩 레포**에 두고 첫 부팅 때 기수별 토큰으로 받아온다.

**Tech Stack:** Docker / s6-overlay cont-init(Hermes 이미지 기본), GitHub Actions + GHCR, Python 3.13 stdlib(플러그인·검증기, 신규 의존성 없음), discord.py(Hermes에 이미 포함), freellmapi 선언형 config(JSON), Syncthing 사이드카.

**Spec:** 별도 스펙 문서 없음 — 이 문서 §0(결정과 근거)이 스펙이다. 근거는 2026-09-26 서아 님 서버(`ssh hermes`) 실측과 upstream 소스 확인.

## Global Constraints

- Hermes 베이스 버전 고정: **v0.21.2 (upstream 2026.9.11)**. 보이스 패치 앵커가 이 버전 기준이다.
- rtk 버전 고정: **rtk-ai/rtk v0.50.0**, 자산 `rtk-x86_64-unknown-linux-musl.tar.gz`, `checksums.txt`로 검증. (서버는 0.43.0 — 0.50.0에서 `rtk rewrite` 동작을 S5에서 확인, 실패 시 0.43.0 고정)
- 키·토큰·`auth.json`·`.env`·개인 플러그인(`hermes-self`, `turn-router`, `session-sticky`, `hermes-snow-search`, `ux-improvements`)은 **공개 이미지에 절대 들어가지 않는다**. CI가 검사한다.
- 키는 **LLM 컨텍스트를 거치지 않는다**: 모달 → 플러그인 → 검증 → `/opt/data/.env`(chmod 600). 채팅 메시지로 받지 않는다.
- `auto:unfiltered` 풀과 allowlist의 `"unfiltered"`는 배포판 어디에도 없다.
- 개인정보 풀(private) allowlist: `groq, cerebras, mistral`. 단 Mistral은 무료 플랜 기본값이 학습 사용이라, `/setup`에서 Mistral 키를 넣을 때 **"Admin Console → Privacy에서 학습 끄기 완료" 체크가 필수**(체크 없으면 키 저장 안 함). (§7 D4 — `xkiro`·`aion` 제외, `cohere`는 freellmapi ToS 리뷰 "❌ 개인용 금지", `requesty`·`opencode`는 미검토라 제외, `cloudflare`는 "⚠️ 모호"라 제외). 학습 미사용 여부는 S10에서 재확인.
- LLM 스타터 = **ChatGPT 구독(openai-codex OAuth) + OpenCode Go(기본) 또는 Command Code GOAT**. 고급 = CLI 워커 팩 + freellmapi 팩. Claude 구독은 스타터에서 안내하지 않음 (§7 D3).
- 볼트는 `work`, `personal` 두 개. 커뮤니티 플러그인은 `dataview`(0.5.70), `obsidian-tasks-plugin`(8.4.0), `tasknotes`(4.13.5) 버전 고정·MIT.
- 신규 Python 의존성 추가 금지. HTTP는 `urllib.request`, YAML은 `hermes config set` CLI 사용.
- 데이터 경로는 `/opt/data`(= `HERMES_HOME`) 고정.
- 시드는 **없는 파일만 복사**. 사용자가 고친 파일은 덮어쓰지 않는다. kit 소유 경로(`plugins/kit-*`, `skills/kit/`)만 버전 변경 시 교체.

---

## 0. 결정과 근거

| # | 결정 | 근거 (실측) |
|---|---|---|
| 1 | 설치 후 LLM 셋업 폐기 → 파생 이미지 | `vps/scripts/09-omh-rtk.sh`가 존재하지 않는 레포(`runelive-ai/rtk`)·경로(`.local/bin`)·config 키(`rtk: enabled`)를 사용. 서버 실제는 `/opt/data/bin/rtk` 0.43.0 + `plugins.enabled`. LLM 생성 스크립트가 틀린 채 배포됐음 |
| 2 | 보이스 패치는 이미지에 | 패치 대상 `/opt/hermes`는 이미지 레이어 → 컨테이너 재생성 시 소실(패치 README 명시) |
| 3 | 키 입력은 디스코드 모달 | `PluginContext.register_platform_handler("discord", factory)`가 `factory(native: commands.Bot, adapter)` 제공(`hermes_cli/plugins.py:831`) → discord.py `Modal` 직접 등록 가능. 별도 웹페이지를 인터넷에 열 필요 없음 |
| 4 | 첫 주인 = 디스코드 서버 소유자 자동 승인 | 미등록 DM은 페어링 코드 발급 후 주인이 CLI로 `hermes pairing approve` 해야 함(`gateway/run_inbound.py:78`). `PairingStore(profile=None)`의 `generate_code`/`approve_code`로 플러그인이 대신 수행 |
| 5 | 팩 단위 키 | Groq=한국어 STT 정확도(`stt.provider: groq, language: ko`), Webshare=원티드 등 클라우드 IP 차단 우회. 둘 다 필수지만 팩 사용자에게만 |
| 6 | freellmapi는 선언형 config | freellmapi `FREEAPI_CONFIG_PATH` JSON(keys/models/fallback/routing, 멱등, 부팅마다 적용). sqlite 직접 패치 불필요 |
| 7 | 공개 이미지 + 비공개 팩 분리 | Hermes MIT, rtk Apache-2.0, freellmapi MIT → 재배포 가능. 노하우는 팩 레포에 |
| 8 | 기본 스킬 정리는 네이티브 명령 | `hermes skills opt-out --remove -y`(수정 안 한 번들 스킬만 삭제) |
| 9 | 배포는 compose 붙여넣기, 원클릭은 후순위 | Hostinger Docker Manager가 compose URL/내용 배포 지원, 공개 API `create new project`도 있음(실험 기능) |

---

## 1. 수강생 경험 (목표)

```
[사람] Hostinger VPS 결제 (Docker OS 템플릿)
[사람] 디스코드 서버 만들기 + Developer Portal에서 New Application → Reset Token 복사 (인텐트·권한은 키트가 API로 설정)
[사람] Hostinger Docker Manager → Compose 붙여넣기 → 환경변수 2칸
        DISCORD_BOT_TOKEN=...   KIT_ACCESS_CODE=... (강사가 준 기수 코드)
[자동] 이미지 pull → 첫 부팅 시드 → 팩 다운로드 → 게이트웨이 기동
[자동] 로그에 봇 초대 링크 출력 → Hostinger 로그 화면에서 클릭 (권한 계산 완료된 링크)
[사람] 디스코드에서 /setup
        ① 서버 소유자 자동 주인 등록 ② 결과 채널 드롭다운 ③ 팩 체크
        ④ 팩별 모달에 키 붙여넣기 → 즉시 검증 ✅ ⑤ LLM 구독 로그인 링크
[자동] 재시작 → 봇이 "준비 끝" 인사
```

기존 매뉴얼 대비 삭제: Claude 데스크탑·Git·작업폴더(1-1~1-3), 레포 수락(1-4), SSH 키(2-2), 개발자모드 ID 복사(2-5), 모델/웹검색 설정(3-1).

---

## 2. 파일 구조

### 레포 A — `Wendy-Nam/hermes-kit` (공개, 이미지 소스)

```
hermes-kit/
├─ Dockerfile                          # 베이스 고정 + rtk + 패치 + 플러그인 + 시드
├─ docker-compose.yml                  # 수강생이 붙여넣는 파일 (hermes + freellmapi + syncthing)
├─ versions.env                        # HERMES_BASE_IMAGE, RTK_VERSION, KIT_VERSION 한 곳에
├─ patches/voice/                      # hermes-voice-patches 그대로 (apply.sh, check.py, patches/*)
├─ plugins/
│  └─ kit-setup/                       # 신규: /setup, 팩, 키 검증, 주인 등록
│     ├─ plugin.yaml
│     ├─ __init__.py                   # register(ctx): discord 핸들러 등록만
│     ├─ packs.py                      # 팩 정의 로드 (packs.json)
│     ├─ packs.json                    # 팩/키/검증기/후처리 선언
│     ├─ validators.py                 # 키별 검증 (urllib)
│     ├─ env_store.py                  # .env 원자적 갱신
│     ├─ owner.py                      # 서버 소유자 → 페어링 승인
│     ├─ discord_ui.py                 # Modal/Select/Button
│     └─ tests/
│        ├─ test_env_store.py
│        ├─ test_validators.py
│        └─ test_packs.py
├─ seed/                               # 첫 부팅 시 /opt/data로 (없는 것만)
│  ├─ config-overlay.yaml              # 공식 기본 config 위에 병합할 키트 설정만
│  ├─ SOUL.md                          # 범용 기본 SOUL (개인 페르소나 없음)
│  ├─ vaults/{work,personal}/.obsidian/  # community-plugins.json + plugins/{dataview,obsidian-tasks-plugin,tasknotes}/ (빌드 시 다운로드)
│  └─ bundled-keep.txt                 # 남길 Hermes 번들 스킬 경로 목록
├─ rootfs/etc/cont-init.d/10-kit-seed  # 시드 + opt-out + 팩 fetch
├─ freellmapi/freellmapi.config.json   # 체인 기본(unfiltered 없음), 키는 비움
├─ scripts/secret-scan.sh              # CI: 금지 파일/패턴 검사
└─ .github/workflows/build.yml         # 빌드 → 스모크 → 스캔 → GHCR push
```

### 레포 B — `Wendy-Nam/hermes-kit-packs` (비공개)

```
hermes-kit-packs/
├─ manifest.json                       # 팩 버전, 포함 스킬 목록
├─ skills/kit/                         # 큐레이션 스킬 (youtube-content Gemini판 등)
├─ soul/                               # 서아 님 튜닝 SOUL 조각 (선택 적용)
├─ freellmapi/chains.json              # 서아 님 체인 (unfiltered 제거판)
└─ packs/job-hunt -> (hermes-job-hunt-for-korean install.sh 호출)
```

---

## Phase 0 — 스파이크 (가정 검증, 코드 작성 전)

각 스파이크는 **통과 기준**과 **실패 시 대안**이 있다. 결과를 이 문서 하단 "스파이크 결과"에 기록한 뒤 Phase 1 시작.

- [ ] **S1. 베이스 이미지 식별.** Hostinger 호스트 셸(hPanel → Terminal, 컨테이너 밖)에서:
  ```bash
  docker inspect hermes-agent-ywj7-hermes-agent-1 --format '{{.Config.Image}} {{.Image}}'
  docker compose -p hermes-agent-ywj7 config 2>/dev/null | head -60
  ```
  통과: 이미지 이름·다이제스트 확보 → `versions.env`의 `HERMES_BASE_IMAGE`. 대안: upstream `NousResearch/hermes-agent` 태그 `v2026.9.11`로 직접 빌드.

- [ ] **S2. 플러그인 discord 핸들러로 앱 커맨드가 동기화되는가.** 테스트 봇·테스트 서버에서, 최소 플러그인:
  ```python
  def register(ctx):
      def factory(bot, adapter):
          import discord
          @bot.tree.command(name="kitping", description="kit spike")
          async def kitping(interaction: discord.Interaction):
              await interaction.response.send_modal(_M())
          class _M(discord.ui.Modal, title="spike"):
              v = discord.ui.TextInput(label="value")
              async def on_submit(self, i): await i.response.send_message(f"len={len(self.v.value)}", ephemeral=True)
      ctx.register_platform_handler("discord", factory)
  ```
  통과: `/kitping` 노출 → 모달 → `len=N` 응답, 게이트웨이 로그에 LLM 호출 없음. 대안: `ctx.register_command("setup", handler, args_hint="<pack> <key>")`(텍스트 인자, ephemeral 여부 확인)로 후퇴.

- [ ] **S3. 주인 자동 승인.** 컨테이너 안에서:
  ```bash
  python3 -c "from gateway.pairing import PairingStore as P; s=P(); c=s.generate_code('discord','<테스트유저ID>','t'); print(c, s.approve_code('discord', c)); print(s.list_approved('discord'))"
  ```
  통과: 승인 목록에 등장 + 그 유저 DM에 봇이 응답. 대안: `DISCORD_ALLOWED_USERS`를 `.env`에 쓰고 재시작.

- [ ] **S4b. cont-init 환경.** `/run/s6/container_environment/`에 compose `environment` 값이 파일로 존재하는지, `#!/bin/sh` 훅이 `01-hermes-setup` 다음에 실행되는지(`ls /etc/cont-init.d` 정렬 순서) 확인.

- [ ] **S4. 게이트웨이 재시작 방법.** `kill -TERM $(pgrep -f "hermes gateway run")` 후 s6가 10초 내 재기동하는지, 새 `.env` 값을 읽는지. 대안: `hermes gateway restart`.

- [ ] **S5. rtk 0.50.0 호환.** `rtk rewrite "git status"` 종료코드·출력이 플러그인 `__init__.py`의 exit code 표와 일치. 대안: 0.43.0 고정.

- [ ] **S6. Composio 연결 흐름.** `x-consumer-api-key`만 넣은 상태에서 Gmail 도구 첫 호출 시 MCP가 OAuth 링크를 돌려주는지. 통과: 키 1개 + 채팅 내 링크 클릭으로 완료 → 별도 링크 생성 코드 불필요. 대안: Composio REST로 connect link 생성(문서 확인 후 validators에 추가).

- [ ] **S7. freellmapi 체인(프로필) 선언형 지원.** freellmapi 문서/소스에서 `auto:<profile>` 체인을 JSON config로 만들 수 있는지(`fallback` 필드 범위). 대안: 부팅 후 REST API로 생성하는 1회성 스크립트 — 서버 `patch-freellmapi-pools.py` 로직을 이식.

- [ ] **S8. 라이선스.** `rtk-hermes`(rtk-rewrite 플러그인 원본) 라이선스, `web-crawl4ai` 플러그인 출처·라이선스, `omh` 휠 라이선스. 재배포 불가면 설치 명령(`hermes plugins install <url>`)만 이미지에 넣는다.

- [ ] **S10. private 풀 학습 정책.** Groq·Cerebras·Mistral 각 약관에서 "무료 티어 입력을 학습에 쓰는지"를 확인하고 링크를 기록. 하나라도 학습에 쓰면 private에서 제외.

- [ ] **S11. 프로필별 볼트.** 서아 님 서버처럼 `gateway.multiplex_profiles: true` + `profile_routes`(채널 → 프로필)를 쓸 때, 프로필별 `config.yaml`의 `OBSIDIAN_VAULT_PATH`가 각각 적용되는지 테스트 서버에서 확인. 대안: 단일 프로필 + obsidian 스킬에 "업무 채널 = work 볼트" 규칙.

- [ ] **S12. CLI 로그인 헤드리스 가능 여부 + 보조 모델 키 검증.** 컨테이너 안(TTY 없음)에서 각 CLI의 로그인이 "URL 출력 → 코드 입력" 흐름으로 끝나는지:
  `codex login --device-auth`, `claude setup-token`, `opencode auth login`, `cline auth`. Antigravity CLI는 서버에 설치돼 있지 않음 → 존재·리눅스 헤드리스 지원부터 확인, 안 되면 제외.
  그리고 `opencode_go`·`commandcode` 검증 URL이 틀린 키에 401을 주는지.
  통과: URL을 디스코드로 중계하고 코드를 모달로 받는 방식이 가능. 대안: 해당 CLI는 "강사 원격 지원 시 설치" 항목으로.

- [ ] **S13. 메신저 헤드리스 로그인.** 테스트 카톡 계정으로 컨테이너 안에서 `agent-kakaotalk auth login --email … --password-file …` → `confirm_on_phone` JSON이 나오고 폰 확인 후 완료되는지, 태블릿 칸 로그인 후 PC 카톡이 유지되는지. `agent-teams` 인증 방식(디바이스 코드/토큰 추출) 확인.

- [ ] **S9. Hostinger 환경변수 입력.** Docker Manager에서 compose를 붙여넣을 때 `${VAR}`가 입력칸으로 뜨는지, 컨테이너 로그를 수강생이 볼 수 있는지(초대 링크 출력 위치).

---

## Phase 1 — 공개 이미지

### Task 1: 이미지 빌드 + 보이스 패치 + rtk

**Files:**
- Create: `Dockerfile`, `versions.env`, `patches/voice/**`(zip 내용 그대로)
- Test: CI 스모크(Task 4)

**Interfaces:**
- Produces: 이미지 안 `/usr/local/bin/rtk`, 패치된 `/opt/hermes`, `/opt/kit/seed`, `/opt/kit/plugins`

- [ ] **Step 1: versions.env**
```sh
HERMES_BASE_IMAGE=docker.io/nousresearch/hermes-agent:v2026.9.11@sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1
RTK_VERSION=0.50.0
KIT_VERSION=1
```

- [ ] **Step 2: Dockerfile**
```dockerfile
ARG HERMES_BASE_IMAGE
FROM ${HERMES_BASE_IMAGE}
ARG RTK_VERSION
USER root

# rtk: 체크섬 검증 후 설치 (plugins/rtk-rewrite가 PATH에서 찾는다)
RUN set -eux; cd /tmp; \
    base="https://github.com/rtk-ai/rtk/releases/download/v${RTK_VERSION}"; \
    curl -fsSLO "$base/rtk-x86_64-unknown-linux-musl.tar.gz"; \
    curl -fsSLO "$base/checksums.txt"; \
    grep " rtk-x86_64-unknown-linux-musl.tar.gz$" checksums.txt | sha256sum -c -; \
    tar xzf rtk-x86_64-unknown-linux-musl.tar.gz; \
    install -m 0755 "$(find . -maxdepth 2 -type f -name rtk | head -1)" /usr/local/bin/rtk; \
    rm -rf /tmp/*; rtk --version

# 보이스 패치: 앵커 불일치면 여기서 빌드 실패 (= 베이스 버전 불일치 신호)
COPY patches/voice /opt/kit/voice-patches
RUN sh /opt/kit/voice-patches/apply.sh --root /opt/hermes

COPY plugins /opt/kit/plugins
COPY seed /opt/kit/seed
COPY freellmapi /opt/kit/freellmapi
COPY rootfs/etc/cont-init.d/10-kit-seed /etc/cont-init.d/10-kit-seed
RUN chmod 0755 /etc/cont-init.d/10-kit-seed
ARG KIT_VERSION
RUN echo "${KIT_VERSION}" > /opt/kit/VERSION
```
(`USER`는 베이스 기본값으로 되돌릴 필요 없음 — s6 `/init`이 root로 시작해야 한다, stage2-hook 주석 참고)

- [ ] **Step 3: 로컬 빌드**
Run: `set -a; . ./versions.env; set +a; docker build --build-arg HERMES_BASE_IMAGE --build-arg RTK_VERSION --build-arg KIT_VERSION -t hermes-kit:dev .`
Expected: `rtk 0.50.0` 출력, `apply.sh` 끝에 check.py 통과, 빌드 성공.

- [ ] **Step 4: 패치 동작 확인**
Run: `docker run --rm --entrypoint python3 hermes-kit:dev /opt/kit/voice-patches/verify.py --root /opt/hermes`
Expected: 전 항목 PASS.

- [ ] **Step 5: Commit** — `git add Dockerfile versions.env patches && git commit -m "feat: base image with voice patches and rtk"`

### Task 1b: 토큰·안정성 패치 선별 이식

서아 님 `/opt/data/patches/`에서 **배포판에 필요한 것만** 이미지 빌드 단계로 옮긴다(서버는 부팅마다 재적용하는 구조, 키트는 빌드 1회).

| 포함 | 이유 |
|---|---|
| `patch-skills-compact.py` | `skills.compact_categories` 설정을 **처음 지원하게 만드는** 패치 — 없으면 seed config의 해당 키가 무효 |
| `patch-skills-view-cap.py` | SKILL.md 본문 6,000자 상한 |
| `patch-budget-caps.py` | 도구 결과 8k, 턴 24k 예산 |
| `patch-cron-max-turns.py` | 크론 잡별 `max_turns` |
| `compression-fix-20260919/` | 압축 루프 수정 (해시 검증 포함) |
| `patch-kanban-interval.py` | 칸반 워처 5s → 30s (CPU 바쁜 대기 방지) |
| `patch-hook-overlap-skip.py`, `patch-lifecycle-guard-sqlite.py` | 훅 중복·sqlite 잠금 안정화 |

| 제외 | 이유 |
|---|---|
| `patch-freellmapi-*`, `patch-aux-route-attribution.py`, `patch-aux-configured-routes-only-v0212.py` | freellmapi 심화팩 전제 → 심화팩에서 판단 |
| `patch-omh-*`, `patch-snow-search-*`, `patch-evo-dspy3.py`, `patch-embed-role.py`, `patch-background-review-pilot.py` | 개인 플러그인·실험 기능 |
| `patch-voice-*`, `patch-tts-provider-none-*`, `patch-elevenlabs-*`, `patch-discord-call-slash.py` | 보이스 패치 번들(Task 1)과 중복 |

- [ ] **Step 1:** 포함 목록을 `patches/core/`로 복사, Dockerfile에서 `for f in patches/core/patch-*.py; do python $f; done && python patches/core/compression-fix-20260919/apply.py && python patches/core/check.py`.
- [ ] **Step 2:** 각 패치를 **깨끗한 베이스 이미지**에 적용 → 출력이 "already patched"면 업스트림이 이미 고친 것 → 목록에서 삭제. 앵커 불일치면 빌드 실패.
- [ ] **Step 3: 효과 측정** — 같은 seed로 패치 전/후 이미지에서 `.skills_prompt_snapshot.json` 크기와 첫 턴 입력 토큰 수 기록.
- [ ] **Step 4: Commit**

### Task 2: 배포용 기본 config + SOUL

**Files:**
- Create: `seed/config.yaml`, `seed/SOUL.md`

서버 `config.yaml`에서 **가져오는 것 / 버리는 것**:

| 가져옴 | 버림 |
|---|---|
| `agent.reasoning_effort: low`, `max_turns: 20` | `OBSIDIAN_VAULT_PATH: .../ehr-wiki` (→ default 프로필 `/opt/data/vaults/personal`, work 프로필 `/opt/data/vaults/work`) |
| `compression` 블록 전체 | `discord.channel_prompts` (개인 채널·롤플레이) |
| `stt: {enabled: true, provider: groq, language: ko}` — 음성 팩이 켤 때만 enabled | `gateway.profile_routes`, `multiplex_profiles` |
| `tts.provider: none`, `voice.auto_tts: false` | `mcp_servers.life-os`, `public_data_lens` |
| `web.search_backend: ddgs`, `web.extract_backend` | `moa` (openai-codex 전제) |
| `tool_budget` 블록 | `image_gen` (openai-codex 전제 — LLM 팩 후처리에서 설정) |
| `file_read_max_chars: 16000`, `timezone: Asia/Seoul` | `fallback_providers`의 nous/freellmapi 항목 (freellmapi 팩에서 추가) |
| `skills.compact_categories`, `creation_nudge_interval: 0` | `known_*_toolsets` (런타임 캐시) |
| `plugins.enabled: [web-crawl4ai, kit-setup]` (rtk-rewrite는 `rtk init`이 추가) | 개인 플러그인 전부 |
| `display.platforms.discord` 블록 | `command_allowlist` (보안상 기본값 유지) |
| `auxiliary.*` → provider `gemini`, model `gemini-3.6-flash` (Gemini 키 1개로 동작) | `auxiliary.*`의 freellmapi 라우팅 (freellmapi 팩이 덮어씀) |

- [ ] **Step 1:** 위 표대로 `seed/config-overlay.yaml` 작성 — **바꿀 키만** 담는다(공식 기본 config 2,135줄을 복제하지 않음). `/opt/kit/bin/merge_yaml.py`(딕셔너리는 재귀 병합, 리스트·스칼라는 교체) + 단위 테스트 1개. `_config_version`은 베이스 이미지의 `hermes config check`가 요구하는 값으로.
- [ ] **Step 2: 검증** — `docker run --rm -v $PWD/seed/config.yaml:/opt/data/config.yaml --entrypoint hermes hermes-kit:dev config check` → 오류 0.
- [ ] **Step 3:** `seed/SOUL.md` — 서버 SOUL에서 개인 페르소나("에르", SAN 등) 제거한 범용 비서 톤. 한국어 답변, 디스코드 가독성 규칙(굵은 제목→2~3문장→빈 줄) 유지.
- [ ] **Step 4: Commit**

### Task 3: 첫 부팅 시드 훅

**Files:**
- Create: `rootfs/etc/cont-init.d/10-kit-seed`

**Interfaces:**
- Consumes: `/opt/kit/{seed,plugins,VERSION}`, env `KIT_ACCESS_CODE`, `DISCORD_BOT_TOKEN`
- Produces: `/opt/data/.kit-version`, `/opt/data/plugins/{rtk-rewrite,kit-setup}`, `/opt/data/skills/kit/`, `.env`의 `DISCORD_BOT_TOKEN`

- [ ] **Step 1: 스크립트**
```sh
#!/bin/sh
# ponytail: 없는 것만 복사. kit 소유 경로만 버전 바뀌면 교체.
# with-contenv shebang 금지: 서아 님 서버 019-self-budget이 이 이미지에서 execlineb로 해석돼
# 부팅마다 실패한 기록(2026-09-20). POSIX sh + s6 환경 파일로 읽는다.
set -eu
envf() { cat "/run/s6/container_environment/$1" 2>/dev/null || true; }
DISCORD_BOT_TOKEN="$(envf DISCORD_BOT_TOKEN)"; KIT_ACCESS_CODE="$(envf KIT_ACCESS_CODE)"
export DISCORD_BOT_TOKEN KIT_ACCESS_CODE
D="${HERMES_HOME:-/opt/data}"; K=/opt/kit
as_h() { s6-setuidgid hermes "$@"; }
new="$(cat $K/VERSION)"; old="$(cat $D/.kit-version 2>/dev/null || echo none)"

# 1) config: Hermes 공식 훅(01-hermes-setup)이 기본 config.yaml(2,135줄)을 먼저 만든다(S2 스파이크 실측)
#    → "없을 때만 복사"는 절대 실행되지 않음. 첫 키트 부팅에만 seed/config-overlay.yaml을 깊은 병합.
if [ "$old" = none ]; then
  as_h /opt/hermes/.venv/bin/python /opt/kit/bin/merge_yaml.py "$D/config.yaml" "$K/seed/config-overlay.yaml"
  as_h cp "$K/seed/SOUL.md" "$D/SOUL.md"   # 공식 훅의 기본 SOUL(668B)을 키트 SOUL로 교체
fi
# rtk: rtk 저장소의 공식 Hermes 플러그인 설치 + plugins.enabled 등록 (HERMES_HOME 존중, S5 실측)
as_h rtk init --agent hermes >/dev/null
for v in work personal; do [ -e "$D/vaults/$v/.obsidian" ] || as_h cp -r "$K/seed/vaults/$v/." "$D/vaults/$v/"; done

# 2) kit 소유 경로: 버전 변경 시 교체
if [ "$new" != "$old" ]; then
  for p in "$K"/plugins/*; do
    n="$(basename "$p")"; rm -rf "$D/plugins/$n"; as_h cp -r "$p" "$D/plugins/$n"
  done
  # 번들 스킬: 시딩을 끄고(opt-out 마커), keep-list에 없는 번들 스킬만 삭제.
  # (opt-out --remove는 hermes-agent 같은 유용한 번들까지 지우므로 쓰지 않는다)
  if [ "$old" = none ]; then
    as_h hermes skills opt-out -y || true
    ( cd /opt/hermes/skills && find . -name SKILL.md | sed 's|/SKILL.md||;s|^\./||' ) | while read -r s; do
      grep -qx "$s" "$K/seed/bundled-keep.txt" || rm -rf "$D/skills/$s"
    done
  fi
fi

# 3) 봇 토큰: env → .env (게이트웨이는 .env를 읽는다)
if [ -n "${DISCORD_BOT_TOKEN:-}" ] && ! grep -q '^DISCORD_BOT_TOKEN=' "$D/.env" 2>/dev/null; then
  as_h sh -c "umask 077; printf 'DISCORD_BOT_TOKEN=%s\n' \"\$DISCORD_BOT_TOKEN\" >> '$D/.env'"
fi

# 4) 비공개 팩 (코드 있을 때만, 실패해도 부팅은 계속)
if [ -n "${KIT_ACCESS_CODE:-}" ] && [ "$new" != "$old" ]; then
  as_h python3 /opt/kit/plugins/kit-setup/fetch_packs.py "$D" || echo "[kit] 팩 다운로드 실패 — /setup 에서 재시도"
fi

# 5) 초대 링크 (Hostinger 로그 화면에 보이게)
as_h python3 /opt/kit/plugins/kit-setup/invite.py || true

as_h sh -c "echo '$new' > '$D/.kit-version'"
```
- [ ] **Step 2: 멱등 테스트**
```bash
# cont-init는 /init 경유 기동에서만 돈다 → 실제 기동 후 20초 뒤 정지 (더미 토큰이라 게이트웨이 로그인은 실패해도 됨)
boot() { docker run -d --name kitboot -e DISCORD_BOT_TOKEN=dummy -v kitdata:/opt/data hermes-kit:dev gateway run >/dev/null; sleep 20; docker logs kitboot 2>&1 | grep '\[kit\]'; docker rm -f kitboot >/dev/null; }
peek() { docker run --rm -v kitdata:/opt/data --entrypoint sh hermes-kit:dev -c 'cd /opt/data && ls -d config.yaml SOUL.md plugins/* .kit-version; grep -c DISCORD_BOT_TOKEN .env'; }
docker volume create kitdata
boot; peek > /tmp/p1
boot; peek > /tmp/p2
diff /tmp/p1 /tmp/p2 && tail -1 /tmp/p2
```
Expected: diff 없음, 마지막 줄 `1` (토큰 중복 없음).
- [ ] **Step 3: 사용자 수정 보존 테스트** — config.yaml에 `# user-edit` 추가 → 재부팅 → 줄이 남아 있음.
- [ ] **Step 4: Commit**

### Task 4: CI — 빌드·스모크·비밀 스캔·GHCR

**Files:**
- Create: `scripts/secret-scan.sh`, `.github/workflows/build.yml`

- [ ] **Step 1: secret-scan.sh**
```sh
#!/bin/sh
# 공개 이미지에 들어가면 안 되는 것. 하나라도 있으면 실패.
set -eu
IMG="$1"; bad=0
list="$(docker run --rm --entrypoint sh "$IMG" -c 'find /opt/kit /etc/cont-init.d -type f')"
echo "$list" | grep -E '(^|/)(\.env|auth\.json|.*\.db|SOUL\.md\.bak.*)$' && bad=1
for p in hermes-self turn-router session-sticky hermes-snow-search ux-improvements unfiltered ehr-wiki; do
  docker run --rm --entrypoint sh "$IMG" -c "grep -rIl '$p' /opt/kit 2>/dev/null" && { echo "금지 문자열: $p"; bad=1; }
done
docker run --rm --entrypoint sh "$IMG" -c "grep -rIEl '(sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|[MN][A-Za-z0-9]{23}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27})' /opt/kit" && bad=1
exit $bad
```
- [ ] **Step 2: 스캔이 실제로 잡는지** — `seed/`에 `AIza` + 35자 더미를 넣고 빌드 → 스캔 exit 1 확인 → 더미 삭제.
- [ ] **Step 3: build.yml** — `on: push tags v*` + `workflow_dispatch`; 단계: `docker build`(versions.env) → Task 1 Step 4 verify → Task 3 Step 2 멱등 테스트 → `plugins/kit-setup/tests` 실행(`python3 -m unittest`) → `secret-scan.sh` → `ghcr.io/wendy-nam/hermes-kit:0.21.2-k${KIT_VERSION}` push. `permissions: packages: write`.
- [ ] **Step 4:** GHCR 패키지 visibility를 **public**으로 설정 (결정 7).
- [ ] **Step 5: Commit + 태그** `v0.21.2-k1`

---

## Phase 2 — `kit-setup` 플러그인

### Task 5: `.env` 저장소

**Files:** Create `plugins/kit-setup/env_store.py`, `tests/test_env_store.py`

**Interfaces:** Produces `set_env(path: Path, updates: dict[str, str]) -> None`, `get_env(path: Path) -> dict[str, str]`

- [ ] **Step 1: 실패 테스트**
```python
import os, stat, tempfile, unittest
from pathlib import Path
from env_store import set_env, get_env

class T(unittest.TestCase):
    def test_update_preserves_others_and_perms(self):
        d = Path(tempfile.mkdtemp()); p = d / ".env"
        p.write_text("# c\nA=1\nB=2\n")
        set_env(p, {"B": "3", "C": "x=y"})
        self.assertEqual(p.read_text(), "# c\nA=1\nB=3\nC=x=y\n")
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(get_env(p), {"A": "1", "B": "3", "C": "x=y"})

    def test_rejects_newline_injection(self):
        p = Path(tempfile.mkdtemp()) / ".env"
        with self.assertRaises(ValueError):
            set_env(p, {"A": "ok\nEVIL=1"})

if __name__ == "__main__":
    unittest.main()
```
- [ ] **Step 2:** `cd plugins/kit-setup && python3 -m unittest tests.test_env_store -v` → FAIL (ImportError)
- [ ] **Step 3: 구현**
```python
import os, tempfile
from pathlib import Path

def get_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1); out[k.strip()] = v
    return out

def set_env(path: Path, updates: dict[str, str]) -> None:
    for k, v in updates.items():
        if "\n" in v or "\r" in v or "\n" in k or "=" in k:
            raise ValueError(f"invalid env entry: {k}")
    lines = path.read_text().splitlines() if path.exists() else []
    todo = dict(updates)
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in todo:
            lines[i] = f"{k}={todo.pop(k)}"
    lines += [f"{k}={v}" for k, v in todo.items()]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # 원자적 교체: 중간에 죽어도 .env가 반쪽이 되지 않음
```
- [ ] **Step 4:** 테스트 PASS
- [ ] **Step 5: Commit**

### Task 6: 키 검증기

**Files:** Create `plugins/kit-setup/validators.py`, `tests/test_validators.py`

**Interfaces:** Produces `VALIDATORS: dict[str, Callable[[str], Result]]`, `Result = tuple[bool, str]` (성공 여부, 사람이 읽을 한 줄). 키 이름: `discord, gemini, groq, webshare, apify, composio`.

- [ ] **Step 1: 실패 테스트** (네트워크 없이 — `_get`을 가짜로 교체)
```python
import unittest, validators as v

class T(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fake(url, headers, proxy=None):
            self.calls.append((url, headers, proxy))
            return self.status, self.body
        v._get = fake

    def test_groq_ok(self):
        self.status, self.body = 200, b'{"data":[{"id":"whisper-large-v3"}]}'
        ok, msg = v.VALIDATORS["groq"]("gsk_x")
        self.assertTrue(ok); self.assertIn("whisper", msg)
        self.assertEqual(self.calls[0][1]["Authorization"], "Bearer gsk_x")

    def test_gemini_key_not_in_url(self):
        self.status, self.body = 200, b'{"models":[]}'
        v.VALIDATORS["gemini"]("AIzaSECRET")
        self.assertNotIn("AIzaSECRET", self.calls[0][0])

    def test_bad_key(self):
        self.status, self.body = 401, b'{}'
        ok, msg = v.VALIDATORS["groq"]("bad")
        self.assertFalse(ok); self.assertIn("401", msg)

    def test_webshare_checks_target_through_proxy(self):
        seq = [(200, b'{"results":[{"proxy_address":"1.2.3.4","port":8080,"username":"u","password":"p"}]}'), (200, b"<html>")]
        v._get = lambda url, headers, proxy=None: (self.calls.append((url, headers, proxy)), seq.pop(0))[1]
        ok, _ = v.VALIDATORS["webshare"]("tok")
        self.assertTrue(ok)
        self.assertEqual(self.calls[1][2], "http://u:p@1.2.3.4:8080")
        self.assertIn("wanted.co.kr", self.calls[1][0])
```
- [ ] **Step 2:** FAIL 확인
- [ ] **Step 3: 구현**
```python
import json, urllib.request, urllib.error

def _get(url, headers, proxy=None):
    h = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    req = urllib.request.Request(url, headers={"User-Agent": "hermes-kit", **headers})
    try:
        with urllib.request.build_opener(*h).open(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception as e:  # 네트워크 오류도 사용자에게 한 줄로
        return 0, str(e).encode()

def _simple(url, header):
    def check(key):
        s, body = _get(url, header(key))
        return (True, _summary(body)) if s == 200 else (False, f"거부됨 (HTTP {s}) — 키를 다시 복사해 주세요")
    return check

def _summary(body):
    try:
        d = json.loads(body)
        items = d.get("data") or d.get("models") or []
        names = [m.get("id") or m.get("name", "") for m in items][:3]
        return "확인됨" + (f" ({', '.join(names)})" if names else "")
    except Exception:
        return "확인됨"

def _discord(tok):
    s, body = _get("https://discord.com/api/v10/users/@me", {"Authorization": f"Bot {tok}"})
    return (True, f"봇 이름: {json.loads(body).get('username')}") if s == 200 else (False, f"봇 토큰 거부 (HTTP {s})")

def _webshare(tok):
    s, body = _get("https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=1",
                   {"Authorization": f"Token {tok}"})
    if s != 200:
        return False, f"Webshare 키 거부 (HTTP {s})"
    p = json.loads(body)["results"][0]
    proxy = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}"
    s2, _ = _get("https://www.wanted.co.kr/", {}, proxy=proxy)
    return (True, "프록시로 원티드 접속 확인") if s2 == 200 else (False, f"키는 맞지만 원티드 접속 실패 (HTTP {s2})")

VALIDATORS = {
    "discord": _discord,
    "gemini": _simple("https://generativelanguage.googleapis.com/v1beta/models?pageSize=3",
                      lambda k: {"x-goog-api-key": k}),
    "groq": _simple("https://api.groq.com/openai/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "apify": _simple("https://api.apify.com/v2/users/me", lambda k: {"Authorization": f"Bearer {k}"}),
    "webshare": _webshare,
    "opencode_go": _simple("https://opencode.ai/zen/go/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "commandcode": _simple("https://api.commandcode.ai/provider/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    # composio: S6 결과로 엔드포인트 확정 후 추가
    # opencode_go·commandcode의 /models가 인증을 요구하는지 S12에서 확인 — 인증 없이 200이면 최소 chat 호출로 교체
}
```
- [ ] **Step 4:** PASS
- [ ] **Step 5: 실키 수동 확인** (서아 님 키로, 컨테이너 안에서 — 출력에 키 없음):
  `python3 -c "import validators as v,os; print(v.VALIDATORS['groq'](os.environ['GROQ_API_KEY']))"`
- [ ] **Step 6: Commit**

### Task 7: 팩 정의

**Files:** Create `plugins/kit-setup/packs.json`, `packs.py`, `tests/test_packs.py`

**Interfaces:** Produces `load_packs() -> list[Pack]`, `Pack(id, title, keys: list[KeySpec], config: dict[str, str], env: dict[str, str])`, `KeySpec(env, label, hint, validator, url)`

- [ ] **Step 1: packs.json**
```json
[
  {"id": "base", "title": "기본", "required": true,
   "keys": [{"env": "GEMINI_API_KEY", "label": "Gemini 키", "validator": "gemini",
             "url": "https://aistudio.google.com/apikey", "hint": "AIza로 시작"}],
   "config": {}},
  {"id": "sub-opencode-go", "title": "⚡ 보조 모델: OpenCode Go", "required_one_of": "sub",
   "keys": [{"env": "OPENCODE_GO_API_KEY", "label": "OpenCode Go 키", "validator": "opencode_go",
             "url": "https://opencode.ai/go", "hint": "구독 후 API 키"}],
   "config": {"delegation.provider": "opencode-go"}},
  {"id": "sub-commandcode", "title": "⚡ 보조 모델: Command Code GOAT", "required_one_of": "sub",
   "keys": [{"env": "COMMANDCODE_API_KEY", "label": "Command Code 키", "validator": "commandcode",
             "url": "https://commandcode.ai/pricing", "hint": "GOAT 플랜 API 키"}],
   "config": {"providers.commandcode.api": "https://api.commandcode.ai/provider/v1",
              "providers.commandcode.key": "${COMMANDCODE_API_KEY}",
              "delegation.provider": "commandcode"}},
  {"id": "voice", "title": "🎙 음성",
   "keys": [{"env": "GROQ_API_KEY", "label": "Groq 키", "validator": "groq",
             "url": "https://console.groq.com/keys", "hint": "gsk_로 시작"}],
   "config": {"stt.enabled": "true", "stt.provider": "groq", "stt.language": "ko"},
   "env": {"DISCORD_VOICE_AUTO_FOLLOW": "{owner_id}:{voice_channel_id}"}},
  {"id": "proxy", "title": "🛡 차단 우회 (원티드 등)",
   "keys": [{"env": "WEBSHARE_API_KEY", "label": "Webshare 키", "validator": "webshare",
             "url": "https://dashboard.webshare.io/userapi/keys", "hint": "API 키"}],
   "config": {}},
  {"id": "scrape", "title": "🕸 SNS·플랫폼 수집",
   "keys": [{"env": "APIFY_TOKEN", "label": "Apify 토큰", "validator": "apify",
             "url": "https://console.apify.com/settings/integrations", "hint": "apify_api_"}],
   "config": {}},
  {"id": "google", "title": "🔗 구글 연동",
   "keys": [{"env": "COMPOSIO_API_KEY", "label": "Composio 키", "validator": "composio",
             "url": "https://dashboard.composio.dev/", "hint": "발급 후 Regenerate 1회"}],
   "config": {"mcp_servers.composio.url": "https://connect.composio.dev/mcp",
              "mcp_servers.composio.enabled": "true"}}
]
```
위는 **기능 팩**(키 단위). 수강생이 고르는 건 **직군 키트**이고, 키트가 필요한 기능 팩을 끌어온다 — `kits.json`:
```json
[
  {"id": "job",   "title": "💼 구직",       "features": ["proxy"],           "skills_dir": "kits/job",   "installer": "job-hunt"},
  {"id": "sales", "title": "📈 세일즈",     "features": ["scrape", "google"], "skills_dir": "kits/sales"},
  {"id": "mkt",   "title": "📣 마케팅",     "features": ["scrape"],           "skills_dir": "kits/mkt"},
  {"id": "pm",    "title": "🧭 기획·PM",    "features": ["google"],           "skills_dir": "kits/pm"},
  {"id": "dev",   "title": "🛠 바이브코딩", "features": [],                   "skills_dir": "kits/dev"},
  {"id": "voice", "title": "🎙 음성 비서",  "features": ["voice"],            "skills_dir": null},
  {"id": "messenger", "title": "💬 카톡·팀즈 읽기", "features": [],            "skills_dir": "packs/messenger", "installer": "messenger", "consent": true}
]
```
`/setup` 흐름: 키트 복수 선택 → 필요한 기능 팩 합집합의 키만 모달로 요청 → 키트 스킬을 `skills/kit/<id>/`로 복사. (`installer: job-hunt`는 `hermes-job-hunt-for-korean/install.sh` 호출)

- [ ] **Step 2: 테스트** — 모든 `validator`가 `VALIDATORS`에 있고(composio는 S6 후), 팩당 키 ≤ 5개(디스코드 모달 한도), `env` 이름이 대문자·밑줄만, 모든 키트의 `features`가 packs.json에 존재.
- [ ] **Step 3: packs.py** — dataclass 로드 + 위 검증.
- [ ] **Step 4:** PASS → Commit

### Task 8: 주인 등록 + 초대 링크

**Files:** Create `plugins/kit-setup/owner.py`, `invite.py`

**Interfaces:** Produces `ensure_owner(guild_owner_id: str, name: str) -> bool`, `invite_url(app_id: str) -> str`

- [ ] **Step 1: owner.py** (S3 결과 반영)
```python
from gateway.pairing import PairingStore

def ensure_owner(user_id: str, name: str) -> bool:
    s = PairingStore()
    if any(str(u.get("user_id")) == user_id for u in s.list_approved("discord")):
        return False
    code = s.generate_code("discord", user_id, name)
    return bool(code and s.approve_code("discord", code))
```
- [ ] **Step 2: invite.py** — `.env`의 토큰으로 `/users/@me` → `id` → 권한 정수로 URL 출력.
  권한(비트 합): View Channels(1<<10) + Send Messages(1<<11) + Send in Threads(1<<38) + Embed Links(1<<14) + Attach Files(1<<15) + Read History(1<<16) + Connect(1<<20) + Speak(1<<21) + Use Slash Commands(1<<31).
  ```python
  PERMS = sum(1 << b for b in (10, 11, 38, 14, 15, 16, 20, 21, 31))
  print(f"[kit] 봇 초대 링크: https://discord.com/oauth2/authorize?client_id={app_id}&permissions={PERMS}&scope=bot%20applications.commands")
  ```
- [ ] **Step 2b: 앱 설정 자동화** (Discord 문서 확인: "Only limited intent flags … can be updated via the API") — `invite.py`가 초대 링크 출력 전에 봇 토큰으로 `PATCH /applications/@me`:
  ```python
  LIMITED = (1 << 19) | (1 << 15)   # GATEWAY_MESSAGE_CONTENT_LIMITED | GATEWAY_GUILD_MEMBERS_LIMITED
  body = {"flags": LIMITED,
          "install_params": {"scopes": ["bot", "applications.commands"], "permissions": str(PERMS)}}
  ```
  → 수강생은 Developer Portal에서 **New Application + Reset Token**만 하면 됨(인텐트 토글·권한 체크박스 단계 삭제). 앱 생성·토큰 발급은 공개 API가 없어 수동 유지. 100개 서버 이상 봇은 limited 인텐트 불가 — 수강생 봇은 해당 없음.
- [ ] **Step 3: 테스트** — `PERMS` 값 고정 assert(`277028654080`, 2026-09-26 테스트 봇에서 이 값으로 필요한 권한 전부 확인), S3 절차로 ensure_owner 두 번 호출 시 두 번째 False, PATCH 후 `GET /applications/@me`의 flags에 limited 비트 존재.
- [ ] **Step 4: Commit**

### Task 9: `/setup` 디스코드 UI

**Files:** Create `plugins/kit-setup/discord_ui.py`, `__init__.py`, `plugin.yaml`

**Interfaces:**
- Consumes: `load_packs`, `VALIDATORS`, `set_env`, `ensure_owner`, `hermes config set` CLI
- Produces: 디스코드 `/setup` 커맨드

흐름:
1. `/setup` → 권한: `interaction.user.id == interaction.guild.owner_id` 또는 이미 승인된 유저. 아니면 ephemeral 거절.
2. `ensure_owner()` → "주인으로 등록했어요".
3. ephemeral 메시지: 결과 채널 `ChannelSelect` + 팩별 버튼(상태 ✅/⬜). 채널 선택 → `DISCORD_HOME_CHANNEL`.
4. 팩 버튼 → `send_modal(PackModal(pack))` (모달은 반드시 인터랙션의 **첫 응답**).
5. 제출 → `defer(ephemeral=True, thinking=True)` → 검증기 병렬 실행(`asyncio.to_thread`) → 전부 통과 시 `set_env` + 각 `config` 항목 `hermes config set k v` → 결과 줄별 표시. 하나라도 실패하면 **아무것도 저장하지 않고** 실패한 키만 다시 입력.
6. "적용하기" 버튼 → "재시작합니다(10초)" 메시지 → S4 방식으로 재시작 → 기동 후 홈 채널에 "준비 끝" 인사(플러그인 `on_startup` 훅 또는 `.kit-pending-greeting` 파일).
7. LLM 구독: "🧠 두뇌 연결" 버튼 → Hermes 기존 `/auth` 흐름으로 안내(새 코드 없음).

- [ ] **Step 1:** `plugin.yaml` (`name: kit-setup`, `kind: standalone`), `__init__.py`의 `register(ctx)`는 `ctx.register_platform_handler("discord", build)`만.
- [ ] **Step 2:** `discord_ui.py` 구현 (S2 스파이크 코드를 확장).
- [ ] **Step 3: 수동 E2E (테스트 봇)** — 체크리스트:
  - [ ] 서버 소유자 아닌 계정 `/setup` → 거절
  - [ ] 틀린 Groq 키 → "거부됨 (HTTP 401)", `.env` 변경 없음
  - [ ] 맞는 키 → ✅, `.env` 600 권한, 게이트웨이 로그·세션 DB에 키 문자열 없음 (`grep -r gsk_ /opt/data/logs /opt/data/sessions` 결과 0)
  - [ ] 음성 팩 → 재시작 후 보이스룸 입장 시 자동 참여
  - [ ] 구직 팩 → Webshare 경유 원티드 확인 메시지
- [ ] **Step 4: Commit**

---

## Phase 3 — 비공개 팩

### Task 10: 팩 레포 + 다운로드

**Files:** 레포 B 생성, 레포 A `plugins/kit-setup/fetch_packs.py`

- [ ] **Step 1:** 레포 B 생성(private). GitHub fine-grained PAT: **이 레포 1개, Contents: Read-only, 만료 = 기수 종료일**. 이 토큰이 `KIT_ACCESS_CODE`.
- [ ] **Step 2:** `fetch_packs.py` — `https://api.github.com/repos/Wendy-Nam/hermes-kit-packs/tarball/main`을 `Authorization: Bearer $KIT_ACCESS_CODE`로 받아 임시 디렉터리에 풀고, `skills/kit/` 교체, `soul/`·`freellmapi/`는 없는 것만 복사. 심볼릭 링크 포함 시 중단(구직 키트 install.sh와 같은 원칙).
- [ ] **Step 3: 테스트** — 만료/틀린 토큰 → 부팅은 성공, 로그에 "팩 다운로드 실패" 한 줄, `/setup`에 재시도 버튼.
- [ ] **Step 4: Commit**

### Task 11: 스킬 큐레이션

- [ ] **Step 1:** §7 D1 목록대로 배치. 번들 keep-list → 레포 A `seed/bundled-keep.txt`, 서아 님 스킬 → 레포 B `skills/kit/{base,job,sales,mkt,pm,dev}/`.
  서아 님 스킬 중 개인 문맥이 박힌 것은 **일반화 후** 포함: `linkedin-post-authoring`("SAN's" 제거), `email-digest-batching`("private" 경로 제거), `mentoring-call-notes`→"통화·미팅 노트", `korean-direct-response-style`·`deterministic-content-retrieval`(15~20KB → 8KB 이하로 축약).
- [ ] **Step 2:** `youtube-content` 배포판: `yt.py`의 Apify 장부 의존 제거 → Gemini 직접 → (Webshare 있으면) 자막 API 순. `SKILL.md`에서 개인 경로(`state/apify-spend.json`, `shared-music`) 삭제.
- [ ] **Step 3:** 각 스킬 `SKILL.md`에서 `/opt/data` 외 개인 경로·채널 ID·이름("SAN", "에르") grep 0건.
- [ ] **Step 4: 토큰 측정** — 시드 설치 직후 `.skills_prompt_snapshot.json` 크기를 기록(서버 현재 59KB 대비 목표 치 §7 D1에서 정함).
- [ ] **Step 5: Commit**

### Task 12: 💸 freellmapi 심화팩 (별도 compose 프로젝트)

**Files:** 레포 A `advanced/docker-compose.freellmapi.yml`, `advanced/freellmapi.config.json`, 팩 정의 추가

**기본 compose에 넣지 않는다.** 스타터(Codex + OpenCode Go)에는 필요 없고, 서아 님 VPS(8GB/2코어)에서도 Hermes 프로세스 하나가 약 2.7GB RSS를 쓴다 — 저사양 VPS 수강생에게 상시 컨테이너를 더 얹을 이유가 없다. 장애도 분리된다(freellmapi가 죽어도 봇은 OpenCode Go로 계속 동작).

- [ ] **Step 0: 네트워크 연결** — 기본 compose가 이름 고정 네트워크를 만든다: `networks: {default: {name: hermes-kit}}`. 심화팩 compose는 `networks: {default: {name: hermes-kit, external: true}}` → Hermes에서 `http://freellmapi:3001`로 접근. 수강생은 Hostinger Docker Manager에 **두 번째 프로젝트로 붙여넣기**만 한다.

- [ ] **Step 1:** 체인은 선언형 config에 **없음**(S7) → 부팅 후 1회성 스크립트 `freellmapi_chains.py`가 관리자 로그인 → `GET /api/profiles` → 없는 이름만 `POST /api/profiles {name, emoji, color, empty: true}` → 모델 지정(`PUT /api/profiles/:id`). 서버 `patch-freellmapi-pools.py` 로직을 REST로 이식. 체인: `private`(`groq, cerebras, mistral` — Mistral 키는 옵트아웃 필수 체크를 거쳐야만 저장됨), `public`, `fast`, `compress`, `vision`, `coding`. **`unfiltered` 없음.** 키는 비워 둠. `aion-rp-*` 등 RP 모델은 어느 체인에도 넣지 않는다.
- [ ] **Step 2:** `ENCRYPTION_KEY`를 수강생이 만들지 않게 — 심화팩 compose에서 첫 기동 시 볼륨에 생성:
  ```yaml
  entrypoint: ["sh", "-c", "k=/app/server/data/.enc; [ -s $$k ] || head -c 32 /dev/urandom | base64 > $$k; export ENCRYPTION_KEY=$$(cat $$k); exec /docker-entrypoint.sh \"$$@\"", "--"]
  ```
  (ponytail: 키와 암호화 데이터가 같은 디스크 — 단일 사용자 VPS에선 .env도 같은 디스크라 차이 없음. 백업 분리 필요해지면 그때 외부화.) `/docker-entrypoint.sh` 경로는 freellmapi 이미지에서 확인.
- [ ] **Step 3:** 팩 정의: 키 입력 칸 = groq/cerebras/mistral/openrouter 중 최대 5개(모두 선택). 제출 → freellmapi CLI(`npx freellmapi keys add <platform>` + dashboard token) 또는 config JSON 갱신 후 freellmapi 재시작.
- [ ] **Step 3b: 관리자 계정 선점** — config JSON의 `admin`에 랜덤 비밀번호(볼륨 파일에 저장)를 넣어 **최초 설정 창을 닫는다**(freellmapi 문서: admin이 있으면 `POST /api/auth/setup`이 409). 포트는 공개하지 않음.
- [ ] **Step 4:** `/setup` 💸이 `http://freellmapi:3001/api/ping` 200을 확인한 **뒤에만** `hermes config set`으로 `auxiliary.*` → `freellmapi` 라우팅, `fallback_providers`는 `[opencode-go(또는 commandcode), freellmapi]` 순 (서버 config의 auxiliary 블록, 모델 `auto:private`/`auto:fast`/`auto:compress`/`auto:vision`).
- [ ] **Step 5: 확인** — `curl -H "Authorization: Bearer $K" http://freellmapi:3001/v1/models | grep -c unfiltered` → 0.
- [ ] **Step 6: Commit**

---

### Task 12b: 🤖 CLI 워커 팩 (고급, 선택)

**Files:** 레포 B `packs/cli-workers/{install.sh, bin/{external-worker,cli-task,cline-proposal}, executors/cli-task-policy.json, skills/free-cli-worker/SKILL.md}`, 레포 A `plugins/kit-setup/cli_login.py`

서아 님 서버에 이미 검증된 구조가 있다: `external-worker`(361줄), `cli-task`(128줄), `cline-proposal`(192줄), 정책 `executors/cli-task-policy.json`, 스킬 `tools/free-cli-worker`. 핵심 안전장치 — **비기밀 작업만**, 작업별 폴더, 영수증(receipt) 기록, 결과는 부모가 검증 후 적용, **Cline은 제안 전용**(Cline 3.0.65가 명령 권한 환경변수를 무시하고 셸을 실행한 사례가 있어 ACP로 모든 권한 요청을 취소). 이걸 그대로 옮긴다.

- [ ] **Step 1: 설치 위치** — CLI는 이미지에 굽지 않고 **볼륨**(`/opt/data/executors/cli-tools`, npm prefix)에 설치. 이유: CLI 버전이 주 단위로 바뀌고, 안 쓰는 사람 이미지가 수백 MB 커지는 걸 피함. 서아 님 서버의 `/usr/local/bin/{opencode,cline,claude}`는 이미지 레이어라 재생성 시 사라지는 구조 — 키트에선 볼륨 경로를 플러그인이 PATH에 추가(rtk-rewrite와 같은 방식).
- [ ] **Step 2: 선택 목록** (`/setup` → 🤖 CLI 워커 → 체크박스)

| CLI | 용도 | 로그인 | 비고 |
|---|---|---|---|
| OpenCode | 무료 모델(앱 전용 free 포함)로 코드·문서 작업, 편집 실행 | `opencode auth login` | 워커 기본값 |
| Cline | 무료 모델 다수, **제안만** | `cline auth` | `cline-proposal` 경유만 허용 |
| Codex CLI | ChatGPT 구독으로 코딩 위임 | `codex login --device-auth` | Codex OAuth 재사용 여부 S12 |
| Claude Code | Claude 구독 보유자용 | `claude setup-token` | **정책 고지 후 본인 선택** |
| Antigravity (`agy`) | 구글 계정(무료 포함)으로 Gemini 에이전트 — 6월부터 개인 계정용 Gemini CLI 대체 | SSH 세션이면 인증 URL 출력(문서) | 헤드리스 `agy -p`. 컨테이너 하위 프로세스에서도 URL 출력되는지 실측 후 공개 |

- [ ] **Step 3: 로그인 중계** — `cli_login.py`: 선택한 CLI의 로그인 명령을 하위 프로세스로 실행 → 출력에서 URL만 추출해 디스코드에 ephemeral로 표시 → 사용자가 브라우저에서 승인 후 받은 코드를 모달로 입력 → 하위 프로세스 stdin에 전달. 토큰은 CLI 자체 저장소(`/opt/data/executors/auth/<cli>`)에만 남고 채팅·로그에 출력하지 않음.
- [ ] **Step 4: 정책 파일 일반화** — `cli-task-policy.json`의 모델 allowlist에서 서아 님 계정 전용 항목 제거, 서버 경로 `/opt/data` 외 참조 grep 0건.
- [ ] **Step 5: 확인** — 서아 님 스킬 문서에 기록된 스모크와 같은 방식: 공개 픽스처 `add.py` 수정 작업을 `cli-task --execute`로 OpenCode·Cline 각각 실행 → 영수증 생성, Cline은 `tool_events: []` + 원본 파일 불변, 부모가 `add(2,3)==5` 확인.
- [ ] **Step 6: Commit**

### Task 12c: 💬 메신저 팩 — 카톡·팀즈 읽기 (선택)

**Files:** 레포 B `packs/messenger/{install.sh, scripts/{kakao-ro.sh, kakao-watch.py, teams-ro.sh}, skills/messenger-readonly/SKILL.md}`, 레포 A `plugins/kit-setup/messenger_login.py`

서아 님 서버의 검증된 구조를 옮긴다.
- `agent-messenger` 2.37.1 (npm, `agent-messenger/agent-messenger`) — `/opt/data/.local/share/agent-messenger-kakao`(볼륨)
- `scripts/kakao-ro.sh`(43줄): 허용 명령만 통과 — `whoami`, `auth status`, `chat list`, `member list`, `message list`. 발송·읽음 처리·방 나가기·인증 변경은 exit 3
- `scripts/kakao-watch.py`(218줄): **LLM 없는** 크론(`no_agent: true`) — 새 메시지만 디스코드로 전달, 없으면 무출력
- 스킬 `kakaotalk-readonly-harness`: 발송은 "초안 → 사용자 확인 → 승인 파일(5분 만료, 사용자 발언 인용)" 2단 확인

- [ ] **Step 1: 설치는 선택 시점에 npm으로** — package.json에 라이선스 표기가 없어(`license: undefined`) 이미지·팩 레포에 **동봉하지 않고** `npm install agent-messenger@2.37.1 --prefix /opt/data/.local/share/agent-messenger`로 버전 고정 설치.
- [ ] **Step 2: 동의 화면** — `/setup` → 💬 메신저 선택 시 먼저 표시, "동의" 버튼을 눌러야 진행:
  > 카카오 공식 봇 API가 아니라 내 계정 세션으로 접속합니다. 카카오 정책에 따라 계정 제한 가능성이 있습니다. 기본은 **읽기 전용**이며, 방 사람들의 메시지가 내 서버와 (요약 시) 내 LLM 구독으로 전달됩니다.
- [ ] **Step 3: 카톡 로그인 중계** (`messenger_login.py`)
  1. 모달: 카카오 이메일 + 비밀번호(1회용). 비밀번호는 `umask 077` 임시 파일 → `agent-kakaotalk auth login --email … --password-file <tmp>` → **즉시 삭제**. 채팅·로그에 남기지 않음.
  2. CLI JSON 출력 분기: `confirm_on_phone` → 디스코드에 "📱 휴대폰 카카오톡에서 **1234** 입력" 표시(CLI가 폴링하며 대기) / `choose_device` → "태블릿 칸이 사용 중: 태블릿 로그아웃 or PC 칸 사용(PC 카톡 로그아웃됨)" 버튼 → `--device-type … --force` 재실행.
  3. 기본은 **태블릿 칸**: 폰·PC 카톡은 그대로 유지. 태블릿 카톡을 쓰는 사람만 선택 필요.
- [ ] **Step 4: 방 선택 + 자동화 템플릿** — 로그인 후 `chat list`로 방 목록 → 드롭다운으로 감시할 방 고르기 → 크론 템플릿 중 선택:
  - 📥 매일 밤 새 메시지 모아 받기 (서버와 같은 `kakao-watch.py`, LLM 없음)
  - 🧾 업무방 하루 요약 → work 볼트 `Meetings/카톡-YYYY-MM-DD.md` (**구독 모델만**, 무료 풀 금지)
  - 🔔 키워드 알림 (LLM 없음, 정규식)
- [ ] **Step 5: 팀즈** — `agent-teams`의 인증 방식(디바이스 코드 여부)을 S13에서 확인 후 같은 패턴으로 `teams-ro.sh` 작성. 확인 전에는 카톡만 제공.
- [ ] **Step 6: 일반화** — 스킬·스크립트에서 "SAN" → "사용자", 서아 님 채널 ID 제거, `san_quote` → `user_quote`.
- [ ] **Step 7: 확인** — 테스트 계정으로: 로그인 후 PC 카톡이 유지되는지, `kakao-ro.sh message send …` → exit 3, 크론 1회 실행 시 새 메시지만 전달, 두 번째 실행은 무출력.
- [ ] **Step 8: Commit**

## Phase 4 — Obsidian / Syncthing

### Task 13: 볼트 2개(work/personal) + 플러그인 동봉 + Syncthing

**Files:** 레포 A `seed/vaults/{work,personal}/`, Dockerfile(플러그인 다운로드), `plugins/kit-setup/obsidian.py`

- [ ] **Step 1: 볼트 템플릿**
  - `personal/`: `Daily/`, `Inbox/`, `Archive/`(가져온 대화), `Profile/`(나에 대한 사실 후보), `TaskNotes/`
  - `work/`: `Projects/`, `Meetings/`, `Research/`, `Archive/`, `TaskNotes/`, (구직 키트 선택 시) `automation/job-hunting/`
  - 두 볼트 모두 `.obsidian/community-plugins.json` = `["dataview","obsidian-tasks-plugin","tasknotes"]` (구직 키트와 동일한 ID)
  - 역할 분리 규칙(SOUL/obsidian 스킬에 한 줄): **Hermes가 만드는 할 일은 TaskNotes 노트로만**, Tasks 플러그인은 사람이 데일리 노트에 쓰는 체크박스용. 칸반은 TaskNotes 칸반 뷰로(별도 Kanban 플러그인 없음).
- [ ] **Step 2: 플러그인 파일 동봉** (Dockerfile에 추가, 버전 고정)
```dockerfile
RUN set -eux; for v in work personal; do \
      for spec in "dataview blacksmithgu/obsidian-dataview 0.5.70" \
                  "obsidian-tasks-plugin obsidian-tasks-group/obsidian-tasks 8.4.0" \
                  "tasknotes callumalpass/tasknotes 4.13.5"; do \
        set -- $spec; d=/opt/kit/seed/vaults/$v/.obsidian/plugins/$1; mkdir -p $d; \
        for a in main.js manifest.json styles.css; do \
          curl -fsSL -o $d/$a https://github.com/$2/releases/download/$3/$a; done; \
      done; done
```
- [ ] **Step 3: 프로필 연결** (S11 통과 시) — `/setup`의 채널 선택 2개(🗂 업무 채널 / 🏠 개인 채널) → `hermes profile create work` + work 프로필 config에 `OBSIDIAN_VAULT_PATH=/opt/data/vaults/work` + `gateway.profile_routes`에 업무 채널 → work. 개인 채널·DM은 default(personal).
- [ ] **Step 4: Syncthing 페어링** — 모달 입력 1칸 = **내 PC Syncthing 기기 ID**. 제출 → REST(`/rest/config/devices`, `/rest/config/folders`)로 기기 추가 + `vaults/work`, `vaults/personal` **폴더 2개** 공유. 서버 기기 ID를 응답에 표시. hermes는 `syncthing-config` 볼륨(읽기 전용)의 `config.xml` `<apikey>`로 `http://syncthing:8384` 호출. (`vps/scripts/remote/st_pair.py`를 먼저 읽고 재사용)
- [ ] **Step 5:** PC 가이드 1장: Syncthing 설치 → 기기 ID → `/setup` → PC에서 폴더 2개 수락 → Obsidian에서 **볼트 2개 각각 열기** → 각 볼트에서 "제한 모드 끄기" 1회.
- [ ] **Step 6: 확인** — 서버 `echo t > /opt/data/vaults/work/sync-test.md` → PC 1분 내 등장. PC Obsidian에서 Dataview 쿼리 블록 렌더링, TaskNotes 칸반 뷰 열림.
- [ ] **Step 7: Commit**

### Task 13b: 기존 ChatGPT·Claude 대화 가져오기

**Files:** 레포 A `plugins/kit-setup/importer.py`, `tests/test_importer.py`; 레포 B `skills/kit/base/conversation-import/SKILL.md`

기존 `vps/scripts/08-claude-sessions.sh`는 폐기 — 함수 밖에서 `local`을 써서 bash 오류로 멈추고, 읽는 경로(`~/.omc/state`)는 Claude 대화가 아니라 OMC 플러그인 상태다.

- [ ] **Step 1: 흐름**
  1. 수강생: ChatGPT(설정 → 데이터 제어 → 데이터 내보내기) / Claude(설정 → 개인정보 → 데이터 내보내기) → 메일로 온 zip을 **PC의 `personal/Inbox/import/`에 넣기** (Syncthing이 서버로 옮김 — 디스코드 첨부 한도 때문에 이 경로가 기본)
  2. `/import` 또는 30분 크론(LLM 없음) → `importer.py`가 zip 안 `conversations.json`을 대화 1개 = 마크다운 1개로 변환 → `personal/Archive/{chatgpt,claude}/YYYY/YYYY-MM-DD 제목.md`, frontmatter: `source, conv_id, created, messages`
  3. (선택, 사용자가 켤 때만) 분류 크론 — **구독 모델로만**(무료 풀 금지): 제목+첫 메시지로 업무/개인 판정 → 업무면 `work/Archive/`로 이동, 나에 대한 사실은 `personal/Profile/후보.md`에 **후보로만** 적고 메모리에는 사람이 승인해야 반영
- [ ] **Step 2: 실패 테스트** — 샘플 `conversations.json` 두 형식(ChatGPT: `mapping` 트리, Claude: `chat_messages` 배열) 각 1건 픽스처 → 파일명·frontmatter·메시지 순서 assert, 같은 zip 두 번 → 파일 수 동일(`conv_id` 기준 멱등), zip 안 `../` 경로 → 거부.
- [ ] **Step 3: 구현** — stdlib `zipfile`·`json`만. ChatGPT는 `current_node`에서 `parent`를 따라 올라가 현재 분기만 복원(편집 전 분기 제외). 파일명에서 `/\:*?"<>|` 제거, 80자 제한.
- [ ] **Step 4:** PASS → 서아 님 실제 export로 1회 실행(로컬), 변환 건수 = 원본 대화 수.
- [ ] **Step 5: Commit**

---

## Phase 5 — 배포 경로

### Task 14: 수강생용 compose

**Files:** `docker-compose.yml`

- [ ] **Step 1:**
```yaml
services:
  hermes:
    image: ghcr.io/wendy-nam/hermes-kit:0.21.2-k1
    restart: unless-stopped
    volumes:
      - hermes-data:/opt/data
      - vaults:/opt/data/vaults                 # 볼트(work, personal)만 별도 볼륨 → syncthing과 공유
      - syncthing-config:/opt/syncthing-config:ro  # 플러그인이 config.xml에서 REST API 키를 읽는다
    environment:
      DISCORD_BOT_TOKEN: ${DISCORD_BOT_TOKEN}
      KIT_ACCESS_CODE: ${KIT_ACCESS_CODE:-}
      TZ: Asia/Seoul
    command: ["gateway", "run"]
  syncthing:
    image: syncthing/syncthing:<고정 버전>
    restart: unless-stopped
    volumes:
      - vaults:/var/syncthing/vaults           # hermes 데이터 전체(.env 포함)는 절대 마운트하지 않는다
      - syncthing-config:/var/syncthing/config
    ports: ["22000:22000/tcp", "22000:22000/udp", "127.0.0.1:8384:8384"]
volumes: {hermes-data: {}, vaults: {}, syncthing-config: {}}
networks: {default: {name: hermes-kit}}   # 심화팩(freellmapi)이 external로 합류
```
(`network_mode: host`를 쓰지 않는다 — 서비스 이름(`syncthing:8384`, 심화팩 `freellmapi:3001`)으로 통신, 대시보드 포트 외부 비노출)
- [ ] **Step 2: 신규 VPS 리허설** — 깨끗한 Hostinger VPS(또는 테스트 VPS)에 붙여넣기 → S9 확인 → 로그에서 초대 링크 → `/setup` 완주. **스톱워치로 시간 기록.**
- [ ] **Step 3 (선택, 리허설 통과 후):** Hostinger API `create new project`로 원클릭 — 수강생이 Hostinger API 토큰을 만들어야 해서 단계가 오히려 늘 수 있음. 리허설 시간이 20분을 넘을 때만 착수.

---

## Phase 6 — 리허설과 매뉴얼

### Task 15: 비개발자 리허설
- [ ] 지인 1명(비개발자)에게 문서만 주고 진행, 서아 님은 관찰만. 막힌 지점·시간 기록 → 이슈로.
- [ ] 합격 기준: 도움 없이 30분 이내 완주, `/setup` 모든 팩 ✅, 디스코드에서 유튜브 요약 1건 성공.

### Task 16: 매뉴얼 v2
- [ ] 1편(준비) = 결제 카드·디스코드 계정·봇 만들기(캡처 3장).
- [ ] 2편(배포) = compose 붙여넣기 + `/setup`.
- [ ] 3편(활용) = 위키·구직 예시(기존 3-3, 3-4 유지).
- [ ] 문제 해결 표: "Claude 데스크탑으로 `ssh`" 항목은 **고급/강사 지원용**으로 이동.
- [ ] 기존 문구 수정: Apify "막아둔 곳 우회" → "공개 페이지 수집용 액터 실행", Obsidian "헤르메스가 설치" → "내 PC에 설치", Gemini "Composio 가입 시 자동" → 기본 팩 키.

---

## Phase 7 — 운영 도구 (원격 지원 줄이기)

### Task 17: `/doctor` — LLM 없는 자가진단
- [ ] 항목: 게이트웨이 가동 시간, 키별 검증(Task 6 재사용, 키 값 출력 없음), OpenCode Go 한도 잔여(가능하면), Syncthing 연결 상태, 심화팩 `freellmapi /api/ping`, 디스크 여유, 최근 크론 실패 3건, kit 버전.
- [ ] 결과는 ephemeral + **"강사에게 보내기용" 복사본**(키·토큰·채널ID·이메일 마스킹). 구직 키트의 `kit-doctor.py` 형식을 먼저 읽고 맞춘다.
- [ ] 합격 기준: Task 15 리허설에서 막힌 지점이 `/doctor` 출력만으로 원인 식별 가능.

### Task 18: 업데이트 알림
- [ ] 주 1회 LLM 없는 크론: GHCR 태그 목록에서 현재 `KIT_VERSION`보다 높은 태그가 있으면 홈 채널에 "업데이트 있음 → Hostinger에서 재배포(1분)" + 변경사항 3줄(릴리스 노트).

### Task 19: 백업·해제
- [ ] 주 1회 LLM 없는 크론: `memories/`, `config.yaml`, `SOUL.md`, `cron/jobs.json`, `profiles/*/config.yaml`을 tar → `vaults/personal/_backup/YYYY-MM-DD.tar.gz` (최근 4개 유지). **`.env`·`auth.json`·메신저 세션은 제외**(키는 `/setup`으로 재입력). Syncthing으로 PC에 자동 사본.
- [ ] `/setup` → "연결 해제": 메신저 `auth logout`, CLI 로그아웃, 팩별 키 삭제(`.env`에서 제거 + config 되돌림).

### Task 20: 첫날 체험용 스타터 크론 (선택 토글)
- [ ] `/setup` 마지막 화면에 켜고 끌 수 있는 3개:
  - ☀️ 아침 브리핑 (서아 님 `daily-korea-morning-brief` 일반화 — 날씨는 외부 프록시 의존이라 제외, 뉴스·일정 위주)
  - 📧 이메일 다이제스트 (🔗 구글 연동 선택 시만, `email-digest-batching` 일반화)
  - 🗓 주간 회고 (번들 `weekly-review-planning`, 일요일 밤)
- [ ] 모두 `max_turns` 지정(Task 1b 패치), 보조 모델(OpenCode Go/Command Code)로 실행해 Codex 한도 보호.

## 운영 정책

- **Hermes 업그레이드:** `versions.env`의 베이스 다이제스트만 바꿔 태그 → CI. 보이스 패치 앵커 불일치면 빌드 실패(수강생 서버는 안전) → 패치 갱신 후 재시도.
- **수강생 업데이트:** Hostinger Docker Manager에서 이미지 태그 변경 → 재배포. 시드 훅이 kit 소유 경로만 교체, 사용자 파일·`.env`·메모리 보존.
- **기수 종료:** 해당 PAT 폐기 → 이미 받은 팩은 남고 업데이트만 끊김.
- **서아 님 서버:** 이 키트로 옮기지 않는다. 개인 플러그인·크론 36개가 있는 운영 서버이므로 키트는 별도 테스트 VPS에서만 검증.

## 리스크

| 리스크 | 대응 |
|---|---|
| S2 실패 (플러그인 모달 불가) | 텍스트 인자 slash + ephemeral로 후퇴. 그래도 채팅 메시지로는 받지 않음 |
| Hostinger가 compose `${VAR}` 입력칸을 안 띄움 (S9) | compose 안에 직접 값 입력하는 안내로 변경, 토큰 1개뿐이라 감당 가능 |
| freellmapi 이미지가 무거워 저사양 VPS에서 느림 | 비용 최적화 팩을 선택 팩으로 유지(기본 compose에서 제외 가능) |
| 수강생 VPS가 ARM | rtk는 `aarch64-unknown-linux-gnu` 자산 있음 → CI에 멀티아치 추가 (그때 착수) |
| 무료 프로바이더 약관 | freellmapi README: 개인 단일 사용자 프록시 전제. 수강생 각자 자기 키 → 매뉴얼에 한 줄 고지 |

---

## §7 결정 (추천안 — 서아 님 확인 후 확정)

근거: 서버 `skills-manifest.yaml`(90개) + 최근 60일 `skill_view` 호출 수(state.db) + 크론 참조 + 업스트림 번들 목록(`/opt/hermes/skills`, 62개).

### D1. 스킬 구성

**번들 keep-list (`seed/bundled-keep.txt`)** — 나머지 번들 62개 중 약 45개는 삭제
```
autonomous-ai-agents/hermes-agent
note-taking/obsidian
media/youtube-content
research/llm-wiki
research/grounded-citations
web/blocked-page-recovery
productivity/pdf
productivity/docx
productivity/xlsx
productivity/powerpoint
productivity/meeting-action-items
productivity/document-to-action-items
productivity/weekly-review-planning
email/email-inbox-triage
```
(`youtube-content`는 레포 B의 Gemini 버전으로 덮어씀. `apple/*`은 리눅스 VPS라 동작 불가 → 삭제)

**기본(전원)** — 레포 B `skills/kit/base/`

| 스킬 | 60일 사용 | 비고 |
|---|---|---|
| web-reader | 30 | |
| methodology-first | 28 | |
| korean-humanizer | 19 | |
| korean-direct-response-style | 16 | 15KB → 축약 |
| deterministic-content-retrieval | 14 | 20KB → 축약 |
| daily-journaling | 7 | personal 볼트 |
| time-awareness | 7 | |
| pdf-document-production | 6 | 한국어 PDF |
| hermes-slash-commands | 4 | |
| efficient-cron-jobs | 0 | 수강생이 크론 만들 때 토큰 절약 |
| conversation-import | 신규 | Task 13b |

**직군 키트**

| 키트 | 스킬 | 필요한 키 |
|---|---|---|
| 💼 구직 | hermes-job-hunt-for-korean 전체(job-search, job-collect 크론), web-reader | Webshare |
| 📈 세일즈 | outbound-scoring, linkedin-post-authoring(일반화), composio-personal-assistant, research/competitor-news-monitor(번들) | Apify, Composio |
| 📣 마케팅 | linkedin-post-authoring, creative/visual-image, naver-news-search, creative/baoyu-infographic(번들), productivity/product-price-monitor(번들) | Apify |
| 🧭 기획·PM | mentoring-call-notes→통화·미팅 노트, google-calendar-event, calendar-operations, email-digest-batching(일반화) | Composio |
| 🛠 바이브코딩 | software-development/{github, codebase-inspection, systematic-debugging, requesting-code-review, simplify-code, spike, hermes-agent-skill-authoring}(번들), autonomous-ai-agents/{claude-code, codex}(번들), geeknews-search | 없음 |
| 🎙 음성 | (스킬 없음, 보이스 패치 + STT 설정) | Groq |

**제외**
- 개인 페르소나·생활 자동화: `er-*`, `san-*`, `selfie-*`, `scene-library-maintenance`, `soul-persona-editing`, `personal-state-review`, `self-runtime-goal-operations`, `continuity-preservation`, cron 카테고리 전체(선톡, 타임캡슐, 라이프 시그널, 자아 승격 등), `hitomi-recs`, `discord-emoji-character-sticker-set`
- 서아 님 인프라 전용: `hermes-model-routing`(freellmapi 라우팅 전제), `hermes-kanban-delegation`, `hermes-profile-agent-interaction`, `hermes-context-*`, `delegation-*`, `autonomy-loop-continuity`, `workflow-dispatch-verification`, `hermes-embedding-retrieval`, `hermes-voice-provider-ops`(29KB), `discord-delivery-routing`, `vault-source-of-truth-navigation`, `candidate-pool-rotation-integrity`
- 메신저 연동(`kakaotalk-readonly-harness` 등)은 기본에서 빼고 **💬 메신저 선택 팩**(Task 12c)으로 이동 — 동의 화면 + 읽기 전용 기본
- 외부 개인 프록시 의존: `korea-weather`, `fine-dust-location` (`k-skill-proxy.nomadamas.org` — 운영자가 내리면 깨짐). 원하면 선택 설치로.

목표: 기본 설치 스킬 수 ≤ 25 (현재 서버 98개, 스킬 목록 스냅샷 59KB). Task 11 Step 4에서 실측.

### D2. omh — 기본에서 제외, "파워 팩"으로만

- 정체: `rlaope/oh-my-hermes` v2.0.5, MIT. 메모리 프로바이더를 omh로 교체하고, 모든 LLM 호출 앞뒤(`pre_llm_call`, `pre_tool_call`, `transform_tool_result` 등 7개 훅)에 개입한다.
- 제외 이유: ① `requires_hermes: ">=0.21.1,<0.22.0"` → Hermes 0.22가 나와도 omh가 따라올 때까지 키트 업그레이드가 묶임 ② 서아 님 서버의 omh는 로컬 패치 3종(`omh-freellmapi`, `omh-native-routing`, `patch-omh-register-once`)이 붙은 상태라 업스트림 그대로 주면 같은 동작이 아님 ③ 비개발자에게 메모리 저장소가 두 종류가 되면 문제 해결이 어려움.
- omh 스킬 중 omh 도구를 쓰는 6개(`omh-code-review`, `omh-memory-sync`, `omh-verification-gate`, `ulw-plan`, `ulw-qa`, `ulw-work`)는 플러그인 없이 동작하지 않음. 바이브코딩 키트에 **선택 항목**으로: `hermes plugins install rlaope/oh-my-hermes`(업스트림 설치 명령)만 제공.

### D3. LLM — 스타터 / 고급 2단계

| 단계 | 구성 | 월 비용 | 키 |
|---|---|---|---|
| **스타터 (기본 안내)** | ChatGPT Plus → `openai-codex` OAuth (메인 두뇌) + **OpenCode Go 또는 Command Code GOAT 중 하나** (위임·보조·폴백용 오픈 모델) + Gemini 무료 키 (유튜브·비전) | 약 $30 ($20 + $10) | OAuth 1 + 키 2 |
| **고급 (선택)** | 스타터 + 🤖 CLI 워커 팩(OpenCode·Cline·Codex·Claude Code CLI, OAuth 로그인) + 💸 freellmapi 팩 | + 무료 키 여러 개 | 선택 |

- **OpenCode Go** ($10/월, 오픈 모델 32종, 5시간 $12·주 $30·월 $60 한도): Hermes 내장 프로바이더 `opencode-go` → 키 1개(`OPENCODE_GO_API_KEY`)만 넣으면 됨. **스타터 기본값으로 추천** — 설정이 가장 짧다.
- **Command Code GOAT** ($10/월, 크레딧 $70, 33개 모델): Hermes 내장 프로바이더가 아님 → `providers.commandcode.api: https://api.commandcode.ai/provider/v1` 커스텀 등록(서아 님 서버 방식). `/setup`이 대신 써 주므로 수강생 수고는 같음. 대안 선택지로 제공.
- 둘 중 하나를 `delegation.provider`와 `fallback_providers` 첫 항목으로 → Codex 한도를 메인 대화에만 쓰게 함.
- **Claude 구독은 스타터에서 안내하지 않음**: Anthropic이 2026-04-04부터 Hermes 같은 서드파티 하네스의 구독 사용을 막았다가 "Agent SDK credit"으로 재허용, 6/15에 그 제도를 일시 중단 — 정책이 계속 바뀜. 서아 님 `vps/SKILL.md`에도 "Hermes 모델로 직접 못 씀", 강의에서도 인증 실패. Claude Code CLI를 워커로 쓰는 건 CLI 워커 팩의 **본인 판단 선택 항목**(정책 고지 문구 포함).

### D4. private 풀 — `xkiro`, `aion` 제외 확정 + 추가 정리

- `xkiro`: 현재 freellmapi 모델 목록(607개)에 없음. allowlist에만 남은 흔적.
- `aion`: 모델 4개 중 `aion-rp-llama-3.1-8b`가 롤플레이 전용. 수강생 기본에 둘 이유 없음.
- 추가 제외: `cohere`(freellmapi ToS 리뷰 "❌ 개인·가정 용도 금지"), `cloudflare`(⚠️ 모호), `requesty`·`opencode`(리뷰 없음).
- 결과(S10 반영): private = **`groq, cerebras, mistral`**. Mistral 무료(Experiment) 플랜은 입력·출력을 **기본적으로 학습에 사용**하지만 Admin Console → Privacy에서 끌 수 있음. API로는 확인 불가 → Mistral 키 모달에 설정 화면 링크 + **"학습 끄기 완료" 필수 체크**. 체크해야만 키가 저장되므로 Mistral 키가 있는 사람은 모두 옵트아웃된 상태.
- `/setup` 💸 안내 한 줄씩: Groq는 Console → Data Controls에서 **Zero Data Retention 켜기**. Cerebras 무료 조건(크레딧 만료 여부)은 가입 화면 기준으로 매뉴얼에 기재.

### D5. 접근 토큰 — 기수별 1개

- 수강생별 토큰의 이점은 "유출자 1명만 끊기"인데, 이미 받아 간 스킬 파일은 끊어도 남는다(수강생 서버에서 읽을 수 있음). 막을 수 있는 건 이후 업데이트뿐.
- 비용: fine-grained PAT는 API로 만들 수 없어 수강생 수만큼 GitHub 화면에서 수동 발급.
- 운영: 기수 시작일에 PAT 1개(레포 B 하나, Contents 읽기 전용, 만료 = 기수 종료 + 1개월). 유출이 보이면 새 PAT로 교체하고 공지(수강생은 Hostinger 환경변수 1칸만 수정).
- 업그레이드 경로: 개인별 통제가 정말 필요해지면 레포 B에 수강생별 read-only deploy key(API로 생성 가능)를 발급하는 방식으로 전환.


### D6. 게이트웨이 — v1은 디스코드 전용

`/setup` 모달·버튼·드롭다운은 디스코드 기능이다. 텔레그램은 모달이 없어 키를 채팅으로 받아야 하는데(봇이 즉시 삭제해도 텔레그램 서버·알림에 남음), 이는 "키는 채팅으로 받지 않는다" 원칙과 충돌한다. → v1은 디스코드만 지원하고 매뉴얼에서도 디스코드를 권장(기존 매뉴얼과 같은 입장). 텔레그램은 셋업을 디스코드로 끝낸 뒤 게이트웨이만 추가하는 방식으로 v2에서 검토.

### D7. freellmapi — 심화팩(별도 compose)

기본 compose에 넣지 않음(Task 12). 이유: 스타터는 불필요, 상시 메모리 비용, 장애 분리. 켜는 법 = Hostinger에 두 번째 프로젝트 붙여넣기 → `/setup` 💸 에서 무료 키 입력. 헬스체크 통과 전에는 라우팅을 바꾸지 않으므로 반쯤 켜진 상태에서 봇이 죽지 않는다.


### D8. 베이스 이미지 — 업스트림 공식 `nousresearch/hermes-agent:v2026.9.11`

- 같은 업스트림 커밋(`5eb99eb2`)이라 Hermes 동작은 운영 서버와 동일. Docker Hub 공식, MIT, **amd64·arm64 둘 다** 제공(ARM VPS 리스크 해소), 다이제스트 고정.
- Hostinger 이미지를 베이스로 쓰지 않는 이유: Hostinger 레이어는 소스·라이선스 비공개라 **공개 파생 이미지로 재배포하기 애매**하고, 그 레이어가 주는 것(4860 대시보드 기본 인증, nexos 기본 모델, Claude Code CLI 선설치)은 키트에서 불필요하거나(`/setup`·`/doctor`가 대시보드 대체) 선택 설치(CLI 워커 팩)로 대체된다.
- 주의: 보이스 패치·코어 패치는 Hostinger 빌드 위에서 검증됐다. Hostinger 레이어가 건드린 파일(nexos/oxylabs 프로바이더 관련)과 겹치는지는 Task 1 빌드의 앵커 검사로 드러남 — 실패하면 해당 패치만 업스트림 기준으로 재작성.

## 스파이크 결과

### 2026-09-26 (읽기 전용 — 운영 서버 변경 없음)

| # | 결과 | 근거 | 계획 반영 |
|---|---|---|---|
| S4b | ✅ `/run/s6/container_environment/`에 compose env가 파일로 존재. cont-init 정렬: `01-hermes-setup` → `015` → `019` → `02-reconcile-profiles` → `10-kit-seed` 순(사전순)이라 공식 셋업 뒤에 실행됨 | 서버 `ls` | Task 3 그대로 |
| S7 | ⚠️ 선언형 config 스키마는 `admin, license, keys, customProviders, models, fallback, routing`뿐 — **프로필(체인) 없음**. 프로필은 `/api/profiles`(requireAuth) REST로만 | `server/src/services/declarative-config.ts:98-117`, `app.ts:256`, `routes/profiles.ts:139` | Task 12 Step 1을 REST 스크립트로 변경 |
| S8 | ✅ `rtk-hermes` 1.2.3 MIT(`ogallotti/rtk-hermes`), `web-crawl4ai` 작성자 = 서아 님 본인, omh MIT. ⚠️ `agent-messenger` 레포·package.json에 라이선스 없음 | PyPI JSON, plugin.yaml, GitHub | 이미지 포함 OK / agent-messenger는 선택 시 npm 설치(Task 12c 그대로) |
| S10 | Groq ✅ 계약상 학습 금지 + ZDR 토글 / Cerebras ✅ 추론 데이터 미보관 / Mistral ⚠️ 무료 플랜 기본 학습 사용, 콘솔에서 끌 수 있음 | Groq Docs "Your Data", Cerebras 개인정보처리방침, Mistral Help Center | private = groq, cerebras, mistral(옵트아웃 필수 체크) |
| S12 (일부) | `claude setup-token`(대화형), `opencode auth login -p <provider> -m <method>`, `cline auth -p <id> -k <key>`(키 방식) 확인. Antigravity `agy`는 SSH 감지 시 URL 출력(문서) | 서버 `--help`, Antigravity 문서 | TTY 없는 하위 프로세스 동작은 테스트 환경에서 |
| S13 (일부) | ✅ Teams: `agent-teams auth login --email` → JSON(`verification_uri`, `user_code`, `device_code`) → 승인 후 `--device-code`로 완료. 리프레시 토큰 자동 갱신 | `skills/agent-teams/SKILL.md:38-56` | Task 12c Step 5: 카톡과 같은 모달 중계로 팀즈 동시 제공 가능 |

| S1 | ✅ 운영 이미지 `hermes-agent:baseline-20260924` = **Hostinger 공개 이미지 `ghcr.io/hostinger/hvps-hermes-agent@sha256:3d3ff729…`를 로컬 태그만 바꾼 것**(Hostinger 태그 목록에 같은 다이제스트). 구성: 업스트림 Hermes(git `5eb99eb2` = v2026.9.11) + Hostinger 레이어(대시보드 `0.0.0.0:4860` + `ADMIN_USERNAME/PASSWORD` 기본 인증, nexos·oxylabs 프로바이더 패치, Claude Code CLI 2.1.270, apt 패키지). Hostinger 레이어 소스는 비공개(레포 404) | `ssh vps` docker inspect/history, compose 백업 3개의 `image:` 줄, GHCR 익명 태그 조회 | 베이스 = §7 D8 |
| S4 | ✅ `kill -TERM <gateway pid>` → s6가 **약 5초** 만에 재기동, 디스코드 재연결, compose env의 토큰 사용 | 테스트 컨테이너 | Task 9 "적용하기" = 이 방식 |
| S5 | ✅ `rtk rewrite`는 정상 치환에 종료코드 **3**, `rtk hook check`는 **0**. 서아 님 서버는 9/9~9/20 `rewrite`+`OK_CODES={0}`으로 치환 거부 4,384건 → **9/20 `hook check` 전환 후 정상 동작**(터미널 HOME `/opt/data/home` 기준 `rtk gain`: 500건, 약 97.5만 토큰 절감, 72%. 9/24 `rtk read` 1건이 85만 차지). 업스트림 rtk-hermes와 rtk 저장소 공식 플러그인(`hooks/hermes`)은 `{0, 3}` 수용 + fail-open. `rtk init --agent hermes`가 `/opt/data/plugins/rtk-rewrite` 설치 + `plugins.enabled` 등록까지 수행 | 테스트 이미지·운영 서버 비교, GitHub 소스 | 키트는 **공식 플러그인**(`rtk init`) 사용, 제3자·로컬 수정본 미사용. 운영 서버 수정은 서아 님 판단 |
| D8 검증 | ✅ 보이스 패치 5종이 **업스트림 v2026.9.11 베이스에 그대로 적용** + `verify.py` 전부 통과 | 일회용 컨테이너 | Task 1 그대로 |
| 첫 부팅 | ⚠️ 공식 훅이 `config.yaml`(2,135줄)·`.env` 템플릿(27KB)·`SOUL.md`를 먼저 생성 | 테스트 컨테이너 | Task 3을 "첫 부팅 병합"으로 변경 |
| S2 | ✅ 모달 동작(사용자 확인 `S2 ok: len=N`). ⚠️ 1차: 전역 트리에 추가한 명령은 **등록 안 됨** — 게이트웨이 safe sync가 플러그인 팩토리보다 수 ms 먼저 전역 트리를 스냅샷(70개만 reconcile). 2차: **길드 전용 명령 + 플러그인이 길드별 `tree.sync(guild=)`** → 0.4초 만에 등록, 게이트웨이 전역 동기화와 충돌 없음 | 게이트웨이 로그 `Safely reconciled 70`, Discord API 명령 목록 | Task 9: `/setup` 등은 **길드 전용 등록** + `on_guild_join` 리스너 |
| S3 | ✅ 서버 소유자만 통과, `PairingStore` 승인 1건 등록. 테스트 중 LLM 호출 0건·세션 0건 | 테스트 컨테이너 | Task 8 그대로 |
| 캐시 | ✅ freellmapi(v0.12 커스텀 빌드) `lossless` 압축은 프롬프트 캐시를 깨지 않음 — 같은 요청 2회 시 2회차 cached 6,656/6,877(97%). freellmapi DB는 `cached_input_tokens`를 **저장하지 않음**(7일 12,867건 전부 null) → 캐시 지표는 Hermes `session_model_usage`에서만 볼 수 있음. 운영 서버의 freellmapi 경유 적중률이 9/24부터 0%가 된 원인은 트래픽이 deepseek(캐싱)→kilo 무료 모델(비캐싱)로 이동한 것 | 테스트 호출 2회, 두 DB | Task 12: **대화·위임 체인은 캐싱 지원 모델 우선**, 제목·압축 같은 일회성 보조 작업만 비캐싱 무료 모델. Task 17 `/doctor` 캐시 지표는 Hermes DB에서 |

### 대기 중 (서아 님 준비물 필요)
- **S2·S3·S4·S5·S6·S11·S12 나머지·S13 카톡**: 테스트 디스코드 봇 + 테스트 서버 (+ 가능하면 테스트 VPS, 테스트 카톡 계정)
- **S9**: Hostinger Docker Manager 화면 확인 (테스트 VPS)
