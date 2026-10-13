#!/usr/bin/env python3
"""Optional local-Docker OmniRoute deployment and OMH/Hermes connector.

The deployment portion is independently derived from the public MIT-licensed
``Wendy-Nam/hermes-kit`` donor named in ``docs/OMNIROUTE.md``.  Provider
credentials stay in OmniRoute's private dashboard; this module accepts only its
local dashboard password and the installation-owned inference key it creates.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import yaml


IMAGE = ("ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-3@"
         "sha256:1572375ba665cad6b46273257f2746834421191ee201cf5cb14b28e4a1cfc979")
OMH_REPOSITORY = "https://github.com/rlaope/oh-my-hermes"
OMH_COMMIT = "b84f096e59d50fc933ed4b43fd36675e8cff593a"
OMH_VERSION = "2.0.5"
OMH_ARCHIVE_SHA256 = "3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a"
OMH_PLUGIN_HOOK_SHA256 = "a0382ed1cf9f78f0cf9202395c027cd29a01953a3b7983d2142747d764b60e3b"
PROJECT = "hermes-outbound-omniroute"
INSTALL_DIR = "omniroute"
STATE = "install-state.json"
CONNECT_STATE = "connection-state.json"
CONFIG_BACKUP = ".omniroute-config.backup.yaml"
PROVIDER = "kit-omniroute"
KEY_ENV = "KIT_OMNIROUTE_API_KEY"
COMBO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,159}$")

# Exact public defaults from OMH 2.0.5 at OMH_COMMIT. This table contains no
# personal routes. An adapter may omit unavailable aliases; it never substitutes
# a different model family or version silently.
RECOMMENDED_CHAINS = {
    "ultrabrain": (("gpt-6-astra", "xhigh"),),
    "deep": (("gpt-5.6-terra", "high"), ("deepseek-flash", "high")),
    "architect": (("claude-fable-5-1", "xhigh"), ("gpt-6-astra", "xhigh"),
                  ("kimi-k3", "xhigh")),
    "unspecified-high": (("kimi-k3", "medium"), ("claude-opus-5", "medium")),
    "unspecified-low": (("glm-5.3", "low"), ("deepseek-flash", "low"),
                        ("claude-opus-5", "low")),
    "quick": (("glm-5.3-flash", "low"), ("kimi-k3", "low"),
              ("gpt-5.6-luna", "low"), ("claude-fable-5-1", "low")),
    "writing": (("kimi-k3", "medium"), ("qwen3-coder", "medium"),
                ("gemini-3.1-pro", "medium")),
    "visual-engineering": (("claude-fable-5-1", "high"), ("kimi-k3", "high")),
    "artistry": (("gemini-3.1-pro", "high"), ("claude-fable-5-1", "high"),
                ("kimi-k3", "high")),
    "capable": (("claude-fable-5-1", "medium"), ("claude-opus-5", "medium"),
                ("kimi-k3", "medium"), ("glm-5.3", "medium")),
    "simple-work": (("gpt-5.6-luna", "low"), ("deepseek-flash", "low"),
                    ("claude-haiku-4-5", "low")),
    "deep-work": (("gpt-6-astra", "high"),),
}


class OmniRouteError(ValueError):
    pass


class OmniClient:
    """Fixed-loopback management/inference client; never accepts a caller URL."""
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            _NoRedirect())

    def request(self, method, path, body=None, key=None, timeout=100):
        if not isinstance(path, str) or not path.startswith("/") or "//" in path:
            raise OmniRouteError("OmniRoute API 경로를 거부했습니다.")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        req = urllib.request.Request("http://127.0.0.1:20128" + path, method=method,
                                     headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise OmniRouteError("OmniRoute 응답 크기 제한을 넘었습니다.")
            value = json.loads(raw or b"{}")
            if not isinstance(value, dict):
                raise ValueError
            return value, dict(getattr(response, "headers", {}))
        except urllib.error.HTTPError as exc:
            exc.close()
            raise OmniRouteError(f"OmniRoute 요청 실패 (HTTP {exc.code})") from None
        except OmniRouteError:
            raise
        except Exception:
            raise OmniRouteError("OmniRoute 연결 또는 응답 확인에 실패했습니다.") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def load_config(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or type(data.get("omniroute_enabled", False)) is not bool:
        raise OmniRouteError("omniroute_enabled는 true/false여야 합니다.")
    return data


def route_documents(bindings: dict[str, str]) -> dict:
    """Build strict OMH documents from tested alias -> OmniRoute combo bindings.

    This is deliberately offline. The caller must supply only combos that already
    passed a real two-turn tool test. Missing aliases are omitted and reported.
    """
    if not isinstance(bindings, dict):
        raise OmniRouteError("bindings는 모델 별칭과 검증된 콤보의 객체여야 합니다.")
    known = {alias for chain in RECOMMENDED_CHAINS.values() for alias, _ in chain}
    if set(bindings) - known:
        raise OmniRouteError("OMH 2.0.5 권장표에 없는 모델 별칭이 있습니다.")
    if any(not isinstance(value, str) or not COMBO.fullmatch(value) for value in bindings.values()):
        raise OmniRouteError("OmniRoute 콤보 ID 형식이 잘못되었습니다.")

    models = {alias: {"provider": PROVIDER, "model": combo}
              for alias, combo in sorted(bindings.items())}
    categories: dict[str, list[dict[str, str]]] = {}
    missing: dict[str, list[str]] = {}
    for category, chain in RECOMMENDED_CHAINS.items():
        available = [{"model": alias, "reasoning_effort": effort}
                     for alias, effort in chain if alias in bindings]
        absent = [alias for alias, _ in chain if alias not in bindings]
        if available:
            categories[category] = available
        if absent:
            missing[category] = absent
    return {
        "providers": {"schema_version": "model_provider_routes/v1", "models": models},
        "chains": {"schema_version": "mixture_chain_overrides/v1", "categories": categories},
        "coverage": {
            "categories_ready": sorted(categories),
            "categories_blocked": sorted(set(RECOMMENDED_CHAINS) - set(categories)),
            "missing_aliases": missing,
            "claim": "mapping_only_not_applied_or_tool_tested",
        },
    }


MODEL_ROUTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,60}/[A-Za-z0-9][A-Za-z0-9._:/@-]{0,160}$")


def _items(client: OmniClient, path: str, key: str) -> list[dict]:
    value, _ = client.request("GET", path)
    rows = value.get(key)
    if not isinstance(rows, list) or value.get("total", len(rows)) > len(rows):
        raise OmniRouteError("OmniRoute 목록이 완전하지 않거나 형식이 다릅니다.")
    return rows


def _identifier(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise OmniRouteError("OmniRoute 객체 ID 형식이 잘못되었습니다.")
    return value


def parse_models(text: str) -> list[str]:
    rows = [item.strip() for item in (text or "").replace("\n", ",").split(",") if item.strip()]
    if not 1 <= len(rows) <= 5 or len(rows) != len(set(rows)) or any(not MODEL_ROUTE.fullmatch(row) for row in rows):
        raise OmniRouteError('모델은 "연결접두사/모델" 형식으로 1~5개 입력하세요.')
    return rows


def _connections(client: OmniClient) -> dict[str, dict]:
    found = {}
    for row in sorted(_items(client, "/api/providers", "connections"),
                      key=lambda item: item.get("priority") or 99):
        provider = str(row.get("provider") or "")
        name = str(row.get("name") or "")
        if (not row.get("isActive") or name.startswith("hermes-outbound-")
                or provider.endswith("-web") or provider == "lmarena"):
            continue
        prefix = str((row.get("providerSpecificData") or {}).get("prefix") or provider)
        if prefix:
            found.setdefault(prefix, row)
    return found


def discover_models(password: str, *, client=None, limit=25) -> list[dict]:
    client = client or OmniClient()
    client.request("POST", "/api/auth/login", {"password": password})
    result = []
    for prefix, connection in _connections(client).items():
        cid = _identifier(connection.get("id"))
        body, _ = client.request("GET", f"/api/providers/{cid}/models")
        for row in body.get("models") or []:
            model = str(row.get("id") or "")
            route = f"{prefix}/{model}"
            if MODEL_ROUTE.fullmatch(route) and not re.search(
                    r"embed|tts|whisper|transcri|rerank|image|moderation|speech|audio", model, re.I):
                result.append({"route": route, "connection_id": cid,
                               "label": str(row.get("name") or model)[:120]})
                if len(result) >= limit:
                    return result
    return result


def _steps(routes: list[str], connections: dict[str, dict]) -> list[dict]:
    result = []
    for route in routes:
        prefix, model = route.split("/", 1)
        connection = connections.get(prefix)
        if not connection:
            raise OmniRouteError("연결되지 않은 모델 경로입니다: " + route)
        result.append({"provider": connection["provider"], "model": model,
                       "connectionId": _identifier(connection.get("id")), "route": route})
    return result


def _two_turn_probe(client: OmniClient, model: str, key: str, connection_id: str) -> None:
    tool = {"type": "function", "function": {"name": "kit_echo",
            "description": "Return the supplied value.", "parameters": {"type": "object",
            "properties": {"value": {"type": "string"}}, "required": ["value"],
            "additionalProperties": False}}}
    messages = [{"role": "user", "content":
                 "Call kit_echo with value KIT_READY. After the tool result reply exactly KIT_READY."}]
    first, headers = client.request("POST", "/v1/chat/completions", {
        "model": model, "messages": messages, "tools": [tool],
        "tool_choice": {"type": "function", "function": {"name": "kit_echo"}},
        "max_tokens": 512, "stream": False}, key=key)
    try:
        message = first["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        call = calls[0]
        arguments = json.loads(call["function"]["arguments"])
        if (len(calls) != 1 or call["function"]["name"] != "kit_echo"
                or arguments != {"value": "KIT_READY"} or not call.get("id")):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise OmniRouteError("모델 도구 호출 1단계가 실패했습니다: " + model) from None
    selected = next((value for name, value in headers.items()
                     if name.lower() == "x-omniroute-selected-connection-id"), None)
    if selected is not None and selected != connection_id:
        raise OmniRouteError("요청 모델과 실제 OmniRoute 연결이 다릅니다.")
    messages += [message, {"role": "tool", "tool_call_id": call["id"], "content": "KIT_READY"}]
    second, _ = client.request("POST", "/v1/chat/completions", {
        "model": model, "messages": messages, "tools": [tool], "tool_choice": "none",
        "max_tokens": 512, "stream": False}, key=key)
    try:
        final = second["choices"][0]["message"]
        if final.get("tool_calls") or final.get("content", "").strip() != "KIT_READY":
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise OmniRouteError("모델 도구 결과 2단계가 실패했습니다: " + model) from None


def _create_combo(client, name: str, steps: list[dict]) -> str:
    body = {"name": name, "strategy": "priority", "description": "hermes-outbound-kit owned",
            "models": [{key: value for key, value in step.items() if key != "route"} for step in steps]}
    created, _ = client.request("POST", "/api/combos", body)
    return _identifier((created.get("combo") or created).get("id"))


def _connection_state_path(home) -> Path:
    return _safe_home(home) / INSTALL_DIR / CONNECT_STATE


def _set_owned_key(home: Path, value: str, *, replacing: bool) -> str | None:
    from services import env_lock
    path = home / ".env"
    with env_lock(home):
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        lines, found, previous_value, matches = [], False, None, 0
        for line in original.splitlines():
            if line.split("=", 1)[0].strip() == KEY_ENV:
                matches += 1
                if matches > 1:
                    raise OmniRouteError(f"중복 {KEY_ENV} 바인딩을 보존했습니다. 먼저 정리하세요.")
                if not replacing:
                    raise OmniRouteError(f"기존 {KEY_ENV} 소유권을 확인할 수 없습니다.")
                previous_value = line.split("=", 1)[1] if "=" in line else ""
                lines.append(KEY_ENV + "=" + value); found = True
            else:
                lines.append(line)
        if not found:
            lines.append(KEY_ENV + "=" + value)
        rendered = "\n".join(lines).rstrip("\n") + "\n"
        _atomic_replace(path, rendered, 0o600)
        return previous_value


def _restore_owned_key(home: Path, applied: str, previous: str | None) -> None:
    """Undo only our exact key value and preserve concurrent unrelated lines."""
    from services import env_lock
    path = home / ".env"
    with env_lock(home):
        if not path.exists():
            return
        lines, restored, found = [], False, False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.split("=", 1)[0].strip() == KEY_ENV:
                found = True
                current = line.split("=", 1)[1] if "=" in line else ""
                if current != applied:
                    raise OmniRouteError(f"{KEY_ENV}가 동시에 변경되어 자동 복원을 거부했습니다.")
                if previous is not None:
                    lines.append(KEY_ENV + "=" + previous)
                restored = True
            else:
                lines.append(line)
        if not found or not restored:
            return
        rendered = "\n".join(lines).rstrip("\n")
        if rendered:
            _atomic_replace(path, rendered + "\n", 0o600)
        else:
            path.unlink(missing_ok=True)


def connect_runtime(data: dict, home, password: str, chat_text: str, strong_text: str = "",
                    *, client=None) -> dict:
    if data.get("omniroute_enabled") is not True:
        raise OmniRouteError("OmniRoute를 선택한 설정이 필요합니다.")
    chat = parse_models(chat_text)
    strong = parse_models(strong_text) if strong_text.strip() else list(chat)
    if not password or any(char in password for char in "\r\n"):
        raise OmniRouteError("OmniRoute dashboard password가 필요합니다.")
    root = _safe_home(home)
    state_path = _connection_state_path(root)
    previous = {}
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (OSError, ValueError):
        raise OmniRouteError("기존 OmniRoute 연결 영수증을 보존했습니다.") from None
    if previous and previous.get("schema_version") != "hermes_outbound_omniroute_connection/v1":
        raise OmniRouteError("기존 OmniRoute 연결 영수증 형식을 보존했습니다.")
    if previous.get("local_applied") is True:
        raise OmniRouteError("새 모델로 다시 connect하기 전에 현재 OmniRoute 설정을 rollback하세요.")
    installation = previous.get("installation") or uuid.uuid4().hex
    client = client or OmniClient()
    created_ids = {"keys": [], "combos": []}
    local_key_written = False
    previous_key = None
    try:
        client.request("POST", "/api/auth/login", {"password": password})
        connections = _connections(client)
        chat_steps, strong_steps = _steps(chat, connections), _steps(strong, connections)
        allowed = sorted({step["connectionId"] for step in chat_steps + strong_steps})
        generation = uuid.uuid4().hex[:8]
        prefix = "hermes-outbound-" + installation[:12]
        created, _ = client.request("POST", "/api/keys", {
            "name": f"{prefix}-key-{generation}", "noLog": True,
            "allowedConnections": allowed})
        inference, key_id = created.get("key"), _identifier(created.get("id"))
        if not isinstance(inference, str) or not inference or any(char in inference for char in "\r\n"):
            raise OmniRouteError("OmniRoute 추론 키 응답이 잘못되었습니다.")
        created_ids["keys"].append(key_id)
        for step in {item["route"]: item for item in chat_steps + strong_steps}.values():
            _two_turn_probe(client, step["route"], inference, step["connectionId"])
        chat_name, strong_name = f"{prefix}-chat-{generation}", f"{prefix}-strong-{generation}"
        chat_id = _create_combo(client, chat_name, chat_steps); created_ids["combos"].append(chat_id)
        strong_id = _create_combo(client, strong_name, strong_steps); created_ids["combos"].append(strong_id)
        previous_key = _set_owned_key(root, inference, replacing=previous.get("key_owned") is True)
        local_key_written = True
        state = {"schema_version": "hermes_outbound_omniroute_connection/v1",
                 "installation": installation, "key_owned": True, "key_id": key_id,
                 "chat_combo": chat_name, "chat_combo_id": chat_id,
                 "strong_combo": strong_name, "strong_combo_id": strong_id,
                 "chat_models": chat, "strong_models": strong,
                 "connection_ids": allowed, "tool_probe": "two_turn_passed",
                 "local_applied": False, "restart_verified": False}
        _atomic_replace(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n", 0o600)
        return {"status": "connected_probed_not_applied", "chat_combo": chat_name,
                "strong_combo": strong_name, "models_tool_tested": True,
                "next_action": "apply with explicit OMH alias bindings"}
    except Exception:
        if local_key_written:
            _restore_owned_key(root, inference, previous_key)
        for kind in ("combos", "keys"):
            for object_id in reversed(created_ids[kind]):
                try: client.request("DELETE", f"/api/{kind}/{object_id}")
                except Exception: pass
        raise


def _load_connection_state(home) -> tuple[Path, dict]:
    path = _connection_state_path(home)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise OmniRouteError("connect 단계의 OmniRoute 영수증이 필요합니다.") from None
    if (state.get("schema_version") != "hermes_outbound_omniroute_connection/v1"
            or state.get("tool_probe") != "two_turn_passed"):
        raise OmniRouteError("도구 호출 검증이 완료된 OmniRoute 영수증이 필요합니다.")
    return path, state


def _load_yaml_config(path: Path) -> dict:
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except (OSError, yaml.YAMLError):
        raise OmniRouteError("Hermes config.yaml을 읽지 못해 보존했습니다.") from None
    if not isinstance(config, dict):
        raise OmniRouteError("Hermes config.yaml 최상위 형식이 잘못되었습니다.")
    return config


def _omh_compatible(root: Path) -> bool:
    try:
        components = json.loads((root / ".kit-components.json").read_text(encoding="utf-8"))
        receipt = (components.get("components") or {}).get("omh-upstream") or {}
    except (OSError, ValueError, AttributeError):
        return False
    return (
        (root / "plugins/omh").is_dir()
        and receipt.get("version") == OMH_VERSION
        and receipt.get("source_commit") == OMH_COMMIT
        and receipt.get("archive_sha256") == OMH_ARCHIVE_SHA256
        and receipt.get("plugin_hook_sha256") == OMH_PLUGIN_HOOK_SHA256
        and receipt.get("plugin_import_smoke") is True
        and receipt.get("plugin_register_smoke") is True
    )


def apply_runtime(data: dict, home, bindings: dict[str, str]) -> dict:
    """Apply only after connect probes; preserves a private rollback snapshot."""
    root = _safe_home(home)
    state_path, state = _load_connection_state(root)
    if not isinstance(bindings, dict) or any(value not in ("chat", "strong") for value in bindings.values()):
        raise OmniRouteError("bindings 값은 chat 또는 strong이어야 합니다.")
    translated = {alias: state[value + "_combo"] for alias, value in bindings.items()}
    routes = route_documents(translated)
    if routes["coverage"]["categories_blocked"]:
        raise OmniRouteError("모든 OMH category에 최소 한 모델 alias binding이 필요합니다.")
    config_path = root / "config.yaml"
    config = _load_yaml_config(config_path)
    providers = config.get("providers")
    if providers is None:
        providers = {}; config["providers"] = providers
    if not isinstance(providers, dict):
        raise OmniRouteError("Hermes providers 설정이 객체가 아니어서 자동 적용을 중단했습니다.")
    provider = providers.get(PROVIDER)
    desired_provider = {"base_url": "http://127.0.0.1:20128/v1", "key_env": KEY_ENV,
                        "api_mode": "chat_completions"}
    if provider and provider != desired_provider:
        raise OmniRouteError("동일 이름의 사용자 provider 설정을 보존했습니다.")
    providers[PROVIDER] = desired_provider
    delegation = config.get("delegation")
    if delegation is None:
        delegation = {}; config["delegation"] = delegation
    if not isinstance(delegation, dict):
        raise OmniRouteError("기존 delegation 설정 형식을 보존했습니다.")
    desired_delegation = {"provider": PROVIDER, "model": state["strong_combo"]}
    existing_route = {key: delegation.get(key) for key in ("provider", "model") if delegation.get(key)}
    prior_owned = (state.get("local_applied") is True
                   and delegation.get("provider") == PROVIDER
                   and delegation.get("model") in (state.get("strong_combo"),))
    if existing_route and existing_route != desired_delegation and not prior_owned:
        raise OmniRouteError("기존 delegation provider/model을 보존했습니다. 수동 병합이 필요합니다.")
    if not prior_owned and any(delegation.get(key) for key in ("base_url", "api_key")):
        raise OmniRouteError("기존 delegation endpoint/credential 설정을 보존했습니다. 수동 병합이 필요합니다.")
    delegation.update({"provider": PROVIDER, "model": state["strong_combo"]})
    delegation.pop("base_url", None); delegation.pop("api_key", None)
    main = config.get("model")
    if main is not None and not isinstance(main, dict):
        raise OmniRouteError("Hermes model 설정이 객체가 아니어서 자동 적용을 중단했습니다.")
    direct = None
    if isinstance(main, dict):
        provider_name, model_name = main.get("provider"), main.get("default")
        if provider_name not in (None, "", "auto", "default", PROVIDER) and model_name:
            direct = {"provider": provider_name, "model": model_name}
    if direct:
        existing_fallback = config.get("fallback_providers")
        if existing_fallback not in (None, [], [direct]):
            raise OmniRouteError("기존 main fallback chain을 보존했습니다. 수동 병합이 필요합니다.")
        config["model"] = {**main, "provider": PROVIDER, "default": state["chat_combo"]}
        config["model"].pop("base_url", None); config["model"].pop("api_mode", None)
        config["fallback_providers"] = [direct]
        main_switched = True
    else:
        main_switched = isinstance(main, dict) and main.get("provider") == PROVIDER

    routing = root / ".omh" / "routing"
    if not _omh_compatible(root):
        raise OmniRouteError("고정된 public OMH 2.0.5 설치 영수증과 plugin smoke를 먼저 확인하세요.")
    routing.mkdir(parents=True, exist_ok=True)
    targets = {config_path: yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
               routing / "model-providers.json": json.dumps(routes["providers"], indent=2, sort_keys=True) + "\n",
               routing / "model-chains.json": json.dumps(routes["chains"], indent=2, sort_keys=True) + "\n"}
    backups = {}
    for target in targets:
        if target.is_symlink():
            raise OmniRouteError("설정 대상 심볼릭 링크를 거부했습니다.")
        backups[str(target)] = target.read_text(encoding="utf-8") if target.exists() else None
    backup_path = root / INSTALL_DIR / CONFIG_BACKUP
    if backup_path.exists() and state.get("local_applied") is not True:
        raise OmniRouteError("알 수 없는 OmniRoute rollback snapshot을 보존했습니다.")
    created_backup = False
    if not backup_path.exists():
        _atomic_create(backup_path, json.dumps(backups, ensure_ascii=False) + "\n", 0o600)
        created_backup = True
    written = []
    try:
        for target, text in targets.items():
            _atomic_replace(target, text, 0o600); written.append(target)
    except Exception:
        for target in reversed(written):
            before = backups[str(target)]
            if before is None: target.unlink(missing_ok=True)
            else: _atomic_replace(target, before, 0o600)
        if created_backup:
            backup_path.unlink(missing_ok=True)
        raise
    state.update({"local_applied": True, "main_switched": main_switched,
                  "bindings": bindings, "routing_applied": True,
                  "applied_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                  "restart_verified": False})
    try:
        _atomic_replace(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n", 0o600)
    except Exception:
        for target in reversed(written):
            before = backups[str(target)]
            if before is None: target.unlink(missing_ok=True)
            else: _atomic_replace(target, before, 0o600)
        if created_backup:
            backup_path.unlink(missing_ok=True)
        raise
    return {"status": "applied_restart_required", "main_switched": main_switched,
            "routing_applied": True, "categories": routes["coverage"]["categories_ready"],
            "next_action": "restart Hermes and run a real delegated task"}


def rollback_runtime(home) -> dict:
    root = _safe_home(home)
    state_path, state = _load_connection_state(root)
    if state.get("local_applied") is not True:
        return {"status": "skipped", "reason": "not_applied"}
    config_path = root / "config.yaml"
    current_hash = hashlib.sha256(config_path.read_bytes()).hexdigest() if config_path.exists() else ""
    if current_hash != state.get("applied_config_sha256"):
        raise OmniRouteError("적용 후 사용자 config 변경이 있어 자동 rollback을 거부했습니다.")
    backup_path = root / INSTALL_DIR / CONFIG_BACKUP
    try:
        backups = json.loads(backup_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise OmniRouteError("rollback snapshot을 읽지 못했습니다.") from None
    for raw, before in backups.items():
        target = Path(raw)
        try: target.relative_to(root)
        except ValueError: raise OmniRouteError("rollback 경로가 home 밖입니다.") from None
        if before is None: target.unlink(missing_ok=True)
        else: _atomic_replace(target, before, 0o600)
    state.update({"local_applied": False, "routing_applied": False,
                  "restart_verified": False})
    _atomic_replace(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n", 0o600)
    return {"status": "rolled_back_restart_required"}


def connection_status(home) -> dict:
    root = _safe_home(home)
    try:
        _, state = _load_connection_state(root)
    except OmniRouteError:
        return {"connected": False, "models_tool_tested": False,
                "local_applied": False, "routing_applied": False,
                "restart_verified": False}
    return {"connected": True, "models_tool_tested": state.get("tool_probe") == "two_turn_passed",
            "local_applied": state.get("local_applied") is True,
            "routing_applied": state.get("routing_applied") is True,
            "main_switched": state.get("main_switched") is True,
            "restart_verified": state.get("restart_verified") is True,
            "chat_models": state.get("chat_models", []), "strong_models": state.get("strong_models", [])}


def verify_runtime(home, password: str, *, client=None) -> dict:
    """Fresh, read-only identity and tool probe of the saved connection.

    This does not mark restart verification: only an independently observed
    Hermes turn/delegated task can establish that state.
    """
    root = _safe_home(home)
    _path, state = _load_connection_state(root)
    if not password or any(char in password for char in "\r\n"):
        raise OmniRouteError("OmniRoute dashboard password가 필요합니다.")
    try:
        secret = None
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if line.split("=", 1)[0].strip() == KEY_ENV and "=" in line:
                secret = line.split("=", 1)[1]
                break
    except OSError:
        secret = None
    if not secret:
        raise OmniRouteError(f"로컬 {KEY_ENV}가 없어 live check를 중단했습니다.")
    client = client or OmniClient()
    client.request("POST", "/api/auth/login", {"password": password})
    keys = {_identifier(row.get("id")) for row in _items(client, "/api/keys", "keys")}
    combos = {_identifier(row.get("id")) for row in _items(client, "/api/combos", "combos")}
    if state.get("key_id") not in keys or any(
            state.get(name) not in combos for name in ("chat_combo_id", "strong_combo_id")):
        raise OmniRouteError("설치 소유 key/combo가 현재 OmniRoute에 없습니다.")
    connections = _connections(client)
    for step in _steps(list(dict.fromkeys(
            (state.get("chat_models") or []) + (state.get("strong_models") or []))), connections):
        _two_turn_probe(client, step["route"], secret, step["connectionId"])
    configured = False
    if state.get("local_applied") is True:
        config = _load_yaml_config(root / "config.yaml")
        configured = ((config.get("providers") or {}).get(PROVIDER) == {
            "base_url": "http://127.0.0.1:20128/v1", "key_env": KEY_ENV,
            "api_mode": "chat_completions"}
            and (config.get("delegation") or {}).get("provider") == PROVIDER
            and (config.get("delegation") or {}).get("model") == state.get("strong_combo"))
        if not configured:
            raise OmniRouteError("Hermes OmniRoute provider 설정이 적용 영수증과 다릅니다.")
        translated = {alias: state[value + "_combo"]
                      for alias, value in (state.get("bindings") or {}).items()}
        expected = route_documents(translated)
        try:
            actual_providers = json.loads((root / ".omh/routing/model-providers.json").read_text())
            actual_chains = json.loads((root / ".omh/routing/model-chains.json").read_text())
        except (OSError, ValueError):
            raise OmniRouteError("OMH route 문서를 읽지 못했습니다.") from None
        if actual_providers != expected["providers"] or actual_chains != expected["chains"]:
            raise OmniRouteError("OMH route 문서가 적용 영수증과 다릅니다.")
    return {"status": "live_connector_verified", "owned_objects_present": True,
            "models_tool_tested_now": True, "local_config_matches": configured,
            "restart_verified": False,
            "next_action": "restart Hermes and observe one main turn plus delegated task"}


def _memory_gib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB$", meminfo.read_text(), re.MULTILINE)
        return int(match.group(1)) / 1024 / 1024 if match else None
    except (OSError, ValueError):
        return None


def _safe_home(home: str | Path) -> Path:
    """Absolute path with no existing symlink component; do not resolve it first."""
    path = Path(home).expanduser().absolute()
    current = path
    while True:
        if current.is_symlink():
            raise OmniRouteError(f"설치 경로의 심볼릭 링크는 허용하지 않습니다: {current}")
        if current == current.parent:
            break
        current = current.parent
    return path


def _run(argv: list[str], *, timeout: int = 120, runner=subprocess.run) -> subprocess.CompletedProcess:
    try:
        result = runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        raise OmniRouteError(f"실행하지 못했습니다: {argv[0]}") from None
    if result.returncode:
        # Docker output can include expanded environment values. Do not forward it.
        raise OmniRouteError(f"명령이 실패했습니다: {' '.join(argv[:3])} (exit {result.returncode})")
    return result


def preflight(*, system: str | None = None, machine: str | None = None,
              memory_gib: float | None = None, which=shutil.which,
              runner=subprocess.run, docker_info: dict | None = None,
              context_host: str | None = None) -> dict:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    blockers = []
    if system not in ("Linux", "Darwin", "Windows"):
        blockers.append("지원 대상은 Linux, macOS, Windows Docker Desktop입니다.")
    supported_hosts = {"Linux": {"x86_64", "amd64"},
                       "Darwin": {"x86_64", "amd64", "arm64", "aarch64"},
                       "Windows": {"x86_64", "amd64", "arm64", "aarch64"}}
    if system in supported_hosts and machine not in supported_hosts[system]:
        blockers.append("지원하지 않는 호스트 CPU 아키텍처입니다.")
    docker = which("docker")
    if not docker:
        blockers.append("Docker CLI가 없습니다.")
    else:
        if docker_info is None:
            try:
                result = runner([docker, "info", "--format", "{{json .}}"],
                                capture_output=True, text=True, timeout=20, check=False)
                docker_info = json.loads(result.stdout) if result.returncode == 0 else None
            except (OSError, subprocess.SubprocessError, ValueError):
                docker_info = None
        if context_host is None:
            try:
                result = runner([docker, "context", "inspect", "--format",
                                 "{{json .Endpoints.docker.Host}}"], capture_output=True,
                                text=True, timeout=20, check=False)
                context_host = json.loads(result.stdout) if result.returncode == 0 else None
            except (OSError, subprocess.SubprocessError, ValueError):
                context_host = None
        try:
            result = runner([docker, "compose", "version", "--short"], capture_output=True,
                            text=True, timeout=20, check=False)
            if result.returncode:
                blockers.append("Docker Compose가 준비되지 않았습니다.")
        except (OSError, subprocess.SubprocessError):
            blockers.append("Docker Compose 상태를 확인하지 못했습니다.")
    if not isinstance(docker_info, dict):
        blockers.append("Docker Engine 정보를 읽지 못했습니다.")
        docker_info = {}
    if str(docker_info.get("OSType") or "").lower() != "linux":
        blockers.append("Docker Engine이 Linux 컨테이너 모드가 아닙니다.")
    docker_os = str(docker_info.get("OperatingSystem") or "")
    docker_arch = str(docker_info.get("Architecture") or "").lower()
    if system in ("Darwin", "Windows") and "docker desktop" not in docker_os.lower():
        blockers.append("macOS/Windows 자동 설치는 로컬 Docker Desktop만 지원합니다.")
    if system == "Linux" and docker_arch not in ("x86_64", "amd64"):
        blockers.append("Linux 서버 자동 설치는 amd64 Docker Engine만 검증되었습니다.")
    if docker_arch not in ("x86_64", "amd64", "arm64", "aarch64"):
        blockers.append("Docker Engine CPU 아키텍처를 지원하지 않습니다.")
    if not isinstance(context_host, str) or not context_host.startswith(("unix://", "npipe://")):
        blockers.append("원격 Docker context는 거부합니다. 로컬 Engine을 선택하세요.")
    try:
        docker_memory_gib = int(docker_info.get("MemTotal")) / 1024 ** 3
    except (TypeError, ValueError):
        docker_memory_gib = memory_gib if system == "Linux" else None
    if docker_memory_gib is None and system == "Linux":
        docker_memory_gib = _memory_gib() if memory_gib is None else memory_gib
    if docker_memory_gib is None or docker_memory_gib < 4:
        blockers.append("Docker Engine/VM에 확인 가능한 RAM 4GiB 이상이 필요합니다.")
    emulation = docker_arch in ("arm64", "aarch64")
    return {"system": system, "machine": machine, "memory_gib": memory_gib,
            "docker_memory_gib": docker_memory_gib, "docker_os": docker_os,
            "docker_arch": docker_arch, "context_host": context_host,
            "emulation_required_unverified": emulation,
            "docker": docker, "blockers": list(dict.fromkeys(blockers)),
            "supported": not blockers}


def _compose() -> str:
    return f'''name: {PROJECT}
services:
  omniroute:
    image: {IMAGE}
    platform: linux/amd64
    restart: unless-stopped
    stop_grace_period: 40s
    mem_limit: 2g
    memswap_limit: 3g
    volumes:
      - omniroute-data:/app/data
    environment:
      INITIAL_PASSWORD: ${{KIT_OMNIROUTE_PASSWORD:?set in the private env file}}
      REQUIRE_API_KEY: "true"
      TZ: Asia/Seoul
    entrypoint:
      - sh
      - -c
      - |
        s=/app/data/.kit-secrets
        [ -s "$$s" ] || {{ umask 077; printf 'JWT_SECRET=%s\\nAPI_KEY_SECRET=%s\\n' "$$(head -c 48 /dev/urandom | base64 | tr -d '\\n')" "$$(head -c 48 /dev/urandom | base64 | tr -d '\\n')" > "$$s"; }}
        set -a; . "$$s"; set +a
        exec /app/check-permissions.sh node dev/run-standalone.mjs
    ports:
      - "127.0.0.1:20128:20128"
volumes:
  omniroute-data: {{}}
'''


def _atomic_create(path: Path, text: str, mode: int) -> None:
    if path.is_symlink():
        raise OmniRouteError(f"심볼릭 링크는 허용하지 않습니다: {path.name}")
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise OmniRouteError(f"기존 파일을 보존했습니다: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".omniroute-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _atomic_replace(path: Path, text: str, mode: int) -> None:
    if path.is_symlink():
        raise OmniRouteError(f"심볼릭 링크는 허용하지 않습니다: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".omniroute-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _health(urlopen=urllib.request.urlopen) -> bool:
    request = urllib.request.Request("http://127.0.0.1:20128/healthz",
                                     headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=3) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def _private_password_file(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    # Accept only the shape this installer writes. We inspect validity but never
    # return, print, compare, hash or log the captured value.
    return re.fullmatch(r"KIT_OMNIROUTE_PASSWORD='[^'\r\n]{16,512}'\n?", text) is not None


def _windows_acl(path: Path, *, directory: bool, runner=subprocess.run,
                 which=shutil.which, user: str | None = None) -> None:
    """Restrict a path before secrets are staged on Windows."""
    icacls = which("icacls") or which("icacls.exe")
    account = user or getpass.getuser()
    if (not icacls or not isinstance(account, str) or not account
            or any(ord(char) < 32 for char in account)):
        raise OmniRouteError("Windows 비밀정보 ACL을 제한할 수 없어 저장을 거부했습니다.")
    grant = account + (":(OI)(CI)(F)" if directory else ":(F)")
    commands = [
        [icacls, str(path), "/inheritance:r"],
        [icacls, str(path), "/remove:g", "*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545"],
        [icacls, str(path), "/grant:r", grant],
    ]
    for command in commands:
        try:
            result = runner(command, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            raise OmniRouteError("Windows 비밀정보 ACL 제한에 실패해 저장을 거부했습니다.") from None
        if result.returncode:
            raise OmniRouteError("Windows 비밀정보 ACL 제한에 실패해 저장을 거부했습니다.")


def _restrict_secret(path: Path, system: str, *, runner=subprocess.run,
                     which=shutil.which, user: str | None = None) -> None:
    if system != "Windows":
        os.chmod(path, 0o600)
        return
    _windows_acl(path, directory=False, runner=runner, which=which, user=user)


def _container_identity(base: list[str], docker: str, *, runner=subprocess.run) -> bool:
    """Prove that loopback health belongs to this project and pinned image."""
    located = _run(base + ["ps", "-q", "omniroute"], timeout=30, runner=runner)
    container_id = located.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{12,64}", container_id):
        raise OmniRouteError("OmniRoute 컨테이너 ID를 확인하지 못했습니다.")
    inspected = _run([docker, "inspect", container_id], timeout=30, runner=runner)
    try:
        documents = json.loads(inspected.stdout)
        document = documents[0]
        labels = document["Config"]["Labels"]
        ports = document["NetworkSettings"]["Ports"]["20128/tcp"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise OmniRouteError("OmniRoute 컨테이너 신원을 확인하지 못했습니다.") from None
    owned = (
        document.get("Config", {}).get("Image") == IMAGE
        and labels.get("com.docker.compose.project") == PROJECT
        and labels.get("com.docker.compose.service") == "omniroute"
        and document.get("State", {}).get("Running") is True
        and isinstance(ports, list) and len(ports) == 1
        and ports[0].get("HostIp") == "127.0.0.1"
        and ports[0].get("HostPort") == "20128"
    )
    if not owned:
        raise OmniRouteError("포트 응답이 설치 소유 OmniRoute 컨테이너와 일치하지 않습니다.")
    return True


def plan(data: dict, home: str | Path) -> dict:
    enabled = data.get("omniroute_enabled", False) is True
    return {
        "schema_version": "hermes_outbound_omniroute_plan/v1",
        "selected": enabled,
        "supported_target": "local Linux Engine or macOS/Windows Docker Desktop; >=4GiB Docker RAM",
        "install_dir": str(_safe_home(home) / INSTALL_DIR),
        "image": IMAGE,
        "dashboard": "loopback-only http://127.0.0.1:20128",
        "omh": {"repository": OMH_REPOSITORY, "version": OMH_VERSION,
                "commit": OMH_COMMIT, "archive_sha256": OMH_ARCHIVE_SHA256,
                "plugin_hook_sha256": OMH_PLUGIN_HOOK_SHA256,
                "categories": list(RECOMMENDED_CHAINS),
                "installation": "separate_required_step_not_performed_here"},
        "after_install": ["private dashboard login", "provider account connection",
                          "model discovery", "two-turn tool probe", "routing apply",
                          "Hermes restart and live delegated task"],
        "claim": "plan_only" if enabled else "not_selected",
    }


def install(data: dict, home: str | Path, *, password: str | None = None,
            runner=subprocess.run, which=shutil.which, health=_health,
            system: str | None = None, machine: str | None = None,
            memory_gib: float | None = None, sleeper=time.sleep,
            docker_info: dict | None = None, context_host: str | None = None,
            windows_user: str | None = None, identity=None) -> dict:
    if data.get("omniroute_enabled", False) is not True:
        return {"status": "skipped", "reason": "not_selected"}
    check = preflight(system=system, machine=machine, memory_gib=memory_gib,
                      which=which, runner=runner, docker_info=docker_info,
                      context_host=context_host)
    if check["blockers"]:
        raise OmniRouteError(" ".join(check["blockers"]))
    root = _safe_home(home) / INSTALL_DIR
    root.mkdir(parents=True, exist_ok=True)
    actual_system = system or platform.system()
    if actual_system == "Windows":
        # Restrict the directory before an atomic secret staging file exists.
        _windows_acl(root, directory=True, runner=runner, which=which, user=windows_user)
    elif os.name == "posix":
        os.chmod(root, 0o700)
    compose, env_file = root / "compose.yaml", root / ".env"
    _atomic_create(compose, _compose(), 0o600)
    if not env_file.exists():
        password = password if password is not None else getpass.getpass("OmniRoute dashboard password: ")
        if (not isinstance(password, str) or len(password) < 16 or len(password) > 512
                or "'" in password or any(ord(char) < 32 for char in password)):
            raise OmniRouteError("대시보드 비밀번호는 작은따옴표·제어문자 없는 16~512자로 정하세요.")
        # Compose dotenv single quotes preserve spaces, # and $ literally.
        _atomic_create(env_file, "KIT_OMNIROUTE_PASSWORD='" + password + "'\n", 0o600)
    elif env_file.is_symlink() or not env_file.is_file():
        raise OmniRouteError("기존 비밀정보 파일 형식을 확인하세요.")
    _restrict_secret(env_file, actual_system, runner=runner, which=which, user=windows_user)
    if not _private_password_file(env_file):
        raise OmniRouteError("기존 비밀정보 파일의 이름·형식·권한을 확인하세요.")

    docker = check["docker"]
    base = [docker, "compose", "--project-directory", str(root), "--env-file", str(env_file),
            "-f", str(compose)]
    _run(base + ["pull", "omniroute"], timeout=600, runner=runner)
    _run(base + ["up", "-d", "omniroute"], timeout=180, runner=runner)
    if identity is None:
        _container_identity(base, docker, runner=runner)
    elif identity(base, docker) is not True:
        raise OmniRouteError("OmniRoute 컨테이너 신원 확인이 실패했습니다.")
    healthy = False
    for _ in range(20):
        if health():
            healthy = True
            break
        sleeper(1)
    if not healthy:
        raise OmniRouteError("컨테이너는 기동했지만 loopback health 확인이 실패했습니다.")
    state_path = root / STATE
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise OmniRouteError("기존 설치 영수증을 읽을 수 없어 보존했습니다.") from None
        if (state.get("schema_version") != "hermes_outbound_omniroute_install/v1"
                or state.get("image") != IMAGE or state.get("project") != PROJECT):
            raise OmniRouteError("기존 설치 영수증의 버전/이미지를 보존했습니다.")
        if state.get("container_identity_verified") is not True:
            state["container_identity_verified"] = True
            _atomic_replace(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n", 0o600)
    else:
        state = {"schema_version": "hermes_outbound_omniroute_install/v1", "image": IMAGE,
                 "project": PROJECT, "installed": True, "dashboard_healthy": True,
                 "container_identity_verified": True,
                 "provider_authenticated": False, "models_tool_tested": False,
                 "routing_applied": False, "restart_verified": False}
        _atomic_create(state_path, json.dumps(state, indent=2, sort_keys=True) + "\n", 0o600)
    return {"status": "installed", **state,
            "emulation_required_unverified": check["emulation_required_unverified"],
            "next": "대시보드에서 계정을 연결한 뒤 모델 discovery와 2-turn tool probe가 필요합니다."}


def status(data: dict, home: str | Path, *, health=_health) -> dict:
    selected = data.get("omniroute_enabled", False) is True
    home_path = _safe_home(home)
    root = home_path / INSTALL_DIR
    state_path, env_path = root / STATE, root / ".env"
    try:
        saved = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    secret_shape = _private_password_file(env_path)
    # The installer fails closed when applying Windows ACLs, but this read-only
    # check does not parse localized icacls output and therefore must not claim
    # that the ACL is still private after the fact.
    private = None if platform.system() == "Windows" else secret_shape
    omh_plugin = (home_path / "plugins/omh").is_dir()
    omh_compatible = _omh_compatible(home_path)
    return {"selected": selected, "configured": (root / "compose.yaml").is_file(),
            "secret_file_shape_valid": secret_shape, "secret_file_private": private,
            "secret_privacy_claim": ("unknown_windows_acl_not_rechecked"
                                     if private is None else "posix_mode_checked"),
            "installed": saved.get("installed") is True,
            "dashboard_healthy": health() if saved.get("installed") is True else False,
            "container_identity_verified": saved.get("container_identity_verified") is True,
            "omh_detected": omh_plugin, "omh_pinned_compatible": omh_compatible,
            "provider_authenticated": saved.get("provider_authenticated") is True,
            "models_tool_tested": saved.get("models_tool_tested") is True,
            "routing_applied": saved.get("routing_applied") is True,
            "restart_verified": saved.get("restart_verified") is True,
            "claim": "saved_identity_and_current_loopback_health_only"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional local-Docker OmniRoute installer")
    parser.add_argument("action", choices=("plan", "install", "discover", "connect", "apply",
                                           "check", "rollback", "routes"))
    parser.add_argument("--config", default="setup.json")
    parser.add_argument("--home", default="~/.hermes-outbound")
    parser.add_argument("--bindings", help="Non-secret JSON object: OMH alias -> tested OmniRoute combo")
    parser.add_argument("--output", help="Stage generated route documents as JSON; existing changes are preserved")
    parser.add_argument("--chat-models", help='Comma-separated dashboard routes: "prefix/model"')
    parser.add_argument("--strong-models", default="", help="Optional delegation routes; defaults to chat")
    parser.add_argument("--live", action="store_true",
                        help="For check: prompt privately and re-probe owned objects/models")
    args = parser.parse_args()
    try:
        data = load_config(args.config)
        if args.action == "plan":
            result = plan(data, args.home)
        elif args.action == "install":
            result = install(data, args.home)
        elif args.action == "discover":
            password = getpass.getpass("OmniRoute dashboard password: ")
            result = {"models": discover_models(password), "claim": "discovery_only_not_tested"}
        elif args.action == "connect":
            if not args.chat_models:
                raise OmniRouteError("connect에는 --chat-models가 필요합니다.")
            password = getpass.getpass("OmniRoute dashboard password: ")
            result = connect_runtime(data, args.home, password, args.chat_models, args.strong_models)
        elif args.action == "apply":
            if not args.bindings:
                raise OmniRouteError("apply에는 alias -> chat/strong --bindings JSON이 필요합니다.")
            bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8-sig"))
            result = apply_runtime(data, args.home, bindings)
        elif args.action == "check":
            result = {"container": status(data, args.home),
                      "connection": connection_status(args.home)}
            if args.live:
                password = getpass.getpass("OmniRoute dashboard password: ")
                result["live"] = verify_runtime(args.home, password)
        elif args.action == "rollback":
            result = rollback_runtime(args.home)
        else:
            if data.get("omniroute_enabled", False) is not True:
                raise OmniRouteError("OmniRoute를 선택한 설정에서만 routes를 생성합니다.")
            if not args.bindings:
                raise OmniRouteError("routes에는 --bindings JSON 파일이 필요합니다.")
            bindings = json.loads(Path(args.bindings).read_text(encoding="utf-8-sig"))
            result = route_documents(bindings)
            if args.output:
                output = _safe_home(args.output)
                _atomic_create(output,
                               json.dumps(result, ensure_ascii=False, indent=2,
                                          sort_keys=True) + "\n", 0o600)
                result = {**result, "staged_output": str(output)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"OmniRoute: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
