# Source → Obsidian Vault 데모

이 데모는 공개 소스 adapter의 JSON envelope를 파일로 고정한 뒤 Obsidian 볼트 workflow에 넣는다.
메일·DM·CRM 쓰기는 없고, 생성되는 Draft는 규칙 기반 교육용 템플릿이다. 사람 승인이 있어도 자동 발송하지 않는다.

## 1. 준비

키트 루트에서 실행한다. Python 3.10 이상만 필요하며 외부 패키지는 설치하지 않는다.

```bash
python3 -m unittest tests.test_sources tests.test_vault_flow -v
python3 vault_flow.py init --vault /tmp/hermes-outbound-demo-vault
```

`init`은 다음 경로를 만든다.

- `/tmp/hermes-outbound-demo-vault/Inbox/Brief.md`: 사람이 작성하는 캠페인 브리프
- `Accounts/`, `Evidence/`, `Scores/`, `Drafts/`, `Runs/`: 러너가 관리하는 노트
- `Review/`: 사람이 검토하고 결정하는 노트
- `Dashboard.md`: 현재 run과 다음 작업
- `.hermes-outbound/state.json`: 멱등 재실행을 위한 상태

기존 사람 작성 Brief와 Review 노트는 다시 실행해도 덮어쓰지 않는다.

## 2. 외부망 없는 source 생성

마법사 설정을 적용한 채용 fixture를 실행하고 stdout JSON을 파일로 저장한다.

```bash
python3 sources.py jobs-import samples/source-jobs.csv \
  --config setup.example.json \
  --as-of 2026-10-13T10:00:00Z \
  > /tmp/hermes-source-envelope.json
```

`--config`는 장식용 옵션이 아니다. `workflows`, `job_keywords`, `exclude_keywords`, `region`이 레코드를
실제로 남기거나 제외하며, 결과의 `metadata.filters`에 입력·유지·제외 사유별 건수가 기록된다. 실제 워크숍에서는
`setup.example.json` 대신 설치 마법사가 만든 `setup.json`을 사용한다.

다른 합성 source를 사용하려면 위 명령만 교체한다.

```bash
python3 sources.py funding \
  --fixture samples/source-funding-wp.json \
  --config setup.json \
  --as-of 2026-10-13T10:00:00Z \
  > /tmp/hermes-source-envelope.json

python3 sources.py ats \
  --provider greenhouse \
  --token example \
  --company "Example Co" \
  --fixture samples/source-ats-greenhouse.json \
  --config setup.json \
  --as-of 2026-10-13T10:00:00Z \
  > /tmp/hermes-source-envelope.json
```

fixture는 합성 데이터이며 실제 회사나 실제 공고의 증거가 아니다.

## 3. Source envelope을 볼트에 반영

```bash
python3 vault_flow.py run \
  --vault /tmp/hermes-outbound-demo-vault \
  --input /tmp/hermes-source-envelope.json

python3 vault_flow.py status --vault /tmp/hermes-outbound-demo-vault
```

`run`은 파일 입력만 받는다. shell pipe를 직접 받지 않는 이유는 수집 당시 envelope과 SHA-256 근거를
재현 가능한 파일로 남기기 위해서다. envelope의 `source`는 한 번의 import/수집 작업 이름이고, 각 record는
서로 다른 `source`를 가질 수 있다. 단, 각 record의 `source`, `source_id`, `url`은 그 record의 evidence와
정확히 일치해야 한다. 불일치하면 볼트에 쓰기 전에 거부한다.

자동 실행에서는 source 실패 뒤 낡은 envelope을 처리하지 않도록 성공 조건으로 연결한다.

```bash
python3 sources.py jobs-import samples/source-jobs.csv --config setup.json \
  > /tmp/hermes-source-envelope.json && \
python3 vault_flow.py run --vault /tmp/hermes-outbound-demo-vault \
  --input /tmp/hermes-source-envelope.json
```

- source `ok`와 `empty`는 종료 코드 0이다. `empty`도 “정상적으로 확인했지만 0건”인 run receipt를 남긴다.
- `blocked`, `failed`, `invalid_response`는 각각 0이 아닌 종료 코드이므로 `&&` 뒤의 vault 실행을 막는다.
- 실패 envelope 자체를 감사 기록으로 남겨야 할 때는 명령을 분리해 파일을 보존한 후 `vault_flow.py run`을
  명시적으로 실행한다. vault는 이를 성공이나 0건으로 바꾸지 않고 `blocked` outcome으로 기록한다.
- 같은 envelope을 다시 실행하면 같은 `run_id`를 사용하며, machine-owned 노트만 멱등 갱신한다.

## 4. 2026-10-13 실행 확인 결과

아래 조합을 이 저장소에서 실제 실행했다.

```text
source: company-export
source_status: ok
필터 입력: 2건
필터 유지: 1건
outcome: review_required
completed: false
stage: identity_blocked
```

유지된 합성 공고에는 확인된 회사명이 없었기 때문에 `Accounts`, `Evidence`, `Scores`, `Drafts`, `Review`의
완료 체인을 만들지 않았다. 대신 `Inbox/run-ebc146113e574a-source.md`와 `Runs/run-ebc146113e574a.md`에
“회사 후보 확인” 다음 작업을 남겼다. 이것이 이 입력의 올바른 결과다. 회사명을 추정하거나 초안 성공으로
꾸미지 않는다.

서로 다른 `public-board-a`, `public-board-b` 값을 가진 2행의 임시 합성 CSV도 source CLI에서
`source=mixed-job-import` envelope로 만든 뒤 새 볼트에 실제 반영했다. 두 Evidence 노트는 각 record의
서로 다른 source를 유지했고, 두 Review는 모두 `pending`, run은 `outcome=review_required`,
`completed=false`였다. 즉 혼합 출처 허용은 승인이나 발송 완료를 뜻하지 않는다.

회사가 명시된 합성 seed로 UI 전체를 보여줄 때만 다음을 별도 실행한다.

```bash
python3 vault_flow.py run --vault /tmp/hermes-outbound-demo-vault
```

입력을 생략하면 `pack/vault/seed/normalized-records.json`을 사용한다. 이 경로의 Draft도 AI 생성 또는 발송
완료를 뜻하지 않으며, `Review/*.md`의 사람 검토가 남아 있어 `completed=false`다.

## 5. 라이브 확인 경계

라이브 확인은 요청량을 작게 유지한다.

```bash
python3 sources.py funding --pages 1 --per-page 3 --config setup.json \
  > /tmp/hermes-source-envelope.json
```

401/403/429, CAPTCHA, 로그인 요구, 네트워크 정책 차단이 나오면 멈춘다. 프록시, 다른 계정, 브라우저
자동화로 우회하지 않는다. 이 환경의 funding smoke는 egress tunnel 403 때문에 `failed`로 끝났으며,
라이브 가용성이 확인됐다고 주장하지 않는다.
