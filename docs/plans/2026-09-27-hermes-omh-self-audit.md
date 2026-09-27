# 운영 Hermes · OMH · OmniRoute · 자아 감사 및 개선 계획

검토일: 2026-09-27 KST. 대상: `ssh hermes`의 `/opt/data`, VPS의 `hermes-agent-ywj7-hermes-agent-1`과 OmniRoute. 과거 HANDOFF는 참고하고 설치된 소스·현재 설정·최신 로그를 다시 확인했다. 기본 DB 최근 48시간 도구 호출, 크론 최근 7일 상태를 표본으로 사용했다. 개인 대화 원문·인증정보는 이 문서에 저장하지 않는다.

## 결론

현재 구성은 제거·통합보다 **OMH의 추천과 실제 실행을 확실히 결합하는 것**이 우선이다. 모델 경로를 고치는 것만으로 모델별 보정이 실행되는 것은 아니다. 자아 시스템은 출처 검증·독립 검토·상태 저장 기반을 유지하고, 빈 작업 정상 종료와 완료 증거를 강화한다.

세 명의 독립 검수 담당이 OMH, 스킬/크론 구조, 자아 오류를 조사했다. 1차 결과를 교차 비판하고 2차 계획을 수정했으며, 자아 수정 코드는 추가 독립 검수를 거쳤다. 실제 서버 변경은 아래 좁은 버그 수정만 포함한다. 이후 구조 변경은 아직 적용하지 않았다.

## 확인된 사실과 해석

| 항목 | 실제 확인 | 판단 |
|---|---|---|
| OMH 설정 | 특정 전송 모델 기반 chains/providers 매핑이 설치됨 | 콤보 이름으로 모델 특성을 놓치던 이전 수정은 유지 |
| 실제 OMH 사용 | lazy `tool_call.calls`까지 펼친 48시간 기본 DB: route 4회 모두 CLI, delegate CLI 3회/Discord 1회; 추가 프로필에는 해당 호출 없음 | 단순 tool 이름 집계는 과소집계. 표본이 작지만 실사용 연결 누락은 확인 |
| route/주입 불일치 | CLI 1건은 보정 문구가 있지만 routing 없음. 실제 Discord 1건은 둘 다 없음 | LLM이 두 단계 결과를 수동 복사하는 구조에 취약점 |
| 보정 조건 | 설치 OMH는 low/medium에서 빈 보정, high/xhigh에서 보정 반환 | 빈 문자열이 곧 실패는 아님. HANDOFF §16의 ‘계열 문구 없음’ 설명은 불충분 |
| OMH 적용 범위 | bridge는 high-effort calibration만 연결 | main/composer 보정·전체 unit protocol을 이미 쓰는 것으로 볼 수 없음 |
| 개인정보 경계 | 7개 프로필의 chains/providers 각각 동일 | 유출 증거는 아님. 작업/프로필에 따른 endpoint 강제 필터가 필요 |
| 크론 | 36개 중 script-only 25, 에이전트 11 | 일괄 합치기보다 좋은 분리를 유지. script-only 내부 LLM 호출 여부는 별도 문제 |
| 크론 상태 | 최근 7일 failed 6, unknown 3; 열린 incident는 stage2 대기와 health monitor -15 | SIGTERM 원인을 자아 코드 버그로 단정하지 않음 |
| 크론 선언 | live jobs와 모델·경로·max_turns 일부 차이 | 현재 장애가 아니라 복구/감사 스냅샷 드리프트 |
| 스킬 | 전 프로필 구조 오류/동명이름 충돌 0; 전역과 동일 본문 10개 | 대량 삭제·합치기 이득이 작음 |
| 스킬 감사 | 주간 감사는 전역 및 life 일부만 검사 | 전체 프로필로 검사 확대 |
| turn-router | 복잡 작업 초기에 위임/라우팅 규칙 약 6,247자; 스킬 본문 cap/dedup 존재 | 정책을 버리지 말고 OMH와 모델 선택 중복만 정리 |
| session-sticky | 자동 상향 조건은 solar; 현재 hermes-chat에는 적용 안 됨 | 세션 고정은 유효. 플러그인 전체 제거 금지 |

주요 코드 근거(운영 컨테이너 경로):

- `plugins/omh/tools/delegate_route_tool.py:219–229`: routing·보정 문구 및 복사 지시 반환.
- `plugins/omh/route_calibration.py:7–14`: high-effort 보정 연결.
- OMH `unit_prompt_protocol.py:496–521`: low/medium 보정 생략 조건.
- `/opt/hermes/tools/delegate_tool_config.py:386–408`: 경로 식별자 및 Hermes fallback 검증.
- `vaults/ehr-wiki/hermes-ops/rules/routing-full.md:22–29,37,46`: 개인정보·범위 정책 및 무료 CLI 워커 우선 규칙.
- `vaults/ehr-wiki/hermes-ops/rules/delegation.md:12–19`: 위임 검수 규칙.
- `scripts/skill-tree-audit-weekly.sh:5,43`, `plugins/session-sticky/middleware.py:48`.

