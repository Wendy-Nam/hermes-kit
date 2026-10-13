# Hermes 엔진 설치 계약

이 문서는 Hermes Outbound Kit의 스킬/설정 파일보다 먼저 필요한 **실제 Hermes Agent 엔진** 설치 경로를
정의한다. `kit.py install`은 엔진을 설치하지 않는다. `engine_bootstrap.py install`은 사용자가 명시적으로
호출한 경우에만 검토·해시 고정된 installer 파일을 안전한 argv로 실행하고, 전용 home의 launcher와 고정
commit을 확인한다. `plan`, `download`, `verify`, `command`는 실행 전 검토 단계다.

설치 도우미 자체는 Python 3.11 이상이 필요하다. 기본 home은 macOS/Linux/WSL2에서
`~/.hermes-outbound`, Windows native에서 `%LOCALAPPDATA%\hermes-outbound` 하나만 사용한다.
전역 PATH의 우연한 `hermes`는 설치 성공이나 실행 대상으로 채택하지 않는다.

## 검토한 upstream

- 공식 저장소: <https://github.com/NousResearch/hermes-agent>
- 공식 README의 지원 경로: Linux, macOS, WSL2의 `install.sh`; Windows native의 `install.ps1`
- 검토일: 2026-10-13
- 안정 태그: `v0.21.7`
- 태그가 가리키는 커밋: `71d34bad1045610252eda02ee79549436896e784`
- `scripts/install.sh`: 1,049줄, 52,776 bytes,
  SHA-256 `034845e34289813ff5fb7fd3e071ec69f6b14aee8ba297a477b31dda6374cb86`
- `scripts/install.ps1`: 1,449줄, raw Git blob 기준 75,835 bytes,
  SHA-256 `61824d6b47be29ab793d0e72872cf56cd7a3e99cbe40abeb177a6c9eef52f485`
- 같은 커밋의 `pm/lock.json` SHA-256:
  `49b79259220160f147255078a19af541a5f328d3871c8041cc1eb909d19eb549`
- 같은 커밋의 `uv.lock` SHA-256:
  `95a3082629ffecdabb1bad0880ccf5a237d47cd8fb67d86094f6d3d331f4eeac`

PowerShell 파일은 저장소 checkout에서 `.gitattributes`에 의해 CRLF로 보일 수 있다. 위 해시는 이 도구가
고정 URL에서 받는 raw Git blob의 LF bytes 기준이다. `v0.21.7`은 annotated release tag이지만 tag object에서
서명은 확인되지 않았다. 따라서 이 키트는 “서명된 installer”라고 주장하지 않고, 검토한 정확한 bytes와
커밋을 allowlist로 고정한다.

공식 README는 다음 one-liner를 안내하지만, 워크숍 키트에서는 사용하지 않는다.

```text
curl .../install.sh | bash
iex (irm .../install.ps1)
```

이 방식은 실행 전에 받은 전체 파일의 해시와 내용을 확인하기 어렵다. 아래 단계는 파일을 먼저 저장하고
검증하며, 해시가 다르면 실행 명령을 만들지 않는다.

## 전체 installer 검토 결과

고정한 두 installer의 전체 파일을 읽고 다음 동작을 확인했다.

- `main` branch에서 지정 commit이 조상인지 확인한 뒤 그 commit을 detached checkout한다.
- upstream PM이 고정한 `uv 0.12.3`을 플랫폼별 SHA-256으로 확인해 내려받는다.
- 관리형 Python 3.14, Python 의존성, Node.js/npm, ripgrep, FFmpeg 등을 `pm/lock.json`과 `uv.lock` 계약으로
  설치한다. 호스트 Python 3.14가 없으면 관리형 Python을 내려받는다.
- `desktop_mode=terminal`은 데스크톱 Electron 앱을 만들지 않는다. `desktop_mode=app`은 검토한 POSIX
  `--include-desktop` 또는 Windows `-IncludeDesktop`을 사용한다. 두 모드 모두 대용량 브라우저와
  computer-use driver는 제외한다.
- `--non-interactive`는 모델/API 설정과 gateway service 설치를 건너뛴다. 엔진 설치 후 사용자가 별도 비공개
  터미널에서 `hermes setup`을 해야 한다.
- `.env`와 `config.yaml`은 없을 때만 example에서 만든다. 그러나 source completion의 config migration과
  bundled skill 동기화는 전용 Hermes home 내부를 갱신할 수 있다.
- 설치 로그와 선택적 shared-metrics receipt가 Hermes home에 생길 수 있다. installer 주석에 따르면
  metrics가 꺼져 있으면 receipt는 전송되지 않고 제거된다. 이 검토는 외부 telemetry 서버 호출 시험이 아니다.

### 실제 쓰기 범위

Linux/macOS/WSL2:

