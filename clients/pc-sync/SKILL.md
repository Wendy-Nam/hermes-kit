---
name: hermes-vps-setup
description: hermes-kit으로 설치한 VPS의 Hermes 에이전트와 내 컴퓨터의 Obsidian을 양방향 동기화. PC에 Syncthing·Obsidian 자동 설치, 업무/개인 볼트 2개 자동 페어링, 실제 파일 왕복까지 검증. "옵시디언 연동", "노트 동기화", "싱크띵", "hermes sync", "PC에서 노트 보기" 요청 시 사용.
---

# Hermes ↔ PC 옵시디언 동기화

`hermes-kit`으로 이미 배포·설정된 VPS의 Hermes 에이전트와, 내 컴퓨터의
Obsidian을 양방향으로 동기화한다. **서버 설정은 변경하지 않는다.**

## 무엇을 하는가 / 하지 않는가

| | 이 스킬 | hermes-kit `/setup` |
|---|---|---|
| 모델·API 키 설정 | ❌ 안 함 | ✅ 담당 |
| OMH·역할 프로필 설치 | ❌ 안 함 | ✅ 담당 |
| Syncthing 서버 설정 | 기기·볼트 **공유 등록만** | 볼트 생성·컨테이너 |
| PC Syncthing·Obsidian 설치·페어링 | ✅ 담당 | ❌ (가이드만) |
| 동기화 동작 검증 | ✅ 실제 파일 왕복 | ❌ 하지 않음 |

> 이전 버전은 서버 config를 직접 덮어썼고(프로필·OMH·크론), 그 결과
> hermes-kit의 `/setup`과 **같은 파일에 두 개가 쓰는** 일이 생겼다.
> 서버 쪽은 전부 kit에 넘기고, 이 스킬은 PC 쪽만 automating한다.

전체 경로(준비물 → VPS 배포 → `/setup` → PC 동기화)는 [ONBOARDING.md](ONBOARDING.md)에
정리되어 있습니다. 이 스킬은 그중 PC 구간만 담당합니다.

이 폴더는 hermes-kit 저장소의 `clients/pc-sync`이며, 별도 저장소를 설치할 필요가 없습니다.

## 전제조건

- hermes-kit이 배포되어 있고 Discord `/setup`을 끝낸 상태 (볼트가 있어야 한다)
- 로컬: 맥 또는 윈도우(Git Bash). `ssh`, `curl` 필요
- 기존 Syncthing이 있으면 재사용한다 (자동으로 찾아 붙인다)

## 🔒 절대 규칙 (Claude가 반드시 지킬 것)

1. **API 키를 이 스킬로 받지 않는다.** 키 설정은 hermes-kit의 Discord `/setup` 모달이 담당한다. 사용자가 키를 여기 붙여넣으려 하면 멈추고 `/setup`을 쓰게 안내한다.
2. **서버 설정을 직접 고치지 않는다.** `config.yaml`, `cron/jobs.json`, 프로필, OMH를 이 스크립트에서 만들거나 덮어쓰지 않는다. hermes-kit이 소유하는 영역이다.
3. **컨테이너 재시작은 서비스 중단이다.** 이 스킬은 재시작하지 않는다. 필요하면 사용자에게 물어 Hostinger에서 직접 하게 한다.
4. 스크립트가 실패하면 **고쳐서 재실행**한다. 전부 멱등이다. 스크립트를 우회해 수동 ssh 명령으로 대체하지 않는다.

## 실행 순서 (3단계)

| 단계 | 명령 | 하는 일 |
|------|------|---------|
| 1 | `bash scripts/00-preflight.sh` | 키트 컨테이너·Syncthing 볼륨·볼트 2개 확인 |
| 2 | `bash scripts/01-pc-sync.sh` | Syncthing 설치/기동/자동실행 등록, 서버 볼트 2개 페어링, Obsidian 설치, 볼트 열기 |
| 3 | `bash scripts/02-verify.sh` | **실제로 파일이 서버→PC로 왕복하는지 확인** |

각 스크립트는 끝에서 다음 단계를 안내한다. 항상 이 스킬 폴더를 기준으로 실행할 것.

## 볼트 구조

서버: `/var/syncthing/vaults/work`, `/var/syncthing/vaults/personal`
PC:   `~/HermesVaults/work`, `~/HermesVaults/personal` (`LOCAL_VAULT_ROOT`으로 변경 가능)

Syncthing 폴더 ID는 `hermes-work`, `hermes-personal`이다. 이 값은
hermes-kit의 `syncthing_setup.FOLDERS`와 **반드시 같아야 한다.**
값이 어긋나면 공유는 만들어지지만 파일이 오가지 않는다.

## 사용자에게 알려 줄 점

- 첫 동기화는 1~2분 걸린다. 파일이 안 오면 "안 된다"가 아니라 아직 전송 중이다.
- 옵시디언을 켜 두면 `workspace` 파일이 계속 바뀌어 충돌 난다. 스크립트가 `.stignore`를 자동 생성한다.
- 동기화는 **양방향**이다. PC에서 지운 파일은 서버에서도 지워진다. 중요 문서는 PC에도 사본을 두거나, 키트의 PC 동기화를 다시 설정하기 전에 확인한다.
- 서버를 지우면 볼트도 함께 사라진다. 정기 백업(키트에서 주간 등록)을 별도로 쓰는 것을 권한다.
