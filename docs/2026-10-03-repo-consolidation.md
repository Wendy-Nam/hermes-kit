# 저장소 통합 — 판단 근거 (2026-10-03)

`omh-omniroute-setup`과 `hermes-vps-setup`을 `hermes-kit`에 편입했다. 이 문서는
그 판단의 근거와 남긴 위험을 기록한다. 결론부터 말하면 **둘 중 무엇도 별도 저장소로
유지할 이유가 없었다.**

## 1. 세 저장소는 평급이 아니었다

역할이 세 층으로 나뉘어 있었다. 평평하게 합칠 필요는 없었다.

| 저장소 | 역할 | 규모 |
|---|---|---|
| `hermes-kit` | **발행 본체.** Docker 이미지, Compose, Discord `/setup`, 패치, 시드, CI | 281 파일 |
| `hermes-vps-setup` | **PC 클라이언트.** Syncthing·Obsidian 페어링. 서버 미변경 | 13 파일 |
| `omh-omniroute-setup` | **기존 호스트용 독립 설치기.** OMH+OmniRoute 배선 | 17 파일 |

`hermes-kit`만이 이미지 빌드·게시 파이프라인을 갖고 있었다. 다른 둘은 그것을 빌려 쓰고
있었다. 마스터는 정해져 있었다.

## 2. 중복 측정 결과

두 저장소를 파일 단위로 비교했다. 겹친 것과 겹치지 않은 것을 구분해야 편입 범위가 나온다.

**완전 동일**
- `advanced/omniroute-rtk-envelope/envelope.cjs` = `omh-omniroute-setup/omniroute-patches/envelope.cjs`
  (바이트 단위 동일). 두 벌로 두고 있었다.

**충돌 — 그대로 합치면 빌드가 깨진다**
- `patch.cjs`: omh 쪽은 `function A` / `e.Xz` (업스트림 3.8.51 기준), kit 쪽은
  `function B` / `e.estimateCompressionTokens`. 앵커 문자열이 다르다.
  omh 저장소의 README도 "이 앵커는 지금 이미 어긋났고, 훅은 손으로 다른 청크에 다시
  적용했다"고 적고 있다. **kit 쪽이 신버전이며 검증되어 있다.** omh 쪽은 폐기했다.

**기능 중복 — kit이 이미 더 나은 것을 갖고 있음**
- OmniRoute 기동: `plugins/kit-setup/omniroute_setup.py`가 omh 스크립트의 1단계를
  완전히 대체한다(대시보드 비밀번호 검증, 실제 응답 확인, 두 턴 시험까지).
  omh 스크립트의 1단계는 불필요하다.
- RTK 설치: kit은 `Dockerfile`에서 체크섬 검증으로 바이너리를 넣고 `rtk init --agent hermes`로
  플러그인을 연다. omh 스크립트의 5단계(RTK 수동 설치 + wheel URL 해석 + 두 가지 안전 수정)는
  **키트 이미지 밖의 호스트**를 위한 것이므로 편입 대상이 아니다.

## 3. 실제로 편입한 것 — kit에 없던 것

측정 결과 kit에 없던 항목만 가져왔다. 이미 있던 것을 복사하지 않았다.

1. **쿼터 인식 라우팅 폴백** (`patches/omh-routing/`) — 가장 큰 이득.
   구독 계정은 사용 한도가 소진돼도 `isActive: true`로 남는다. OmniRoute는 이런 계정을
   사전 필터에서 빼고 429로 응답한다. 기존 판정은 이를 살아 있는 경로로 봤으므로,
   **체인 1순위에 턴을 쓰고 그 자리에서 실패하며 다음 후보로 넘어가지 않았다.**
   `route_readiness.py`의 `_quota_exhausted()`가 계정 풀을 읽어, 요청을 쓰기 **전에**
   다음 후보로 넘어가게 한다. 100%로 확정된 판정만 소진으로 보며, 없거나 null·형식이
   깨진 값은 `unknown`으로 남는다 — 없는 증거를 "사용 불가"로 읽으면 안 된다.