- 기본 전용 home: `~/.hermes-outbound`
- source checkout: `~/.hermes-outbound/hermes-agent`
- tool/runtime/config/log/session/skill 디렉터리: 전용 home 아래
- launcher: `~/.local/bin/hermes`, `hermes-acp`, `hermes-agent`
- PATH 설정: 현재 shell에 따라 `~/.bashrc`, `~/.profile`, 기존 `~/.bash_profile`/`~/.bash_login`,
  `~/.zshrc`, `~/.zprofile`, 또는 fish config에 한 줄을 추가할 수 있음
- 최소 Linux에서 `libatomic.so.1`이 없으면 distro package가 필요하다. 비대화 설치 명령은 sudo password를
  받지 않으므로 사전에 `libatomic1`(Debian/Ubuntu 계열)을 설치해야 할 수 있음

Windows native:

- 기본 전용 home: `%LOCALAPPDATA%\hermes-outbound`
- source checkout과 tools/config/bin: 전용 home 아래
- `%LOCALAPPDATA%\hermes-outbound\bin`을 Windows User PATH에 추가
- Git이 없으면 해시 고정된 Portable Git을 전용 tool store에 설치하며 system Git을 교체하지 않음
- 이 키트 명령은 `-IncludeDesktop`을 쓰지 않으므로 desktop/Start Menu shortcut을 만들지 않음

### 기존 설치 위험

upstream installer를 기존 checkout에 다시 실행하면 변경 파일을 stash하고, branch가 fast-forward되지 않을 때
backup ref를 만든 뒤 `reset --hard origin/main`을 수행할 수 있다. upstream은 관련 없는 launcher를 인식하면
덮어쓰지 않지만, 그 경우 새 설치보다 기존 `hermes`가 계속 PATH에서 먼저 실행될 수 있다.

그래서 `engine_bootstrap.py command`는 다음 중 하나라도 있으면 명령 생성을 거부한다.

- 전용 `install-dir`가 이미 비어 있지 않음
- 공유 `hermes` launcher가 이미 존재함
- `hermes`가 이미 PATH에 있음
- 전용 home이 symlink, 파일, 또는 읽을 수 없는 디렉터리임

기존 Hermes가 있다면 새로 설치하지 말고 먼저 그 실행 파일·home·버전을 식별한다. 개인 Hermes를 워크숍
전용 home으로 “업데이트”하지 않는다. 이 보수적 거부는 자동 복구 기능이 아니라 사용자 데이터 보호 gate다.

## Linux 또는 macOS

키트 루트에서 계획을 먼저 본다.

```bash
python3 engine_bootstrap.py plan
```

`conflicts`가 비어 있고 `ready_to_download=true`, `python_3_11_plus=true`일 때만 고정 installer를 받는다.

```bash
python3 engine_bootstrap.py download \
  --platform posix \
  --output .engine-artifacts

python3 engine_bootstrap.py verify \
  --platform posix \
  --artifact .engine-artifacts/hermes-install-0.21.7.sh
```

원하면 실행 전에 전체 파일을 직접 연다.

```bash
less .engine-artifacts/hermes-install-0.21.7.sh
```

설치 방식에 따라 `--desktop-mode terminal` 또는 `--desktop-mode app`을 정한다. 데스크톱 앱 모드 예시는
다음과 같다.

```bash
python3 engine_bootstrap.py command \
  --platform posix \
  --artifact .engine-artifacts/hermes-install-0.21.7.sh \
  --desktop-mode app
```

`command`는 실행하지 않는다. 실제 설치를 명시적으로 수행하려면 같은 검증된 artifact로 다음을 실행한다.

```bash
python3 engine_bootstrap.py install \
  --platform posix \
  --artifact .engine-artifacts/hermes-install-0.21.7.sh \
  --desktop-mode app
```

POSIX install 액션은 upstream이 쓰는 `HOME`, `HERMES_HOME`, runtime store를 전용 home으로 묶는다.
따라서 사용자의 공용 `~/.local/bin`이나 공용 shell rc를 설치 성공 판정에 사용하지 않는다. 설치가 끝나면
고정 commit, 전용 managed Python의 `--version`, 전용 launcher의 `--help`, 앱 모드에서는 공식 release
산출물까지 확인한다. 후속 Python helper는 `paths.resolve_python()`으로 이 managed Python을 재사용하며
호스트의 우연한 `python`/`PYTHONPATH` 환경을 설치 성공으로 간주하지 않는다.

```bash
git -C ~/.hermes-outbound/hermes-agent rev-parse HEAD
HERMES_HOME="$HOME/.hermes-outbound" "$HOME/.local/bin/hermes" --help
```

키트와 자동화에서는 위 공용 launcher 예시 대신 `paths.resolve_hermes()`가 찾는
`~/.hermes-outbound/hermes-agent/.hermes/bin/hermes`를 사용한다. 데스크톱 앱 실행 argv는 다음으로 확인한다.

```bash
python3 engine_bootstrap.py app-command --platform posix
```

이는 브라우저 wizard가 아니라 공식 scoped launcher의 `hermes desktop --skip-build`다.

