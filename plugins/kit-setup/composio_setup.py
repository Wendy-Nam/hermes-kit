"""Check Composio Connect consumer credentials with read-only MCP discovery."""
import json
import re
import urllib.error
import urllib.request

URL = "https://connect.composio.dev/mcp"
MAX_RESPONSE = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect refused")


def _post(payload, key, session=None, protocol=None):
    headers = {"x-consumer-api-key": key, "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=20) as response:
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        session_id = response.headers.get("Mcp-Session-Id")
        if "id" not in payload:
            # A JSON-RPC notification has no response. Streamable HTTP accepts it
            # with 202; do not wait for an event stream to close.
            if response.status != 202:
                raise ValueError("notification not accepted")
            return None, session_id
        if content_type == "text/event-stream":
            # Consume only through the matching response; servers may keep SSE open.
            total, data = 0, []
            while True:
                line = response.readline(MAX_RESPONSE + 1)
                total += len(line)
                if total > MAX_RESPONSE:
                    raise ValueError("response limit")
                if not line:
                    raise ValueError("incomplete SSE")
                text = line.decode("utf-8").rstrip("\r\n")
                if text.startswith("data:"):
                    data.append(text[5:].lstrip(" "))
                elif not text and data:
                    event = json.loads("\n".join(data));data = []
                    if isinstance(event, dict) and event.get("id") == payload["id"]:
                        return event, session_id
        if content_type != "application/json":
            raise ValueError("unexpected response type")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("response limit")
        return json.loads(raw), session_id


def _result(response, request_id):
    if (not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
            or response.get("id") != request_id or "error" in response
            or not isinstance(response.get("result"), dict)):
        raise ValueError("invalid MCP response")
    return response["result"]


def validate_consumer_key(key: str) -> tuple[bool, str]:
    """Verifies Connect tools only. Never authorizes or reads a Google account."""
    if not isinstance(key, str) or not re.fullmatch(r"ck_[A-Za-z0-9_-]{8,512}", key):
        return False, "Composio For You의 ck_ 소비자 키를 입력해 주세요. Platform의 ak_ 키와 다릅니다."
    try:
        response, session = _post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
            "protocolVersion":"2025-03-26","capabilities":{},
            "clientInfo":{"name":"hermes-kit-setup","version":"1.0"}}}, key)
        result = _result(response, 1)
        protocol = result.get("protocolVersion")
        if protocol not in ("2024-11-05", "2025-03-26", "2025-06-18"):
            raise ValueError("unsupported protocol")
        if session is not None and (not isinstance(session, str) or not re.fullmatch(r"[\x21-\x7e]{1,1024}", session)):
            raise ValueError("invalid session")
        _post({"jsonrpc":"2.0","method":"notifications/initialized"},key,session,protocol)
        response, _ = _post({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},key,session,protocol)
        tools = _result(response, 2).get("tools")
        if not isinstance(tools, list) or not tools or not all(isinstance(t,dict) and isinstance(t.get("name"),str) for t in tools):
            raise ValueError("invalid tools")
        names = {t["name"] for t in tools}
        if not {"COMPOSIO_SEARCH_TOOLS", "COMPOSIO_MANAGE_CONNECTIONS"}.issubset(names):
            raise ValueError("Connect tools missing")
        return True, "Composio 도구 연결을 확인했습니다. Google 계정은 별도로 브라우저에서 연결해야 합니다."
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status in (401,403):
            return False, "Composio 소비자 키가 거부됐습니다. For You에서 키와 계정 권한을 확인해 주세요."
        return False, "Composio 서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."
    except Exception:
        return False, "Composio 연결을 검증하지 못했습니다. 네트워크와 소비자 키를 확인해 주세요."
