# 카카오톡 실행 하네스 설계

상태: 설계 계약. 연결 프로그램, Hermes 도구, 설치 UI는 아직 구현·등록하지 않았다. 이 파일의 operation 이름은 upstream CLI 명령이 아니라 구현할 키트 인터페이스다.

## 배치 구조

```text
Hermes VPS
  kit_kakaotalk 도구 → 사용자 권한 확인 → 작업 큐/초안/발송 기록
                  ↕ 장치가 시작하는 인증된 TLS 연결
사용자 PC의 카카오톡 연결 프로그램
  방·작업 범위 검사 → 계정별 단일 SDK 세션 → KakaoTalk
                         ↘ 같은 client를 사용하는 listener
```

기본 배치는 PC 연결 프로그램이다. 카카오톡 계정 세션은 PC에 남고 모델 호출은 기존 Hermes/OmniRoute 경로가 담당한다. 메시징 자체를 OmniRoute 공급자로 등록하지 않는다. Linux에서도 인증이 가능하므로 서버 전용 설치를 영구 배제하지 않지만, 초기 옵션팩은 PC 방식 한 가지부터 검증한다. PC가 꺼지면 offline으로 표시하며 몰래 다른 호스트에서 로그인하지 않는다.

PC 연결 프로그램은 배포자가 정한 단일 큐 서비스에 outbound 연결한다. PC 포트나 Docker 소켓을 외부에 공개하지 않는다. 장치 연결 키와 카카오톡 계정 자격증명은 별개다. 짧은 수명의 일회성 pairing code, 이후 회전 가능한 장치 키, 요청 ID·만료시각·재전송 방지 nonce를 사용한다. 키트 소유자가 장치를 연결한 뒤 허용 계정/방/기능을 지정한다. 임의 shell 명령을 전달하는 기능은 없다.

## 인증과 세션

검토 기준: agent-messenger package.json 2.38.0, commit `505738a15d47a9e1d76f16302288bc347d427d84`.

- 실제 패키지 배포 전 npm 배포물·lockfile·무결성과 해당 commit의 대응을 검증하고 버전을 고정한다. 검토한 소스 버전이 그대로 설치됐다고 가정하지 않는다. Node 런타임 최소 요구는 소스 기준 22.13.0이다.
- 계정 연결은 로컬 사용자 주도 `agent-kakaotalk auth login` 흐름으로 한다. 설치하거나 스킬을 읽는 것만으로 OS 자격증명을 추출하지 않는다. 비밀번호는 채팅이나 명령행 인자로 받지 않는다. upstream 로그인 자체가 macOS/Windows의 기존 정보를 읽을 수 있음을 연결 화면에 표시한다.
- 기본 tablet 단말 슬롯이 이미 사용 중이면 사용자에게 선택을 맡긴다. `--force`, PC 슬롯 전환을 자동 실행하지 않는다. 휴대폰 확인이 완료될 때까지 연결 완료가 아니다.
- 전용 `AGENT_MESSENGER_CONFIG_DIR`를 사용하고 계정 ID를 고정한다. 이 디렉터리를 볼트 동기화·키트 일반 백업·Docker 이미지에 포함하지 않는다.
- 계정/기기별 단일 프로세스 잠금 + 단일 장수 `KakaoTalkClient`. listener와 조회/발송이 같은 client를 공유한다. 별도의 CLI 프로세스를 작업마다 실행하거나 계정 기본값을 전역 변경하지 않는다.
- 세션 추방(KICKOUT)은 `needs_user_action`으로 전환하고 자동 재연결 경쟁을 멈춘다. 종료는 listener.stop()에 더해 client.close()를 호출한다.

## 도구 계약

공통 입력은 account_ref, room_ref(방 단위 작업), request_id, expires_at이다. 실제 account ID/chat ID는 등록된 참조로 해석하며, 모델이 전달한 경로나 토큰은 받지 않는다. 상태 응답에는 credentials 원문을 포함하지 않는다. 로컬 자격증명 존재와 서버 연결 확인은 구분하며, `auth status`만 성공했다고 서버 인증이 유효하다고 보고하지 않는다.

