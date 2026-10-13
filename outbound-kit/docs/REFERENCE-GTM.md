# GTMOS 참고 감사 기록

## 범위와 출처

- 고정 공개 출처 commit: `6eae4313aee169542bc7e8d2ed992a7214e92540`
- 확인한 fork: <https://github.com/Wendy-Nam/GTMOS>
- 원 저작자 표기로 사용한 upstream: <https://github.com/shyftai/GTMOS>
- 확인한 라이선스: MIT License, Copyright (c) 2026 Shyft.ai
- 적용 범위: ICP 브리프, 회사 후보 목록 QA, 카피 작성·검수 원칙

GTMOS의 개인 workspace, `.env`, 연락처, 캠페인 결과, donor 프로필은 복사하지 않았다. 이 키트에 가져온
것은 일반적인 문서 구조와 검수 원칙뿐이며 Hermes 워크숍의 읽기·초안·사람 승인 경계에 맞게 다시 썼다.

## 파일 단위 감사

| GTMOS 파일 | 참고한 실무 원칙 | 이 키트의 적용 | 제외한 부분 |
|---|---|---|---|
| `_template/ICP.md` | 회사 포함·제외, persona, 신호, 0~3 판단 | `gtm-icp-brief`의 필수/가점/제외/미상 | donor 값 없음 |
| `_template/PERSONA.md` | 역할·직급·반대 persona·proof 차이 | 회사 적합도와 담당자 적합도 분리 | 개인 프로필 없음 |
| `_template/campaigns/_campaign-template/BRIEFING.md` | offer, hook, proof, CTA, 금지 주장 | 검증 proof와 CTA 하나 | campaign shipping 없음 |
| `.claude/commands/gtm/list-brief.md` | 소싱 전에 구조적 brief | 시나리오·출처·필터 질문 | Apollo/SalesNav 자동화 없음 |
| `.claude/commands/gtm/brief-audit.md` | offer·hook·tone·CTA·제약의 누락 질문 | 브리프가 비면 카피 전에 질문 | 자동 campaign gate 없음 |
| `.claude/commands/gtm/clean-list.md` | 원본 보존, 정규화, 중복·누락 flag | 회사 후보 원본/정제/제외 로그 분리 | 개인 연락처 정제 없음 |
| `.claude/commands/gtm/validate-list.md` | 원본 보존, dedupe, ICP 기반 사유 | 회사 후보 QA와 review 사유 | 이메일 enrichment·ship 없음 |
| `.claude/commands/gtm/score-list.md` | 행 점수와 목록 수준 QA 분리 | 작은 목록은 등급 대신 건수·사유 | ship 등급 없음 |
| `.claude/gtmos/references/lead-scoring.md` | 회사/담당자/신호/데이터 품질 분리 | fit/signal/freshness/coverage 분리 | engagement 추적 없음 |
| `.claude/gtmos/references/list-quality-scorecard.md` | 중복·편중·coverage의 목록 수준 점검 | 건수와 사유 중심 목록 QA | 발송 가능 등급 없음 |
| `.claude/commands/gtm/write.md` | 컨텍스트를 먼저 읽고 초안 뒤 검수 | evidence→가설→offer→CTA | sequence 발송 없음 |
| `.claude/commands/gtm/validate-copy.md` | brief·voice·claim·CTA 검수 | 항목별 pass/review/fail | 승인 후 ship 없음 |
| `.claude/gtmos/references/cold-email-skill.md` | 관찰 우선, 간결성, 단일 CTA | `gtm-copy-qa` 작성 계약 | 고정 영문 문구 복사 없음 |
| `.claude/gtmos/references/csv-format.md` | UTF-8, 원본/정제본 분리, 명시적 컬럼 | source URL·ID·날짜·사유 계약 | 개인 이메일·전화·LinkedIn 컬럼 없음 |
| `.claude/gtmos/references/spam-words.md` | 과장·기만·가짜 긴급성 검수 | 근거·claim·voice 검수에 일반 원칙만 반영 | 정상 B2B 단어까지 막는 정적 blacklist는 채택 안 함 |
| `_template/TOV.md` | 채널별 voice와 금지 표현 | 사용자 voice가 기본보다 우선 | 특정 브랜드 voice 없음 |
| `ACCEPTABLE-USE.md` | 합법적 출처, suppression, 허위 proof 금지 | 개인정보·우회·허위 주장·자동발송 금지 | 법률 준수 보증 없음 |

## 채택하지 않은 기능

- 자동 메일·LinkedIn 발송과 sequence shipping
- 개인 이메일·전화번호 enrichment
- 결제·credit 사용
- CRM, pipeline, reply 상태 쓰기
- LinkedIn 자동화
- donor의 `.env`, workspace, contact, campaign 데이터

## MIT 고지

The following license notice is preserved for the GTMOS-derived/adapted material:

> MIT License  
> Copyright (c) 2026 Shyft.ai  
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions: The above copyright
> notice and this permission notice shall be included in all copies or substantial portions of
> the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
> PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
> LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
> OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
> IN THE SOFTWARE.

이 문서는 upstream의 Legal Disclaimer나 Acceptable Use Policy를 이 프로젝트의 별도 계약으로 편입하는
것이 아니다. 각 사용자는 적용 법률과 플랫폼 약관을 별도로 확인해야 한다.
