"""First owner registration and the invite link.

The student creates a Discord app by hand (there is no public API for app creation) and pastes
only the bot token. Everything after that — intents, permissions, invite URL — is set from here
so the manual does not have a checkbox checklist for a non-developer to get wrong.
"""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

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
        log.warning("install_params update failed (%s) — invite link still usable", e)
    return invite_url(str(app.get("id"))), None


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
