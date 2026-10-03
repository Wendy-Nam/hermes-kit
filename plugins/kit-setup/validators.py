"""Live key checks, so a student finds out here rather than three days later.

Every check is a single cheap authenticated GET. A 401 means the key is wrong;
a 0 means the network failed. Those are different problems for the user, so they
are reported differently. Keys go in headers only — never a query string, which
ends up in proxy logs and browser history.
"""
import json
import urllib.error
import urllib.request

Result = tuple[bool, str]   # (ok, one human-readable line)

_UA = "hermes-kit"


def _get(url, headers, proxy=None):
    opener_args = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **headers})
    try:
        with urllib.request.build_opener(*opener_args).open(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except urllib.error.URLError as e:
        # An HTTPS CONNECT tunnel refused by the proxy surfaces as URLError("Tunnel connection
        # failed: 407 ..."), not HTTPError. Without this it reads as "no internet".
        if "407" in str(e.reason):
            return 407, b""
        return 0, str(e).encode()
    except Exception as e:
        return 0, str(e).encode()


def _denied(status: int) -> str:
    if status == 0:
        return "인터넷 연결을 확인해 주세요 (검증 서버에 닿지 못했습니다)"
    if status in (401, 403):
        return f"키가 거부됐습니다 (HTTP {status}) — 공백 없이 다시 복사해 주세요"
    return f"검증에 실패했습니다 (HTTP {status}) — 잠시 후 다시 시도해 주세요"


def _summary(body: bytes) -> str:
    try:
        d = json.loads(body)
        items = d.get("data") or d.get("models") or []
        names = [m.get("id") or m.get("name", "") for m in items][:3]
        return "확인됨" + (f" ({', '.join(n for n in names if n)})" if any(names) else "")
    except Exception:
        return "확인됨"


def _simple(url, header):
    def check(key):
        status, body = _get(url, header(key))
        return (True, _summary(body)) if status == 200 else (False, _denied(status))
    return check


def _discord(tok):
    status, body = _get("https://discord.com/api/v10/users/@me", {"Authorization": f"Bot {tok}"})
    if status != 200:
        return False, _denied(status)
    try:
        return True, f"봇 이름: {json.loads(body).get('username')}"
    except Exception:
        return True, "확인됨"


def _webshare(tok):
    status, body = _get(
        "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=1",
        {"Authorization": f"Token {tok}"},
    )
    if status != 200:
        return False, _denied(status)
    try:
        p = json.loads(body)["results"][0]
        proxy = f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}"
    except Exception:
        return False, "Webshare 응답을 해석하지 못했습니다 — 다시 시도해 주세요"
    # The key being valid is not enough: the point of this pack is reaching Korean sites through
    # the proxy, so confirm the proxy actually works before telling the user it does.
    status2, _ = _get("https://www.wanted.co.kr/", {}, proxy=proxy)
    return (True, "프록시로 원티드 접속 확인") if status2 == 200 else \
        (False, f"키는 맞지만 프록시 접속 실패 (HTTP {status2})")


def _composio(tok):
    status, _ = _get("https://backend.composio.dev/api/v3/connected_accounts?limit=1",
                     {"x-api-key": tok})
    if status == 200:
        return True, "확인됨"
    if status in (401, 403):
        return False, _denied(status)
    return (False, f"Composio 확인 실패 (HTTP {status}) — 키는 저장되지만 연동은 확인해 주세요")


VALIDATORS = {
    "discord": _discord,
    "gemini": _simple("https://generativelanguage.googleapis.com/v1beta/models?pageSize=3",
                      lambda k: {"x-goog-api-key": k}),
    "groq": _simple("https://api.groq.com/openai/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "apify": _simple("https://api.apify.com/v2/users/me", lambda k: {"Authorization": f"Bearer {k}"}),
    "webshare": _webshare,
    # Registered as a real validator rather than intercepted in the UI, so packs.py
    # can still check at import time that every pack names a validator that exists.
    "webshare_api_key": lambda key: webshare_from_api_key(key)[:2],
    "composio": _composio,
    "opencode_go": _simple("https://opencode.ai/zen/go/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "commandcode": _simple("https://api.commandcode.ai/provider/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
}


def webshare_from_api_key(token):
    """Look up proxy credentials with the API key alone, so the student pastes one thing.

    Webshare shows the same Username/Password in two places: the API key page and
    the Proxy list. The dashboard login email is neither of them, and students
    paste that by mistake often enough that the old two-field form spelled the
    difference out in both hints. One field removes the opportunity entirely.

    Returns (ok, message, {env: value}) or (ok, message, {}). The credentials are
    returned rather than written so the caller decides where they land, and they
    never appear in the message.
    """
    status, body = _get(
        "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=1",
        {"Authorization": f"Token {token.strip()}"},
    )
    if status != 200:
        return False, _denied(status), {}
    try:
        entry = json.loads(body)["results"][0]
        username, password = entry["username"], entry["password"]
    except Exception:
        return False, "Webshare 응답을 해석하지 못했습니다 — 다시 시도해 주세요", {}
    if not username or not password:
        return False, "이 API 키에는 프록시가 없습니다 — Webshare에서 프록시 하나를 먼저 열어야 합니다", {}
    # p.webshare.io only accepts "<user>-rotate"; the API returns the plain form.
    if not username.endswith("-rotate"):
        username += "-rotate"
    # A valid key is not a working proxy. The whole point of the pack is reaching
    # blocked sites, so confirm that before telling the student it is set up.
    status2, _ = _get("https://www.wanted.co.kr/", {}, proxy=_proxy_url(username, password))
    if status2 != 200:
        return False, f"키는 맞지만 프록시 접속이 실패했습니다 (HTTP {status2})", {}
    return True, "프록시로 원티드 접속 확인", {
        "WEBSHARE_PROXY_USERNAME": username,
        "WEBSHARE_PROXY_PASSWORD": password,
    }


def _proxy_url(username, password):
    from urllib.parse import quote
    return "http://" + quote(username, safe="") + ":" + quote(password, safe="") + "@p.webshare.io:80"


def webshare_credentials(username, password):
    """Validate the proxy credentials as a pair, never as two API tokens.

    Kept for students who already have the Username/Password pair from the Proxy
    list screen, or whose API key lookup did not work.
    """
    if not username or not password:
        return False, "프록시 사용자명과 비밀번호를 모두 입력해 주세요"
    # p.webshare.io only accepts "<user>-rotate", the same form youtube-transcript-api builds from
    # the plain dashboard username. Store what the student pasted; test the form that is used.
    username = username.strip()
    if not username.endswith("-rotate"):
        username += "-rotate"
    status, _ = _get("https://www.wanted.co.kr/", {}, proxy=_proxy_url(username, password.strip()))
    if status == 200:
        return True, "프록시 접속 확인"
    if status == 407:
        return False, ("프록시가 사용자명·비밀번호를 거부했습니다 — Webshare 로그인 정보가 아니라 "
                       "Proxy 목록 화면의 Username/Password를 넣어 주세요")
    return False, f"프록시 접속 실패 (HTTP {status}) — 잠시 후 다시 시도해 주세요"

from composio_setup import validate_consumer_key
VALIDATORS["composio_consumer"] = validate_consumer_key
