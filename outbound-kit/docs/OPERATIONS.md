# 운영·스케줄·서버 볼트 동기화

이 문서는 수동으로 성공한 아웃바운드 workflow를 **명시적 승인 후에만** 반복 실행하고,
서버가 만든 Markdown 결과를 로컬 볼트로 안전하게 가져오는 방법을 설명한다. 자동 메일/DM
발송은 포함하지 않는다.

## 증거 수준

- `operations.py`: 스케줄 계획, 실제 `workflow.py run` 1회 실행, receipt, Linux user
  systemd/macOS LaunchAgent/Windows user Task Scheduler descriptor 생성 코드가 있다.
- `vault_sync.py`: StrictHostKeyChecking을 유지하는 read-only SSH manifest/pull과 staging,
  충돌 보고 코드가 있다.
- 테스트는 임시 디렉터리와 mock subprocess/transport만 사용한다. 이 저장소의 검증이 실제
  사용자 계정에 persistent job을 등록했거나 실제 SSH 서버를 동기화했다는 뜻은 아니다.
- persistent scheduler 등록, 재부팅/로그인 후 실행, 실제 서버 SSH는 대상 기기에서 별도로
  확인해야 한다.

## 설정 필드

`setup.json`의 비밀값이 아닌 운영 필드는 다음과 같다.

```json
{
  "schedule_enabled": false,
  "schedule_frequency": "daily",
  "schedule_time": "09:00",
  "timezone": "Asia/Seoul"
}
```

`schedule_enabled` 기본값은 `false`다. 빈도는 `daily` 또는 `hourly`, timezone은 시스템이
인식하는 IANA 이름이어야 한다. `schedule_time`은 daily의 시각이며 hourly에서는 분 값을
사용한다. Linux systemd는 IANA timezone을 `OnCalendar`에 넣는다. macOS launchd와 Windows
Task Scheduler trigger는 호스트 timezone을 사용하므로, 실제 적용 전 호스트 timezone이 설정과
같은지 확인해야 한다. `TZ`도 workflow 프로세스에 전달된다.

## 수동 실행을 먼저 증명하기

도움말과 plan은 아무것도 등록하지 않는다.

```sh
python3 operations.py --help
python3 operations.py plan \
  --config setup.json \
  --home ~/.hermes-outbound \
  --output ./output \
  --vault ~/Documents/Hermes-Outbound
```

계획의 workflow argv는 항상 같은 Python과 canonical 경로로 아래 계약을 실행한다.
`source_mode`와 `draft_mode`는 생략하지 않는다. 생략하면 workflow parser 기본값인
`sample/template`로 조용히 바뀔 수 있기 때문이다.

```text
python workflow.py run --config CONFIG --home HOME --output OUTPUT --vault VAULT \
  --source-mode MODE [--source-path PATH] --draft-mode MODE [--drafts-file PATH]
```

`scenario`가 지정되면 `--scenario`도 전달한다. `source_mode=file`은 `source_path`,
`draft_mode=provided`는 `drafts_path`가 없으면 plan 단계에서 중단한다. config digest뿐 아니라
해석된 source/draft 경로와 mode도 operation contract digest에 포함되어, 다른 실제 소스의 성공
receipt가 scheduler 설치 승인으로 재사용되지 않는다. 값이 없는 기본 경로도 argv에는
`--source-mode sample --draft-mode template`로 명시된다.

첫 수동 실행:

```sh
python3 operations.py run-once \
  --config setup.json \
  --home ~/.hermes-outbound \
  --output ./output \
  --vault ~/Documents/Hermes-Outbound
```

성공하면 `.operations/operations.json`의 `last_attempt`와 `last_success`에 실제 exit code와
계약 digest가 기록된다. 실패하면 `last_attempt`만 바뀌고 마지막 성공은 보존된다. subprocess
stdout/stderr, 설정 본문, command line은 운영 로그에 저장하지 않는다. 겹치는 실행은 lock으로
중단하며 JSONL 운영 로그는 최근 100개 metadata 이벤트로 제한한다.

## scheduler 설치·상태·해제

`install`만 입력해도 등록되지 않는다. 다음 조건이 모두 필요하다.

1. `schedule_enabled: true`
2. 같은 config와 `<KIT_HOME>/vault` 계약의 **수동** `run-once` 성공 receipt
3. 사용자가 직접 입력한 `install --apply`

