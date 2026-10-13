#!/usr/bin/env python3
"""Optional outbound service preparation with redacted, additive secret handling.

Authentication probes establish only that a provider accepted a credential and returned
the expected discovery shape. They never establish that STT, a proxy target, an Actor, or
an OAuth-connected app works.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import getpass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE = 1024 * 1024
RUNTIME_PLAN = "outbound-services.runtime.json"


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    label: str
    env: tuple[str, ...]
    prep_url: str
    dependencies: tuple[str, ...]
    platform_notes: tuple[str, ...]


SERVICES = {
    "webshare": ServiceSpec(
        "webshare", "Webshare proxy", ("WEBSHARE_API_KEY",),
        "https://dashboard.webshare.io/",
        ("A permitted source-specific transport adapter",),
        ("Authentication does not verify any target source.",
         "Never use it to bypass login, CAPTCHA, rate limits, robots, or access denial."),
    ),
    "groq": ServiceSpec(
        "groq", "Groq speech-to-text", ("GROQ_API_KEY",),
        "https://console.groq.com/keys",
        ("A Hermes version with an explicitly configured Groq STT adapter",),
        ("Audio leaves the device; obtain consent before a functional test.",
         "Desktop microphone capture and server audio upload are separate checks."),
    ),
    "apify": ServiceSpec(
        "apify", "Apify collector", ("APIFY_TOKEN",),
        "https://console.apify.com/account/integrations",
        ("An explicitly selected Actor and reviewed input schema",),
        ("Actor execution can cost money and retain datasets.",
         "Authentication does not start an Actor or verify a source."),
    ),
    "composio": ServiceSpec(
        "composio", "Composio Connect MCP", ("COMPOSIO_CONSUMER_KEY",),
        "https://connect.composio.dev/",
        ("A separate user-authorized app connection with least-privilege scopes",),
        ("MCP discovery does not authorize Gmail, calendar, CRM, or sending.",
         "OAuth approval and each app capability require separate browser checks."),
    ),
}


ENDPOINTS = {
    "webshare": "https://proxy.webshare.io/api/v2/proxy/list/?page=1&page_size=1",
    "groq": "https://api.groq.com/openai/v1/models",
    "apify": "https://api.apify.com/v2/users/me",
    "composio": "https://connect.composio.dev/mcp",
}
ALLOWED_ORIGINS = {
    "https://proxy.webshare.io",
    "https://api.groq.com",
    "https://api.apify.com",
    "https://connect.composio.dev",
}


class ServiceError(ValueError):
    """A deliberately redacted user-facing service error."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ServiceError("리디렉션을 거부했습니다. 제공자 주소 변경 여부를 확인하세요.")


def selected_services(data: dict) -> list[str]:
    selected = data.get("services", [])
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        raise ServiceError("services는 서비스 이름 목록이어야 합니다.")
    if len(selected) != len(set(selected)):
        raise ServiceError("services에 중복 항목이 있습니다.")
    unknown = sorted(set(selected) - set(SERVICES))
    if unknown:
        raise ServiceError("지원하지 않는 서비스가 있습니다: " + ", ".join(unknown))
    return selected


