# Source adapter reuse and provenance

이 문서는 `sources.py`가 참고한 공개 저장소와 의도적으로 가져오지 않은 동작을 기록한다.
현재 구현은 독립적으로 다시 작성했으며, donor의 구조·실패 사례·필드 계약을 설계 근거로 사용했다.

## 구현 계약

`sources.py`는 다음 경로만 제공한다.

1. 사용자가 제공한 CSV/JSON 채용 공고 정규화
2. Greenhouse, Lever, Ashby 공개 job-board API 한 곳 읽기
3. 제한된 공개 WordPress 투자 뉴스 후보 수집
4. 제한된 공개 Wanted 키워드 검색과 Saramin 1페이지 검색

공통 결과 상태는 `ok`, `empty`, `blocked`, `failed`, `invalid_response`다. 차단·네트워크 실패·파서 변경은
절대로 정상 0건으로 바꾸지 않는다. 로그인, CAPTCHA, 유료벽, 프록시, 계정 전환, CRM 쓰기, 메시지 발송은
구현하지 않는다.

## Donor A — hermes-headhunt-kit

- 저장소: `Wendy-Nam/hermes-headhunt-kit`
- 검토 커밋: `15c11f730fce70486dc66b249efa936436fd219b`
- 라이선스: MIT, Copyright (c) 2026 Wendy Nam (남서아)
- 참고 파일:
  - `skills/headhunt/funded-startup-search/scripts/funded_search.py`
  - `skills/headhunt/startup-enrich/scripts/startup_enrich.py`
  - `skills/headhunt/startup-score/scripts/startup_score.py`

채택한 아이디어:

- WordPress REST 응답에서 제목·요약·게시일·URL을 제한적으로 읽는 방식
- 투자 유치와 투자사 펀드 결성을 분리해야 한다는 규칙
- 투자 신호와 채용 신호를 별도 근거로 유지한다는 구조

다시 작성하거나 제외한 부분:

- donor의 회사명 정규식은 설명형 제목을 실제 회사명으로 오인한다. 새 구현은 제목 값 전체를
  `company_candidate`로만 취급하며 `company`는 `null`로 둔다.
- donor는 본문의 첫 금액을 선택한다. 새 구현은 금액이 정확히 하나일 때만 단일 후보로 내고, 여러 개면
  `amount_candidate=null`, `review_required=true`로 둔다.
- donor의 `HERMES_SCRAPER_PROXY`와 Wanted 차단 우회는 가져오지 않았다.
- donor scorer는 미확인 금액·채용·날짜에도 양의 점수를 준다. 새 adapter는 점수를 만들지 않고 unknown을
  `null`로 보존한다.
- donor 저장소에는 collector fixture/unit test가 없었고 README의 “실동작 검증 완료” 주장을 재현할
  테스트 증거가 없었다. 따라서 그 주장을 이 키트의 검증 근거로 사용하지 않는다.

## Donor B — hermes-agent-kit

- 저장소: `Wendy-Nam/hermes-agent-kit`
- 검토 커밋: `76e15170a2dc8b2bce270bd50e07287a14c3dd6b`
- 라이선스: MIT, Copyright (c) 2026 Wendy Nam (남서아)
- 참고 파일:
  - `bundle/job-search/scripts/job-collect.py`
  - `bundle/job-search/scripts/job_collect/public_export.py`
  - `bundle/job-search/scripts/job_collect/ledger.py`
  - `bundle/job-search/skills/job-search/ats-search/scripts/ats_search.py`
  - `bundle/job-search/skills/job-search/wanted-search/scripts/wanted_search.py`
  - `bundle/job-search/skills/job-search/kr-search/scripts/kr_job_search.py`
  - `bundle/job-search/skills/job-search/jobfilter.py`

채택한 아이디어:

- 사람이 읽는 Markdown을 다시 파싱하지 않고 JSON을 기계 계약으로 사용
- 공개 산출물 필드 제한, record/byte 상한, 원자적 산출물이라는 방어 패턴
- Greenhouse·Lever·Ashby 응답을 provider별로 정규화
- Wanted `positions` 응답과 Saramin `item_recruit`/`rec_idx` 공개 표식
- provider native ID를 우선하고 URL을 두 번째 식별자로 쓰는 중복 제거
- 손상·차단·파서 변경을 정상 empty와 분리

다시 작성하거나 제외한 부분:

- donor의 수집 오케스트레이터는 `/opt/data`, 개인 검색 프로필, 위키, 크론, 프록시 닥터와 강하게 결합되어
  독립 수집기에 복사하지 않았다.
