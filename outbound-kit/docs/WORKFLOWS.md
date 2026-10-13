# 실행 가능한 아웃바운드 워크플로

`workflow.py`는 선택한 소스를 읽고 정규화된 근거, 보수적 점수, 초안, Obsidian
검토 노트까지 만든다. 메시지 발송, CRM 쓰기, 로그인 우회는 하지 않는다.

## 시나리오

| 새 ID | setup.json 호환값 | record type | live 범위 |
|---|---|---|---|
| `job_signal` | `jobs` | `job_posting` | 공개 Greenhouse/Lever/Ashby board slug |
| `funding_signal` | `funding` | `funding_signal` | 제한된 공개 Platum WordPress 후보 수집 |
| `tender_watch` | `tenders` | `procurement` | 현재는 공식 export의 file 모드 |
| `overseas_partner` | `overseas` | `overseas_partner` | 현재는 공식 export의 file 모드 |

지원하지 않는 live 모드는 빈 성공으로 위장하지 않고 실패 상태와 file export 안내를
반환한다. 접근 차단, rate limit, 응답 형식 변경도 `empty`와 구분된다.

## 가장 단순한 실행

```bash
python workflow.py run \
  --config setup.json \
  --home ~/.hermes-outbound \
  --output ./output \
  --vault ./OutboundVault \
  --source-mode sample \
  --draft-mode template
```

`--scenario`를 생략하면 `workflows`에 선택한 항목을 모두 실행한다. `file` 모드는
입력 경로가 어느 시나리오용인지 명확하도록 `--scenario` 하나를 요구한다.

```bash
python workflow.py run --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ./OutboundVault \
  --scenario tender_watch --source-mode file --source-path ./tenders.csv
```

CSV/JSON은 최소 `company`, `title`, `url`을 권장한다. 회사가 없으면 식별 확인
단계에서 차단된다. `source`, `source_id`, `published_at`, `location`, `description`을
제공하면 근거 품질이 높아진다. 채용 파일은 `stack`도 받는다.

## 초안 모드

- `template`: 제품·고객 프로필을 포함한 규칙 기반 초안이다. AI 결과로 표시하지 않는다.
- `hermes`: 이 설치 홈이 소유한 Hermes launcher만 사용한다. 공식 one-shot 계약
  `hermes chat --query-file PATH --oneshot --quiet --format text`를 호출한다.
- `provided`: 외부 AI 또는 사람이 만든 결과를 검증해 가져온다.

provided 파일 계약:

```json
{
  "drafts": {
    "source-id-1": "검토할 초안 본문"
  }
}
```

쓰기 전에 계약만 검사할 수도 있다.

```bash
python workflow.py draft-import --input ./drafts.json
```

모든 source record의 초안이 있어야 쓰기를 시작한다. 빈 결과, 12,000자를 넘는 본문,
알 수 없는 형식은 실패한다.

## 산출물과 검토

각 실행은 새 `run-*` ID를 만들고 output에 source envelope과 다음 계약을 저장한다.

- `records`: 정규화된 사실 후보
- `scores`: product/customer 용어 일치, urgency, field coverage. 근거가 없으면 `unknown`
- `sourceEvidence`: source, URL, source ID, 수집 시각, raw SHA-256
- `automatic_send: false`

볼트의 `Inbox/Brief.md`는 최초 생성만 하며 제품, 고객, 캠페인, 언어에서 만든다.
동일 회사의 여러 공고/공고문은 서로 다른 Evidence 노트로 남고 Account의
`evidence_ids`에 누적된다. 새 실행이 과거 evidence를 지우지 않는다.

Review는 사람 소유 파일이다. 승인에는 현재 draft body의 SHA-256이 필요하다.
제품·고객 프로필이나 초안 본문이 바뀌면 해시가 바뀌므로 이전 승인은
`invalidated`가 된다. 실제 발송은 별도 수동 승인 이후에도 이 러너가 수행하지 않는다.