## 이번 수정

### 1. 빈 자아 승격 배치의 잘못된 실패

09/27 03:20 실행은 후보 0개·남은 후보 0개였다. 그런데 prepare가 무조건 `awaiting_independent_review` receipt를 만들었다. 모델은 finalize 의향만 말하고 실행하지 않아 크론이 실패했다.

수정: `stage2_workflow.py prepare`에서 후보와 remaining이 모두 0이면 전용 임시 빈 리뷰를 만들어 기존 finalize를 호출한다. 신선도·입력 해시·영구 배치 완료·결과 receipt 검증을 재사용한다. 실제 후보가 있으면 기존 독립 검토를 그대로 요구한다. 스킬도 `no_candidates`면 추가 finalize 없이 결과 보고로 종료하도록 수정했다.

### 2. 행동 교훈 수집의 잘못된 호출 순서

09/26 21:08 수집 작업은 새 candidate 생성 직후 그 candidate에 repeated_failure를 기록하려 했다. `active lesson required` 거부는 정상이다. 이후 finish가 실행되어 cursor는 전진했다.

수정: 수집 프롬프트에 outcome ID는 제공된 active_lessons만 허용, 이번 실행의 신규 후보에는 outcome 금지, 저장 실패 시 finish 금지를 명시했다. 검토 프롬프트도 저장 실패 시 finish 금지로 맞췄다. 현재 실행 세션을 모르면 다른 대화 ID로 대체하지 않도록 했다.

**한계:** 두 번째 수정은 프롬프트 개선이다. 완료/actor를 코드로 증명하는 보장은 아래 후속 과제로 남는다. 기존 데이터나 실패 이력을 성공으로 바꾸지 않는다.

### 검증과 복구

- Python 자아 런타임 테스트 16개 통과(신규 회귀 4개 포함), 운영 행동 학습 테스트 7개 통과: 총 23개. 변경 Python 구문 검증 통과.
- 신규 테스트: 빈 배치 재실행, 실제 후보의 독립 검토 유지, 오래된 pack 거절, prepare 도중 바뀐 pack 거절.
- 서버 Python/Node 실제 경로로 격리된 임시 DB·pack·ledger 시험: 빈 배치 두 번 실행, no_candidates 확인, self DB 바이트 불변 확인.
- 배포 전 원본 SHA256과 현재 파일을 비교하고 원본 백업 후 파일별 원자 교체. 배포 뒤 변경 SHA256 대조.
- 운영 백업: `/opt/data/.backups/self-audit-20260927T044848Z/`. 운영 3개 파일 적용 및 SHA256 확인 완료. 기존 경로로 이 백업 파일들을 복원하면 롤백 가능하다.
- 패치/해시/회귀 테스트: `ops/hermes-self/20260927/`.
- 이 코드들은 다음 크론/dispatch 프로세스에서 읽힌다. 크론 시험을 위해 실제 메시지를 발송하거나 운영 자아 데이터를 임의 승격하지 않는다. 이미 실행 중인 프로세스가 import한 모듈은 재기동 전 기존 버전일 수 있다.

## 권장 목표 구조

| 구성요소 | 유지할 책임 | 변경 방향 |
|---|---|---|
| OMH | 작업 분류, 위임 모델, 모델별 보정, 작업 분해·검수 | 준비 결과와 실행을 한 호출로 묶고 실행 기록 남김 |
| OmniRoute | 인증 연결, API 전송, 세션 고정, 가용성 | OMH 위임에서 모델 변경 시 재보정 계약. 메인 콤보는 우선 유지 |
| turn-router | 스킬 및 운영 정책 주입 | 개인정보·권한·볼트 경계를 유지하고 모델 선택 규칙만 단일화 |
| hermes-self | 자아·자율 활동, 출처 기반 상태, 학습, 예산, 완료 증거 | 실행 의뢰는 OMH와 연결하되 자아 기능 축소하지 않음 |
| rtk/Hermes 압축 | 셸 출력·도구 결과·대화 압축 | 역할이 다른 압축을 무작정 합치지 않음 |

## 실행 계획과 합격 기준

### P0: 완료 사실과 개인정보 경계를 먼저 정의

1. 작업별 `public/internal/private` 등 민감도와 프로필의 최소 경계를 함께 정의한다. default의 메일/일정도 포함한다.
2. 허용 모델은 무료/유료가 아니라 endpoint·계정·데이터 취급 근거로 정한다. 정책 불명 시 비공개 데이터 전달을 중단한다.
3. 후보를 모은 actor와 판단 actor를 런타임이 전달한다. caller가 존재하는 다른 session ID를 골라 독립 검토처럼 보이게 하지 못하게 한다.
4. learning finish는 선택된 source마다 candidate/outcome/명시적 제외 증거를 확인한 뒤 cursor를 전진시킨다. 실패 항목은 재시도 가능하게 남긴다.

