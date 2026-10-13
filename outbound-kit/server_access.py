#!/usr/bin/env python3
"""Safe SSH access preparation for a remote Hermes Outbound server.

This module creates only a local key when explicitly requested. Its explicit deploy action
uploads an allowlisted kit and a non-secret transformed config to a new remote staging
directory. It never changes sshd/firewall settings, installs Hermes, starts services, or
accepts host keys automatically.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import PurePosixPath


MAX_CONFIG = 1024 * 1024
MAX_BUNDLE = 32 * 1024 * 1024
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$", re.I)
HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,64}={0,2}$")
PROBE_COMMAND = (
    "printf '%s\\n' '--- os ---'; uname -srm; "
    "printf '%s\\n' '--- python3 ---'; "
    "if command -v python3 >/dev/null 2>&1; then command -v python3; python3 --version; "
    "python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 42)' "
    "&& printf '%s\\n' compatible-3.11+ || printf '%s\\n' unsupported-before-3.11; "
    "else printf '%s\\n' missing; fi; "
    "printf '%s\\n' '--- hermes ---'; "
    "if command -v hermes >/dev/null 2>&1; then command -v hermes; hermes --version; else printf '%s\\n' missing; fi"
)
DEPLOY_FILES = (
    "README.md", "VALIDATION.md", "kit.py", "wizard.html", "installer.py",
    "server_access.py", "paths.py", "engine_bootstrap.py", "omh_setup.py", "omniroute_setup.py",
    "services.py", "runtime_connect.py", "docs_support.py", "sources.py", "vault_flow.py",
    "workflow.py", "operations.py", "vault_sync.py", "support.py", "start.py",
    "bootstrap.command", "bootstrap.ps1", "local_smoke.py", "test_bot.py",
    "privacy_audit.py", "public_data_lens.py", "LICENSE",
    "setup.example.json", "시작하기.command", "시작하기.bat",
)
DEPLOY_TREES = {
    "agent-skill": {".md", ".py"}, "docs": {".md"},
    "pack": {".md", ".json", ".csv"}, "samples": {".json", ".csv", ".html"},
}
REMOTE_STAGE = re.compile(r"^/[A-Za-z0-9._/-]+/hermes-outbound-stage\.[A-Za-z0-9]{8}$")
REMOTE_KIT = re.compile(r"^/[A-Za-z0-9._/-]+/hermes-outbound-stage\.[A-Za-z0-9]{8}/hermes-outbound-kit$")
OMNIROUTE_REMOTE_PORT = 20128
REMOTE_PYTHON_CHECK = (
    "command -v python3 >/dev/null 2>&1 && "
    "python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 42)' && "
    "python3 --version"
)
REMOTE_EXTRACT_SCRIPT = r'''import pathlib, shutil, stat, sys, zipfile
stage = pathlib.Path(sys.argv[1]).resolve()
archive = pathlib.Path(sys.argv[2]).resolve()
config = pathlib.Path(sys.argv[3]).resolve()
if archive.parent != stage or config.parent != stage:
    raise SystemExit("upload path escaped stage")
root = stage / "hermes-outbound-kit"
if root.exists() or root.is_symlink():
    raise SystemExit("final staging directory already exists")
total = 0
with zipfile.ZipFile(archive) as zf:
    infos = zf.infolist()
    if not infos or len(infos) > 1000:
        raise SystemExit("invalid archive member count")
    for info in infos:
        part = pathlib.PurePosixPath(info.filename)
        mode = (info.external_attr >> 16) & 0xffff
        if part.is_absolute() or not part.parts or ".." in part.parts or part.parts[0] != "hermes-outbound-kit":
            raise SystemExit("unsafe archive path")
        if stat.S_ISLNK(mode) or (mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
            raise SystemExit("unsafe archive file type")
        total += info.file_size
        if total > 32 * 1024 * 1024:
            raise SystemExit("archive too large")
        target = stage.joinpath(*part.parts)
        if stage not in target.resolve().parents:
            raise SystemExit("archive target escaped stage")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=False)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise SystemExit("archive target already exists")
        with zf.open(info) as source, target.open("xb") as sink:
            shutil.copyfileobj(source, sink, 1024 * 1024)
setup = root / "setup.json"
if setup.exists() or setup.is_symlink():
    raise SystemExit("setup target already exists")
with config.open("rb") as source, setup.open("xb") as sink:
    shutil.copyfileobj(source, sink, 1024 * 1024)
print(root)
'''


def _text(value, name, limit=300, required=True):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{name}: 문자열이어야 합니다.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{name}: 값이 필요합니다.")
    if len(value) > limit or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError(f"{name}: 공백·제어문자 또는 허용 길이를 확인하세요.")
    return value


def validate_host(value):
    host = _text(value, "server_host", 253)
    if host.startswith("-") or any(c in host for c in "@/\\[]"):
        raise ValueError("server_host: 호스트명 또는 IP만 입력하세요.")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.rstrip(".").split(".")
    if not labels or any(not HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("server_host: 유효한 DNS 호스트명 또는 IP가 아닙니다.")
    return host.rstrip(".")


def validate_user(value):
    user = _text(value, "server_user", 32)
    if not USER.fullmatch(user) or user.startswith("-"):
        raise ValueError("server_user: 안전한 Linux 사용자 이름이 필요합니다.")
    return user


def validate_port(value):
    if isinstance(value, bool):
        raise ValueError("server_port: 1~65535 정수여야 합니다.")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("server_port: 1~65535 정수여야 합니다.") from None
    if str(port) != str(value).strip() and not isinstance(value, int):
        raise ValueError("server_port: 정수 표기만 허용합니다.")
    if not 1 <= port <= 65535:
        raise ValueError("server_port: 1~65535 범위여야 합니다.")
    return port


def validate_key_path(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000 or any(ord(c) < 32 for c in value):
        raise ValueError("ssh_key_path: 유효한 파일 경로가 필요합니다.")
    raw = value.strip()
    path = Path(raw).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("ssh_key_path: 심볼릭 링크는 사용할 수 없습니다.")
    parent = path.parent
    while parent != parent.parent:
        if parent.exists() and parent.is_symlink():
            raise ValueError("ssh_key_path: 상위 경로의 심볼릭 링크는 사용할 수 없습니다.")
        parent = parent.parent
    if path.name in ("", ".", ".."):
        raise ValueError("ssh_key_path: 개인키 파일 경로가 필요합니다.")
    return path


def load_config(path):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONFIG:
        raise ValueError("config는 1MiB 이하의 일반 JSON 파일이어야 합니다.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"config JSON 오류: {exc.msg}") from None
    if not isinstance(raw, dict):
        raise ValueError("config는 JSON 객체여야 합니다.")
    location = raw.get("install_location", "remote" if raw.get("target") == "server" else "local")
    if location not in ("local", "remote"):
        raise ValueError("install_location은 local 또는 remote여야 합니다.")
    if location == "local":
        return {"install_location": "local"}
    # Use one spelling throughout. Ambiguous legacy names are refused rather than guessed.
    if "key_path" in raw or "server_key_path" in raw:
        raise ValueError("개인키 경로 필드는 ssh_key_path를 사용하세요.")
    action = raw.get("ssh_key_action", "existing")
    if action not in ("existing", "generate"):
        raise ValueError("ssh_key_action은 existing 또는 generate여야 합니다.")
    return {
        "install_location": "remote",
        "server_host": validate_host(raw.get("server_host")),
        "server_user": validate_user(raw.get("server_user")),
        "server_port": validate_port(raw.get("server_port", 22)),
        "ssh_key_path": validate_key_path(raw.get("ssh_key_path")),
        "ssh_key_action": action,
    }


def availability():
    return {"ssh": shutil.which("ssh"), "ssh_keygen": shutil.which("ssh-keygen"),
            "scp": shutil.which("scp")}


def _key_status(config):
    key = config["ssh_key_path"]
    public = Path(str(key) + ".pub")
    if key.exists() and (key.is_symlink() or not key.is_file()):
        return "invalid"
    if public.exists() and (public.is_symlink() or not public.is_file()):
        return "invalid"
    if key.is_file() and public.is_file():
        return "present"
    if key.exists() or public.exists():
        return "partial"
    return "missing"


def plan(config):
    tools = availability()
    if config["install_location"] == "local":
        return {"status": "not_applicable", "install_location": "local",
                "next": "로컬 설치 경로를 사용하세요.", "tools": tools}
    key_status = _key_status(config)
    action = config["ssh_key_action"]
    blocked = []
    if not tools["ssh"]:
        blocked.append("ssh_missing")
    if not tools["scp"]:
        blocked.append("scp_missing")
    if action == "generate" and not tools["ssh_keygen"]:
        blocked.append("ssh_keygen_missing")
    if action == "existing" and key_status != "present":
        blocked.append("existing_key_unavailable")
    if action == "generate" and key_status != "missing":
        blocked.append("key_path_not_unique")
    return {
        "status": "blocked" if blocked else "ready",
        "install_location": "remote", "host": config["server_host"],
        "user": config["server_user"], "port": config["server_port"],
        "ssh_key_path": str(config["ssh_key_path"]), "ssh_key_action": action,
        "key_status": key_status, "tools": tools, "blocked": blocked,
        "next": ("명시적으로 keygen을 실행한 뒤 공개키를 서버에 등록하세요."
                 if action == "generate" and not blocked else
                 "서버 제공자 또는 관리자 경로로 공개키를 등록한 뒤 trust를 실행하세요."
                 if not blocked else "blocked 항목을 해결한 뒤 plan을 다시 실행하세요."),
    }


def generate_key(config, runner=subprocess.run):
    if config["install_location"] != "remote" or config["ssh_key_action"] != "generate":
        raise ValueError("config에서 remote와 ssh_key_action=generate를 명시해야 합니다.")
    executable = shutil.which("ssh-keygen")
    if not executable:
        raise ValueError("ssh-keygen을 찾을 수 없습니다.")
    if _key_status(config) != "missing":
        raise ValueError("키 경로가 비어 있지 않습니다. 기존 키를 덮어쓰지 않습니다.")
    key = config["ssh_key_path"]
    if key.parent.exists() and (key.parent.is_symlink() or not key.parent.is_dir()):
        raise ValueError("키 상위 경로를 안전하게 만들 수 없습니다.")
    key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(key.parent, 0o700)
    command = [executable, "-t", "ed25519", "-a", "100", "-f", str(key),
               "-C", "hermes-outbound@" + config["server_host"]]
    print("ssh-keygen이 passphrase를 직접 묻습니다. 빈 passphrase를 자동 설정하지 않습니다.")
    # Deliberately inherit stdin/stdout/stderr. Passphrases never enter argv, config, or logs.
    result = runner(command, check=False)
    if result.returncode != 0 or _key_status(config) != "present":
        raise ValueError("SSH 키 생성이 완료되지 않았습니다. 부분 파일이 있으면 직접 검토하세요.")
    if os.name == "posix":
        os.chmod(key, 0o600)
        os.chmod(Path(str(key) + ".pub"), 0o644)
    return {"status": "generated", "ssh_key_path": str(key),
            "public_key_path": str(key) + ".pub",
            "next": "공개키(.pub)만 서버 제공자 콘솔 또는 관리자가 승인한 방법으로 등록하세요."}


def _base_ssh(config, strict):
    executable = shutil.which("ssh")
    if not executable:
        raise ValueError("ssh를 찾을 수 없습니다.")
    if _key_status(config) != "present":
        raise ValueError("개인키와 공개키 쌍을 확인하세요.")
    return [executable, "-p", str(config["server_port"]), "-i", str(config["ssh_key_path"]),
            "-o", "IdentitiesOnly=yes", "-o", f"StrictHostKeyChecking={strict}",
            "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
            config["server_user"] + "@" + config["server_host"]]


def _base_scp(config):
    executable = shutil.which("scp")
    if not executable:
        raise ValueError("scp를 찾을 수 없습니다.")
    if _key_status(config) != "present":
        raise ValueError("개인키와 공개키 쌍을 확인하세요.")
    return [executable, "-P", str(config["server_port"]), "-i", str(config["ssh_key_path"]),
            "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
            "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1"]


def trust(config, fingerprint, *, input_fn=input, runner=subprocess.run):
    fingerprint = _text(fingerprint, "fingerprint", 100)
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("fingerprint는 독립 경로로 확인한 SHA256:... 형식이어야 합니다.")
    print("서버 제공자 콘솔/관리자 등 SSH와 다른 경로에서 받은 fingerprint와 아래 값을 대조하세요:")
    print(fingerprint)
    typed = input_fn("독립 확인한 fingerprint를 다시 입력하세요: ").strip()
    if typed != fingerprint:
        raise ValueError("fingerprint 재확인이 일치하지 않습니다.")
    command = _base_ssh(config, "ask") + ["exit"]
    print("이제 SSH가 제시하는 fingerprint가 위 값과 같은 경우에만 yes를 입력하세요.")
    result = runner(command, check=False)
    if result.returncode != 0:
        raise ValueError("최초 SSH 신뢰/인증이 완료되지 않았습니다.")
    return {"status": "trusted_and_authenticated", "fingerprint": fingerprint,
            "next": "StrictHostKeyChecking=yes probe를 실행하세요."}


def probe(config, runner=subprocess.run):
    command = _base_ssh(config, "yes") + [PROBE_COMMAND]
    result = runner(command, check=False, capture_output=True, text=True, timeout=25)
    stdout = (result.stdout or "")[:16384]
    if result.returncode != 0:
        return {"status": "failed", "exit_code": result.returncode,
                "output": stdout, "next": "known_hosts, 키 등록, 사용자·포트와 네트워크를 확인하세요."}
    return {"status": "passed", "exit_code": 0, "output": stdout,
            "checks": {"os": "--- os ---" in stdout,
                       "python3": "compatible-3.11+" in _section(stdout, "python3"),
                       "hermes": "--- hermes ---" in stdout and "missing" not in _section(stdout, "hermes")},
            "next": "이 probe는 읽기 전용입니다. 배포·엔진 설치·서비스 변경은 아직 수행되지 않았습니다."}


def _read_full_config(path):
    """Load through the kit schema so unknown/secret-shaped fields are refused."""
    import kit
    return kit.load(path)


def _remote_config(path):
    data = dict(_read_full_config(path))
    if data.get("install_location") != "remote" or data.get("target") != "server":
        raise ValueError("deploy는 remote/server 설정에서만 실행할 수 있습니다.")
    for name in ("server_host", "server_port", "server_user", "ssh_key_path",
                 "ssh_key_action", "ssh_auth"):
        data.pop(name, None)
    data["install_location"] = "local"
    data["target"] = "server"
    data["os_hint"] = "linux"
    data["desktop_mode"] = "terminal"
    data["install_home"] = "~/.hermes-outbound"
    data["output_path"] = "~/.hermes-outbound/output"
    if data.get("vault_mode", "none") != "none":
        data["vault_mode"] = "new"
        data["vault_path"] = "~/.hermes-outbound/vault"
    else:
        data["vault_path"] = ""
    data["vault_existing_approved"] = False
    if data.get("omniroute_enabled"):
        data["routing_bindings_path"] = "~/.hermes-outbound/omniroute/routes.json"
    import kit
    return kit.validate(data)


def _bundle_members(root):
    root = root.resolve()
    paths = []
    for name in DEPLOY_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("배포 필수 파일이 없거나 링크입니다: " + name)
        paths.append(path)
    for folder, suffixes in DEPLOY_TREES.items():
        base = root / folder
        if not base.is_dir() or base.is_symlink():
            raise ValueError("배포 필수 디렉터리가 없거나 링크입니다: " + folder)
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                raise ValueError("배포 allowlist 내 심볼릭 링크를 거부합니다: " + str(path))
            if path.is_file() and path.suffix in suffixes:
                paths.append(path)
    return sorted(set(paths), key=lambda p: p.relative_to(root).as_posix())


def _build_deploy_zip(root, target):
    root = root.resolve()
    total = 0
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in _bundle_members(root):
            total += path.stat().st_size
            if total > MAX_BUNDLE:
                raise ValueError("배포 묶음이 32MiB 허용량을 넘었습니다.")
            archive.write(path, "hermes-outbound-kit/" + path.relative_to(root).as_posix())


def _validated_stage(output):
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if len(lines) != 1 or not REMOTE_STAGE.fullmatch(lines[0]):
        raise ValueError("원격 mktemp가 안전한 절대 경로 하나를 반환하지 않았습니다.")
    path = PurePosixPath(lines[0])
    if ".." in path.parts:
        raise ValueError("원격 stage 경로를 거부합니다.")
    return lines[0]


def deploy(config, config_path, *, runner=subprocess.run, root=None):
    """Stage an allowlisted kit; does not install an engine or start anything."""
    if config["install_location"] != "remote":
        raise ValueError("deploy는 remote 설정에서만 실행할 수 있습니다.")
    root = Path(__file__).resolve().parent if root is None else Path(root).resolve()
    transformed = _remote_config(config_path)
    destination = config["server_user"] + "@" + config["server_host"]
    checked = runner(_base_ssh(config, "yes") + [REMOTE_PYTHON_CHECK], check=False,
                     capture_output=True, text=True, timeout=25)
    if checked.returncode != 0:
        raise ValueError("known_hosts/SSH/Python 확인이 실패해 배포를 시작하지 않았습니다.")
    made = runner(_base_ssh(config, "yes") + ['mktemp -d "$HOME/hermes-outbound-stage.XXXXXXXX"'],
                  check=False, capture_output=True, text=True, timeout=25)
    if made.returncode != 0:
        raise ValueError("원격 stage 디렉터리를 만들지 못했습니다.")
    stage = _validated_stage(made.stdout)
    with tempfile.TemporaryDirectory(prefix="hermes-outbound-deploy-") as temporary:
        temporary = Path(temporary)
        bundle = temporary / "kit.zip"
        remote_setup = temporary / "setup.remote.json"
        _build_deploy_zip(root, bundle)
        remote_setup.write_text(json.dumps(transformed, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        copied = runner(_base_scp(config) + [str(bundle), str(remote_setup),
                                             destination + ":" + stage + "/"],
                        check=False, capture_output=True, text=True, timeout=60)
        if copied.returncode != 0:
            raise ValueError("키트 ZIP/비밀 없는 설정 복사가 실패했습니다. 새 stage는 자동 삭제하지 않습니다.")
    extract_args = [stage, stage + "/kit.zip", stage + "/setup.remote.json"]
    remote_command = "python3 -c " + shlex.quote(REMOTE_EXTRACT_SCRIPT)
    remote_command += " " + " ".join(shlex.quote(arg) for arg in extract_args)
    extracted = runner(_base_ssh(config, "yes") + [remote_command], check=False,
                       capture_output=True, text=True, timeout=60)
    if extracted.returncode != 0:
        raise ValueError("원격 안전 압축 해제가 실패했습니다. 엔진/서비스는 실행되지 않았습니다.")
    expected = stage + "/hermes-outbound-kit"
    if [line.strip() for line in (extracted.stdout or "").splitlines() if line.strip()] != [expected]:
        raise ValueError("원격 압축 해제 결과 경로를 확인할 수 없습니다.")
    return {"status": "staged", "remote_path": expected, "engine_installed": False,
            "services_started": False,
            "next": "server_access.py resume로 원격 설치를 사용자 터미널에서 계속하세요."}


def _validated_remote_kit_path(value):
    if not isinstance(value, str) or not REMOTE_KIT.fullmatch(value) or ".." in PurePosixPath(value).parts:
        raise ValueError("remote_path는 deploy가 반환한 고유 kit 절대 경로여야 합니다.")
    return value


def _interactive_ssh(config, remote_command):
    base = _base_ssh(config, "yes")
    return [*base[:-1], "-t", base[-1], remote_command]


def resume(config, remote_path, *, execute=False, terminal=None, runner=subprocess.run):
    remote_path = _validated_remote_kit_path(remote_path)
    remote_command = ("cd " + shlex.quote(remote_path) +
                      " && python3 installer.py setup --config setup.json")
    argv = _interactive_ssh(config, remote_command)
    terminal = (sys.stdin.isatty() and sys.stdout.isatty()) if terminal is None else terminal
    if not execute or not terminal:
        return {"status": "needs_user_terminal", "argv": argv,
                "reviewable_command": shlex.join(argv), "remote_path": remote_path,
                "executed": False,
                "next": "사용자 소유 터미널에서 이 명령을 검토·실행하거나 --execute를 직접 호출하세요."}
    result = runner(argv, check=False)
    return {"status": "setup_executed_unverified" if result.returncode == 0 else "failed",
            "exit_code": result.returncode, "remote_path": remote_path, "executed": True,
            "live_verified": False}


def setup_remote(config, config_path, *, execute=False, terminal=None,
                 runner=subprocess.run, root=None):
    staged = deploy(config, config_path, runner=runner, root=root)
    result = resume(config, staged["remote_path"], execute=execute,
                    terminal=terminal, runner=runner)
    result["deployed"] = True
    return result


def tunnel(config, *, selected, local_port=OMNIROUTE_REMOTE_PORT, execute=False,
           terminal=None, runner=subprocess.run):
    if selected is not True:
        raise ValueError("OmniRoute를 선택한 설정에서만 tunnel을 만들 수 있습니다.")
    local_port = validate_port(local_port)
    if local_port < 1024:
        raise ValueError("local-port는 권한이 필요 없는 1024~65535 범위여야 합니다.")
    base = _base_ssh(config, "yes")
    forward = f"127.0.0.1:{local_port}:127.0.0.1:{OMNIROUTE_REMOTE_PORT}"
    argv = [*base[:-1], "-o", "ExitOnForwardFailure=yes", "-N", "-L", forward, base[-1]]
    terminal = (sys.stdin.isatty() and sys.stdout.isatty()) if terminal is None else terminal
    if not execute or not terminal:
        return {"status": "needs_user_terminal", "argv": argv,
                "reviewable_command": shlex.join(argv), "executed": False,
                "local_url": f"http://127.0.0.1:{local_port}",
                "remote_bind": f"127.0.0.1:{OMNIROUTE_REMOTE_PORT}"}
    result = runner(argv, check=False)
    return {"status": "tunnel_closed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode, "executed": True,
            "local_url": f"http://127.0.0.1:{local_port}",
            "remote_bind": f"127.0.0.1:{OMNIROUTE_REMOTE_PORT}"}


def _section(output, name):
    marker = f"--- {name} ---"
    tail = output.split(marker, 1)[1] if marker in output else ""
    return tail.split("---", 1)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe SSH access and explicit kit staging")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "keygen", "trust", "probe", "deploy", "setup", "resume", "tunnel"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--config", required=True)
        if action == "trust":
            cmd.add_argument("--fingerprint", required=True,
                             help="independently verified SHA256 host fingerprint")
        if action == "resume":
            cmd.add_argument("--remote-path", required=True)
        if action == "tunnel":
            cmd.add_argument("--local-port", type=int, default=OMNIROUTE_REMOTE_PORT)
        if action in {"setup", "resume", "tunnel"}:
            cmd.add_argument("--execute", action="store_true",
                             help="run only from the user's own interactive terminal")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.action == "plan": result = plan(config)
        elif args.action == "keygen": result = generate_key(config)
        elif args.action == "trust": result = trust(config, args.fingerprint)
        elif args.action == "probe": result = probe(config)
        elif args.action == "deploy": result = deploy(config, args.config)
        elif args.action == "setup": result = setup_remote(config, args.config, execute=args.execute)
        elif args.action == "resume": result = resume(
            config, args.remote_path, execute=args.execute)
        else:
            selected = _read_full_config(args.config).get("omniroute_enabled", False)
            result = tunnel(config, selected=selected, local_port=args.local_port,
                            execute=args.execute)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in ("failed", "blocked") else 2
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