첫 출력은 반드시 `71d34bad1045610252eda02ee79549436896e784`여야 한다. 그 다음 모델 연결은 비밀값이
노출되지 않는 사용자 터미널에서 진행한다.

```bash
HERMES_HOME="$HOME/.hermes-outbound" "$HOME/.local/bin/hermes" setup
HERMES_HOME="$HOME/.hermes-outbound" "$HOME/.local/bin/hermes" doctor
```

`--help` 성공은 모델 응답이나 gateway 동작의 증거가 아니다. 실제 모델에 무해한 질문 한 번을 보내고,
선택한 channel은 본인 허용 사용자 왕복과 미허용 사용자 거부를 별도로 확인한다.

## Windows native

PowerShell에서 키트 루트로 이동한 뒤 실행한다. Python launcher가 `py`인 환경은 `python3` 대신 `py -3`을 쓴다.

```powershell
py -3 engine_bootstrap.py plan --platform windows
py -3 engine_bootstrap.py download --platform windows --output .engine-artifacts
py -3 engine_bootstrap.py verify --platform windows `
  --artifact .engine-artifacts\hermes-install-0.21.7.ps1
py -3 engine_bootstrap.py command --platform windows `
  --artifact .engine-artifacts\hermes-install-0.21.7.ps1 --desktop-mode app
py -3 engine_bootstrap.py install --platform windows `
  --artifact .engine-artifacts\hermes-install-0.21.7.ps1 --desktop-mode app
py -3 engine_bootstrap.py app-command --platform windows
```

마지막 출력의 `private_terminal_command`를 사용자가 같은 비공개 PowerShell에서 직접 실행한다. 새 터미널을
연 다음 확인한다.

```powershell
git -C "$env:LOCALAPPDATA\hermes-outbound\hermes-agent" rev-parse HEAD
$env:HERMES_HOME = "$env:LOCALAPPDATA\hermes-outbound"
& "$env:LOCALAPPDATA\hermes-outbound\bin\hermes.exe" --help
& "$env:LOCALAPPDATA\hermes-outbound\bin\hermes.exe" setup
& "$env:LOCALAPPDATA\hermes-outbound\bin\hermes.exe" doctor
```

Windows Defender가 `uv.exe`를 격리하는 사례는 upstream README에도 기록되어 있다. 경고를 무조건 무시하거나
폴더 전체를 즉시 예외 처리하지 말고, upstream이 안내한 GitHub attestation과 내려받은 archive 비교를 먼저
수행한다.

## Windows WSL2

WSL2는 Windows native와 별개 설치다. WSL 터미널 안에서 Linux 절차를 사용하며 home은 WSL의
`~/.hermes-outbound`, launcher는 WSL의 `~/.local/bin/hermes`다. Windows의 `%LOCALAPPDATA%` 설치와 설정,
gateway service, 볼륨을 공유한다고 가정하지 않는다. 워크숍에서는 native 또는 WSL2 중 하나를 먼저 고르고
그 경로로 끝까지 검증한다.

## Linux 서버

서버에서도 Linux 절차와 동일한 고정 installer를 **서버의 사용자 계정**에서 실행한다. root와 일반 사용자를
섞지 않는다. 먼저 foreground CLI와 모델 응답을 검증한 다음에만 설치된 버전의 help를 보고 gateway service를
설치한다.

```bash
HERMES_HOME="$HOME/.hermes-outbound" "$HOME/.local/bin/hermes" gateway --help
HERMES_HOME="$HOME/.hermes-outbound" "$HOME/.local/bin/hermes" gateway install --help
```

이 문서 작성 환경에는 기존 `hermes` 실행 파일이 없어 Hermes 자체 `--help`는 실행하지 못했다. 대신 검증된
installer 사본의 `--help`만 실행했고, installer나 엔진을 현재 HOME에 실행하지 않았다. 원격 서버 설치와
service 활성화도 수행하지 않았다.

## 현재 검증 상태

- official tag/commit 조회: live GitHub read-only 확인
- 두 installer 전체 파일: clone과 exact raw URL bytes 비교 완료
- POSIX installer `--help`: 실행 완료, home/runtime 쓰기 없음
- `engine_bootstrap.py download`: exact raw 파일 다운로드와 SHA-256 확인 완료
- `engine_bootstrap.py command`: 고정 commit, 전용 home, non-interactive, browser/computer-use 제외 명령 생성 확인
- 이 작업 환경의 실제 Hermes dependency 설치: **실행하지 않음**. `install` 구현은 임시 가짜 subprocess와
  설치 산출물로 검증했으며, 실제 공유 환경에는 자동 실행하지 않았다.
- 실제 Hermes CLI/model/gateway: **미검증**

다운로드 검증이 성공해도 dependency CDN, OS library, 모델 계정, gateway 권한이 동작한다는 뜻은 아니다.
설치와 로그인은 사용자 명시 행동이며, 각 단계 결과를 별도로 기록한다.
