# Linux 서버 SSH 접근 준비

`server_access.py`는 로컬 SSH 키 준비, 최초 host key 신뢰, 읽기 전용 환경 probe, 명시적인
키트 staging을 담당합니다. `deploy`는 파일을 복사하지만 Hermes/Python을 설치하거나 실행하지 않고,
`sshd`, 방화벽, 사용자, 서비스 설정을 바꾸지 않습니다.

## 설정 필드

실제 wizard가 만든 `setup.json`의 원격 설치 항목은 다음 이름을 사용합니다.

```json
{
  "target": "server",
  "install_location": "remote",
  "server_host": "server.example.com",
  "server_user": "ubuntu",
  "server_port": 22,
  "ssh_key_action": "existing",
  "ssh_key_path": "<USER_HOME>/.ssh/hermes_outbound_server_ed25519"
}
```

- `install_location`: `local` 또는 `remote`. remote일 때만 SSH 필드가 필요합니다.
- `ssh_key_action`: 기존 키 쌍은 `existing`, 새 전용 키는 `generate`.
- `ssh_key_path`: 항상 개인키 경로입니다. 공개키는 같은 경로의 `.pub`입니다.
- 호스트에 `user@host`를 넣지 않습니다. 사용자와 호스트를 별도 필드에 둡니다.
- `key_path`, `server_key_path` 같은 다른 이름은 추측하지 않고 거부합니다.

설정 파일에는 비밀번호, key passphrase, private key 본문을 넣지 마세요.

## 1. 계획만 확인

```sh
python3 server_access.py plan --config setup.json
```

이 명령은 `ssh`/`ssh-keygen` 발견 여부, key pair 상태와 다음 단계만 출력합니다. SSH 연결이나
파일 변경은 하지 않습니다. `blocked` 원인을 해결한 뒤 다시 실행합니다.

## 2A. 기존 키 사용

`ssh_key_action=existing`이면 private key와 `.pub`이 모두 있어야 합니다. 기존 개인키의
passphrase를 setup.json이나 채팅에 입력하지 않습니다. 키가 다른 서비스용이라면 재사용 정책을
검토하고, 워크숍 전용 키를 새로 만드는 편이 관리하기 쉽습니다.

## 2B. 새 전용 키 생성

설정에서 아직 존재하지 않는 고유 경로와 `ssh_key_action=generate`를 선택한 뒤 실행합니다.

```sh
python3 server_access.py keygen --config setup.json
```

실제 `ssh-keygen -t ed25519 -a 100`이 실행되고 같은 터미널에서 passphrase를 직접 묻습니다.
passphrase는 명령 인자·설정·로그에 들어가지 않습니다. 러너는 빈 passphrase를 자동 지정하지 않고,
private key 또는 `.pub` 중 하나라도 이미 있으면 덮어쓰지 않습니다.

## 3. 공개키를 서버에 등록 — 명시적 사람 단계

서버 제공자 콘솔의 SSH Keys 기능이나 조직 관리자가 승인한 절차를 우선 사용하세요. 업로드하는 것은
`.pub` 공개키 한 줄뿐이며 private key는 로컬 기기를 떠나면 안 됩니다.

서버가 이미 password SSH를 허용하고 조직 정책상 `ssh-copy-id`가 승인된 경우에만, 사용자가 직접
다음 형식의 명령을 실행할 수 있습니다.

```sh
ssh-copy-id -i /absolute/path/to/key.pub -p 22 REMOTE_USER@REMOTE_HOST
```

이 단계는 원격 `authorized_keys`를 변경하고 password를 대화형으로 요구할 수 있으므로
`server_access.py`가 자동 실행하지 않습니다. password를 setup.json, 셸 인자, 채팅, 로그에 넣지
마세요. 이 도구는 원격 password 로그인, sshd 설정 변경, 방화벽 포트 개방을 대신하지 않습니다.

## 4. Host fingerprint를 독립적으로 확인

최초 연결 전에 서버 제공자 콘솔, 인스턴스 상세 화면 또는 관리자를 통해 ED25519 host key의
`SHA256:...` fingerprint를 확보합니다. 같은 SSH 연결에서 받은 값만으로 스스로 검증했다고
간주하면 안 됩니다.

```sh
python3 server_access.py trust \
  --config setup.json \
  --fingerprint 'SHA256:독립적으로_확인한_값'
```

명령이 fingerprint를 다시 입력받은 뒤 `StrictHostKeyChecking=ask`로 최초 SSH를 엽니다. SSH가
표시한 값이 독립 확인값과 정확히 같을 때만 사용자가 직접 `yes`를 입력합니다. 불일치하면 즉시
중단하고 서버 제공자/관리자에게 확인하세요. `accept-new`, `no`, `ssh-keyscan` 자동 등록은 사용하지
않습니다.

