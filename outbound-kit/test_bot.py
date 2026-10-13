#!/usr/bin/env python3
"""Owner-only Telegram test-bot setup and bounded checks.

This helper never creates a Telegram account/bot, polls updates, accepts a bot
token on argv, or claims that an owner round trip passed merely because getMe
worked.  Messaging remains the installed Hermes gateway's responsibility.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import kit
import paths


ROOT = Path(__file__).resolve().parent


def default_test_home(target: str = "auto", *, env=None,
                      user_home: str | Path | None = None) -> Path:
    """Put the test bot beside, but never inside, the normal kit home."""
    base = paths.default_home(target, env=env, user_home=user_home)
    return base.with_name(base.name + "-test-bot")


DEFAULT_HOME = default_test_home()
SELF_TEST_TEXT = "Hermes Outbound 비공개 연결 확인입니다. 자동 발송 기능은 활성화되지 않았습니다."
OWNER_RE = re.compile(r"[1-9][0-9]{3,24}")
TOKEN_RE = re.compile(r"[0-9]+:[A-Za-z0-9_-]+")


def validate_owner(owner_id: str) -> str:
    value = str(owner_id or "").strip()
    if not OWNER_RE.fullmatch(value):
        raise ValueError("owner-id: 본인의 숫자 Telegram 사용자 ID가 필요합니다.")
    return value


def safe_home(home: str | Path) -> Path:
    path = Path(home).expanduser().absolute()
    if path == Path(path.anchor) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("전용 test-bot home은 루트나 심볼릭 링크일 수 없습니다.")
    return path


def plan(home: str | Path, owner_id: str | None = None) -> dict:
    target = safe_home(home)
    launcher = paths.resolve_hermes(target, required=False)
    owner_status = "provided_nonsecret" if owner_id and OWNER_RE.fullmatch(str(owner_id)) else "required_before_configure"
    return {
        "schema_version": 1,
        "action": "plan",
        "changes_applied": False,
        "home": str(target),
        "owner_id": owner_status,
        "official_botfather_steps": [
            "Telegram에서 인증 배지가 있는 @BotFather와 1:1 대화를 연다.",
            "/newbot으로 테스트봇 이름과 bot으로 끝나는 username을 만든다.",
            "/setjoingroups에서 이 봇의 그룹 참여를 Disable로 둔다.",
            "발급 token은 복사하되 채팅·setup.json·명령행에 붙이지 않는다.",
            "configure의 로컬 비표시 prompt에만 token을 입력한다.",
        ],
        "configure": {
            "credential_input": "local hidden prompt only",
            "storage": str(target / ".env"),
            "implementation": "kit.connect owner allowlist; check performs a fresh Telegram getMe",
        },
        "check_claims": {
            "getMe": "bot credential identity only",
            "send_self_test": "optional explicit bot-to-owner delivery only",
            "owner_roundtrip": "not verified until the owner messages the Hermes gateway and receives its response",
        },
        "gateway": {
            "new_poller_created": False,
            "engine_status": "scoped_launcher_found" if launcher else "missing_scoped_launcher",
            "prerequisite": (None if launcher else
                             "Install Hermes into this exact dedicated home before the gateway round trip."),
            "launcher": str(launcher) if launcher else None,
            "environment": {"HERMES_HOME": str(target)},
            "foreground_help_first": ([str(launcher), "gateway", "run", "--help"]
                                      if launcher else None),
            "foreground": [str(launcher), "gateway", "run"] if launcher else None,
            "status": [str(launcher), "gateway", "status"] if launcher else None,
        },
        "first_result_flow": [
            "owner opens the bot's direct chat and presses Start",
            "owner sends the documented question-quality prompt",
            "Hermes gateway—not this helper—must receive it and reply",
            "owner checks clarification quality and confirms no research/send occurred before approval",
        ],
        "never": ["BotFather automation", "getUpdates polling", "arbitrary receiver", "public group", "automatic outreach send"],
    }


def configure(home: str | Path, owner_id: str, *, connector=kit.connect) -> dict:
    """Reuse kit.connect so token entry stays hidden and storage stays additive/private."""
    target = safe_home(home)
    owner = validate_owner(owner_id)
    data = {
        "channel": "telegram",
        "telegram_owner": owner,
        "telegram_mode": "direct",
    }
    connector(data, target)
    return {
        "schema_version": 1,
        "action": "configure",
        "status": "credential_configured_identity_unverified",
        "home": str(target),
        "owner_allowlist": "configured_single_owner",
        "owner_roundtrip_verified": False,
        "next": "Run check for a fresh getMe, then start the scoped Hermes gateway and complete the owner direct-message round trip.",
    }


def _read_credentials(home: str | Path, owner_id: str) -> tuple[str, str]:
    target = safe_home(home)
    owner = validate_owner(owner_id)
    env_path = target / ".env"
    if env_path.is_symlink() or any(parent.is_symlink() for parent in env_path.parents) or not env_path.is_file():
        raise ValueError("저장된 Telegram credential이 없습니다. configure를 로컬 터미널에서 먼저 실행하세요.")
    if os.name == "posix" and env_path.stat().st_mode & 0o077:
        raise ValueError("credential 파일 권한이 너무 넓습니다. 소유자만 읽도록 복구하세요.")
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in values:
            raise ValueError("credential 파일에 중복 키가 있어 보존하고 중단했습니다.")
        values[key] = value
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    bound_owner = values.get("TELEGRAM_ALLOWED_USERS", "")
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("저장된 Telegram credential 형식을 확인하세요. 값은 출력하지 않습니다.")
    if bound_owner != owner:
        raise ValueError("저장된 owner allowlist와 --owner-id가 다릅니다. 기존 값을 보존했습니다.")
    return token, owner


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TelegramAPI:
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())

    def _call(self, token: str, method: str, payload: dict[str, str] | None = None) -> dict:
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("Telegram credential 형식이 잘못되었습니다.")
        url = f"https://api.telegram.org/bot{token}/{method}"
        data = urllib.parse.urlencode(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("Telegram 응답이 안전 한도를 넘었습니다.")
            body = json.loads(raw.decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError,
                json.JSONDecodeError, ValueError):
            raise ValueError(f"Telegram {method} 확인에 실패했습니다. token·네트워크·봇 상태를 확인하세요.") from None
        if not isinstance(body, dict) or body.get("ok") is not True or not isinstance(body.get("result"), dict):
            raise ValueError(f"Telegram {method} 응답이 유효하지 않습니다.")
        return body["result"]

    def get_me(self, token: str) -> dict:
        result = self._call(token, "getMe")
        if result.get("is_bot") is not True:
            raise ValueError("Telegram getMe 결과가 bot 계정이 아닙니다.")
        can_join_groups = result.get("can_join_groups")
        return {
            "bot_identity_verified": True,
            "bot_id": result.get("id"),
            "username": result.get("username") or "",
            "can_join_groups": can_join_groups,
            "group_join_disabled_verified": can_join_groups is False,
        }

    def send_self_test(self, token: str, owner_id: str) -> dict:
        owner = validate_owner(owner_id)
        result = self._call(token, "sendMessage", {
            "chat_id": owner,
            "text": SELF_TEST_TEXT,
            "disable_notification": "true",
            "protect_content": "true",
        })
        chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
        if str(chat.get("id", "")) != owner:
            raise ValueError("self-test 응답 대상이 owner와 일치하지 않습니다.")
        return {"outbound_self_test_sent": True, "message_id": result.get("message_id")}


def check(home: str | Path, owner_id: str, *, send_self_test: bool = False,
          api: TelegramAPI | None = None) -> dict:
    token, owner = _read_credentials(home, owner_id)
    client = api or TelegramAPI()
    identity = client.get_me(token)
    result = {
        "schema_version": 1,
        "action": "check",
        "status": ("owner_only_transport_ready_roundtrip_pending"
                   if identity["group_join_disabled_verified"] else
                   "bot_identity_verified_group_setting_unverified"),
        "credential_present": True,
        "owner_allowlist": "configured_single_owner",
        **identity,
        "self_test_requested": bool(send_self_test),
        "outbound_self_test_sent": False,
        "owner_roundtrip_verified": False,
        "gateway_polling_verified": False,
    }
    if send_self_test:
        result.update(client.send_self_test(token, owner))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Private owner-only Telegram test-bot setup; no update polling")
    parser.add_argument("action", choices=["plan", "configure", "check"])
    parser.add_argument("--home", default=str(DEFAULT_HOME), help="dedicated Hermes home; token is stored only in HOME/.env")
    parser.add_argument("--owner-id", help="your numeric Telegram user ID; non-secret")
    parser.add_argument("--send-self-test", action="store_true",
                        help="check only: explicitly send one fixed harmless message to the configured owner")
    args = parser.parse_args(argv)
    try:
        if args.send_self_test and args.action != "check":
            raise ValueError("--send-self-test는 check에서만 명시적으로 사용할 수 있습니다.")
        if args.action == "plan":
            result = plan(args.home, args.owner_id)
        elif args.action == "configure":
            result = configure(args.home, validate_owner(args.owner_id or ""))
        else:
            result = check(args.home, validate_owner(args.owner_id or ""),
                           send_self_test=args.send_self_test)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
