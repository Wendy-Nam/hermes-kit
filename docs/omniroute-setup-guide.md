# Hermes 라우팅 설정 복제 가이드

Hermes 에이전트가 OmniRoute를 거쳐 여러 모델 제공자를 쓰는 구성을 따라 만들 수 있게 정리한 문서입니다. 모델 목록보다 설정·정책·자동화 위주로 정리했으며 API 키, 계정 ID, 사용자 식별자는 포함하지 않습니다.

- 기준일: 2026-11-23
- OmniRoute `3.8.54` (원본) / Hermes `v0.23.3` / OMH `5.0.0`

---

## 1. 전체 구조

- Hermes(컨테이너) → `http://omniroute:20128/v1`(OpenAI 호환) → 모델 제공자.
- Hermes는 모델 이름 대신 **역할 이름**(`role-chat`, `role-worker` 등)을 보내고, 그 역할의 콤보에서 OmniRoute가 실제 모델을 고릅니다.
- 두 컨테이너는 같은 Docker 네트워크(`hermes-kit`)에 있으며, OmniRoute 포트는 호스트 루프백(`127.0.0.1:20128`)에만 열려 있습니다.
- 무료 모델 시험과 콤보 정리는 호스트 스크립트와 타이머가 담당합니다(8장).

---

## 2. OmniRoute 실행 설정

`3.8.54`부터는 **커스텀 패치 없이 원본 이미지**를 사용합니다. 예전 패치와 덮어쓰기는 원본에 이미 반영되었거나 효과가 없어 제거했습니다.

| 항목 | 값 | 이유 |
|---|---|---|
| 이미지 | `ghcr.io/diegosouzapw/omniroute:3.8.54` | 원본. 패치 불필요 |
| 메모리 | `mem_limit: 4g`, `NODE_OPTIONS=--max-old-space-size=2048` | 기본 1GB 힙에서는 GC 지연 발생 (4GB VPS는 `2g`/스왑 권장) |
| 카탈로그 | `CATALOG_BUILD_TIMEOUT_MS=60000` | 모델 9천 개 카탈로그 첫 빌드에 25~50초 소요 |
| 타임아웃 | `FETCH_TIMEOUT_MS=180000`, `STREAM_IDLE_TIMEOUT_MS=90000`, `STREAM_READINESS_TIMEOUT_MS=60000`, `STREAM_READINESS_MAX_TIMEOUT_MS=90000`, `STREAM_ACTIVE_TIMEOUT_MS=1260000` | 생각이 긴 모델과 긴 에이전트 턴 대응 |
| 자동 제한 | `RATE_LIMIT_AUTO_ENABLE=false` | 요청 제한은 콤보와 키 단위로 직접 관리 |
| 맥락 창 재조정 | `CONTEXT_WINDOW_RECONCILE_INTERVAL=0` | 끔 |
| RTK 필터 | `OMNIROUTE_RTK_ENABLED_FILTERS` (git, shell, docker, test, stacktrace 등 23종) | 도구 출력 압축 대상 |
| 헬스체크 | `node healthcheck.mjs`, 120초 간격 | 첫 기동은 1~4분 소요 가능 |

> [!WARNING]
> 업데이트 전에는 반드시 DB(`storage.sqlite`)를 스냅샷하고 이전 이미지 태그를 남겨두세요. 버전이 바뀌면 DB 마이그레이션이 앞으로만 진행되어 되돌릴 수 없습니다.

---

## 3. 전역 설정 (기본값에서 바꾼 항목)