2. **모델 정체성 → 실제 제공자 매핑** (`omh_provider_mapper.py`).
   OMH는 모델 *정체성*(`kimi-k3`)을 추천하고 OmniRoute는 주소로 받는다. 그 사이가 이 파일이다.
   다른 모델로 몰래 바꾸지 않는다 — 버전이 다르면 낮은 등급으로 보고한다.
3. **`providers.json` entitlement 문서.** 없는 제공자는 판단할 수 없고, 제외된 제공자는
   살아 있어도 밀린다.
4. **CommandCode Anthropic shim.** 게이트웨이는 OpenAI 형식을 말하는데 이 제공자는
   Anthropic Messages를 말한다. 없으면 **연결이 정상으로 보이면서 요청 하나도 처리하지 못한다.**
5. **대시보드 키 경고 패치.** 꺼 둔 연결까지 경고를 띄워 경고를 무시하게 만드는 문제.
6. **PC 동기화 클라이언트** (`clients/pc-sync/`).
7. **RTK wheel 안전 수정 2건** — 키트 이미지 밖 호스트 전용이라 편입하지 않았고,
   그 이유를 위 2번 항목에 기록했다.

## 4. 통합 방식의 판단

**선택한 방식: `hermes-kit` 마스터 흡수.** 새 저장소를 만들지 않았다.

새 저장소를 만들면 kit의 281개 파일을 그대로 복제하게 된다. 복제본은 이후 실제 배포본과
어긋나고, 이미지 태그와 CI를 둘로 관리하게 된다. 그 비용 없이 이득(단일 배포 단위)만
얻는다.

`hermes-vps-setup`의 서버 측 짝(장치 페어링)은 kit에 이미 있으므로, PC 스크립트는 그
반대편만 채운다. 중복이 아니라 **완성**이었다.

## 5. 게시 이미지를 건드리지 않은 이유

CommandCode shim과 UI 패치는 kit의 게시 이미지 파이프라인(`omniroute-rtk-json-3`)에
직접 넣지 않고 [advanced/omniroute-patches](../advanced/omniroute-patches)의 오버레이로
넣었다.

이유는 검증 상태다. RTK envelope 어댑터는 이 저장소의 CI가 세 가지 API 형식과 실제 RTK
런타임까지 검증한다. 반면 CommandCode shim은 kit의 검증 대상이 아니었고, UI 패치는
번들 문자열 앵커에 의존한다. **검증되지 않은 패치를 모든 학생의 기본 이미지에 넣으면,
고장 났을 때 되돌릴 경로가 없다.** 오버레이로 두면opting in 하는 학생만 영향을 받고,
되돌리기는 `KIT_OMNIROUTE_IMAGE` 한 줄이다.

## 6. 검증 결과와 남은 한계

Docker 데몬을 켜고 실제로 빌드해 확인했다. 통과한 항목이다.

- **이미지 빌드 성공.** `versions.env` 그대로. 패치 앵커가 어긋나면 빌드가 실패하는
  설계 덕분에 업스트림 드리프트가 없다는 것도 함께 확인됐다.
- **이미지 안에서 테스트 262개 통과** (`/opt/kit/plugins/kit-setup/tests`), 로컬 21개 통과.
- **실제 이미지 안에서 패치 적용 확인.** OMH 원본 3개와 routing 디렉터리 없는 상태로
  시작해 `pending` -> `apply` -> `ok`, 세 파일 모두 배포본과 바이트 일치, 재실행 시 변경 0.
  이게 통합의 핵심 동작이고, 이미지 안에서 성립함을 확인했다.
- **오버레이 빌드 성공.** `patch-ui.cjs`의 앵커가 실제 게시 이미지 대시보드 청크에
  매칭되어 패치가 적용됐고, CommandCode shim 파일도 정상 배치됐다.
- **PC 동기화 e2e 통과.** 실제 Syncthing 1.27.10 두 인스턴스로 파일 왕복·내용 일치·
  삭제 전파까지 확인(FINAL_EXIT=0).