```sh
# 적용 전 계획만 반환
python3 operations.py install --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ~/Documents/Hermes-Outbound

# 명시적으로 적용
python3 operations.py install --apply --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ~/Documents/Hermes-Outbound

python3 operations.py status --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ~/Documents/Hermes-Outbound
```

플랫폼별 대상은 다음과 같다.

- Linux: `~/.config/systemd/user/hermes-outbound.service`와 `.timer`
- macOS: `~/Library/LaunchAgents/com.hermes.outbound.plist`
- Windows: `%LOCALAPPDATA%\HermesOutbound\HermesOutbound.xml`, user Task
  `HermesOutbound`

descriptor 또는 task가 다르면 덮어쓰지 않는다. 해제도 먼저 계획만 보여주며 `disable
--apply`가 필요하다. 이 helper가 만든 것과 내용이 다른 descriptor는 보존한다.

```sh
python3 operations.py disable --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ~/Documents/Hermes-Outbound
python3 operations.py disable --apply --config setup.json --home ~/.hermes-outbound \
  --output ./output --vault ~/Documents/Hermes-Outbound
```

## Hermes gateway lifecycle

Hermes Agent v0.21.7 소스의 CLI 도움말/파서에서 확인한 lifecycle은 다음과 같다.

```text
hermes gateway run
hermes gateway install
hermes gateway start
hermes gateway status
hermes gateway stop
```

`gateway run`은 foreground 확인 경로다. `operations.py plan`은 위 명령과 동일한
`HERMES_HOME`을 안내하지만 실행하지 않는다.
gateway background service와 kit workflow scheduler는 서로 다른 lifecycle이다. 대상 기기의
설치된 `hermes --help`와 각 subcommand help를 다시 확인한 뒤 실행한다.

## 서버 볼트 pull

서버에서 생성한 결과를 로컬 Obsidian 볼트로 가져올 때는 기존 SSH 키와 이미 신뢰한 host key가
필요하다. 비밀번호 bootstrap, host key 자동 승인, private-key 내용 입력은 지원하지 않는다.

```sh
python3 vault_sync.py --help
python3 vault_sync.py plan \
  --config setup.json \
  --host server.example.com --port 22 --user ubuntu \
  --key ~/.ssh/hermes_workshop \
  --remote-vault /srv/hermes/vault \
  --local-vault ~/Documents/Hermes-Outbound
```

`plan`은 네트워크를 사용하지 않는다. 실제 read-only pull은 별도 동작이다.

```sh
python3 vault_sync.py pull \
  --config setup.json \
  --host server.example.com --port 22 --user ubuntu \
  --key ~/.ssh/hermes_workshop \
  --remote-vault /srv/hermes/vault \
  --local-vault ~/Documents/Hermes-Outbound
```

안전 계약:

- OpenSSH `BatchMode=yes`, `StrictHostKeyChecking=yes`, `IdentitiesOnly=yes`
- 서버를 수정하지 않는 `python3` manifest/read 명령만 사용
- shell glob/recursive `scp`/`rsync` 없이 manifest의 각 Markdown 파일을 개별 확인
- `Dashboard.md`, `Inbox/`, `Accounts/`, `Evidence/`, `Scores/`, `Drafts/`, `Review/`,
  `Runs/` 아래 `.md`만 허용
- `.env`, 키, credential, config JSON, symlink, 비 Markdown 파일 제외
- 파일별 size/SHA-256 확인 후 staging
- machine-owned 노트는 로컬 `user-notes` 구간을 보존해 병합
- 서로 다른 사람 관리 노트와 인식할 수 없는 로컬 노트는 덮어쓰지 않고
  `conflicts.json`과 staging 경로를 남김
- 로컬 파일을 삭제하지 않음

상태 확인:

```sh
python3 vault_sync.py status \
  --config setup.json \
  --host server.example.com --user ubuntu --key ~/.ssh/hermes_workshop \
  --remote-vault /srv/hermes/vault --local-vault ~/Documents/Hermes-Outbound
```

`last_attempt`와 `last_success`는 분리된다. 실패한 최신 pull이 과거 성공을 성공으로 가장하지
않는다. 충돌이 0이어도 Obsidian GUI 동작이나 서버의 workflow가 live 검증됐다는 의미는 아니다.
