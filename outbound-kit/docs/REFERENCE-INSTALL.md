# 공개 reference 구현 감사와 설치 범위

감사일: 2026-10-13. 이 문서는 파일이 **실제로 구현한 것**, 공개 donor에서 가져온 설계,
아직 구현하지 않았거나 실기기에서 확인하지 않은 것을 구분한다. 개인 저장소, 개인 프로필,
개인 라우팅·계정 설정은 근거로 사용하거나 배포하지 않았다.

## 고정한 공개 출처

| 저장소 | 감사 commit | 이 키트에서 참고한 영역 |
|---|---|---|
| `Wendy-Nam/hermes-kit` | `858fd1b7d2b25a1a3844dc71e8005493a49df228` | 서버 Compose, 안전한 컴포넌트 설치, OMH, OmniRoute, Composio, Syncthing |
| `Wendy-Nam/hermes-vps-setup` | `028b59e6c392fd27e5c15b2f1a89bca225e5d436` | PC↔서버 볼트 페어링과 실제 파일 왕복 검사 |
| `Wendy-Nam/hermes-headhunt-kit` | `15c11f730fce70486dc66b249efa936436fd219b` | 투자 신호→보강→점수→초안→사람 관리의 업무 흐름 |
| `NousResearch/hermes-agent` | tag `v0.21.7`, commit `71d34bad1045610252eda02ee79549436896e784` | 공식 엔진/desktop installer와 CLI 계약 |
| `rlaope/oh-my-hermes` | tag `v2.0.5`, commit `b84f096e59d50fc933ed4b43fd36675e8cff593a` | OMH core distribution |

로컬 checkout의 commit을 기록한 것이며 “최신 버전” 주장이나 제3자 서비스의 현재 가용성
증거가 아니다. 공개 donor의 설명보다 현재 키트 코드와 테스트가 우선한다.

## 파일 단위 대응표

### 설치·데스크톱·서버

| 공개 reference | 현재 구현 | 관계와 보존한 계약 | 남은 차이 |
|---|---|---|---|
| Hermes `scripts/install.sh`, `scripts/install.ps1` | `engine_bootstrap.py`, `paths.py`, `bootstrap.command`, `bootstrap.ps1` | commit과 installer SHA-256을 고정하고 공식 `--hermes-home`/`--dir`/desktop 플래그를 사용한다. 전역 PATH의 Hermes 대신 전용 home launcher와 managed Python만 해석한다. | 서명된 독립 outbound 앱이 아니다. Mac/Windows 실기기, Gatekeeper, 백신, GUI 시작은 별도 검증이다. |
| `hermes-kit/docker-compose.yml` | `server_access.py`, `installer.py`, `operations.py` | 서버 입력 검증, strict host key, 읽기 전용 probe, allowlist ZIP, 새 stage 배포, 사용자 TTY의 setup 재개를 제공한다. 예약은 수동 성공 뒤 별도 descriptor로 만든다. | donor의 사전 빌드 Hermes/Syncthing Compose를 복제하지 않는다. deploy는 키트 복사이지 엔진·데몬·방화벽 설치 완료가 아니다. 재부팅 복구도 실서버에서 확인해야 한다. |
| `hermes-vps-setup/scripts/{00-preflight,01-pc-sync,02-verify}.sh`와 `hermes-kit/clients/pc-sync` | 직접 포함하지 않음; `vault_flow.py`, `docs/OBSIDIAN.md`만 제공 | 두 공개 저장소의 위 세 스크립트는 감사 checkout에서 바이트 단위로 동일했다. “공유 설정”과 “실제 파일 도착”을 분리하는 원칙을 문서/상태에 유지한다. | Syncthing 설치·페어링·왕복 검증, Obsidian GUI 설치는 현재 outbound 번들 범위 밖이다. 필요하면 공개 PC-sync를 별도 선택 모듈로 vendoring하고 commit/hash를 고정해야 한다. |
| `hermes-kit/plugins/kit-setup/components.py`, `config_store.py`, `env_store.py` | `installer.py`, `kit.py`, `services.py`, `runtime_connect.py` | 소유권을 모르는 파일 보존, atomic write, 비밀과 비밀 없는 설정 분리, 단계별 상태를 재구현했다. | donor plugin의 Discord `/setup` UI를 가져오지 않는다. 현재 UI는 설치 스킬/`start.py`/선택적 `wizard.html`이다. |

### OMH와 OmniRoute

