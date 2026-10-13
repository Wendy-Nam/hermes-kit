---
name: gtm-list-qa
description: 회사 후보 목록의 중복, 출처, ICP 적합도, 신호 최신성, 누락값을 점검하고 사람이 볼 보류·제외 사유를 만든다.
license: MIT
metadata:
  category: sales
  source: GTMOS by Shyft.ai
  source_url: https://github.com/shyftai/GTMOS
---

# 타깃 목록 QA

이 스킬은 **회사 후보 목록**을 검토한다. 이메일 발송 적합성이나 개인정보 수집 허가를 대신 판단하지
않으며, 개인 이메일을 찾거나 검증하지 않는다.

## 순서

1. 원본 파일과 ICP 브리프를 보존하고 행 수·열 이름·수집 시점을 기록한다.
2. URL과 source ID를 우선해 정확 중복을 찾는다. 회사명 유사도만으로 합치지 않는다.
3. 회사 적합도, 신호 관련성, 신호 최신성, 데이터 완전성을 **별도 항목**으로 평가한다.
4. 제외 조건은 점수보다 먼저 적용한다. 미상 값은 0 또는 불일치로 꾸미지 않고 보류 사유로 남긴다.
5. 목록 전체의 출처 coverage, 중복률, 회사 편중, 필수 필드 누락률, 검토 필요 비율을 요약한다.

## 행별 출력

`company`, `source_url`, `source_id`, `observed_at`, `fit`, `signal`, `freshness`, `coverage`,
`decision=keep|review|exclude`, `reason_codes[]`, `unknowns[]`를 남긴다.

권장 사유 코드는 `duplicate`, `excluded_industry`, `excluded_region`, `weak_fit`, `stale_signal`,
`identity_unclear`, `missing_evidence`, `source_failed`다. source 실패를 “후보 0건”으로 바꾸지 않는다.

## 목록 수준 QA

- 출처 URL이 있는 비율
- stable source ID가 있는 비율
- 정확 중복과 검토할 유사 회사 수
- 한 회사·한 도메인으로 과도하게 몰린 비율
- ICP 필수 조건을 확인할 수 없는 비율
- 최신성 기준을 지난 신호 비율
- `keep`, `review`, `exclude` 건수와 상위 사유

100건 미만의 작은 목록에서는 등급보다 실제 건수와 사유를 보여준다. 큰 목록에서도 단일 종합 점수만으로
자동 승인하지 않는다. 원본, 정제본, 제외 로그를 분리하고 사람 검토 전 발송하지 않는다.

## 금지

- 개인 이메일·전화번호를 새로 수집하거나 donor 데이터에서 복사
- 이름 유사도만으로 회사 병합
- 없는 값을 AI가 보충한 뒤 사실로 표시
- 자동 발송, 유료 enrichment, CRM 쓰기

## 출처

MIT 라이선스 GTMOS의 `validate-list.md`, `lead-scoring.md`, `list-quality-scorecard.md`, `RULES.md`에서
목록 정리·ICP 분리·중복·coverage 원칙을 참고해 회사 근거 검토용으로 새로 작성했다. 이메일 발송·CRM
기능은 제외했다. 상세 출처와 라이선스는 `docs/REFERENCE-GTM.md`를 따른다.
