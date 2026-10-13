#!/usr/bin/env python3
"""Apply reviewed Hermes 0.21.7 runtime settings without embedding secrets.

The authoritative shapes come from the pinned v0.21.7 ``cli-config.yaml.example``:
``stt.provider``/``stt.groq`` and ``mcp_servers.<name>.url/headers``.  Updates
are additive and ownership-tracked; an unknown user value is never replaced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import yaml


SCHEMA = "hermes_outbound_runtime/v1"
STATE = ".outbound-runtime-state.json"
CONNECTORS = "outbound-connectors.json"
COMPOSIO_URL = "https://connect.composio.dev/mcp"
APIFY_RUN = "https://api.apify.com/v2/acts/{actor}/runs"
WEBSHARE_PROXIES = "https://proxy.webshare.io/api/v2/proxy/list/?page=1&page_size=1"
MAX_FETCH_BYTES = 5 * 1024 * 1024
MISSING = {"__hermes_outbound_missing__": True}


class RuntimeConnectError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an Apify bearer to a redirect target."""
    def redirect_request(self, *args, **kwargs):
        return None


def _safe_home(home) -> Path:
    root = Path(home).expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise RuntimeConnectError("런타임 설정 경로의 심볼릭 링크는 허용하지 않습니다.")
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(root, 0o700)
    return root