- donor의 Saramin, JobKorea, LinkedIn, ATS 하위 수집기는 일부 네트워크 오류를 stderr에만 쓰고 rc=0의
  빈 JSON을 반환한다. 상위 오케스트레이터가 이를 정상 empty로 오인할 수 있어 새 구현에서는 모든 source가
  명시적 상태를 반환한다.
- donor URL 중복 제거는 일반 URL의 query를 모두 제거할 수 있다. `rec_idx`처럼 query에 있는 native ID가
  서로 다른 공고를 하나로 합칠 수 있으므로 새 구현은 Wanted/Saramin/JobKorea/LinkedIn native ID를 먼저
  추출하고, 추적 파라미터만 제거한 canonical URL을 사용한다.
- 개인 직무 선호, 회사 alias, 경력 컷, Gmail·지원 상태·노트 쓰기, generic web/DDG 검색은 가져오지 않았다.
- donor 전체 smoke는 이 환경에서 collector·잠금·SSRF 관련 단계가 실행된 뒤 PDF 렌더 selftest에서 실패했다.
  실행된 collector 관련 단계와 저장소 전체 green 상태를 구분한다.

## Reference C — vendored job-posting-match

- 로컬 경로: `hermes-kit/seed/kskill/job-posting-match`
- `hermes-kit` 검토 커밋: `858fd1b7d2b25a1a3844dc71e8005493a49df228`
- upstream: `NomaDamas/k-skill@9fade13b1066bc58fd820fe659145a9a21974138`
- 라이선스: MIT. `hermes-kit/seed/kskill/NOTICE.md`는 upstream 테스트가 제외되었다고 명시한다.

안전 문구와 공개 정보 한계는 참고했지만 HTML parser와 구직자 적합도 점수는 복사하지 않았다. 해당 구현의
전역 `dedupe()`는 URL query를 제거해 서로 다른 Saramin `rec_idx` 공고를 하나로 합치는 회귀가 합성 입력에서
재현되었다. 이 회귀는 `tests/test_sources.py::test_saramin_query_ids_remain_distinct`로 고정했다.

## 현재 코드의 provenance 분류

| 대상 | 분류 | 설명 |
|---|---|---|
| `sources.py` | bounded adaptation / rewrite | 공개 donor endpoint·필드 계약을 MIT 고지와 함께 stdlib 상태·record·CLI 계약으로 재작성 |
| funding 필터 개념 | adapted design | Donor A의 분리 원칙을 보수적으로 재설계 |
| ATS provider mapping | adapted design | Donor B가 사용한 공개 endpoint와 필드 형태를 새 계약으로 재작성 |
| CSV/JSON importer | new | donor에 없던 workshop-first 입력 경로 |
| fixtures | new synthetic data | 실회사·실투자·개인정보를 포함하지 않는 합성 자료 |
| tests | new | 차단/empty, 오탐, unknown, native-ID dedup 회귀 |

`setup.json` 필터 계층도 donor에서 복사하지 않은 새 구현이다. `workflows`, 직무/투자 키워드, 제외어,
채용 지역을 명시적으로 적용하고 `metadata.filters`에 입력과 제외 사유별 건수를 남긴다. 지역이 없는 채용
레코드는 지역 불일치로 추정하지 않으며, 투자 뉴스에는 근거 없는 지역 추정을 하지 않는다. 필터는 정상
`ok`/`empty` 결과에만 적용하므로 source 차단·실패·스키마 변경을 0건으로 가리지 않는다.

donor 코드를 다시 직접 복사하는 변경이 생기면 해당 저장소의 MIT 고지와 정확한 커밋·파일·함수를 이 문서와
배포 NOTICE에 추가해야 한다.

## 검증 범위

```bash
python3 -m unittest tests.test_sources -v
```

테스트는 합성 fixture와 모킹된 HTTP 차단을 사용한다. 이는 parser·상태·중복 제거 계약의 검증이지 라이브
서비스 가용성이나 이용 허가의 증명이 아니다. 설정 필터 테스트는 키워드·제외어·지역 unknown·workflow
비활성화와 건수 메타데이터를 고정한다. 라이브 smoke는 다음처럼 요청량을 작게 유지한다.

```bash
python3 sources.py funding --pages 1 --per-page 3
python3 sources.py ats --provider greenhouse --token PUBLIC_BOARD_SLUG --company "COMPANY NAME" --limit 3
python3 sources.py wanted "영업" --limit 1
python3 sources.py saramin "영업" --limit 1
```

네트워크 정책으로 실패하면 그 결과를 그대로 `blocked` 또는 `failed`로 기록한다. 프록시나 다른 계정으로
재시도하지 않는다.