| 공개 reference | 현재 구현 | 실제 구현 | 아직 증명하지 않는 것 |
|---|---|---|---|
| `hermes-kit/plugins/kit-setup/upstream_omh.py` | `omh_setup.py`, `docs/OMH.md` | 공개 OMH 2.0.5 archive SHA-256, archive path/type, package metadata, plugin hook hash를 검사한다. 전용 venv에 배치하고 upstream core setup, import/register smoke, receipt/rollback을 수행한다. | 설치 성공은 실제 Hermes 프로세스의 plugin load, route tool 노출, child delegation 성공이 아니다. 개인 wrapper·개인 route는 포함하지 않는다. |
| `omh_enhancements.py`, `omh_routing.py` | `omniroute_setup.py`의 route documents/apply | `model_provider_routes/v1`, `mixture_chain_overrides/v1` 폐쇄 계약과 명시적 alias binding을 사용한다. | donor의 모든 quota/readiness patch를 vendoring하지 않는다. version-sensitive hook은 실제 host 검증 전 완료로 표시하지 않는다. |
| `advanced/docker-compose.omniroute.yml`, `plugins/kit-setup/omniroute_setup.py`, `omniroute_mode.py` | `omniroute_setup.py`, `docs/OMNIROUTE.md` | digest-pinned amd64 image, loopback-only 포트, local Docker context, RAM/arch/secret 권한, 소유 container identity를 검사한다. connect는 connection-scoped key와 2-turn tool probe 뒤에만 apply 자료를 만든다. | Docker Desktop/Engine 자체를 설치하지 않는다. ARM Linux는 지원하지 않고, Apple Silicon/Windows ARM64 emulation 및 각 실기기 ACL은 미검증이다. Hermes 재시작 후 실제 delegated task도 별도 gate다. |

### 서비스·채널·소스

| 공개 reference | 현재 구현 | 재사용/강화 | 의도적 제한 |
|---|---|---|---|
| donor `composio_setup.py` | `services.py`, `runtime_connect.py` | 고정 Composio origin의 MCP initialize/tools discovery와 `${COMPOSIO_CONSUMER_KEY}` runtime 참조를 분리했다. | key 승인과 Google/CRM OAuth·권한·도구 호출·발송은 각각 별도이며 자동화하지 않는다. |
| donor feature/setup 경계 | `services.py` | Webshare/Groq/Apify/Composio 키를 숨김 입력으로 받고 provider별 read-only discovery만 수행한다. 오류는 비밀을 포함하지 않는다. | Webshare target fetch, Groq 합성 음성 STT, Apify explicit Actor run, Composio OAuth read call은 별도 functional gate다. discovery 성공을 기능 성공으로 부르지 않는다. |
| donor runtime integration | `runtime_connect.py` | Hermes 0.21.7 설정 모양에 Groq STT와 Composio MCP를 ownership-tracked 방식으로 연결하고, Webshare exact-origin fetch와 Apify 수동 run helper를 둔다. | 자동 Actor 실행, 일반 프록시, 임의 URL, microphone capture, 자동 send는 없다. |
| donor Discord gateway | `kit.py`, `installer.py` | `none`/Telegram/Discord/둘 다, owner allowlist, token identity 검증과 전용 home gateway argv를 제공한다. | identity probe는 owner의 실제 메시지 왕복이 아니다. Discord invite/intents/채널 권한과 Telegram Start는 실계정 확인이 필요하다. |
| headhunt `funded-startup-search` | `sources.py` | 같은 공개 Platum WordPress 계열을 bounded/no-login 후보 소스로 사용하되 fund formation 제외, candidate confidence, raw hash와 explicit failure state를 추가했다. | 회사 후보를 검증 회사로 자동 승격하지 않는다. 단일 공개 소스의 완전성을 주장하지 않는다. |
| headhunt `startup-enrich` | `sources.py`, `runtime_connect.py` | 공개 ATS Greenhouse/Lever/Ashby와 사용자 파일 adapter를 사용하고, source-scoped Webshare만 허용한다. | Wanted 전용 비공식 endpoint와 “VPS면 proxy 필수” 동작은 가져오지 않았다. 403/429를 프록시로 우회하지 않는다. |
| headhunt `startup-score` | `workflow.py` | fit, urgency, field coverage를 분리하고 근거 없으면 `unknown`으로 둔다. | 투자금·라운드·채용량의 고정 가중치를 구매 가능성 점수로 쓰지 않는다. |
| headhunt `bd-outreach`, `startup-crm` | `workflow.py`, `vault_flow.py`, `pack/skills/evidence-to-outreach` | verified evidence→겸손한 CTA→사람 검토, machine/human note 분리, content-hash 승인 무효화를 재구현했다. | 개인정보 profile, invented contact, 자동 발송, 완전한 CRM 접촉/응답/계약 ledger는 포함하지 않는다. |

### 스킬 팩

| 공개 reference | 현재 구현 | 판단 |
|---|---|---|
| `hermes-kit/seed/kits/sales/SKILL.md` | `pack/skills/outbound/SKILL.md` | 고객 상황/가설 분리와 발송 전 확인 원칙을 유지하고 source→research→score→draft→monitor로 확장했다. |
| headhunt 5개 스킬 | `buying-signals`, `evidence-to-outreach`, `workflow.py` | 투자/채용 신호와 초안 부분만 일반 영업용으로 가져왔다. 개인 profile과 헤드헌팅 전용 CRM/점수는 제외했다. |
| donor `/setup` plugin | `agent-skill/hermes-outbound-setup/SKILL.md` | 비개발자용 질문, 비밀값 비공개 입력, desktop/server 분기, 상태별 완료표를 설치 지원 AI 지침으로 재작성했다. |