## 5. 읽기 전용 probe

```sh
python3 server_access.py probe --config setup.json
```

probe는 반드시 `StrictHostKeyChecking=yes`를 사용하고 다음 고정 명령만 실행합니다.

- `uname -srm`
- `command -v python3`, `python3 --version`, Python 3.11 이상 판정
- `command -v hermes`, `hermes --version`

사용자 입력을 remote command에 삽입하지 않습니다. 결과는 OS/Python/Hermes의 존재와 버전 확인일
뿐이며, 원격 설치·수정·gateway 가동·서비스 복구 증거가 아닙니다.

## 6. 명시적 키트 staging

probe가 성공한 뒤에만 다음을 실행합니다.

```sh
python3 server_access.py deploy --config setup.json
```

deploy는 `StrictHostKeyChecking=yes`로 SSH와 원격 `python3 >= 3.11`을 다시 확인한 뒤, 매번 새
`$HOME/hermes-outbound-stage.XXXXXXXX`를 만듭니다. 기존 설치 경로는 선택하거나 덮어쓰지 않습니다.

- 명시 allowlist의 Python, 문서, skill, pack, 합성 sample만 ZIP에 넣습니다.
- `setup.json`, `.env`, 키, token, 현장 output, cache는 ZIP에 넣지 않습니다.
- 원본 설정은 kit schema로 다시 검증하고 SSH 접속 필드를 제거합니다.
- 원격용 설정은 `install_location=local`, `target=server`, `os_hint=linux`,
  `desktop_mode=terminal`, `install_home=~/.hermes-outbound`로 변환됩니다. 데스크톱 앱 선택은
  원격 서버에 잘못 전달하지 않습니다.
- 배포 묶음에는 canonical home과 scoped launcher를 강제하는 `paths.py`가 포함됩니다. 서버에서도 전역
  PATH의 우연한 `hermes`를 설치 성공으로 간주하지 않습니다.
- 로컬 vault 경로는 비우며, 서버에서 새로 선택해야 합니다.
- 원격 Python extractor는 절대·`..` 경로, stage 이탈, symlink, 특수 파일, 기존 target을
  거부하고 파일을 독점 생성합니다.

성공 JSON의 `remote_path`는 새 키트 위치입니다. SSH로 그 경로에 접속해 `setup.json`의
서버 설치를 계속할 수 있습니다. 원격 변환 설정에는 전용 output/vault 기본 경로가 들어갑니다.

비대화형 환경에서는 다음 명령이 배포 후 검토 가능한 SSH argv만 반환합니다.

```sh
python3 server_access.py setup --config setup.json
```

사용자 소유 터미널에서 검토 후 명시적으로 실행할 때만 `--execute`를 붙입니다. 실제 TTY가 아니면
`--execute`가 있어도 실행하지 않고 `needs_user_terminal`을 반환합니다.

```sh
python3 server_access.py setup --config setup.json --execute
```

중단 후에는 setup 결과의 `remote_path`로 새 배포 없이 재개할 수 있습니다.

```sh
python3 server_access.py resume --config setup.json \
  --remote-path <REMOTE_STAGE>/hermes-outbound-kit \
  --execute
```

실제 원격 명령은 고정된 `cd <validated-remote-path> && python3 installer.py setup --config setup.json`이며,
비밀값을 argv나 stdin으로 운반하지 않습니다. staging 또는 setup 프로세스 exit 0은 모델 응답, 채널 왕복,
gateway 재시작 성공을 의미하지 않습니다.

## 7. 선택 OmniRoute localhost tunnel

OmniRoute를 선택한 설정만 loopback tunnel 명령을 만들 수 있습니다. 서버의 `127.0.0.1:20128`을 로컬
loopback에만 연결하며 LAN/공인 인터페이스로 공개하지 않습니다.

```sh
python3 server_access.py tunnel --config setup.json --local-port 22128
python3 server_access.py tunnel --config setup.json --local-port 22128 --execute
```

첫 명령은 argv만 반환합니다. 두 번째도 사용자 소유 TTY에서만 `ssh -N -L
127.0.0.1:22128:127.0.0.1:20128`을 실행합니다.

## 현재 의도적으로 하지 않는 것

- 키 자동 업로드 또는 password 자동 입력
- unknown host key 자동 수락
- Python/Hermes/OMH 설치
- `sshd_config`, 방화벽, systemd 변경

`deploy` 이후의 엔진·서비스 설치는 서버 상태와 사용자 승인을 확인하는 별도 단계입니다.
