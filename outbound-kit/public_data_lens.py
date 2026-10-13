#!/usr/bin/env python3
"""Safe optional Hermes 0.21.7 connector for the public Public Data Lens MCP.

This configures catalog discovery only.  It never submits a private query during
setup and it does not represent a G2B order plan or tender-notice collector.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request

import yaml


ENDPOINT = "https://service.datahub.kr/projects/public-data-lens/mcp"
SERVER_NAME = "public-data-lens"
STATE = ".public-data-lens-state.json"
SCHEMA = "hermes_outbound_public_data_lens/v1"
MAX_RESPONSE = 2 * 1024 * 1024
TOOLS = (
    "search_datasets", "get_dataset", "compare_datasets", "get_catalog_changes",
    "get_catalog_stats", "search_by_columns", "get_dataset_structure",
    "build_data_plan", "get_context",
)
DESIRED = {
    "url": ENDPOINT,
    "headers": {"X-Datanav-No-Log": "1"},
    "strict_redirect_headers": True,
    "enabled": True,
    "tools": {"include": list(TOOLS)},
    "connect_timeout": 30,
    "timeout": 120,
}


class PublicDataLensError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _safe_home(home, *, create: bool) -> Path:
    root = Path(home).expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise PublicDataLensError("설정 경로의 심볼릭 링크는 허용하지 않습니다.")
    if create:
        root.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(root, 0o700)
    return root


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise PublicDataLensError("기존 config.yaml을 안전하게 읽을 수 없습니다.")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError):
        raise PublicDataLensError("기존 config.yaml 형식을 보존했습니다.") from None
    if not isinstance(value, dict):
        raise PublicDataLensError("config.yaml 최상위는 객체여야 합니다.")
    return value


def _atomic(path: Path, text: str) -> None:
    if path.is_symlink():
        raise PublicDataLensError("설정 심볼릭 링크를 덮어쓰지 않습니다.")
    fd, staged = tempfile.mkstemp(prefix=".public-data-lens-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.chmod(staged, 0o600)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


@contextmanager
def _config_lock(root: Path):
    """Serialize read/merge/replace so a parallel installer cannot lose an update."""
    path = root / ".public-data-lens.lock"
    if path.is_symlink():
        raise PublicDataLensError("설정 잠금 파일의 심볼릭 링크를 거부했습니다.")
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0"); stream.flush()
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


def plan(home) -> dict:
    root = _safe_home(home, create=False)
    return {
        "status": "plan_only", "hermes_home": str(root), "server": SERVER_NAME,
        "endpoint": ENDPOINT, "authentication": "none", "no_log_header": True,
        "tools": list(TOOLS), "scope": "catalog_discovery_not_procurement_notices",
        "mutations": ["config.yaml mcp_servers.public-data-lens", STATE,
                      ".public-data-lens.lock"],
    }


def apply(home) -> dict:
    """Add the fixed no-log MCP entry without replacing user-owned config."""
    root = _safe_home(home, create=True)
    with _config_lock(root):
        return _apply_locked(root)


def _apply_locked(root: Path) -> dict:
    config_path, state_path = root / "config.yaml", root / STATE
    config = _read_yaml(config_path)
    servers = config.get("mcp_servers")
    if servers is None:
        servers = {}; config["mcp_servers"] = servers
    if not isinstance(servers, dict):
        raise PublicDataLensError("기존 mcp_servers가 객체가 아니어서 보존했습니다.")
    current = servers.get(SERVER_NAME)
    previous_state = {}
    if state_path.exists():
        try:
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PublicDataLensError("기존 Public Data Lens 영수증을 보존했습니다.") from None
    if previous_state and previous_state.get("schema_version") != SCHEMA:
        raise PublicDataLensError("알 수 없는 Public Data Lens 영수증을 보존했습니다.")
    owned = previous_state.get("applied") == current == DESIRED
    if current is not None and current != DESIRED and not owned:
        raise PublicDataLensError("기존 mcp_servers.public-data-lens 설정을 덮어쓰지 않았습니다.")
    servers[SERVER_NAME] = DESIRED
    rendered = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    state = {
        "schema_version": SCHEMA, "endpoint": ENDPOINT, "applied": DESIRED,
        "config_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "network_probed": False, "catalog_discovery_only": True,
    }
    before_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    before_state = state_path.read_text(encoding="utf-8") if state_path.exists() else None
    written = []
    try:
        _atomic(config_path, rendered); written.append(config_path)
        _atomic(state_path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except Exception:
        for path, before in ((config_path, before_config), (state_path, before_state)):
            if path in written:
                if before is None: path.unlink(missing_ok=True)
                else: _atomic(path, before)
        raise
    return {"status": "applied_restart_required", "server": SERVER_NAME,
            "no_log_header": True, "functional_verified": False,
            "scope": "catalog_discovery_not_procurement_notices"}


def check(home) -> dict:
    root = _safe_home(home, create=False)
    config = _read_yaml(root / "config.yaml")
    configured = (config.get("mcp_servers") or {}).get(SERVER_NAME) == DESIRED \
        if isinstance(config.get("mcp_servers") or {}, dict) else False
    try:
        state = json.loads((root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    return {"status": "configured_restart_unverified" if configured else "not_applied",
            "configured": configured, "receipt_valid": state.get("schema_version") == SCHEMA,
            "no_log_header": configured, "network_probed": False,
            "functional_verified": False,
            "scope": "catalog_discovery_not_procurement_notices"}


def _post(payload: dict, *, opener, session=None, protocol=None, notification=False):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "X-Datanav-No-Log": "1"}
    if session:
        headers["Mcp-Session-Id"] = session
    if protocol:
        headers["MCP-Protocol-Version"] = protocol
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE + 1)
            response_session = response.headers.get("Mcp-Session-Id")
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        if 300 <= code < 400:
            raise PublicDataLensError("Public Data Lens redirect를 거부했습니다.") from None
        raise PublicDataLensError(f"Public Data Lens MCP가 HTTP {code}를 반환했습니다.") from None
    except Exception:
        raise PublicDataLensError("Public Data Lens MCP 연결에 실패했습니다.") from None
    if len(raw) > MAX_RESPONSE:
        raise PublicDataLensError("Public Data Lens MCP 응답이 2MiB 제한을 넘었습니다.")
    if (response_session is not None
            and not re.fullmatch(r"[\x21-\x7e]{1,1024}", response_session)):
        raise PublicDataLensError("Public Data Lens MCP session ID 형식이 잘못되었습니다.")
    if notification and not raw:
        return {}, response_session
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise PublicDataLensError("Public Data Lens MCP 응답이 JSON이 아닙니다.") from None
    if not isinstance(body, dict):
        raise PublicDataLensError("Public Data Lens MCP 응답 형식이 잘못되었습니다.")
    return body, response_session


def probe(*, opener=None) -> dict:
    """Perform only MCP initialization and tools/list; never send a search query."""
    transport = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    initialized, session = _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "hermes-outbound-kit", "version": "0.1"}}},
        opener=transport)
    try:
        result = initialized["result"]
        protocol = result["protocolVersion"]
        if not isinstance(protocol, str) or not re.fullmatch(r"20\d\d-\d\d-\d\d", protocol):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise PublicDataLensError("Public Data Lens MCP initialize 응답이 잘못되었습니다.") from None
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, opener=transport,
          session=session, protocol=protocol, notification=True)
    listed, _ = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                      opener=transport, session=session, protocol=protocol)
    try:
        tools = listed["result"]["tools"]
        by_name = {row["name"]: row for row in tools
                   if isinstance(row, dict) and isinstance(row.get("name"), str)}
        names = set(by_name)
    except (KeyError, TypeError):
        raise PublicDataLensError("Public Data Lens MCP tools/list 응답이 잘못되었습니다.") from None
    missing = sorted(set(TOOLS) - names)
    if missing:
        raise PublicDataLensError("Public Data Lens 필수 read-only tool이 없습니다: " + ", ".join(missing))
    unsafe = []
    for name in TOOLS:
        annotations = by_name[name].get("annotations")
        if (not isinstance(annotations, dict)
                or annotations.get("readOnlyHint") is not True
                or annotations.get("destructiveHint") is not False):
            unsafe.append(name)
    if unsafe:
        raise PublicDataLensError("read-only annotation을 확인할 수 없습니다: " + ", ".join(unsafe))
    return {"status": "mcp_discovery_verified", "no_log_header_sent": True,
            "tools_verified": sorted(set(TOOLS)), "query_sent": False,
            "readonly_annotations_verified": True,
            "procurement_notice_verified": False, "functional_verified": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Optional Public Data Lens catalog-discovery MCP")
    parser.add_argument("action", choices=("plan", "apply", "check", "probe"))
    parser.add_argument("--home", default=str(Path.home() / ".hermes-outbound"))
    args = parser.parse_args(argv)
    try:
        result = {"plan": plan, "apply": apply, "check": check}.get(args.action, lambda _home: probe())(args.home)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