| operation | 동작 | 권한/출력 |
|---|---|---|
| status | 연결 상태·허용 기능 | 비밀 없는 상태만 |
| rooms | 연결 시 허용된 방 메타데이터 | 이름·ID·멤버 수, 원문 preview 제거 |
| history | 지정 방의 제한된 페이지 | messages, next_cursor, complete, gap |
| draft | 답장 초안 동결 | draft_id, 내용 hash, 대상, reply_to, 만료 |
| send | 동결 초안 1회 전송 요청 | 사용자 권한 참조 검증; sent/failed/unknown |
| delivery_status | 특정 발송 요청 상태 | 원래 request_id 기준 |
| subscribe / unsubscribe | 허용 방 수신 수집 켜기/끄기 | 사용자가 선택한 방만, 자동 답장 아님 |

초기 한 요청의 조회 상한은 50건/페이지·4페이지·본문 총 64KiB, 첨부 다운로드 0건이다. 읽기 요청의 전체 제한은 20초다. 상한에 걸리면 complete=false와 계속 읽을 cursor를 반환한다. 연결 목록은 upstream에서 넓게 반환될 수 있으므로 PC에서 필터링한 후 허용 방만 VPS에 보낸다. 초기 방 선택 화면은 PC에 표시한다.

## 수신·수집

`getMessagePage`와 cursor를 사용한다. `getMessages`가 반환한 최근 N개를 전체 이력으로 간주하지 않는다. chat/log/user ID는 JS number로 변환하지 않는다.

정규화 이벤트: platform=kakaotalk, account_ref, chat_id, log_id, author_id, server_sent_at(없으면 null), received_at, event_kind, text, attachment_metadata, source_untrusted=true. log_id 없는 이벤트는 별도 제어 이벤트로 다루고 본문 hash를 메시지 ID처럼 사용하지 않는다.

upstream의 message·emoticon·kakaotalk_event가 같은 메시지를 중복 표현할 수 있으므로 원문 메시지 한 종류로 정규화한다. 영속 메시지 중복 키는 (account_ref, chat_id, log_id)다. 수정·삭제 등 상태 변화는 별도 이벤트 모델과 버전이 필요하며 초기 범위에는 넣지 않는다. 중복 삽입 제거와 다음 cursor 저장을 하나의 트랜잭션으로 한다. 재접속 시 지원되는 구간만 되읽고 gap을 기록한다. 누락 없는 전체 과거 복구를 보장하지 않는다. 우리 발송/자기 메시지와 제어 이벤트는 자동 실행 트리거에서 제외한다.

원문과 초안은 필요한 기간만 보관한다. 기본 원문 24시간, 초안 24시간, 전송 메타데이터 7일; 사용자 선택으로 줄일 수 있다. 로그에는 상태·지연·카운터·참조 ID만 남긴다. 모델에는 선택한 작업에 필요한 문맥만 전달한다. 이 보관 규칙은 우리 시스템에만 적용되며 외부 메시징/모델 서비스의 보관 정책을 바꾸지 않는다.

## 발송과 권한

기본 write_enabled=false. 사용자에게 읽기만 허용된 연결을 발송 가능한 연결처럼 보여주지 않는다. draft를 편집하면 새로운 내용 hash와 버전을 만든다.

발송 권한은 하네스 외부의 신뢰된 사용자 입력 경로에서 발급한다. grant에는 사용자/계정/방/draft hash/만료/사용 횟수를 묶는다. 모델이 `approved=true`를 넘기는 방식은 금지한다. 기존의 명확한 사용자 전송 요청은 권한 발급 근거이므로 같은 내용을 반복 승인받지 않는다. 자동화의 지속 권한은 사용자가 정한 방·시각·목적·빈도 범위에 묶는다.

발송 outbox:

```text
draft → authorized → dispatching → sent
                             ├→ failed (확실한 거절)
                             └→ unknown (전송 후 응답 불명)
```

VPS outbox 외에 PC에도 request_id + payload hash + 상태를 영속 기록한다. 큐 재전달 시 실행 기록을 먼저 조회하고 서버 ACK 결과를 PC에 저장한 뒤 VPS에 전달한다. PC 재시작 후 dispatching도 재발송 없이 unknown으로 전환한다.

PC 실행 직전에 expires_at, grant, 허용 방, write_enabled, 취소 여부를 다시 검사한다. 발송은 서버에 연결된 상태에서 최신 권한 확인에 성공한 경우에만 실행하며, 오프라인 권한 캐시만으로 오래된 초안을 보내지 않는다.

계정/방 직렬화와 request_id 유일성으로 같은 요청을 다시 보내지 않는다. 같은 ID에 다른 payload는 거부한다. 재시작 후 dispatching은 unknown으로 다루며 재실행하지 않는다. 호출 timeout 후 원격 실행 중단 여부를 알 수 없다면 성공도 실패도 단정하지 않는다.