빌드 중 발견해 고친 실제 결함 하나:

- `LABEL io.hermes.patches+=` -- Docker에 `+=` 연산자가 없다. 키 이름이 `io.hermes.patches+`
  인 라벨이 생기고 `io.hermes.patches` 조회 결과는 항상 비었다. 전체 값을 한 줄로 선언하도록
  고쳤다. UI 패치는 적용됐는데도 "패치 없음"으로 보이는, 조용히 잘못되는 종류였다.

실제 게이트웨이 앞에서의 확인 (로컬에 어댑터+오버레이 이미지를 띄우고 k17 이미지와 같은
네트워크로 연결해 실측):

- `route_readiness.readiness_snapshot()`이 살아있는 게이트웨이에서 `unknown` +
  `management_credentials_unavailable`을 반환합니다. 연결이 없으면 추측하지 않고
  판단을 보류하는 쪽입니다.
- `_quota_exhausted()` 경계값을 실제 패치 파일로 확인했습니다. `children[].quota.
  windows[].usedPercentage`가 100 / 100.0 이거나, 형제 중 하나가 100이거나,
  `aggregate.status`가 가용 상태가 아니면 True. 99.9%, 0%, 값 없음, 문자열로 깨진
  값, `unavailable` 자식, pool 자체가 없는 경우는 전부 False — 없는 증거를
  "사용 불가"로 읽지 않는다는 설계가 그대로 성립합니다.
- CommandCode shim이 실제 게이트웨이 이미지에서 로드되고, `claude-*` 요청을 Anthropic
  Messages 형식(`messages` + `max_tokens`)으로 변환함을 확인했습니다.

이 과정에서 실제 결함 하나를 찾아 고쳤습니다:

- **`verify.py`가 OMH 미설치 상태에서 `degraded`를 보고했습니다.** 모듈 최상위에서
  `omh.hermes_delegation`을 import하는데 OMH가 없으면 예외가 나고 종료 코드가 1이
  됩니다. 그런데 호출부는 1을 "1순위 경로에 살아있는 연결이 없다"로 읽고, **OMH가
  안 설치된 것**을 "providers.json을 고치라"로 안내했습니다. 원인이 완전히 다른
  두 상태가 같은 코드로 나갔던 것입니다. OMH 없음은 종료 코드 2("게이트웨이를 읽을 수
  없음")로 분리했습니다. 회귀 테스트를 붙였습니다.

남는 한계:

- **CommandCode shim의 실계정 API 왕복은 확인하지 못했다.** 모듈 로드와 요청 변환까지만
  실측했습니다. 실제 `claude-*` 요청이 오가는 것은 실계정이 필요하며, 그 제공자를 쓰는
  학생이 처음 켤 때 한 번 확인해야 합니다.
- **`chunk-88137.js`는 편입하지 않았다.** 압축 콤보 헤더 지정 패치인데, 3.8.51 빌드의
  **청크 파일 전체 교체**라 업스트림이 조금만 바뀌면 다른 바이트가 들어간다. 앵커 기반이
  아니라 검증할 방법이 없어, 두 벌 다 되는 상황은 "안 넣는 것"이 맞다고 판단했다.
- **역할 프로필·cron 등 나머지 kit 경로는 통합으로 건드리지 않았다.** 회귀 286개가
  그대로 통과한 것이 그 확인이다.

## 7. 학생 관점에서 달라진 것

**이전**: 저장소 3개를 찾아 각각 설치. OmniRoute를 쓸지는 별도 설치기가 정해 줬다.

**현재**: 저장소 1개. `/setup`을 마치면 OMH 라우팅 폴백이 자동으로 켜져 있고, PC 동기화는
`clients/pc-sync`를 한 폴더 복사하면 된다. 이미 돌고 있는 호스트에는 이미지 재배포 없이

```sh
docker exec <hermes-컨테이너> python3 /opt/data/plugins/kit-setup/bootstrap.py omh-routing apply
```

한 줄이면 같은 상태가 된다.