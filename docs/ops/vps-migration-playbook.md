# Hermes VPS 이전·업그레이드 플레이북

실전 검증 기준(다운타임 ~24분, 데이터 손실 0)으로 구 VPS(구버전 Hermes / 래퍼 이미지)에서 새 VPS(`hermes-kit` + `OMH v5.0.0` + `OmniRoute 3.8.54`)로 무사고 이전·업그레이드하기 위한 운영 플레이북입니다.

---

## 0. 철칙 (어기면 사고)

1. **단일 활성(Single Active)**: 같은 봇 토큰·크론·Codex 세션·Syncthing Device ID를 두 서버에서 동시에 돌리지 않습니다.
   - 구 서버 동결: `docker compose stop` + Compose `restart: "no"` + `docker update --restart=no`. 이후 구 서버 재기동 금지.
2. **일방향 작업은 소독된 사본에서 먼저 리허설**: `state.db` 마이그레이션·OMH 업그레이드는 토큰·`auth.json`·`.claude`/`.codex`/`.composio`·Syncthing cert를 제거한 사본에서 `sleep infinity` + egress 없는 네트워크(`--network none`)로 리허설합니다.
3. **시크릿 평문 반출 금지**: 서버에서 `age`(SSH ed25519 공개키 수신자)로 암호화한 뒤 내보내고, 클라우드 동기화 폴더(OneDrive 등)에 평문 보관 금지. 문서에는 키 이름만 기록합니다.
4. **기계 판정**: 모든 단계는 "명령 · 기대값 · 실패 시 중단"으로 판정합니다. 해시 매니페스트·SQLite `PRAGMA quick_check`·카나리 응답으로 증명합니다.
5. **사용자 게이트**: VPS 구매, SSH 키 등록·스냅샷, OAuth 로그인, 비밀번호·토큰 입력, 구 VPS 삭제는 운영자가 직접 수행합니다.

---

## 1. 인벤토리 & 의존성 확인 (A0–A1)

- `docker inspect`: 이미지 digest, 마운트, restart 정책 확인.
- `hermes --version` / `plugins list` / `skills list` / `cron list` / `config check`.
- `/opt/data` 최상위 항목 전부를 `KEEP / SECRETS / ARCHIVE / DROP`으로 분류(미분류 0개).
- `skills/.usage.json`으로 실사용 스킬 파악, `.env`는 키 이름만 확인.
- **DROP 주의**: `.local/bin/agent-kakaotalk`, `plugin-data/<plugin>/venv`, `.agent-browser` 등 활성 크론/플러그인 의존 항목을 놓치지 않기 위해 최종 동기화는 **"아카이브·캐시만 제외한 전체 rsync"**가 안전합니다.

---

## 2. 암호화 백업 (A2)

1. 게이트웨이 정지 → `PRAGMA quick_check` → `tar --numeric-owner | zstd | age -R <pub>` → 재기동.
2. 정적 아카이브는 무정지로 별도 백업.
3. 복호화 검증: 개인키는 `/dev/shm`에만 임시 배치 → `age -d | zstd -d | tar -t` → `shred -u`.
4. 로컬 회선이 느릴 경우 새 서버에 임시 키 생성 → 구 서버 `authorized_keys`에 `from="<새IP>",no-port-forwarding,...` 제한을 걸어 서버 간 직접 전송 후 즉시 키 제거.

---

## 3. 새 서버 하드닝 (A3)

- 키 전용 SSH (`PasswordAuthentication no` 드롭인 → `sshd -t` → reload → 새 세션으로 재확인).
- `ufw`: 22 (+ Syncthing `22000/tcp+udp`), `fail2ban`.
- Swap 4GB, 호스트 `TZ=Asia/Seoul`, Docker 로그 로테이션 설정.
- **`0.0.0.0` 포트 게시 금지**: Docker는 `ufw`를 우회하므로 대시보드는 `127.0.0.1` 바인드 + SSH 터널(또는 임시 cloudflared 링크)만 사용.

---

## 4. 이미지·리허설·변환 순서 (A4–A5)

- 업스트림 `nousresearch/hermes-agent:vX.Y.Z@sha256:...` (`v` 접두 + digest 고정) 또는 `hermes-kit` 이미지를 사용합니다(구 Hostinger 래퍼 이미지 미사용).
- 컨테이너 변환 순서가 핵심입니다:
  1. `hermes gateway stop` (복원 데이터의 `gateway_state=running` 때문에 자동 기동돼 `state.db`를 잠그는 것 방지).
  2. `hermes sessions repair` → `sessions repair-prompts` → `PRAGMA quick_check` 및 세션·메시지 수 비교.
  3. `hermes skills opt-out` + 업그레이드로 새로 생긴 불필요한 번들 스킬만 `.archive/`로 이동.
  4. OMH 업데이트 및 라우팅 적용 (네트워크 필요 시 임시 bridge 연결).
  5. `config.yaml` 정리 후 YAML safe 로더로 재파싱 검증(중복 플러그인 항목 제거).