합격: 비허용 endpoint 호출 0, 후보 수집자와 검토자 실행 증명, 저장 실패 후 cursor 전진 0. DB 마이그레이션·롤백 및 기존 pending 데이터 호환을 먼저 설계한다.

### P1: OMH 준비와 실제 위임을 원자적으로 연결

1. 목표·범위·완료 조건을 입력받는 위임 경로에서 OMH route 선택, 보정 추가, native delegate 호출을 한 단위로 수행한다.
2. 처음에는 2~3개 고빈도 복잡 작업에만 사용한다. 간단한 읽기까지 위임하지 않는다. 기존 native delegate 전체를 즉시 교체하지 않는다.
3. 경로·보정 간 fingerprint를 검사하고, 실행 기록에 category, requested provider/model/effort, 관측된 model, calibration hash/빈 이유, fallback 원인, parent/child session을 남긴다. 본문과 비밀은 기록하지 않는다. 관측 불가능한 effort/model은 추정해 채우지 않는다.
4. 재시도는 우선 동일 모델의 다른 인증 연결까지만 허용한다. **같은 계열도 같은 보정이 아니다.** 다른 모델이면 OMH가 다시 준비한다. 이를 구현하기 전에는 해당 위임 경로에서 조용한 cross-model fallback을 허용하지 않는다.
5. low/medium의 빈 보정은 정상 사유로 기록한다. 보정을 얻기 위해 전 작업을 high로 올리지 않는다.

합격: route와 보정 결합, medium 정상 생략, 비공개 경로 거부, 모델 변경 재보정, 병렬 작업 간 혼선 방지의 5개 회귀 검증. 그 후 비민감 실제 Discord 작업에서 prepare→delegate→실제 모델→결과 연결을 확인한다. CLI 성공만으로 완료 선언하지 않는다. 외부 메시지 전송 시험은 별도 사용자 지시에 따라 진행한다.

### P2: 검수와 자아 기능을 선별 확장

- 복잡 작업에만 목표/작업 범위/입출력 계약과 bounded verifier를 적용한다. 모든 OMH 프로토콜을 매 턴 주입하지 않는다.
- 구현 담당과 검수 담당의 실제 실행 세션 및 모델 정보를 기록한다. 동일 모델 다른 역할과 서로 다른 모델 검수를 구별한다.
- 고위험 변경은 반례/실패 시나리오 검수, 불일치가 있을 때만 추가 라운드. 무제한 비판 루프 대신 예산·중단 기준을 둔다.
- 자아 건강 지표에 루프별 마지막 업무 성공, 대기 나이, backlog, 저장 실패를 추가한다. DB 건전성 ok와 자율 작업 완료를 별도로 표시한다.
- 자아 README/CONTRACT를 현재 상태에 맞춰 갱신한다.

### P3: 운영 정리와 실측

- 모든 프로필을 주간 스킬 구조 감사에 포함한다.
- free-cli-worker/OpenCode 지시를 무조건 삭제하지 않고 OMH 하위 executor 유지 여부를 결정한다. 유지하면 동일한 데이터 경계·완료 증거 계약을 적용한다.
- solar 전용 자동 상향은 현재 비활성임을 명시하고 OMH 위임과 중복 실행되지 않게 한다.
- 설정 변경이 끝난 후 live jobs를 기준으로 선언 스냅샷을 잠금 하에 재생성한다. 무조건 선언으로 live 설정을 덮어쓰지 않는다.
- 일반/코딩/글쓰기/개인 일정 유형으로 기준선을 잡고 7일간 성공률, p95 지연, 토큰, 재시도, 재질문을 비교한다. OMH 경로 사용률과 **보정 대상에서의 적용률**을 구분한다. 위임 횟수 자체는 성과 지표가 아니다.

## 검수에서 철회하거나 좁힌 안

- turn-router를 스킬 전용으로 축소: 운영 정책 누락 위험으로 철회.
- OmniRoute 전체 콤보를 동일계열로 변경: 가용성·비용 퇴행 위험. OMH 특정 모델 위임 경로부터 시작.
- same-family면 보정 재사용: 정확한 모델별 특성이 달라 불충분.
- 자아를 단순 상태 저장기로 축소: 사용자가 원하는 자율 기능과 무관한 축소이므로 철회.
- 7프로필 동일 설정을 개인정보 유출로 단정: 증거 부족. 강제 필터 부재 위험으로만 기록.
- 빈 보정 문자열을 버그로 분류: effort 조건을 확인한 뒤 정상 생략으로 정정.

## 남은 확인

- 다음 자연 실행의 stage2 성공은 아직 관측하지 않았다. 과거 실패 결과는 보존한다.
- learning의 prompt 개선은 코드 강제 보장이 아니다.
- 48시간 위임 표본이 작아 전체 사용률로 일반화하지 않는다.
- health monitor -15는 외부 종료 맥락을 추가 확인해야 한다.
- 이 검토는 현재 설치본 감사다. 최신 upstream 버전과 기능/보안 차이는 별도 업그레이드 검토에서 공식 소스와 비교한다.