| 설정 | 값 | 의미 |
|---|---|---|
| `requireLogin` / `REQUIRE_API_KEY` | 켬 | 대시보드는 로그인, API는 키 필요 |
| `comboStrategy` | `fallback` | 기본 콤보는 순서대로 다음 대상으로 대체 |
| `promptCacheAffinityEnabled` | 켬 | 같은 대화를 같은 계정으로 보내 캐시 적중률 향상 |
| `geminiPromptCacheMode` | `implicit` | Gemini 자동 캐시 사용 |
| `stickyRoundRobinLimit` | `3` | 라운드로빈 콤보에서 같은 대상을 3번까지 연속 사용 |
| `connectionAwareExpansion` | 켬 | 계정이 여러 개면 계정 단위로 펼쳐 대체 |
| `requestRetry` / `maxRetryIntervalSec` | `1` / `3초` | 짧게 한 번만 재시도 |
| `autoRefreshProviderQuota` | 켬, `180초` | 제공자 남은 한도 자동 갱신 |
| `comboAutoPromoteEnabled` | 켬 | 잘 응답하는 대상을 앞으로 승격 |
| `localOnlyManageScopeBypassEnabled` | 켬 | 호스트 내부 관리 API는 manage 키 없이 허용 |
| `proxyEnabled` / `defaultNewConnectionProxyEnabled` | 켬 | 연결별 프록시 사용 |
| `modalityBridgeVisionEnabled` | 켬 (`agy/gemini-3.8-flash-medium`) | 이미지 미지원 모델에 이미지 입력 시 대신 설명 |
| MCP / A2A / memory / skills / cloud | 끔 | Hermes가 직접 처리 |

---

## 4. 기능 플래그 (기본값에서 바꾼 8개)

| 플래그 | 값 | 이유 |
|---|---|---|
| `CLAUDE_CACHE_TAIL_TTL_1H` | `true` | 대화가 5분 넘게 쉬어도 Claude 캐시 유지 |
| `ANTIGRAVITY_ACCOUNT_LEASE_ENABLED` | `true` | 여러 Antigravity 계정을 스트림마다 하나씩 점유해 충돌 방지 |
| `STREAM_RECOVERY_ENABLED` | `true` | 응답 시작 전 끊기면 조용히 재시도 |
| `STREAM_EARLY_EOF_SIBLING_FAILOVER_ENABLED` | `true` | 출력 없이 닫힌 스트림은 다른 계정으로 1회 넘김 |
| `USAGE_LIMIT_IGNORE_UNPRICED` | `true` | 가격 없는 모델(무료·구독)은 USD 한도에서 `$0`으로 계산 |
| `UNPRICED_USAGE_BUDGET_POLICY` | `count_as_zero` | 위와 동일 |
| `REQUIRE_API_KEY` | `true` (env) | 키 없는 요청 거부 |
| `RATE_LIMIT_AUTO_ENABLE` | `false` (env) | 자동 제한 끔 |

**의도적으로 켜지 않은 항목**
- `STREAM_RECOVERY_MIDSTREAM_ENABLED`: 도구 호출 중복 위험.
- `COMBO_AUTO_PRUNE_STALE_STEPS`: 호스트 스크립트가 관리하는 콤보와 충돌.
- PII 가리기·주입 방어: Hermes 측에서 처리.
- `UNIVERSAL_CONTEXT_HANDOFF_ENABLED`: 기본값(켬) 유지.

---

## 5. 압축 프록시 & 출력 스타일 묶음

OmniRoute 압축은 가볍게만 사용합니다. 큰 압축은 Hermes 플러그인 `rtk-rewrite`가 전송 전에 이미 90% 이상 처리합니다.

| 항목 | 값 |
|---|---|
| 전역 | `enabled=true`, `defaultMode=rtk`, `autoTriggerMode=lite`, `cacheMinutes=5` |
| 시스템 프롬프트 | `preserveSystemPrompt=always` (캐시 앞부분 보존) |
| 켠 엔진 | `rtk`(standard)만 활성화 (`session-dedup`, `headroom` 등은 프롬프트 캐시를 깨므로 전역 비활성화) |
| RTK 범위 | 도구 결과에만 적용 (코드 블록·assistant 메시지 제외, 결과당 최대 120줄 / 12,000자, 동일 줄 3회 초과 시 접음) |
| MCP 설명 압축 | 켬 |

원칙은 **사람이 직접 읽는 곳은 말투를 건드리지 않고, 기계(하위 에이전트)가 읽는 곳만 짧게**입니다.

