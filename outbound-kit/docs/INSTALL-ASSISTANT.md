# AI 설치 도우미와 함께 설치하기

이 키트의 설치 도우미는 특정 AI 제품 전용 플러그인이 아니라, 저장소를 읽고 터미널을 사용할 수 있는
코딩 AI가 따르는 이식 가능한 스킬입니다.

```text
agent-skill/hermes-outbound-setup/SKILL.md
```

## 가장 짧은 시작 프롬프트

Codex, Claude Code, Gemini CLI 등에서 키트 폴더를 연 뒤 다음을 그대로 보냅니다.

> `agent-skill/hermes-outbound-setup/SKILL.md`를 끝까지 읽고 내 Hermes Outbound를 설치해줘. 한 번에 1~3개만 쉬운 말로 물어보고, 실행 전 계획을 보여줘. 비밀값은 채팅으로 묻지 말고, 실제 확인하지 않은 것은 완료라고 하지 마.

AI가 파일이나 터미널을 사용할 수 없는 일반 채팅 화면이라면 실제 설치는 할 수 없습니다. 이 경우에는
화면 안내와 명령 복사까지만 요청하세요.

## 사용자가 보게 될 7단계

1. **하고 싶은 일** — 채용 신호, 투자 신호, 입찰 확인, 해외 파트너 중 하나
2. **데이터** — 연습 데이터, 내 CSV/JSON, 지원되는 공개 소스
3. **사용할 장소** — 내 컴퓨터의 Desktop 앱(권장), 터미널, 준비된 서버
4. **모델과 대화 장소** — 모델 로그인, 선택형 Telegram/Discord
5. **설치 계획** — 설치 폴더, 로그인·비용·수동 확인이 필요한 단계
6. **첫 결과** — 후보, 근거, 사람이 검토할 메시지 초안
7. **선택 운영** — Obsidian, OMH, OmniRoute, 예약, 서버 계속 실행

처음에는 `채용 신호 + 연습 데이터 + 템플릿 초안 + Desktop 앱`이 기본입니다. 실제 AI 초안과 메신저는
기본 흐름이 성공한 뒤 연결합니다.

## 공식 Hermes 문서 확인 방식

설치 도우미는 검색 결과나 블로그 명령을 그대로 실행하지 않습니다. `docs_support.py`가 검토된 Hermes
버전에 맞는 공식 저장소 README와 `docs/` 문서만 고정 commit에서 가져옵니다.

```sh
python3 docs_support.py version
python3 docs_support.py sync
python3 docs_support.py query desktop
python3 docs_support.py help desktop
```

조회 주제는 `install`, `desktop`, `model`, `telegram`, `discord`, `cron`, `plugins`,
`troubleshooting`입니다. `query`는 공식 GitHub 인용 링크를 보여주고, 실제 명령은 설치된 버전의 `help`
결과를 우선합니다. 버전이 맞지 않거나 네트워크가 없으면 내려받은 내용을 실행 지시로 취급하지 않고,
키트 문서와 설치된 도움말로 돌아갑니다.

## 한 명령으로 시작·재개하기

AI의 질문 UI가 없다면 사용자 터미널에서 다음을 실행합니다. 설정이 없으면 질문을 시작하고, 있으면
완료 기록을 확인해 이어갑니다.

```sh
python3 start.py --help
python3 start.py
```

Windows PowerShell에서는 `python3` 대신 `py -3`을 사용합니다. 계정 로그인 없이 연습 결과부터
확인하려면 `python3 start.py --offline`을 사용합니다. `start.py`는 비밀이 아닌 선택만 저장하고 기존
설정을 덮어쓰지 않으며, 설치기 `setup` 또는 `resume`으로 연결합니다. 기본 설치 폴더는 Mac/Linux의
`~/.hermes-outbound`, Windows의 `%LOCALAPPDATA%\hermes-outbound`입니다.

설정만 따로 만들 때는 `prepare.py`, 브라우저 입력이 편하면 `wizard.html`을 사용할 수 있습니다. 이 두
경로의 결과는 `setup.json`이며, 이후 `start.py --config setup.json`으로 설치를 계속합니다.

## Python이 없을 때