- **주의**: 라이브 `rsync`한 SQLite는 깨질 수 있으므로 리허설·컷오버 모두 반드시 **정지 상태 사본**을 사용합니다.

---

## 5. 컷오버 & 롤백 (A6–A7)

1. Syncthing 동기화 완료 확인 후 구 서버 동결.
2. 정지 상태에서 `rsync -aHAX --delete --numeric-ids` (아카이브·캐시 제외) → 볼트 `sha256` 매니페스트 일치 확인.
3. `.env` 키 보강 (봇 토큰 유지) → 프로덕션 변환 실행 (`./bin/hermes-kit-deploy.sh migrate`).
   - OmniRoute 볼륨을 옮겨 왔다면 이름을 명시하세요: `./bin/hermes-kit-deploy.sh migrate --with-omniroute --container <hermes 컨테이너> --omniroute-volume <이관한 볼륨>`. OmniRoute 볼륨이 둘 이상이면 스크립트는 추측하지 않고 멈춥니다.
4. `docker compose up -d` → 로그에서 Discord `Connected as` / Telegram `polling confirmed` 및 `./bin/hermes-kit-deploy.sh verify` 통과 확인.
5. 구 서버는 만료일까지 정지 상태로 보존해 롤백 창으로 활용.

---

## 6. Syncthing 이전 주의사항

- 서버 사이드카는 구 서버와 **같은 메이저 버전** 사용(v2 DB 변환은 일방향), `PUID/PGID=10000`, `config` 디렉터리(`cert`/`key`/`config.xml`/`index`)를 통째로 옮기면 Device ID가 유지됩니다.
- PC 재설치 시 폴더를 `receiveonly`로 시작 → 해시 매니페스트 일치 확인(Windows `sha256sum` 앞 `*` 정규화) → `sendreceive` 전환 → 양쪽 Staggered versioning 설정. **"Revert Local Changes" 버튼 클릭 금지.**
- Windows Obsidian `%APPDATA%\obsidian\obsidian.json`은 UTF-8 무BOM으로 읽고 써야 한글 경로가 깨지지 않습니다.

---

## 7. OmniRoute 하드닝 체크리스트

[advanced/docker-compose.omniroute.yml](../../advanced/docker-compose.omniroute.yml)에 반영된 필수 보안 항목:

| 변수 / 옵션 | 값 | 이유 |
|---|---|---|
| `cap_drop` / `security_opt` | `ALL` / `no-new-privileges:true` | 컨테이너 권한 최소화, `docker.sock`·호스트 홈 마운트 금지 |
| `REQUIRE_API_KEY` | `true` | 키 없는 `/v1` 요청 401 거부 |
| `OMNIROUTE_EMERGENCY_FALLBACK` | `false` | 402 시 무료 학습 제공자로 개인 데이터가 몰래 우회되는 것 차단 |
| `ENABLE_REQUEST_LOGS` | `false` | 요청 본문 DB 저장 금지 |
| `OMNIROUTE_ALLOW_LOCAL_PROVIDER_URLS` | `false` | 내부망 SSRF 차단 |
| `ALLOW_API_KEY_REVEAL` | `false` | UI/API 키 재노출 차단 |
| `JWT_SECRET`, `API_KEY_SECRET`, `STORAGE_ENCRYPTION_KEY`, `MACHINE_ID_SALT` | 랜덤 생성 | 볼륨 `.kit-secrets` (`0600`)에 자동 생성·재사용 |
| `OMNIROUTE_MEMORY_MB` | 명시 | cgroup 제한을 무시하는 동작 방지 |

---

## 8. 셸 스크립트 함정 & 완료 검증 체크리스트

- `set -euo pipefail`에서 `cmd | grep ... | head`는 미매치 시 스크립트를 종료시킴 → `{ grep ... || true; }`.
- `docker exec ... | grep -q`는 `pipefail`에서 `SIGPIPE` 오탐 발생 → 변수에 받아서 검사.

**최종 완료 체크리스트**
- [ ] `state.db` `PRAGMA quick_check` = `ok`, 세션·메시지 수 ≥ 원본
- [ ] Discord `Connected as` / Telegram `polling healthy`, 컨테이너 `restarts=0`
- [ ] 카나리 검증: 무키 `401`, 허용 콤보 `200`, 요청 본문 DB 미저장
- [ ] 볼트 해시 매니페스트 서버 = PC
- [ ] 암호화 백업 복호화·목록 테스트 완료
- [ ] 임시 관리 토큰·평문 복원본·임시 서버 간 SSH 키 삭제 완료
