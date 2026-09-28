# 외부 저장소 감사 — 학생 키트 편입 판단 (2026-09-28)

사용자가 자신의 GitHub 저장소 7개를 키트에 넣을지 검토를 요청했다. 전수 감사 결과다.

## 1. 먼저 알아야 할 사실 3가지

1. **7개 중 4개는 원작이 아니라 포크다.** `solo-skills`→`bam-bam-2/solo-skills`, `bookforge`→`gongnyang/bookforge`, `public-data-lens`→`hike-lab/public-data-lens`, `gongnyang-prompt-kit`→`gongnyang/gongnyang-prompt-kit`. 저작권은 각 원저자에게 있다. 크레딧을 바꾸면 안 된다.
2. **Hermes 네이티브는 2개뿐.** `hermes-job-hunt-for-korean`, `hermes-skills-kr`. 나머지는 Claude Code / MCP / 독자 웹앱 타겟이라 Hermes에서 그대로 도지 않는다.
3. **키트 현황과 다르다.** 키트의 한국어 스킬은 `hermes-skills-kr`가 아니라 **`NomaDamas/k-skill`**에서 가져온 것이다(`plugins/kit-setup/kskills.json`). `hermes-skills-kr`는 youtube-summary 하나만 쓴다.

## 2. 판단

| 저장소 | 정체 | Hermes에서 도나 | 재배포 가능 | 판정 |
|---|---|---|---|---|
| hermes-skills-kr | 스킬 1개(youtube-summary) | ✅ | ✅ MIT | **포함** |
| hermes-job-hunt-for-korean | 구직 자동화 오버레이 | ✅ | ✅ MIT | **수정 후 포함** |
| solo-skills | 37개 스킬 | ⚠️ Hermes 무설정 동작분만 | ✅ MIT(포크) | **7개 선별** |
| gongnyang-prompt-kit | 이미지 프롬프트 컴파일러 1개 | ✅ (복사 필요) | ✅ MIT(포크) | 선택팩 |
| wendy-pr-intelligence | 뉴스 브리핑 | ❌ 미검증 스텁 | ✅ MIT | **제외** |
| public-data-lens | HIKE 연구실 MCP 웹앱 | ❌ N/A | ⚠️ 타 연구실 | **제외** |
| bookforge | 한국어 전자책 PDF | ⚠️ Playwright | ✅ MIT+OFL | 선택팩 |

### 제외 2건의 이유
- **wendy-pr-intelligence**: Hermes 대응이 16라인 스텁이다(`register(ctx)`가 `register_skill`이 있을 때만 동작하는 관용적 가드). LLM 백엔드가 `claude -p` 서브프로세스에 묶여 있고 모델명이 `claude-sonnet-4-6` 등 **존재하지 않는 ID를 기본값으로 쓴다.** 넣으면 학생의 첫 실행이 실패한다. Hermes를 지원한다고 표방하는 게 오히려 가장 큰 위험이다.
- **public-data-lens**: 스킬이 아니다. HIKE 연구실의 도메인·URI 규범이 하드코딩된 풀스택(FastAPI+React+nginx)이고 서비스가 특정 데이터 포털에 묶여 있다. 개인 학생에게 줄 수 없다.

### bookforge 라이선스
GitHub이 `NOASSERTION`을 낸 건 파일이 순수 MIT가 아니기 때문이다. 실제 `LICENSE`는 **MIT (Copyright gongnyang) + 폰트만 SIL OFL 1.1**. 즉 **재배포 가능하다.** 경고가 아니라 파싱 실패다. 단 Gmarket Sans은 RFN(Reserved Font Name) 선언이 있어 폰트명·파생폰트 개명 의무가 걸린다. 폰트 57MB와 예제 PDF 23MB는 빼고 코드만 편입한다.

## 3. 편입 전 필수 조치 ( mystudent에게 절대 그대로 못 보냄)

1. **`bundle/vault/automation/job-hunting/resume/master_resume.md:36`의 `<Gildong Hong>` 삭제.** 유일하게 남은 실제 신원. 나머지(이메일·전화)는 이미 플레이스홀더다.
2. `search-profile.yaml`의 "시노님" → "사용자 본인"으로 일반화(job-hunt 5곳).
3. `.claude-plugin/marketplace.json`·`plugin.json`의 `sharedwendy999@gmail.com` 제거.
4. `bundle/cron/jobs.json`의 `/opt/hermes`·`/opt/data` 하드코딩을 템플릿 변수로. **이 잡에는 작성자 본인의 Gmail 정리(휴지통 이동)까지 들어 있다** — 학생에게 이 잡을 그대로 넘기면 안 된다.
5. 4개 포크의 원저자 크레딧 유지. `solo-skills` HEAD는 업스트림과 바이트 동일(기여 0)이라 README를 그대로 쓰면 안 된다.
6. solo-skills에서 `remote-offload`(Tailscale IP `100.75.197.6` 하드코딩), `iphone-sms-read`·`naver-travel-post`(`/Users/mac/...` 절대경로), `multi-method-image-generation`(`~/geuljam-bot/.env`에서 **다른 프로젝트 키 재사용 안내**)은 제외. 이건 안전 문제가 아니라 배포 금지다.
7. gongnyang `gpt-image-2`는 구버전. 현재는 `gpt-image-2.5`.

## 4. solo-skills에서 고를 것

**권장(7)**: `humanize-korean`(한국어 AI 문체 제거, 재사용 가치 최대), `harness`(에이전트 설계 패턴), `orchestration`, `style-skill-creator`, `meeting-summary`, `meeting-minutes`, `workshop-prep`

**제외**: `getback-*`(GET100 특정 업무), `naver-*`(업자 개인 블로그 컨텍스트), `claude-codex-fallback`(Hermes 무의미), `discord-agent-fleet`, `iphone-sms-read`, `remote-offload`, `kakaotalk-cli`, `advisory-minutes`, 그 외 GET100 종속.

**주의**: 키트에 이미 `korean-humanizer`(k-skill)가 있다. `humanize-korean`과 이름이 비슷한데 출처가 다르므로, 두 개를 같이 넣으면 충돌할 수 있다. 넣기 전에 비교가 필요하다.
