# OMH 설치 계약

이 키트는 `rlaope/oh-my-hermes` **2.0.5**를 실제로 설치한다. upstream의
`curl | sh` 또는 `irm | iex`를 실행하지 않는다. `omh_setup.py`가 아래 공개
아티팩트 하나만 받아 전체 SHA-256과 압축 경로를 검사한 뒤 전용 Hermes 홈에
격리 설치한다.

- source commit: `b84f096e59d50fc933ed4b43fd36675e8cff593a`
- archive SHA-256: `3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a`
- audited plugin hook SHA-256: `a0382ed1cf9f78f0cf9202395c027cd29a01953a3b7983d2142747d764b60e3b`
- license: MIT (upstream package metadata and `LICENSE`)

## 사용

Mac/Linux/Windows 모두 Python 3.11 이상에서 같은 명령을 쓴다. Windows의
venv 실행 파일은 자동으로 `Scripts/python.exe`, Mac/Linux는 `bin/python`을
사용하며 심볼릭 링크를 만들지 않는다.

```bash
python omh_setup.py plan --config setup.json --home ~/.hermes-outbound
python omh_setup.py install --config setup.json --home ~/.hermes-outbound
python omh_setup.py check --config setup.json --home ~/.hermes-outbound
```

`install`은 고정 `pyproject.toml`의 package map, 이름, 버전, 빈 runtime
dependency 목록, MIT 라이선스를 검사한다. 그 뒤 전용 venv에 pure-Python package와
package data, metadata, upstream `LICENSE`를 직접 배치한다. 따라서 setuptools/wheel을
네트워크에서 받거나 host에 미리 설치해 둘 필요가 없다. 이어 다음 upstream CLI
계약을 호출한다.

```text
omh --hermes-home <home> --omh-home <home>/.omh setup --core --yes
    --no-interactive --no-omh-tui --no-menubar --memory-mode off
    --default-executor hermes --json
```

플러그인의 import와 register smoke가 모두 참이어야 영수증
`<home>/.kit-components.json`이 기록된다. 기존 `.omh`, `.omh-runtime/2.0.5`,
`plugins/omh`가 있으나 이 고정 영수증이 없으면 소유권을 추측하지 않고 중단한다.
setup 실패 시 기존 `config.yaml` 바이트를 복구하고 이번 실행이 만든 OMH 대상만
제거한다. upstream core setup이 쓰는 `skins/omh*.yaml`, skin manifest,
`tui-widgets/omh-status.mjs`, widget manifest도 설치 전에 소유권을 확인한다. 해당
경로에 알 수 없는 기존 파일이 있으면 덮어쓰지 않고 중단하며, setup 또는 영수증
이후 단계가 실패하면 이번 실행이 만든 파일만 제거하고 기존 config와 component
receipt를 원래 바이트로 복구한다. 같은 디렉터리의 사용자 소유 파일은 유지한다.

아카이브 안의 `pyproject.toml`과 설치 후 `importlib.metadata` 모두 distribution
버전을 `2.0.5`로 확인해야 한다. 같은 고정 아카이브를 `1.0.3`으로 표시하지 않는다.

## 상태를 한 덩어리로 표현하지 않는 이유

`check`는 다음을 별도로 보고한다.

1. 고정 패키지와 영수증 설치
2. upstream doctor 및 플러그인 import/register 정적 smoke
3. 실제 Hermes 프로세스의 플러그인 로드
4. `omh_delegate_route` 도구 노출과 route 적용
5. Hermes 재시작
6. 실제 위임 작업 성공

Hermes 실행 파일이 없으면 3~6은 `pending`이다. 실행 파일이 있어도 버전 출력만
확인할 뿐 플러그인 로드나 실작업 성공으로 승격하지 않는다. 공개 donor에서 확인된
baseline은 Hermes `0.21.2-k18`뿐이다. upstream manifest의 선언 범위
`>=0.21.1,<0.22.0`와 실제 검증은 다른 주장이다. Hermes 0.21.7은 격리 환경에서
setup, plugin load, tool exposure, route write/restore, live delegated task를 모두
통과하기 전에는 검증됨으로 표시하지 않는다.

## 라우팅과 OmniRoute 경계

OMH 설치가 먼저고 OmniRoute는 선택 사항이다. 라우팅 문서는 OMH 2.0.5 계약인
`mixture_chain_overrides/v1`과 `model_provider_routes/v1`만 허용한다. 카테고리는
12개 폐쇄 집합이다. provider route가 Hermes 설정에 연결될 때에는 이름 있는
provider의 `api`, `key_env`, `transport=openai_chat`이 필요하며, delegation에는
provider와 model을 기록하고 오래된 `base_url`/`api_key`를 남기지 않아야 한다.
Hermes 0.21.x에는 `delegate_task(routing=...)` 계약이 없으므로 그 인자를 가정하지
않는다. OMH의 `omh_delegate_route` 쓰기/복구 증거가 있어야 route-applied로 본다.

OmniRoute의 별도 수용 차단 조건은 `omniroute_setup.py` 문서를 따른다. 특히 Docker
engine OS/arch/memory, amd64 digest/platform, loopback dashboard, 포트 소유권,
compose config, pull 후 digest/architecture, 시작 컨테이너의 project/service/image
소유권, Windows secret directory의 user-only DACL까지 검증돼야 한다. 임의의
`/healthz` 응답만으로 완료 처리하면 안 된다.

## 공급망 및 제한

- archive는 64 MiB, 항목 12,000개, 압축 해제 160 MiB로 제한한다.
- 절대경로, `..`, symlink, hardlink, device 항목을 거부한다.
- upstream 2.0.5는 Python runtime dependency가 없다. 선언된 build backend
  `setuptools>=77`은 일반 wheel 빌드 경로에만 필요하다. 이 설치기는 검증된 source
  package map을 그대로 배치하므로 build dependency를 다운로드하지 않는다.
- private wrapper `1.0.3`은 별도 제품이며 이 설치 대상 또는 호환성 근거가 아니다.