def load_config(path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ServiceError("설정 파일은 JSON 객체여야 합니다.")
    selected_services(data)
    return data


def _safe_endpoint(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if (parsed.scheme != "https" or origin not in ALLOWED_ORIGINS or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ServiceError("허용되지 않은 서비스 주소입니다.")


def _opener():
    # Ignore ambient HTTP(S)_PROXY for credential checks: proxy URL logs are an unnecessary
    # secret boundary, and every probe destination is a fixed provider origin.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _read_json(response) -> dict:
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type not in ("application/json", "application/json-rpc"):
        raise ServiceError("제공자가 예상하지 않은 응답 형식을 반환했습니다.")
    raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ServiceError("제공자 응답이 안전 한도를 넘었습니다.")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ServiceError("제공자 응답 구조가 잘못되었습니다.")
    return value


def _secret_shape(service: str, secret: str) -> None:
    if (not isinstance(secret, str) or len(secret) < 8 or len(secret) > 4096
            or any(char.isspace() or ord(char) < 32 for char in secret)):
        raise ServiceError(f"{SERVICES[service].label} 키 형식을 확인하세요.")
    if service == "composio" and not re.fullmatch(r"ck_[A-Za-z0-9_-]{8,512}", secret):
        raise ServiceError("Composio For You의 ck_ 소비자 키가 필요합니다.")


def _get_json(service: str, secret: str, opener=None) -> dict:
    url = ENDPOINTS[service]
    _safe_endpoint(url)
    headers = {"Accept": "application/json"}
    if service == "webshare":
        headers["Authorization"] = "Token " + secret
    else:
        headers["Authorization"] = "Bearer " + secret
    request = urllib.request.Request(url, headers=headers)
    with (opener or _opener()).open(request, timeout=20) as response:
        return _read_json(response)


def _mcp_post(payload: dict, secret: str, *, session=None, protocol=None, opener=None):
    url = ENDPOINTS["composio"]
    _safe_endpoint(url)
    headers = {
        "x-consumer-api-key": secret,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session:
        headers["Mcp-Session-Id"] = session
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    request = urllib.request.Request(
        url, data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers, method="POST")
    with (opener or _opener()).open(request, timeout=20) as response:
        response_session = response.headers.get("Mcp-Session-Id")
        if response_session is not None and not re.fullmatch(r"[\x21-\x7e]{1,1024}", response_session):
            raise ServiceError("MCP 세션 식별자가 잘못되었습니다.")
        if "id" not in payload:
            if response.status not in (200, 202, 204):
                raise ServiceError("MCP 초기화 알림이 거부됐습니다.")
            return None, response_session or session
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type == "application/json":
            return _read_json(response), response_session or session
        if content_type != "text/event-stream":
            raise ServiceError("MCP 응답 형식이 잘못되었습니다.")
        total, event_lines = 0, []
        while True:
            line = response.readline(MAX_RESPONSE + 1)
            total += len(line)
            if total > MAX_RESPONSE or not line:
                raise ServiceError("MCP 스트림이 불완전하거나 너무 큽니다.")
            text = line.decode("utf-8").rstrip("\r\n")
            if text.startswith("data:"):
                event_lines.append(text[5:].lstrip())
            elif not text and event_lines:
                event = json.loads("\n".join(event_lines))
                event_lines = []
                if isinstance(event, dict) and event.get("id") == payload["id"]:
                    return event, response_session or session


def _rpc_result(response, request_id):
    if (not isinstance(response, dict) or response.get("jsonrpc") != "2.0"
            or response.get("id") != request_id or "error" in response
            or not isinstance(response.get("result"), dict)):
        raise ServiceError("MCP JSON-RPC 응답이 잘못되었습니다.")
    return response["result"]


def probe(service: str, secret: str, *, opener=None) -> dict:
    """Run read-only authentication discovery; never claim functional readiness."""
    if service not in SERVICES:
        raise ServiceError("지원하지 않는 서비스입니다.")
    _secret_shape(service, secret)
    try:
        if service == "composio":
            response, session = _mcp_post({
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "hermes-outbound-kit", "version": "0.1"},
                }}, secret, opener=opener)
            initialized = _rpc_result(response, 1)
            protocol = initialized.get("protocolVersion")
            if protocol not in ("2024-11-05", "2025-03-26", "2025-06-18"):
                raise ServiceError("지원하지 않는 MCP 프로토콜입니다.")
            _mcp_post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                      secret, session=session, protocol=protocol, opener=opener)
            response, _ = _mcp_post(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                secret, session=session, protocol=protocol, opener=opener)
            tools = _rpc_result(response, 2).get("tools")
            if not isinstance(tools, list) or not tools or not all(
                    isinstance(tool, dict) and isinstance(tool.get("name"), str) for tool in tools):
                raise ServiceError("MCP 도구 목록이 잘못되었습니다.")
        else:
            body = _get_json(service, secret, opener=opener)
            if service == "groq" and not isinstance(body.get("data"), list):
                raise ServiceError("Groq 모델 목록이 없습니다.")
            if service == "apify" and not isinstance(body.get("data"), dict):
                raise ServiceError("Apify 사용자 응답이 없습니다.")
            if service == "webshare" and not (
                    isinstance(body.get("results"), list) or isinstance(body.get("count"), int)):
                raise ServiceError("Webshare 프록시 목록 응답이 없습니다.")
        return {
            "service": service,
            "auth_valid": True,
            "functional_verified": False,
            "message": "인증 탐색 통과; 실제 기능은 아직 검증되지 않았습니다.",
        }
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if status in (401, 403):
            raise ServiceError(f"{SERVICES[service].label} 인증이 거부됐습니다.") from None
        raise ServiceError(f"{SERVICES[service].label} 제공자 응답을 확인하지 못했습니다.") from None
    except ServiceError:
        raise
    except Exception:
        raise ServiceError(
            f"{SERVICES[service].label} 인증을 검증하지 못했습니다. 네트워크와 키를 확인하세요.") from None


def _parse_env_names(text: str) -> set[str]:
    names = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name in names:
            raise ServiceError(f".env에 중복 키가 있습니다: {name}")
        names.add(name)
    return names


def _safe_home(home) -> Path:
    root = Path(home).expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ServiceError("서비스 설정 경로에 심볼릭 링크가 있습니다.")
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(root, 0o700)
    return root


@contextmanager
def env_lock(home):
    """Cross-platform advisory lock exported for the main installer to reuse."""
    root = _safe_home(home)
    lock_path = root / ".outbound-env.lock"
    if lock_path.is_symlink():
        raise ServiceError("비밀값 잠금 파일이 심볼릭 링크입니다.")
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def merge_env_additive(home, updates: dict[str, str]) -> None:
    """Append new env bindings under a lock; never replace an existing binding."""
    if not updates:
        return
    for name, value in updates.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
            raise ServiceError("환경변수 이름이 잘못되었습니다.")
        if not isinstance(value, str) or not value or any(c in value for c in "\r\n\0"):
            raise ServiceError(f"{name} 값 형식을 확인하세요.")
    root = _safe_home(home)
    path = root / ".env"
    if path.is_symlink():
        raise ServiceError("비밀값 저장 파일이 심볼릭 링크입니다.")
    with env_lock(root):
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        collisions = sorted(_parse_env_names(original) & set(updates))
        if collisions:
            raise ServiceError("기존 비밀값을 보존했습니다: " + ", ".join(collisions))
        prefix = original + ("\n" if original and not original.endswith("\n") else "")
        rendered = prefix + "\n".join(f"{key}={value}" for key, value in updates.items()) + "\n"
        fd, staged = tempfile.mkstemp(prefix=".outbound-env-", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "posix":
                os.chmod(staged, 0o600)
            os.replace(staged, path)
            if os.name == "posix":
                directory = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(staged):
                os.unlink(staged)


def runtime_plan(selected: list[str]) -> dict:
    entries = {}
    for service in selected:
        common = {
            "credential_env_refs": list(SERVICES[service].env),
            "state": "staged_apply_required",
            "auth_is_not_functional_verification": True,
        }
        if service == "groq":
            common.update(purpose="speech_to_text", provider="groq",
                          instruction="Select a supported Groq STT model in the installed Hermes version; obtain audio consent; restart and transcribe a synthetic clip.")
        elif service == "composio":
            common.update(transport="streamable_http_mcp", endpoint=ENDPOINTS[service],
                          header_env_ref="COMPOSIO_CONSUMER_KEY",
                          instruction="Register the fixed MCP endpoint using an environment reference, then authorize each app with least privilege in the user's browser.")
        elif service == "webshare":
            common.update(purpose="source_specific_proxy_transport",
                          helper="runtime_connect.py proxy-fetch",
                          instruction="Apply one exact HTTPS origin, then invoke the bounded helper for a reviewed URL; authentication alone enables no target and bypass is forbidden.")
        elif service == "apify":
            common.update(purpose="bounded_actor_run",
                          instruction="Choose one Actor, review its source terms/input/cost/result limit/retention, then approve one manual run; no Actor is selected by setup.")
        entries[service] = common
    return {"version": 1, "managed_by": "hermes-outbound-kit", "services": entries,
            "restart_required_after_apply": bool(set(selected) & {"groq", "composio"})}


def write_runtime_plan(home, selected: list[str]) -> Path:
    root = _safe_home(home)
    path = root / RUNTIME_PLAN
    if path.is_symlink():
        raise ServiceError("런타임 계획 파일이 심볼릭 링크입니다.")
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise ServiceError("기존 런타임 계획 파일을 보존했습니다. 수동 검토가 필요합니다.") from None
        if prior.get("managed_by") != "hermes-outbound-kit":
            raise ServiceError("사용자 런타임 계획 파일을 덮어쓰지 않았습니다.")
    payload = json.dumps(runtime_plan(selected), ensure_ascii=False, indent=2) + "\n"
    fd, staged = tempfile.mkstemp(prefix=".outbound-services-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(staged, 0o600)
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    return path


def service_status(data: dict, home) -> list[dict]:
    selected = selected_services(data)
    path = Path(home).expanduser().absolute() / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() and not path.is_symlink() else ""
    names = _parse_env_names(text)
    rows = []
    for service in selected:
        required = SERVICES[service].env
        present = [name for name in required if name in names or name in os.environ]
        rows.append({
            "service": service,
            "selected": True,
            "credential_present": len(present) == len(required),
            "auth_valid": None,
            "functional_verified": False,
            "restart_apply_required": True,
        })
    return rows


def connect_services(data: dict, home, *, prompt: Callable[[str], str] = getpass.getpass,
                     prober: Callable[..., dict] = probe) -> list[dict]:
    selected = selected_services(data)
    existing = {row["service"]: row for row in service_status(data, home)}
    updates, results = {}, []
    try:
        for service in selected:
            if existing[service]["credential_present"]:
                results.append({**existing[service], "message": "기존 비밀값을 보존했습니다. 인증은 다시 검사하지 않았습니다."})
                continue
            spec = SERVICES[service]
            if len(spec.env) != 1:
                raise ServiceError("이 버전에서 복수 비밀값 서비스는 지원하지 않습니다.")
            value = prompt(f"{spec.label} key (화면에 표시되지 않음): ")
            result = prober(service, value)
            if not result.get("auth_valid") or result.get("functional_verified"):
                raise ServiceError(f"{spec.label} 인증 결과가 안전 계약과 맞지 않습니다.")
            updates[spec.env[0]] = value
            results.append(result)
        merge_env_additive(home, updates)
        write_runtime_plan(home, selected)
        return results
    except ServiceError:
        raise
    except Exception:
        raise ServiceError("서비스 연결을 완료하지 못했습니다. 비밀값은 출력하지 않았습니다.") from None
    finally:
        updates.clear()


def _print_rows(rows):
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Outbound optional services")
    parser.add_argument("action", choices=("plan", "status", "connect", "apply", "check", "run-apify"))
    parser.add_argument("--config", default="setup.json")
    parser.add_argument("--home", default=str(Path.home() / ".hermes-outbound"))
    parser.add_argument("--apify-input", help="Reviewed Actor input JSON for an explicit manual run")
    parser.add_argument("--confirm-paid-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = load_config(args.config)
        selected = selected_services(data)
        if args.action == "plan":
            path = write_runtime_plan(args.home, selected)
            print(f"비밀값 없는 런타임 적용 계획: {path}")
            _print_rows([{"service": service, **asdict(SERVICES[service])} for service in selected])
        elif args.action == "status":
            _print_rows(service_status(data, args.home))
        elif args.action == "connect":
            _print_rows(connect_services(data, args.home))
            print("인증 탐색과 비밀값 저장 완료. 런타임 적용·재시작·실제 기능 검증은 아직 필요합니다.")
        elif args.action in ("apply", "check"):
            from runtime_connect import RuntimeConnectError, apply_services, check_services
            try:
                result = apply_services(data, args.home) if args.action == "apply" else check_services(data, args.home)
            except RuntimeConnectError as exc:
                raise ServiceError(str(exc)) from None
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            if "apify" not in selected or not args.apify_input:
                raise ServiceError("run-apify에는 선택된 apify와 --apify-input이 필요합니다.")
            from runtime_connect import RuntimeConnectError, run_apify
            try:
                result = run_apify(data, args.home, args.apify_input,
                                   confirm=args.confirm_paid_run)
            except RuntimeConnectError as exc:
                raise ServiceError(str(exc)) from None
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ServiceError, OSError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
