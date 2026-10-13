# 비공개 owner-only Telegram 테스트봇

이 helper의 목적은 워크숍 전에 한 사람만 사용할 Telegram 테스트 채널을 안전하게 연결하는
것이다. BotFather 계정/봇 생성을 자동화하지 않고, Telegram update를 직접 polling하지 않으며,
임의 수신자나 공개 그룹에 메시지를 보내지 않는다.

## 1. 계획부터 확인

```sh
python3 test_bot.py --help
python3 test_bot.py plan \
  --home ~/.hermes-outbound-test-bot \
  --owner-id YOUR_NUMERIC_TELEGRAM_ID
```

`owner-id`는 비밀값이 아니지만 본인 ID만 사용한다. bot token, 로그인 코드, 전화번호,
비밀번호는 채팅이나 명령행에 넣지 않는다. `plan`은 파일이나 Telegram을 변경하지 않는다.

## 2. BotFather에서 직접 만들기

Telegram에서 인증 배지가 있는 `@BotFather`와의 1:1 대화를 직접 연다.

1. `/newbot`을 실행하고 테스트용 이름과 `bot`으로 끝나는 username을 정한다.
2. `/setjoingroups`에서 방금 만든 봇을 선택하고 `Disable`로 둔다.
3. 발급된 token을 복사하되 AI 채팅, `setup.json`, shell history, 문서에 붙이지 않는다.
4. token을 잃어버렸거나 노출했다면 BotFather에서 revoke하고 새 token을 사용한다.

이 저장소는 Telegram 계정을 만들거나 BotFather 대화를 대신할 수 없다.

## 3. 로컬 숨김 prompt에서만 연결

```sh
python3 test_bot.py configure \
  --home ~/.hermes-outbound-test-bot \
  --owner-id YOUR_NUMERIC_TELEGRAM_ID
```

`configure`는 기존 `kit.connect` 경로를 재사용한다. token은 터미널의 비표시 prompt로만 받고,
전용 home의 `.env`에 owner allowlist와 함께 저장한다. 명령행, JSON 출력, 로그, `setup.json`에는
token을 넣지 않는다. 기존 `.env` 값은
덮어쓰지 않으며 POSIX에서는 소유자 전용 권한을 사용한다.

기존 `.env`를 재사용한 경우 `kit.connect`가 Telegram에 다시 접속하지 않을 수 있으므로,
`configure`의 성공 상태는 `credential_configured_identity_unverified`이다. 바로 다음 `check`가
저장된 credential로 새 `getMe` 요청을 수행해야 bot identity가 현재 유효하다고 말할 수 있다.

`check`의 `group_join_disabled_verified`가 true여야 `getMe`도 BotFather의 그룹 참여 비활성
상태를 확인한 것이다. false이면 credential은 유효해도 owner-only 준비 완료로 표시하지 않으며,
BotFather의 `/setjoingroups` 설정을 다시 확인한다.

`check`에서 `bot_identity_verified`가 true여도 아직 다음을 증명하지 않는다.

- owner가 bot에게 메시지를 보낼 수 있음
- Hermes gateway가 그 메시지를 받음
- 모델이 답을 생성함
- owner가 실제 답을 받음

## 4. 제한된 확인

저장된 credential로 bot identity만 다시 확인한다.

```sh
python3 test_bot.py check \
  --home ~/.hermes-outbound-test-bot \
  --owner-id YOUR_NUMERIC_TELEGRAM_ID
```

원할 때만 고정된 무해한 문장 하나를 owner 자신에게 보낼 수 있다.

```sh
python3 test_bot.py check --send-self-test \
  --home ~/.hermes-outbound-test-bot \
  --owner-id YOUR_NUMERIC_TELEGRAM_ID
```

`--send-self-test`는 저장된 단일 owner ID만 사용한다. 수신자 인수를 받지 않고 알림을 끄며
protected content로 요청한다. 이것도 **bot→owner 단방향 전달**만 확인한다. owner round trip이나
Hermes gateway 동작을 성공으로 표시하지 않는다. owner가 먼저 bot의 direct chat에서 Start를
누르지 않았다면 Telegram이 전송을 거절할 수 있다.

## 5. 첫 유용한 결과는 기존 Hermes gateway로 확인

이 helper는 `getUpdates` poller를 만들지 않는다. 별도 poller는 Hermes gateway와 같은 token을
놓고 경쟁해 메시지 유실이나 Telegram 409 충돌을 만들 수 있다. 모델과 kit가 같은 전용
`HERMES_HOME`에 준비된 뒤, `plan` 결과의 `gateway.launcher`가
`scoped_launcher_found`인지 확인하고 그 절대경로로 도움말을 먼저 실행한다. launcher가
`missing_scoped_launcher`이면 이 전용 home에 Hermes를 먼저 설치해야 한다.

```sh
# 예시(POSIX): 실제 경로는 test_bot.py plan 결과를 사용
HERMES_HOME="$HOME/.hermes-outbound-test-bot" \
  "$HOME/.hermes-outbound-test-bot/hermes-agent/.hermes/bin/hermes" gateway run --help
HERMES_HOME="$HOME/.hermes-outbound-test-bot" \
  "$HOME/.hermes-outbound-test-bot/hermes-agent/.hermes/bin/hermes" gateway run
```

단순히 `HERMES_HOME=... hermes ...`라고 쓰면 shell의 ambient `PATH`에서 다른 Hermes를 집어
올 수 있어 격리가 보장되지 않는다. `plan`은 전용 home 내부에서 찾은 launcher만 출력하며,
없을 때는 명령을 만들어내지 않는다.

Telegram의 봇 1:1 대화에서 Start를 누르고 아래처럼 보낸다.

> 우리 회사의 아웃바운드 타겟을 정하려고 해. 제품, 타겟, 바잉 시그널, 지역, 제외조건을
> 한 번에 하나씩 물어봐 줘. 답을 받은 뒤 조사 계획과 근거 필드를 표로 요약하되,
> 내 승인 전에는 외부 조사나 메시지 발송을 시작하지 마.

좋은 첫 응답의 기준:

- 곧바로 실행했다고 주장하지 않고 첫 번째 명확한 질문을 한다.
- 제품과 타겟뿐 아니라 신호·지역·제외조건·허용 소스를 구분한다.
- 조사 계획, 근거, 초안과 실제 발송을 분리한다.
- 승인 전 자동 발송을 하지 않는다고 명시한다.
- 모르는 값과 검증되지 않은 기능을 성공으로 표시하지 않는다.

이 owner 메시지가 Hermes gateway에 들어가고 답이 같은 direct chat에 돌아온 뒤에만
owner round trip을 사람이 확인한다. background service가 필요하면 설치된 Hermes의
`gateway install/start/status/stop` 도움말을 각각 확인하고 동일한 `HERMES_HOME`으로 실행한다.