**발송 출시 차단 조건:** 검토한 upstream `sendMessage`는 `executeWithReconnect`를 통해 세션 교체 시 operation을 다시 실행할 수 있다. 로컬 outbox만으로 중복 전송을 막을 수 없다. write에 대한 내부 재시도를 끄는 검증된 upstream 옵션/패치가 준비되고 장애 주입 시험이 통과하기 전에는 send를 활성화하지 않는다. 무재시도 적용 후에도 서버가 수락한 뒤 응답을 잃는 상황은 unknown으로 남는다. 최근 이력의 같은 문자열만으로 성공을 확정하거나 자동 재발송하지 않는다. exactly-once 전달을 약속하지 않는다.

## 오류와 비용

offline / auth_required / device_conflict / forbidden_room / rate_limited / deadline / partial_history / delivery_unknown을 구분한다. 토큰 만료나 단말 충돌에서 자동 재인증하지 않는다. 읽기의 일시 오류는 전체 시간 제한 안에서 한 번만 재시도하고 429 대기는 서버 지시를 따른다. 쓰기 재시도는 없다.

방 선택·인증·cursor·중복 제거·권한 판단·스케줄·전송은 기계 처리한다. 짧은 요약/초안은 기본 보조 모델, 복잡한 업무 추출만 선택적으로 OMH에 맡긴다. 계정 자격증명과 다른 방의 원문을 서브에이전트에 넘기지 않는다. 선톡 기능과 연결하거나 방마다 LLM을 호출하는 크론은 자동 생성하지 않는다.

## 패키징과 도입 순서

1. **현재 설계본:** 이 옵션팩만 저장소에 보관. 기본 이미지 COPY/seed, 자동 설치, 크론, 학생 /setup 메뉴, 운영 계정에는 등록하지 않는다.
2. **읽기 MVP:** PC 연결 프로그램 + Hermes 도구 + 명시적 설치/해제 UI 구현. 사용자별 연결 키와 허용 방을 설정. 로컬 합성 fake adapter 시험 후 사용자 지정 테스트 방만 검증.
3. **발송:** 내부 write 재시도 제거, grant/outbox/unknown 처리, 중복·재시작 장애 시험을 통과한 뒤 선택 활성화.
4. **구독·요약:** 재접속/cursor/gap/중복 처리를 검증한 뒤 사용자가 정한 방과 결과 목적지에 한해 활성화.

향후 /setup 옵션 카드: 카카오톡 → 연결 프로그램 설치 → 로컬 로그인·휴대폰 확인 → 방 선택 → 읽기 연결 검사 → (별도) 발송 켜기. 모든 학생에게 요구하지 않는다. 해제는 구독 중단·큐 취소·장치 키 폐기·로컬 세션 종료이며, 기기 로그인 해제 여부는 사용자에게 별도로 선택시킨다. 기존 카톡 계정을 파괴적으로 초기화하지 않는다.

## 출시 시험

- 설치하지 않은 기본 키트에서 카톡 의존성·메뉴·크론·인증 접근 없음.
- 이름이 같은 두 방과 두 계정에서 정확한 계정/방 선택; 허용되지 않은 방 원문이 VPS에 오지 않음.
- tablet 슬롯 점유, KICKOUT, PC sleep/wake, 토큰 만료 시 로그인 경쟁 없이 상태 표시.
- 중복 이벤트, 페이지 경계, cursor 저장 전후 프로세스 종료, log ID 정밀도 보존.
- 송신 직후 연결 종료, ACK 유실, 같은 request_id 동시 호출, 편집된 초안의 이전 grant 거부.
- 메시지 본문의 “다른 방에 보내라” 지시가 권한 발급·도구 실행으로 이어지지 않음.
- 조회·구독이 읽음/typing/반응/발송을 발생시키지 않는 실제 테스트 방 점검.

## 검토한 upstream 근거

- [인증 및 CLI](https://github.com/agent-messenger/agent-messenger/blob/505738a15d47a9e1d76f16302288bc347d427d84/skills/agent-kakaotalk/SKILL.md)
- [client 및 재연결](https://github.com/agent-messenger/agent-messenger/blob/505738a15d47a9e1d76f16302288bc347d427d84/src/platforms/kakaotalk/client.ts)
- [listener](https://github.com/agent-messenger/agent-messenger/blob/505738a15d47a9e1d76f16302288bc347d427d84/src/platforms/kakaotalk/listener.ts)