## 현재 키트의 실제 capability graph

```text
start.py / 설치 스킬 / wizard(설정만)
  -> kit.py schema + installer.py state machine
     -> paths.py + engine_bootstrap.py -> scoped Hermes / optional Desktop build
     -> pack/skills -> outbound + buying-signals + evidence-to-outreach
     -> services.py -> credential discovery
        -> runtime_connect.py -> owned runtime config / explicit helper
     -> omh_setup.py -> pinned OMH core
        -> omniroute_setup.py (optional Docker) -> tool-tested bindings -> explicit apply
     -> workflow.py
        -> sources.py -> evidence envelope
        -> score_records -> fit/urgency/coverage
        -> vault_flow.py -> Accounts/Evidence/Scores/Drafts/Review/Runs
     -> kit.py channel config -> scoped Hermes gateway
     -> operations.py (optional, only after manual success)

remote selection
  -> server_access.py trust -> probe -> allowlist deploy -> user-owned SSH setup
```

각 화살표는 앞 단계가 뒤 단계의 **선택 또는 전제**라는 뜻이지, 설정 파일에 값이 있다는 것만으로
뒤 단계가 통과했다는 뜻은 아니다.

## 네 시나리오의 구현 수준

| 시나리오 | sample | file | live | 결과 게이트 |
|---|---:|---:|---:|---|
| 채용 신호 | 구현 | CSV/JSON 구현 | 공개 Greenhouse/Lever/Ashby 한 board 구현 | evidence와 회사 식별 후 review |
| 투자 신호 | 구현 | typed CSV/JSON 구현 | bounded Platum WordPress 후보 구현 | candidate 회사/금액 확인 후 review |
| 입찰 모니터링 | 구현 | typed CSV/JSON 구현 | 미구현 | 공식 export 사용; 미지원 live는 명시 실패 |
| 해외 파트너 | 구현 | typed CSV/JSON 구현 | 미구현 | 공식 export 사용; 미지원 live는 명시 실패 |

현재 구현은 초안까지만 간다. `template`은 규칙 기반이며 AI 생성이라고 부르지 않는다. `hermes`는
전용 home의 launcher로 실제 응답을 받은 경우에만 모델 초안이고, 어느 모드도 발송하지 않는다.

## 자기 컴퓨터에서 하는 격리형 오프라인 품질 smoke

Python 3.11 이상에서 키트 루트 안에 실제 설치 없이 실행한다.

```bash
python3 local_smoke.py
```

기본은 권한 제한된 새 임시 폴더를 만들고 삭제하지 않아 사용자가 산출물을 볼 수 있게 한다. 위치를
직접 지정하려면 **새 폴더 또는 빈 폴더만** 쓸 수 있다.

```bash
python3 local_smoke.py --root ./my-offline-smoke
```

이 명령은 다음을 실제로 검사한다.

1. 네 시나리오가 각각 합성 record 1건과 raw evidence SHA-256을 만든다.
2. fit/urgency/coverage가 존재하고, 모르는 값이 사실로 채워지지 않는다.
3. Obsidian 구조의 Account→Evidence→Score→Draft→Review→Run 파일이 모두 생긴다.
4. review는 `pending`이고 현재 draft hash를 요구한다.
5. draft는 “실제 AI 생성 결과 아님/자동 발송 없음”으로 표시된다.
6. Dashboard에 네 실행의 다음 작업이 나타난다.
7. 표준 네트워크 entry point가 호출되면 즉시 실패한다.
8. 전용 Hermes home은 빈 상태로 남는다.

결과의 `smoke-report.json`은 `synthetic_offline_workflow_quality_only`라고 명시한다. 이것은 Hermes,
모델, OMH, OmniRoute, 메신저, 라이브 소스, GUI, 서버 데몬의 작동 증거가 아니다.

검증기 자체의 회귀 테스트:

```bash
python3 -m unittest tests.test_local_smoke -v
```

## release 전 남은 실환경 증거

- macOS Intel/Apple Silicon과 Windows x64/ARM64에서 bootstrap→Desktop 창→종료/재시작
- 실제 모델 로그인과 짧은 응답, 전용 launcher/home 일치
- Telegram/Discord 각각 owner 왕복과 둘 중 하나 실패 시 독립 상태
- 선택 서비스마다 discovery 다음의 명시적 functional check
- OMH plugin load/route tool/harmless delegated task
- OmniRoute real provider의 two-turn probe, apply, Hermes 재시작 후 expected connection
- Linux 서버 fresh host의 SSH deploy→engine→foreground gateway→restart/reboot
- 예약 작업의 수동 성공 prerequisite, 중복 방지, 실패/empty/blocked 분리
- tender/overseas live adapter를 추가한다면 공식 API/export 계약과 source-specific 테스트
- PC 볼트 동기화를 제품 범위에 넣는다면 공개 PC-sync의 hash-pinned vendoring과 실제 파일 왕복

이 항목 전에는 “모든 환경 원클릭 설치 완료”, “24시간 자동화 완료”, “실시간 네 소스 모두 지원”으로
표현하지 않는다.
