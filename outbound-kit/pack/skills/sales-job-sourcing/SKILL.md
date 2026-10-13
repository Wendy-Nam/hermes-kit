---
name: sales-job-sourcing
description: 사람인·원티드·공개 ATS의 채용공고를 회사의 활동 신호 후보로 수집하고 근거와 함께 영업 조사로 넘긴다.
license: MIT
metadata:
  category: sales
  locale: ko-KR
---

# Sales Job Sourcing

공개 채용공고를 바잉 시그널 **후보**로 수집한다. 채용은 회사가 움직이고 있다는 근거일 수 있지만 예산,
구매 의사, 담당자의 연락 허가를 증명하지 않는다. 이 스킬은 조사와 초안까지만 수행하며 발송하지 않는다.

## 입력 선택

`setup.json`의 `workflows`에 `jobs`를 넣고 실행 방식을 명시한다.

- `source_mode=sample`: 합성 실습 자료. 실제 회사 신호가 아니다.
- `source_mode=file`: 사용자가 제공한 CSV/JSON export. `source_path`가 필요하다.
- `source_mode=live`: `jobs_provider`를 `wanted`, `saramin`, `both`, `ats` 중 선택한다.
- Wanted/Saramin은 `jobs_query`가 필요하다. `both`는 같은 검색어로 두 곳을 각각 한 번씩 제한 조회한다.
- ATS는 `ats_provider`, 공개 `ats_board` slug, 표시용 `ats_company`가 필요하다. 비밀 API 키가 아니다.

`source_mode`를 생략하지 않는다. 라이브를 의도했는데 합성 샘플이 실행되는 일을 막기 위해 실행기는
CLI와 설정 모두에 값이 없으면 실패한다.

## 실행

키트 루트에서 evidence-first 전체 흐름을 실행한다.

```bash
python3 workflow.py run \
  --config setup.json \
  --home "$HERMES_HOME" \
  --output ./outbound-runs \
  --vault ./Outbound-Vault \
  --scenario job_signal \
  --source-mode live \
  --draft-mode template
```

수집기만 확인하려면 다음처럼 제한한다.

```bash
python3 sources.py wanted "산업용 AI 영업" --limit 10 --config setup.json
python3 sources.py saramin "해외영업" --limit 10 --config setup.json
```

네트워크 없이 파서 계약을 확인할 수 있는 합성 fixture:

```bash
python3 sources.py wanted "영업" --fixture samples/source-wanted.json \
  --as-of 2026-10-13T10:00:00Z
python3 sources.py saramin "영업" --fixture samples/source-saramin.html \
  --as-of 2026-10-13T10:00:00Z
```

## 판정 규칙

1. `ok`만 새 조사 후보로 넘긴다. `empty`는 정상 조회 0건이다.
2. `blocked`, `failed`, `invalid_response`는 0건이 아니다. 중단하고 원인을 그대로 보고한다.
3. `both`에서 한 곳이라도 실패·차단·형식 변경이면 부분 결과를 완전한 결과로 저장하지 않는다.
4. 회사명, 위치, 날짜, 기술 스택이 없으면 `null`을 유지한다.
5. `source_id`, URL, 조회 시각, 원자료 SHA-256을 evidence로 보존한다.
6. 회사 동일성과 최근성은 원문에서 사람이 확인한 뒤 초안에 사용한다.
7. 로그인, CAPTCHA, 유료벽, 접근 차단, rate limit을 우회하지 않는다. 프록시 회전도 하지 않는다.
8. 자동 메일·DM 발송, CRM 쓰기, 입사지원은 하지 않는다.

## 결과 사용

`metadata.filters`에서 키워드·제외어·지역 필터의 입력/제외/유지 건수를 확인한다. `review_required=true`이면
회사명을 먼저 검증한다. 초안은 `Drafts/`에서 사람이 근거 URL과 문구를 승인한 뒤 별도 도구로 보내며,
이 스킬은 승인 상태를 발송 권한으로 해석하지 않는다.