Python이 없는 새 컴퓨터에서는 먼저 검토된 공식 Hermes 설치 파일 전체를 내려받고 SHA-256을 확인해야
합니다. 인터넷 응답을 바로 shell에 연결하지 않습니다. Python이 있다면 현재 고정 버전과 hash는
`engine_bootstrap.py --help`와 [엔진 설치 안내](ENGINE-INSTALL.md)에서 확인합니다. Python 자체가 없다면
같은 안내의 Mac 또는 Windows 명령을 사용하세요.

이 경로는 깨끗한 모든 기기 조합에서 자동 성공을 보장하지 않습니다. 오류 화면을 보존하고 설치 도우미에게
다음 조치를 요청하세요.

## 비밀값은 어디에 입력하나요?

| 항목 | 입력하는 곳 | `setup.json` 저장 |
|---|---|---|
| 제품·타깃·키워드·결과 폴더 | AI 질문, `prepare.py`, 브라우저 마법사 | 예 |
| 서버 주소·사용자·SSH 키 **경로** | AI 질문 또는 `prepare.py` | 예 |
| 모델 로그인·API 키 | 공식 로그인 화면 또는 사용자가 연 비공개 터미널 | 아니요 |
| Telegram/Discord 토큰 | 사용자가 연 비공개 터미널의 숨김 입력 | 아니요 |
| SSH 개인키 내용·암호 | 사용자의 OpenSSH 화면 | 아니요 |

AI가 연 터미널 입력창이 자동으로 비공개라는 뜻은 아닙니다. 키·토큰·비밀번호를 AI 채팅이나 터미널
자동입력 도구에 붙여넣지 마세요. 사용자가 직접 연 터미널에서 도구가 안내하는 숨김 입력을 사용합니다.

## 서버를 선택했다면

“SSH는 이 컴퓨터에서 서버에 안전하게 접속하는 방법”이라고 이해하면 됩니다. 서버 제공자 화면에서
주소/IP, 사용자 이름, 포트를 찾고 다음 순서로 진행합니다.

1. `server_access.py plan`으로 필요한 값을 확인
2. 새 키라면 사용자 터미널에서 `keygen` 후 `.pub` 공개키만 서버에 등록
3. 제공자 화면에서 따로 확인한 fingerprint로 `trust`
4. `probe`로 읽기 전용 접속 확인
5. `deploy`로 매번 새 폴더에 비밀 없는 키트 복사
6. 사용자가 직접 연 SSH 터미널에서 반환된 폴더로 이동해 설치 계획부터 계속

정확한 인자는 먼저 `python3 server_access.py --help`로 확인합니다. `deploy` 성공은 파일 복사
성공이지 Hermes 설치나 24시간 실행 성공이 아닙니다.

## 실행과 재개

일반 사용자는 같은 시작 명령을 다시 실행하면 완료 기록부터 이어집니다.

```sh
python3 start.py --config setup.json
```

문제를 진단하거나 특정 단계만 다시 확인할 때만 `python3 installer.py --help`와 `status`를 사용합니다.
모델, 채널, 외부 서비스 단계는 비밀 입력이 필요할 수 있으므로 사용자가 직접 연 터미널에서 실행합니다.
OMH는 권장 기본값이지만 설치와 확인은 별도 상태로 보고합니다. OmniRoute는 사용자가 선택했고 Docker
요건을 충족할 때만 진행합니다. 세부 명령은 `omh_setup.py --help`, `omniroute_setup.py --help`에서
확인합니다.

예약과 서버 서비스는 첫 수동 결과 이후에만 켭니다. “예약 등록”과 “다음 예약 시각에 실제 성공”,
“서비스 등록”과 “재부팅 뒤 다시 실행”을 구분해서 확인합니다.

## 완료 보고에서 확인할 것

| 항목 | 선택 | 상태 | 확인한 증거 | 다음 행동 |
|---|---|---|---|---|
| Hermes 앱/명령 |  |  | 실제 실행 화면 |  |
| 모델 |  |  | 실제 짧은 응답 |  |
| 메신저 |  |  | 본인 왕복·타인 거부 |  |
| 데이터 |  |  | sample/file/live와 출처 |  |
| 결과 |  |  | 후보·근거·초안 경로 |  |
| 예약/서버 |  |  | 다음 실행·재부팅 시험 |  |

연습 데이터 성공은 실시간 수집 성공이 아니고, 인증 저장은 실제 모델 응답이나 메시지 왕복 성공이
아닙니다. 막힌 단계는 오류, 이미 확인한 것, 다음 재개 명령을 함께 남깁니다.
