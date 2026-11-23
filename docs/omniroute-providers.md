# OmniRoute 공급자 참고 카탈로그 및 프라이버시 분류

> **수강생 안내:** 아래 31곳은 강사 운영 환경에서 검증한 **참고 카탈로그(선택지 모음)**입니다. 전부 따라 연결할 필요가 전혀 없습니다. 본인이 가진 구독/API 키 1~2개만 연결해도 `/setup`의 **2. 모델 고르기**나 **추천 가용 리소스 콤보 자동 셋업**이 **내가 연결한 제공자만 골라서** 자동으로 콤보를 만들어 줍니다. 무료 풀을 더 확보하고 싶을 때 참고용으로 골라 쓰세요.

OmniRoute에 연결할 수 있는 공급자의 분류 기준과 운영 노트를 정리한 문서입니다. [OmniRoute 라우팅 설정 가이드](omniroute-setup-guide.md)와 함께 참고하세요. API 키와 계정 정보는 포함하지 않습니다.

- 기준일: 2026-11-23
- 코드 반영 위치: [`plugins/kit-setup/omniroute_presets.py`](../plugins/kit-setup/omniroute_presets.py)의 `PRIVATE_PROVIDERS` / `TRAINING_FREE_PROVIDERS`

## 분류 기준

| 분류 | 뜻 | 규칙 |
|---|---|---|
| **개인 허용 (`PRIVATE_PROVIDERS`)** | 개인 데이터를 보내도 되는 곳(구독 계정 또는 입력 학습 미사용) | 메인, 위임, 판정 등 모든 개인 콤보에 사용 |
| **학습·무료 집계 (`TRAINING_FREE_PROVIDERS`)** | 무료 대신 입력을 학습에 쓸 수 있거나 출처가 섞인 집계 서비스 | **공개 작업 전용** (`hermes-free`, `role-web-leaf` 등). 개인 콤보 혼입 차단 |
| **그 밖** | 위 두 목록에 없는 공급자 | 약관 확인 후 용도에 맞게 선택 배치 |

---

## 1. 개인 허용 (9곳)

| 공급자 | 인증 | 특징 / 주로 쓰는 콤보 | 비고 |
|---|---|---|---|
| `claude` | OAuth (구독) | `role-chat`, `hermes-private`, `role-coding`, `role-ultrabrain` | Claude Sonnet·Opus 주력. 1시간 캐시 플래그 대상 |
| `codex` | OAuth (구독) | `role-chat`, `role-coding`, `role-fusion`, `role-ultrabrain` | GPT-6 계열 |
| `agy` | OAuth | `role-chat`, `hermes-private`, `role-compress`, `role-coding` | Antigravity 계열(Gemini·Claude) |
| `antigravity` | OAuth (다중) | `role-chat`, `hermes-private`, `role-compress` | 다중 계정 시 `ANTIGRAVITY_ACCOUNT_LEASE_ENABLED=true`로 충돌 방지 (`claude-*-high`는 404 빈발 주의) |
| `cohere` | API 키 | `hermes-private`, `role-compress`, `role-writing` | Command A 계열 |
| `mistral` | API 키 | `hermes-private`, `role-fast`, `role-private-lite` | 빠른 소형·코딩 모델 |
| `cloudflare-ai` | API 키 | `role-private-lite`, `role-free` | Workers AI |
| `scaleway` | API 키 | `hermes-private`, `role-chat-fallback` | Qwen3 대형 모델 |
| `exaone` (커스텀) | API 키 | `role-chat`, `hermes-private`, `role-writing`, `role-fast` | LG K-EXAONE 2.5 (`https://api.exaone.ai/v1`, `k-exaone_v2.5`, 학습 미동의) |

---

## 2. 학습·무료 집계 (11곳) — 공개 작업 전용

| 공급자 | 인증 | 비고 |
|---|---|---|
| `openrouter` | API 키 | `:free` 모델 위주 (`openrouter/auto`는 유료) |
| `kilocode` | OAuth | 무료 풀 |
| `nvidia` | API 키 | NIM 무료 모델 |
| `cline` | OAuth | 무료 풀 |
| `orcarouter` | API 키 | 무료 풀 |
| `inception` | API 키 | 무료 풀 |
| `electronhub` | API 키 | 동시 테스트 시 429 빈발 |
| `kilo-anon` (커스텀) | API 키 | `https://api.kilo.ai/api/gateway/v1` |
| `ovh-anon` (커스텀) | API 키 | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` |
| `clod` (커스텀) | API 키 | `https://api.clod.io/v1` |
| `dreamprompting` (커스텀) | API 키 | `https://dreamprompting.com/api/v1` |

---

## 3. 그 밖 (용도별 선택)

| 공급자 | 인증 | 비고 |
|---|---|---|
| `opencode-go` | API 키 | DeepSeek·GLM 계열, 메인·위임 대비용 |
| `kiro` | OAuth | Claude Sonnet 4.5, 코딩·위임용 |
| `gemini` | API 키 | Google AI Studio 키 (개인 허용 목록 제외 시 공개/보조용) |
| `vercel-ai-gateway` | API 키 | 광범위 모델 게이트웨이 |
| `pollinations` | API 키 | 이미지 등 |
| `agnes`, `sail`, `aion`, `morph`, `agentrouter`, `moondream` | API 키 | 특화 용도(코드 apply, 비전, 무료 폴백 등) |

> **주의 (`vertex`)**: Google Cloud 무료 체험 계정은 Gemini 호출이 403으로 막히므로 유료 결제 계정 전환 전까지 보류합니다.

---

## 4. 새 공급자 추가 체크리스트

1. OpenAI 호환 서비스는 대시보드에서 **OpenAI Compatible 노드**(이름·접두어·Base URL) 생성 후 연결에 API 키 등록.
2. 연결 옵션에서 `autoFetchModels`, `autoSync` 활성화(무료 전용이면 `importFreeModelsOnly` 추가).
3. 개인 허용 vs 학습·무료 집계 분류를 확정하고 `PRIVATE_PROVIDERS` / `TRAINING_FREE_PROVIDERS`에 반영.
4. 텍스트·도구 호출·JSON·스트리밍을 1회씩 시험하고 OmniRoute 로그(`call_logs`)에서 **해당 공급자가 직접 200을 반환했는지** 확인.
