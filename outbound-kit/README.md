# Hermes Outbound Kit 0.1

데스크톱과 Linux 서버에 같은 세일즈 팩을 설치하도록 돕는 AI 스킬과 구성 템플릿.
Telegram / Discord / 둘 다 / 로컬 대화를 지원합니다.

## AI 설치 스킬로 시작

키트 폴더를 코딩 AI에서 열고 다음을 요청하세요.

> agent-skill/hermes-outbound-setup/SKILL.md를 읽고 필요한 질문을 받아 내 환경에 설치해줘. 비밀값은 채팅에 묻지 마.

스킬은 대화/질문 스크립트로 설정을 받고, `installer.py`의 실제 단계들을 호출합니다.
서버면 `server_access.py`로 SSH 키·호스트 신뢰·접속부터 준비합니다.
토큰·로그인은 사용자 터미널의 비공개 입력 단계로 분리합니다.
자세한 실행 연결은 [스킬 우선 설치](docs/SKILL-FIRST.md)를 보세요.

## 선택: 브라우저로 먼저 설정 만들기

1. [사전 준비](docs/PREPARE.md)를 읽습니다.
2. `wizard.html`을 브라우저로 열고 입력한 뒤 `setup.json`을 키트 폴더에 저장합니다.
3. 코딩 AI에 `agent-skill/hermes-outbound-setup/SKILL.md`를 읽고 이 설정으로 설치해 달라고 요청합니다.

이 버전은 **AI 설치 스킬과 실제 단계별 설치 실행기**입니다. 브라우저는 비밀 없는 설정만 만듭니다.
서명된 독립 데스크톱 앱은 아니며, 없는 엔진은 고정 버전 다운로드·해시 검사 후 공식 설치 절차를
사용자 터미널에서 실행합니다. 상세 흐름은 스킬이 안내하고 검증합니다.

## 직접 실행 (Python 3.11 이상)

처음 실행할 때는 `python3 start.py`로 질문과 설치를 함께 진행합니다. 계정 없이 결과 흐름부터
보려면 `python3 start.py --offline`을 사용합니다. 아래 개별 명령은 고급 사용·진단용입니다.

```sh
python3 kit.py validate --config setup.json
python3 kit.py install --config setup.json
python3 kit.py sample --config setup.json --output output
python3 kit.py model
python3 kit.py connect --config setup.json
python3 kit.py doctor
python3 kit.py chat
```

Windows에서는 `python3` 대신 `py -3`을 사용합니다. 봇으로 대화하려면 마지막 명령 대신:

```sh
python3 kit.py gateway
```

Hermes 엔진이 준비되어 있다면 설치·샘플·모델 선택·채널 연결·진단을 한 명령으로 진행합니다:

```sh
python3 kit.py setup --config setup.json
```

필수 단계가 실패하면 다음 단계로 넘어가지 않습니다. 기존 채널 토큰과 owner가 일치하면 보존하고
재입력을 생략합니다. owner 불일치나 부분 설정은 중지합니다. 보존은 재인증 성공을 뜻하지 않습니다.

기본 설치 경로는 Mac/Linux `~/.hermes-outbound`, Windows `%LOCALAPPDATA%\\hermes-outbound`입니다.
다른 경로는 모든 명령에 동일한 `--home`을 전달하세요.
기존 설정과 변경된 스킬 파일은 덮어쓰지 않습니다. 변경하려면 새 home을 쓰거나 기존 내용을 검토하세요.
채널 재설정은 같은 home에서 `hermes gateway setup`을 사용합니다.

## 서버

서버에 키트를 복사한 뒤 같은 명령으로 설치합니다. `target=server`는 설치 지원 AI에게 서버
절차를 선택하게 하는 메타데이터이며, 생성만으로 원격 배포되지는 않습니다.
우선 foreground gateway에서 양쪽 채널의 메시지 왕복을 확인하세요. 백그라운드/재부팅 복구는
[서버 안내](docs/SERVER.md)의 upstream 서비스 절차로 설정합니다.

## OMH와 선택 OmniRoute

OMH는 설치 스킬의 기본 코어이며 `installer.py run --step omh`로 실제 고정 버전을 설치합니다.
OmniRoute는 선택 사항이고 `--step routing`에서 Docker 환경 점검 후 설치합니다.
Linux Docker Engine, macOS/Windows Docker Desktop(Linux containers)을 지원하는 코드 경로가 있으며
메모리·이미지 아키텍처·로컬 Docker context·비밀 파일 권한 조건을 확인합니다.
자세한 조건은 [OMH](docs/OMH.md), [OmniRoute](docs/OMNIROUTE.md)를 보세요.

플러그인 파일/컨테이너 설치와 실제 계정 로그인·Hermes 로드·추천 모델 도구 호출·자동 라우팅 활성화는
별개입니다. 현재 실기기/실계정 완료로 인증한 제품은 아닙니다.

## 포함/미포함

- 포함: 대화형 설정 도구, 단계별 실행기·상태 기록, SSH 접속 준비, 오프라인 구성 화면,
  독립 skill home 설치, 봇 인증/allowlist, 선택 서비스 인증 discovery,
  채용 파일·공개 ATS·Wanted·Saramin·투자 소스 adapter, 근거→초안→검토 Obsidian 체인,
  ICP·리스트·초안 검수 스킬과 AI 설치 지원 스킬.
- 자동 발송과 native GUI 패키징은 포함하지 않습니다. OMH/OmniRoute는 선택 시 현재 helper와
  호환성 검증 결과를 확인해야 하며, 선택했다는 이유로 설치·모델 라우팅 완료로 보지 않습니다.
- 모델 응답과 실채널 연결, Mac/Windows 실행은 실제 계정/기기에서 추가 확인해야 합니다.

## 워크숍 자료

- [실행 가능한 소스→볼트 데모](docs/DEMO.md)
- [기존 kit 입력 누락 감사](docs/WIZARD-FIELD-AUDIT.md)
- [서비스별 준비](docs/SERVICES.md), [옵시디언](docs/OBSIDIAN.md)

검증 상태는 [VALIDATION.md](VALIDATION.md), 구현 범위는 [PLAN.md](PLAN.md)를 보세요.

- [전체 레퍼런스 통합 감사](docs/REFERENCE-INTEGRATION.md)
- [격리 로컬 테스트와 결과 품질 평가](docs/RESULT-QUALITY.md)
- [본인 전용 Telegram 테스트봇](docs/TEST-BOT.md)
- [공개 배포 개인정보 점검](docs/PRIVACY-RELEASE.md)

PPT는 배포 범위에서 제외했습니다. 내부 계획·검토 문서, 사용자 설정·결과·볼트·비밀 파일은
공개 ZIP에 포함하지 않습니다. 공개 전 개인정보 검사는 자동 탐지와 수동 검토를 함께 수행해야 합니다.
