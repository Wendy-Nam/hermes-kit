# 국내 채용 소스 통합 근거

## 공개 donor

- 저장소: `Wendy-Nam/hermes-agent-kit` 및 동일 HEAD를 가리킨 것으로 확인된
  `Wendy-Nam/hermes-job-hunt-for-korean`
- 검토 커밋: `76e15170a2dc8b2bce270bd50e07287a14c3dd6b`
- 커밋 시각: `2026-09-24T23:34:12Z`
- 라이선스: MIT, Copyright (c) 2026 Wendy Nam (남서아)

개인 저장소, 개인 프로필, 지원 기록, 실제 검색어, 프록시 설정은 출처나 배포 입력으로 사용하지 않았다.

## 파일별 계약과 적용

| 공개 donor 파일 | 확인한 계약 | 키트 적용 |
|---|---|---|
| `bundle/job-search/skills/job-search/wanted-search/scripts/wanted_search.py` | `GET /api/chaos/search/v1/results`, `query`/`limit`, `positions` list 또는 `data`/`list` wrapper, `/wd/{id}` URL | `collect_wanted`/`normalize_wanted`; 공개 ID·제목·회사·지역만 제한 정규화 |
| `bundle/job-search/skills/job-search/kr-search/scripts/kr_job_search.py` | 사람인 검색 URL, `item_recruit`, `rec_idx`, `job_tit`, `corp_name/area_corp` HTML 표식 | `collect_saramin`/`normalize_saramin_html`; 1페이지·최대 50건, native `rec_idx` 보존 |
| `bundle/job-search/scripts/job-collect.py` | 여러 collector orchestration과 proxy doctor | 복사하지 않음. 개인 프로필·프록시 회전·차단 우회 결합을 제외 |
| `bundle/job-search/skills/job-search/jobfilter.py` | 구직자 개인 적합도/연차 필터 | 복사하지 않음. 영업 신호 수집은 개인 구직 선호와 다른 목적 |

`sources.py`는 donor의 공개 endpoint와 필드 계약을 참고해 stdlib 기반으로 다시 작성한 bounded adapter다.
소스 상단에 공개 커밋·파일 경로와 MIT 저작권 출처를 남긴다.

## 실패·빈 결과 계약

- HTTP 401/403/429는 `blocked`다.
- DNS, timeout, 기타 HTTP/파일 오류는 `failed`다.
- Wanted의 `positions` 구조가 사라지거나 Saramin의 결과/명시적 empty 표식이 모두 없으면
  `invalid_response`다.
- 올바른 Wanted 빈 배열 또는 Saramin의 명시적 검색 결과 없음 문구만 `empty`다.
- `both`는 한 provider의 실패를 다른 provider의 성공으로 숨기지 않는다. 부분 레코드 수는 metadata에
  기록하지만 workflow에는 실패 상태를 반환해 저장을 중단한다.

로그인, CAPTCHA, 유료벽, 프록시 회전, 계정 전환, 자동 발송, CRM 쓰기는 구현하지 않는다.

## 설정 계약

`source_mode=live`, `workflows`에 `jobs`가 있을 때:

| `jobs_provider` | 필수 필드 | 동작 |
|---|---|---|
| `wanted` | `jobs_query` | 공개 Wanted 검색 1회, 최대 50건 |
| `saramin` | `jobs_query` | 공개 Saramin 검색 1페이지, 최대 50건 |
| `both` | `jobs_query` | 두 bounded collector 실행; 부분 실패를 성공으로 승격하지 않음 |
| `ats` | `ats_provider`, `ats_board`, `ats_company` | Greenhouse/Lever/Ashby 공개 board |

CLI와 설정에 `source_mode`가 모두 없으면 workflow는 실패한다. 샘플 모드는 사용자가 명시해야 한다.

## 재현 가능한 검증

```bash
python3 -m unittest tests.test_sources tests.test_workflow
python3 sources.py wanted "영업" --fixture samples/source-wanted.json \
  --as-of 2026-10-13T10:00:00Z
python3 sources.py saramin "영업" --fixture samples/source-saramin.html \
  --as-of 2026-10-13T10:00:00Z
```

합성 fixture는 parser·native ID·evidence·상태 계약을 검증한다. 라이브 서비스 가용성이나 이용 허가를
증명하지 않는다. 2026-10-13 이 환경에서 limit 1 라이브 smoke는 두 서비스 모두 DNS 실패로 `failed`를
반환했다. 라이브 성공이라고 주장하지 않는다.