def _atomic(path: Path, text: str, mode=0o600) -> None:
    if path.is_symlink():
        raise RuntimeConnectError(f"심볼릭 링크를 덮어쓰지 않습니다: {path.name}")
    fd, staged = tempfile.mkstemp(prefix=".outbound-runtime-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, mode)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


def _atomic_bytes(path: Path, raw: bytes, mode=0o600) -> None:
    if path.is_symlink():
        raise RuntimeConnectError(f"심볼릭 링크를 덮어쓰지 않습니다: {path.name}")
    fd, staged = tempfile.mkstemp(prefix=".outbound-fetch-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.chmod(staged, mode)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise RuntimeConnectError("config.yaml을 안전하게 읽을 수 없습니다.")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError:
        raise RuntimeConnectError("기존 config.yaml 형식을 읽을 수 없어 보존했습니다.") from None
    if not isinstance(value, dict):
        raise RuntimeConnectError("config.yaml 최상위는 객체여야 합니다.")
    return value


def _get(document: dict, dotted: str):
    node = document
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    return node


def _set(document: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = document
    for part in parts[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            raise RuntimeConnectError(f"기존 설정과 충돌합니다: {dotted}")
        node = child
    node[parts[-1]] = value


def _desired(data: dict) -> tuple[dict, dict, list[dict]]:
    selected = data.get("services", [])
    yaml_updates, connectors, rows = {}, {}, []
    if "groq" in selected:
        if data.get("groq_audio_consent") is not True:
            raise RuntimeConnectError("Groq STT 적용 전 오디오 외부 전송 동의가 필요합니다.")
        yaml_updates.update({
            "stt.enabled": True,
            "stt.provider": "groq",
            "stt.groq.model": "whisper-large-v3-turbo",
        })
        rows.append({"service": "groq", "runtime_configured": True,
                     "functional_verified": False, "next_action": "synthetic audio transcription"})
    if "composio" in selected:
        if data.get("composio_scope_ack") is not True:
            raise RuntimeConnectError("Composio 최소권한 범위 검토 확인이 필요합니다.")
        yaml_updates["mcp_servers.composio"] = {
            "url": COMPOSIO_URL,
            "headers": {"x-consumer-api-key": "${COMPOSIO_CONSUMER_KEY}"},
            # Hermes 0.21.7 strips configured credentials from cross-origin
            # redirects only when this fail-closed option is enabled.
            "strict_redirect_headers": True,
            "enabled": True,
        }
        rows.append({"service": "composio", "runtime_configured": True,
                     "functional_verified": False, "next_action": "restart, OAuth and read-only tool call"})
    if "webshare" in selected:
        raw = str(data.get("webshare_allowed_target") or "").strip()
        try:
            parsed = urllib.parse.urlsplit(raw)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                    or parsed.port not in (None, 443)):
                raise ValueError
        except ValueError:
            raise RuntimeConnectError("Webshare에는 허용된 단일 HTTPS 대상 URL이 필요합니다.") from None
        origin = f"https://{parsed.hostname}" + (f":{parsed.port}" if parsed.port not in (None, 443) else "")
        connectors["webshare"] = {"allowed_origin": origin, "key_env": "WEBSHARE_API_KEY",
                                   "policy": "source_scoped_no_access_bypass"}
        rows.append({"service": "webshare", "runtime_configured": True,
                     "component": "runtime_connect.webshare_fetch",
                     "functional_verified": False,
                     "next_action": "run one reviewed proxy-fetch on the exact allowed origin"})
    if "apify" in selected:
        actor = str(data.get("apify_actor_name") or "").strip()
        budget = str(data.get("apify_budget_usd") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}(?:[~/][A-Za-z0-9_-]{1,80})?", actor):
            raise RuntimeConnectError("Apify Actor ID 또는 owner/Actor 이름이 필요합니다.")
        if data.get("apify_cost_ack") is not True or not re.fullmatch(r"\d{1,6}(?:\.\d{1,2})?", budget):
            raise RuntimeConnectError("Apify 비용 확인과 USD 예산 상한이 필요합니다.")
        connectors["apify"] = {"actor": actor, "budget_usd": budget,
                                "token_env": "APIFY_TOKEN", "automatic_runs": False}
        rows.append({"service": "apify", "runtime_configured": True,
                     "functional_verified": False, "next_action": "review Actor input then explicit manual run"})
    return yaml_updates, connectors, rows


def apply_services(data: dict, home) -> dict:
    from services import env_lock
    root = _safe_home(home)
    updates, connectors, rows = _desired(data)
    config_path, state_path, connector_path = root / "config.yaml", root / STATE, root / CONNECTORS
    with env_lock(root):
        config = _read_yaml(config_path)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"schema_version": SCHEMA, "owned": {}}
        except (OSError, ValueError):
            raise RuntimeConnectError("기존 runtime ownership 영수증을 보존했습니다.") from None
        if state.get("schema_version") != SCHEMA or not isinstance(state.get("owned"), dict):
            raise RuntimeConnectError("알 수 없는 runtime ownership 영수증을 보존했습니다.")
        owned = state["owned"]
        for dotted, desired in updates.items():
            current = _get(config, dotted)
            prior = owned.get(dotted)
            if current != MISSING and current != desired and not (isinstance(prior, dict) and current == prior.get("applied")):
                raise RuntimeConnectError(f"사용자 설정을 보존했습니다. 충돌: {dotted}")
            if dotted not in owned:
                owned[dotted] = {"before": current, "applied": desired}
            else:
                owned[dotted]["applied"] = desired
            _set(config, dotted, desired)
        connector_rendered = None
        if connectors:
            previous = {}
            if connector_path.exists():
                try:
                    previous = json.loads(connector_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise RuntimeConnectError("기존 connector 설정을 보존했습니다.") from None
                if previous.get("managed_by") != "hermes-outbound-kit":
                    raise RuntimeConnectError("사용자 connector 설정을 덮어쓰지 않았습니다.")
            merged = dict(previous.get("connectors") or {})
            for name, desired in connectors.items():
                dotted = "connectors." + name
                current = merged.get(name, MISSING)
                prior = owned.get(dotted)
                if (current != MISSING and current != desired
                        and not (isinstance(prior, dict) and current == prior.get("applied"))):
                    raise RuntimeConnectError(f"사용자 connector 설정을 보존했습니다. 충돌: {name}")
                if dotted not in owned:
                    owned[dotted] = {"before": current, "applied": desired}
                else:
                    owned[dotted]["applied"] = desired
                merged[name] = desired
            payload = {"schema_version": 1, "managed_by": "hermes-outbound-kit", "connectors": merged}
            connector_rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        config_rendered = yaml.safe_dump(config, allow_unicode=True, sort_keys=False) if updates else None
        # Multi-file replacement is made failure-atomic by restoring only the
        # files written by this transaction.  The interprocess lock prevents a
        # second kit process from racing those snapshots.
        targets = []
        if connector_rendered is not None:
            targets.append((connector_path, connector_rendered))
        if config_rendered is not None:
            targets.append((config_path, config_rendered))
        predicted_config = (config_rendered.encode() if config_rendered is not None
                            else (config_path.read_bytes() if config_path.exists() else b""))
        state["config_sha256"] = hashlib.sha256(predicted_config).hexdigest()
        targets.append((state_path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"))
        snapshots = {path: path.read_text(encoding="utf-8") if path.exists() else None
                     for path, _text in targets}
        written = []
        try:
            for path, text in targets:
                _atomic(path, text); written.append(path)
        except Exception:
            for path in reversed(written):
                before = snapshots[path]
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic(path, before)
            raise
    return {"status": "applied_restart_required", "rows": rows,
            "config": str(config_path), "connectors": str(connector_path) if connectors else None}


def check_services(data: dict, home) -> dict:
    root = _safe_home(home)
    updates, connectors, rows = _desired(data)
    config = _read_yaml(root / "config.yaml")
    yaml_ok = all(_get(config, key) == value for key, value in updates.items())
    connector_ok = not connectors
    try:
        saved = json.loads((root / CONNECTORS).read_text(encoding="utf-8"))
        connector_ok = all((saved.get("connectors") or {}).get(key) == value for key, value in connectors.items())
    except (OSError, ValueError):
        pass
    return {"status": "configured_restart_unverified" if yaml_ok and connector_ok else "not_applied",
            "yaml_configured": yaml_ok, "connector_contracts_configured": connector_ok,
            "functional_verified": False, "rows": rows}


def run_apify(data: dict, home, input_path, *, confirm=False, opener=None) -> dict:
    if not confirm:
        raise RuntimeConnectError("유료 가능 Actor 실행에는 --confirm-paid-run이 필요합니다.")
    check = check_services(data, home)
    if not check["connector_contracts_configured"]:
        raise RuntimeConnectError("먼저 Apify runtime contract를 apply하세요.")
    root = _safe_home(home)
    try:
        bindings = {}
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1); bindings[key.strip()] = value
        token = bindings["APIFY_TOKEN"]
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError):
        raise RuntimeConnectError("Apify token과 검토 완료된 JSON input이 필요합니다.") from None
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 256 * 1024:
        raise RuntimeConnectError("Apify input은 256KiB 이하 JSON 객체여야 합니다.")
    # Apify accepts either an opaque Actor id or the canonical owner~Actor
    # notation.  The workshop form also accepts owner/Actor for readability.
    actor = urllib.parse.quote(str(data["apify_actor_name"]).replace("/", "~"), safe="~")
    budget = urllib.parse.quote(str(data["apify_budget_usd"]), safe="")
    url = APIFY_RUN.format(actor=actor) + "?maxTotalChargeUsd=" + budget
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        safe_opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        with safe_opener.open(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise RuntimeConnectError("Apify 실행 응답 크기 제한을 넘었습니다.")
            body = json.loads(raw)
    except RuntimeConnectError:
        raise
    except Exception:
        raise RuntimeConnectError("Apify 수동 실행 요청이 실패했습니다. 키·Actor·예산을 확인하세요.") from None
    run = body.get("data") if isinstance(body, dict) else None
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise RuntimeConnectError("Apify 실행 응답 형식이 예상과 다릅니다.")
    return {"status": "submitted_not_completed", "run_id": run["id"],
            "functional_verified": False, "next_action": "inspect run status, cost and dataset output"}


def _env_secret(root: Path, name: str) -> str:
    try:
        matches = []
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() == name:
                    matches.append(value)
    except OSError:
        matches = []
    if len(matches) != 1 or not matches[0] or any(ord(ch) < 32 for ch in matches[0]):
        raise RuntimeConnectError(f"로컬 {name} 바인딩 하나가 필요합니다.")
    return matches[0]


def _https_origin(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise RuntimeConnectError("허용 대상 URL 형식이 잘못되었습니다.") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or port not in (None, 443) or len(url) > 4096
            or any(ord(ch) < 33 for ch in url)):
        raise RuntimeConnectError("허용된 HTTPS origin의 URL만 가져올 수 있습니다.")
    return "https://" + parsed.hostname.lower()


def _proxy_url(row: dict) -> str:
    """Validate one direct Webshare proxy record and return its private URI."""
    host = str(row.get("proxy_address") or "")
    username, password = str(row.get("username") or ""), str(row.get("password") or "")
    try:
        port = int(row.get("port"))
    except (TypeError, ValueError):
        port = 0
    if (not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) or not 1 <= port <= 65535
            or not username or not password or len(username) > 512 or len(password) > 2048
            or any(ord(ch) < 33 for ch in username + password)):
        raise RuntimeConnectError("Webshare 프록시 응답 형식이 예상과 다릅니다.")
    auth = urllib.parse.quote(username, safe="") + ":" + urllib.parse.quote(password, safe="")
    return f"http://{auth}@{host}:{port}"


def webshare_fetch(data: dict, home, url: str, output, *, api_opener=None,
                   proxy_opener_factory=None) -> dict:
    """Fetch one allowlisted HTTPS resource through one selected Webshare proxy.

    A 403 or 429 is terminal.  This function never rotates proxies, retries a
    denial, follows redirects, or changes the requested target.
    """
    if "webshare" not in data.get("services", []):
        raise RuntimeConnectError("Webshare가 선택된 setup.json이 필요합니다.")
    root = _safe_home(home)
    configured = check_services(data, root)
    if not configured["connector_contracts_configured"]:
        raise RuntimeConnectError("먼저 Webshare connector contract를 apply하세요.")
    try:
        contract = json.loads((root / CONNECTORS).read_text(encoding="utf-8"))
        allowed = contract["connectors"]["webshare"]["allowed_origin"]
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeConnectError("Webshare 허용 origin contract를 읽지 못했습니다.") from None
    if _https_origin(url) != allowed:
        raise RuntimeConnectError("요청 URL이 Webshare에 승인된 exact HTTPS origin과 다릅니다.")
    key = _env_secret(root, "WEBSHARE_API_KEY")
    api_request = urllib.request.Request(
        WEBSHARE_PROXIES, headers={"Authorization": "Token " + key, "Accept": "application/json"})
    try:
        provider_opener = api_opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        with provider_opener.open(api_request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RuntimeConnectError("Webshare 프록시 목록 응답이 너무 큽니다.")
        envelope = json.loads(raw)
        rows = envelope.get("results") if isinstance(envelope, dict) else None
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise RuntimeConnectError("사용 가능한 Webshare 프록시 한 개를 찾지 못했습니다.")
        proxy = _proxy_url(rows[0])
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        if code in (403, 429):
            raise RuntimeConnectError(f"Webshare HTTP {code}: 중단했습니다. 회전·재시도·우회하지 않습니다.") from None
        raise RuntimeConnectError("Webshare 프록시 선택 요청이 실패했습니다.") from None
    except RuntimeConnectError:
        raise
    except Exception:
        raise RuntimeConnectError("Webshare 프록시 선택 요청이 실패했습니다.") from None

    target_request = urllib.request.Request(
        url, headers={"User-Agent": "Hermes-Outbound-Kit/0.1", "Accept": "*/*"})
    try:
        fetcher = (proxy_opener_factory(proxy) if proxy_opener_factory else
                   urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy}), _NoRedirect()))
        with fetcher.open(target_request, timeout=30) as response:
            body = response.read(MAX_FETCH_BYTES + 1)
        if len(body) > MAX_FETCH_BYTES:
            raise RuntimeConnectError("대상 응답이 5MiB 제한을 넘었습니다.")
    except urllib.error.HTTPError as exc:
        code = exc.code; exc.close()
        if code in (403, 429):
            raise RuntimeConnectError(f"대상 HTTP {code}: 중단했습니다. 프록시 회전·재시도·우회하지 않습니다.") from None
        if 300 <= code < 400:
            raise RuntimeConnectError("대상 redirect를 거부했습니다. 허용 origin을 다시 검토하세요.") from None
        raise RuntimeConnectError(f"대상 요청이 HTTP {code}로 실패했습니다.") from None
    except RuntimeConnectError:
        raise
    except Exception:
        raise RuntimeConnectError("Webshare 대상 요청이 실패했습니다. 키나 proxy 비밀값은 표시하지 않습니다.") from None
    destination = Path(output).expanduser().absolute()
    if any(path.is_symlink() for path in (destination, *destination.parents)):
        raise RuntimeConnectError("출력 경로의 심볼릭 링크는 허용하지 않습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_bytes(destination, body)
    return {"status": "fetched", "allowed_origin": allowed,
            "url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(), "output": str(destination),
            "bytes": len(body), "proxy_rotated": False, "access_bypass": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Outbound reviewed runtime connectors")
    parser.add_argument("action", choices=("proxy-fetch",))
    parser.add_argument("--config", default="setup.json")
    parser.add_argument("--home", default=str(Path.home() / ".hermes-outbound"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        from services import load_config
        result = webshare_fetch(load_config(args.config), args.home, args.url, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