| 묶음 | 파이프라인 | 캐이브맨 출력 | 출력 스타일 | 붙인 콤보 |
|---|---|---|---|---|
| **Agent — caveman + adhd** | `rtk` | `lite` | `i-have-adhd`, `terse-prose` | `role-worker`, `hermes-private`, `role-fast`, `role-reason`, `role-ultrabrain`, `role-fusion`, `role-reason-fusion`, `role-private-panel`, `role-web-leaf`, 공개 무료 풀 |
| **Worker/Coding** | `rtk + headroom` | `lite` | `i-have-adhd`, `terse-prose`, `less-code`, `ponytail` | `role-coding`, `role-intelligent-coding`, `role-fusion-coding`, `role-code-omh` |
| **Writing — antislop copy** | `rtk` | 없음 | `antislop-copy` | `role-writing` |
| **Visual — antislop UI** | `rtk` | `lite` | `antislop-ui`, `i-have-adhd` | `role-visual-engineering` |
| **RTK — tool output only** | `rtk` | 없음 | 없음 | `role-chat` (메인) |
| **hermes-tool-context** (기본값) | `session-dedup + rtk + headroom + lite` | 없음 | 없음 | `role-chat-fallback` |

> 메인 대화(`role-chat`, `role-chat-fallback`), 메인 맥락 유입(`role-compress`, `role-vision`, `role-private-lite`), 최종 글(`role-writing`)에는 캐이브맨을 붙이지 않습니다.

---

## 6. 콤보 설계

콤보 이름은 역할 단위(`role-*`)로 짓고, Hermes 설정에는 역할 이름만 적습니다. 모델을 바꿀 때는 Hermes를 건드리지 않고 콤보만 수정합니다.

| 콤보 | 쓰는 곳 | 전략 | 대상 수 | 대상 / 전체 제한 |
|---|---|---|---|---|
| `role-chat` | 메인 대화 | `priority` | 13 | 15초 / 90초 |
| `role-chat-fallback` | 메인 대비 | `priority` | 6 | 15초 / 90초 |
| `role-worker` | 위임(하위 에이전트) | `round-robin` | 8 | 30초 / 90초 |
| `role-intelligent-coding` | coder 봇 | `priority` | 7 | 30초 / 90초 |
| `role-coding` | 코딩 작업 | `weighted` | 8 | 30초 / 90초 |
| `hermes-private` | 판정(goal judge 등) | `priority` | 7 | 20초 / 75초 |
| `role-compress` | 대화 요약 | `priority` | 4 | 40초 / 120초 |
| `role-writing` | 글쓰기 | `weighted` | 7 | 30초 / 90초 |
| `role-vision` | 이미지 이해 | `priority` | 5 | 20초 / 60초 |
| `role-fast` | 짧고 빠른 작업 | `weighted` | 5 | 15초 / 45초 |
| `role-reason` | 추론 | `weighted` | 9 | 30초 / 90초 |
| `role-fusion`, `role-reason-fusion` | 여러 모델 답 합치기 | `fusion` | 4 | 패널 최대 4 |
| `role-ultrabrain`, `role-private-panel` | 최상위 판단 | `priority` | 4~6 | 90초 / 150초 |
| `role-visual-engineering` | UI 작업 | `priority` | 6 | 60초 / 120초 |
| `role-web-leaf`, `role-free` | 공개 무료 작업 | `round-robin` | 5~34 | 15~18초 / 60~90초 |

### 콤보 공통 규칙
- `failoverBeforeRetry: true`, `maxRetries: 0`, `maxGlobalAttempts` 4~14.
- `allowedProviders`: 개인 정보가 가는 콤보에는 학습에 쓰지 않는 제공자만 허용.
- 생각이 긴 모델(`-high` 등)은 1순위에 두지 않음.
- `fusion` 콤보에서 4개 이상 패널을 쓰려면 `config.fusionTuning.maxPanel` 상향 필요.
- 콤보에 넣기 전 해당 제공자가 직접 응답했는지 로그로 확인(OmniRoute 폴백으로 겉으로는 200이 나올 수 있음).

---

## 7. 제공자 그룹 분리

