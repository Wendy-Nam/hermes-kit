"""First owner registration and the invite link.

The student creates a Discord app by hand (there is no public API for app creation) and pastes
only the bot token. Everything after that — intents, permissions, invite URL — is set from here
so the manual does not have a checkbox checklist for a non-developer to get wrong.
"""
import json
import logging
import os
from pathlib import Path
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

# Where boot keeps the link so it survives a log the student can no longer scroll back to.
INVITE_FILE = ".kit-invite-url"

# Every permission the bot needs across the kit: text, threads, embeds, files, history,
# voice, slash commands. Summed so a student never has to tick boxes in the Developer Portal.
PERM_BITS = (1 << 10, 1 << 11, 1 << 38, 1 << 14, 1 << 15, 1 << 16, 1 << 20, 1 << 21, 1 << 31)
PERMS = sum(PERM_BITS)
# Message-content intent is the only one a student must tick manually in the portal; the guild-members
# intent is not needed at all, but both limited bits are declared here so the portal shows what is on.
GATEWAY_MESSAGE_CONTENT_LIMITED = 1 << 19
GATEWAY_GUILD_MEMBERS_LIMITED = 1 << 15
LIMITED = GATEWAY_MESSAGE_CONTENT_LIMITED | GATEWAY_GUILD_MEMBERS_LIMITED


def _discord_get(path, token):
    req = urllib.request.Request(f"https://discord.com/api/v10{path}",
                                 headers={"Authorization": f"Bot {token}", "User-Agent": "hermes-kit"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _discord_patch(path, token, body):
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}", data=json.dumps(body).encode(), method="PATCH",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "hermes-kit"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def invite_url(app_id: str) -> str:
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}"
            f"&permissions={PERMS}&scope=bot%20applications.commands")


PORTAL_STEPS = (
    "링크를 직접 만들려면 Discord Developer Portal에서:\n"
    "1) 내 앱 → 해당 봇 → **OAuth2 → URL Generator**\n"
    "2) Scopes: `bot`, `applications.commands` 를 모두 체크\n"
    "3) Bot Permissions: `Administrator` 를 체크 (키트가 필요한 권한을 대신 설정합니다)\n"
    "4) **Copy Link**를 브라우저에 붙여 넣어 본인 서버를 고르고 승인합니다.\n"
    "5) 그다음 Discord에서 `/setup` 을 실행합니다."
)


def configure_app(token: str) -> tuple[str | None, str | None]:
    """Set intents + install params via the API. Returns (invite_url, error_message).

    Never raises: a student who hits this needs a sentence they can act on, not a traceback.
    """
    try:
        app = _discord_get("/applications/@me", token)
    except urllib.error.HTTPError as e:
        return None, f"봇 토큰이 거부됐습니다 (HTTP {e.code}) — Developer Portal에서 Reset Token을 다시 하세요"
    except Exception as e:
        return None, f"디스코드에 연결하지 못했습니다 ({type(e).__name__})"
    try:
        _discord_patch("/applications/@me", token, {
            "flags": LIMITED,
            "install_params": {"scopes": ["bot", "applications.commands"],
                               "permissions": str(PERMS)},
        })
    except Exception as e:
        # Not fatal: the student can still invite the bot, they may just have to tick a box.
        log.warning("install_params update failed (%s) — invite link still usable", type(e).__name__)
    return invite_url(str(app.get("id"))), None


def remember_invite(data_dir, url: str) -> bool:
    """Keep the link on the data volume. Returns whether it was written.

    The link itself is a public client id plus a permission number, not a credential — but it is
    the only way into a brand new server, so it is stored 0600 like every other kit file, and the
    token never comes near it.
    """
    if not isinstance(url, str) or not url.startswith("https://discord.com/oauth2/authorize?"):
        return False
    path = Path(data_dir) / INVITE_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(url)
        return True
    except OSError:
        log.warning("invite link could not be saved — it is still in the container log")
        return False


def remembered_invite(data_dir) -> str | None:
    """The saved link, or None. Never raises: this runs on a student's first boot."""
    try:
        return (Path(data_dir) / INVITE_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def bot_token(data_dir) -> str:
    """The bot token from .env, else the environment Compose injected. Never logged or printed."""
    from env_store import get_env

    try:
        stored = get_env(Path(data_dir) / ".env").get("DISCORD_BOT_TOKEN", "")
    except Exception:
        stored = ""
    token = (stored or os.environ.get("DISCORD_BOT_TOKEN", "")).strip()
    return "" if token in ("dummy", "") else token


def invite_link(data_dir) -> tuple[str | None, str]:
    """(url, message) for a student who cannot find the link in the log.

    A fresh lookup wins, so a link saved before the app was recreated cannot become the wrong
    answer; the saved one is the fallback when Discord is unreachable. `dummy` — the token CI boots
    with — counts as no token at all, so a test run never reports success.
    """
    saved = remembered_invite(data_dir)
    token = bot_token(data_dir)
    if not token:
        if saved:
            return saved, "저장해 둔 링크입니다. (봇 토큰은 현재 환경변수에 없습니다.)"
        return None, ("봇 토큰을 찾지 못했습니다. Hostinger Compose의 DISCORD_BOT_TOKEN 환경변수를 "
                      "확인하고 컨테이너를 다시 시작하세요.\n\n" + PORTAL_STEPS)
    url, error = configure_app(token)
    if url:
        remember_invite(data_dir, url)
        return url, ""
    if saved:
        return saved, f"새 링크를 받아오지 못했습니다 ({error}). 대신 예전에 저장한 링크를 보여드립니다."
    # A rejected token cannot reveal the application id, and guessing one would point the
    # student at a stranger's app. The Portal recipe is the only honest answer here.
    return None, f"{error or '초대 링크를 만들지 못했습니다.'}\n\n{PORTAL_STEPS}"


def main() -> int:
    """`python owner.py` inside the container: print the invite link again, token never shown."""
    data = Path(os.environ.get("HERMES_HOME") or "/opt/data")
    url, note = invite_link(data)
    if note:
        print(note)
    if not url:
        return 1
    print(url)
    return 0


def ensure_owner(user_id: str, name: str) -> bool:
    """Approve the guild owner so they can talk to the bot. True when a new approval was made.

    Approval is done by the plugin rather than by the student typing a pairing code: the person
    running the server is definitionally its owner, and this is their own instance.
    """
    from gateway.pairing import PairingStore

    store = PairingStore()
    uid = str(user_id)
    for entry in store.list_approved("discord"):
        got = entry.get("user_id") if isinstance(entry, dict) else entry
        if str(got) == uid:
            return False
    code = store.generate_code("discord", uid, name)
    return bool(code and store.approve_code("discord", code))


def is_approved(user_id: str) -> bool:
    from gateway.pairing import PairingStore

    uid = str(user_id)
    for entry in PairingStore().list_approved("discord"):
        got = entry.get("user_id") if isinstance(entry, dict) else entry
        if str(got) == uid:
            return True
    return False


# Reached from the host when the log line is gone:
#   docker compose exec hermes /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/owner.py
if __name__ == "__main__":
    raise SystemExit(main())