| 그룹 | 제공자 | 쓰는 곳 |
|---|---|---|
| **개인 허용 (private)** | OAuth 구독: `claude`, `codex`, `agy`, `antigravity`, `kiro`<br>API 키: `mistral`, `cohere`, `scaleway`, `cloudflare-ai`, `exaone`(학습 미동의) | 메인, 위임, 판정 등 개인 데이터가 가는 모든 콤보 |
| **학습·무료 집계 (public only)** | `openrouter`, `cline`, `kilocode`, `kilo-anon`, `orcarouter`, `electronhub`, `nvidia`, `inception` 등 | 공개 자율·무료 풀 전용 (개인 콤보 혼입 차단) |
| **기타 API 키** | `gemini`, `opencode-go`, `pollinations`, `agnes`, `agentrouter`, `aion`, `morph`, `vercel-ai-gateway` 등 | 용도별 선택 배치 |

- 연결마다 `importFreeModelsOnly`, `autoFetchModels`, `autoSync`를 켜두면 카탈로그에 무료 모델만 유지됩니다.

---

## 8. 무료 모델 검증 & 운영 자동화

- **가져오기 → 도구 호출 증명 → 배치** 파이프라인을 주기 실행하고, 모든 스크립트는 `.maintenance.lock`으로 상호 배제합니다.
- 학습 제공자가 개인 콤보에 들어가면 즉시 중단하고, 개인 풀 무료 후보가 비면 `role-private-lite`로 폴백합니다.
- "모델이 더 이상 없다"를 HTTP 200으로 반환하는 모델은 별도로 차단합니다.

---

## 9. Hermes 측 연동 (`config.yaml`)

| 설정 | 값 | 비고 |
|---|---|---|
| 기본 제공자 | `provider: omniroute`, `http://omniroute:20128/v1` | 키는 `.env`의 `OMNIROUTE_API_KEY` |
| 기본 헤더 | `x-omniroute-no-cache: "true"` | 응답 캐시 끄고 프롬프트 캐시만 사용 |
| 메인 모델 | `role-chat` | 프로필별 역할 지정 (`coder` → `role-intelligent-coding`, `creator` → `role-writing`) |
| 위임 | `delegation.model: role-worker`, 동시 5개, `require_task_routing: true` | 전체 프로필 공통 |
| 보조 작업 | `goal_judge`/`kanban_decomposer` → `hermes-private`(75초), `title_generation` → `role-private-lite`(30초) | `configured_routes_only: true` |
| 도구 숨김 | `tools.tool_search.defer` (브라우저 등 33개) | 메인 턴당 약 8,300자 절감 |
| 대화 압축 | `threshold_tokens: 50000`, `target_ratio: 0.15`, `protect_last_n: 8`, `proactive_prune_tokens: 40000` | `role-compress` 콤보 사용 |
| 도구 출력 상한 | `tool_output.max_bytes: 3500`, `max_lines: 100` | `rtk-rewrite` 플러그인이 선압축 |

---

## 10. 복제 순서

1. [advanced/docker-compose.omniroute.yml](../advanced/docker-compose.omniroute.yml)로 OmniRoute `3.8.54` 원본 이미지를 기동하고 `hermes-kit` 네트워크에 연결합니다.
2. 대시보드 로그인 후 Hermes용 API 키를 생성합니다.
3. 구독형은 OAuth, 나머지는 API 키로 연결하고 `importFreeModelsOnly`를 켭니다.
4. 개인 허용 제공자 목록을 확정하고 역할 콤보(`role-chat`, `role-worker` 등)를 생성합니다.
5. 4장의 기능 플래그 8개와 5장의 압축·출력 스타일 묶음을 적용합니다(메인 대화에는 캐이브맨 미적용).
6. Hermes `config.yaml`에 base URL, `x-omniroute-no-cache: "true"` 헤더, 역할 이름, 위임·보조 작업 경로, 도구 숨김 목록을 반영합니다.
7. 대표 콤보마다 텍스트·도구 호출·JSON·스트리밍을 1회씩 시험하고 OmniRoute 로그에서 의도한 제공자가 직접 응답했는지 확인합니다.
