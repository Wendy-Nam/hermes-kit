#!/usr/bin/env python3
"""Install the audited OMH 2.0.5 source into an isolated Hermes home.

This deliberately does not execute the upstream curl/PowerShell installers.
It downloads one immutable source archive, verifies its digest and archive
layout, installs it into a private venv, and invokes the pinned OMH setup CLI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request


VERSION = "2.0.5"
REPOSITORY = "https://github.com/rlaope/oh-my-hermes"
COMMIT = "b84f096e59d50fc933ed4b43fd36675e8cff593a"
ARCHIVE_SHA256 = "3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a"
ARCHIVE_URL = f"https://codeload.github.com/rlaope/oh-my-hermes/tar.gz/{COMMIT}"
ARCHIVE_ROOT = f"oh-my-hermes-{COMMIT}"
PLUGIN_HOOK_SHA256 = "a0382ed1cf9f78f0cf9202395c027cd29a01953a3b7983d2142747d764b60e3b"
RECEIPT = ".kit-components.json"
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024
MAX_MEMBERS = 12000
MODEL_CATEGORIES = {
    "ultrabrain", "deep", "architect", "unspecified-high", "unspecified-low",
    "quick", "writing", "visual-engineering", "artistry", "capable",
    "simple-work", "deep-work",
}
SETUP_SURFACE_FILES = (
    "skins/.omh-skin.manifest.json", "skins/omh-amber.yaml",
    "skins/omh-crimson.yaml", "skins/omh-mono.yaml", "skins/omh.yaml",
    "tui-widgets/.omh-status.manifest.json", "tui-widgets/omh-status.mjs",
)


class OmhSetupError(ValueError):
    pass


def _safe_home(value: str | Path) -> Path:
    home = Path(value).expanduser().absolute()
    for part in (home, *home.parents):
        if part.is_symlink():
            raise OmhSetupError(f"설치 경로에 심볼릭 링크가 있습니다: {part}")
    return home


def _load_config(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or type(data.get("omh_enabled", False)) is not bool:
        raise OmhSetupError("omh_enabled는 true/false여야 합니다.")
    return data


def _venv_python(runtime: Path) -> Path:
    return runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _read_receipt(home: Path) -> dict:
    try:
        raw = json.loads((home / RECEIPT).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _matching_receipt(home: Path) -> bool:
    item = (_read_receipt(home).get("components") or {}).get("omh-upstream") or {}
    return (
        item.get("version") == VERSION
        and item.get("source_commit") == COMMIT
        and item.get("archive_sha256") == ARCHIVE_SHA256
        and item.get("plugin_hook_sha256") == PLUGIN_HOOK_SHA256
        and item.get("plugin_import_smoke") is True
        and item.get("plugin_register_smoke") is True
    )


def _atomic_json(path: Path, payload: dict) -> None:
    if path.is_symlink():
        raise OmhSetupError(f"상태 파일 링크는 덮어쓰지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".omh-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_receipt(home: Path, setup_payload: dict) -> None:
    path = home / RECEIPT
    body = _read_receipt(home)
    components = body.setdefault("components", {})
    if not isinstance(components, dict):
        raise OmhSetupError(f"기존 {RECEIPT} 형식을 보존했습니다. 수동 확인이 필요합니다.")
    existing = components.get("omh-upstream")
    if existing and not _matching_receipt(home):
        raise OmhSetupError("알 수 없는 기존 OMH 영수증을 보존했습니다.")
    plugin = setup_payload.get("plugin_distribution") or {}
    components["omh-upstream"] = {
        "version": VERSION,
        "repository": REPOSITORY,
        "source_commit": COMMIT,
        "archive_sha256": ARCHIVE_SHA256,
        "plugin_hook_sha256": PLUGIN_HOOK_SHA256,
        "skill_profile": "core",
        "plugin_import_smoke": plugin.get("import_smoke") is True,
        "plugin_register_smoke": plugin.get("register_smoke") is True,
    }
    body["schema_version"] = "hermes_outbound_components/v1"
    _atomic_json(path, body)


def _download(path: Path, *, opener=None) -> None:
    # This is a public, non-credentialed artifact. Honor the operator's normal
    # HTTPS proxy configuration; integrity is enforced by the pinned SHA-256.
    opener = opener or urllib.request.build_opener()
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "hermes-outbound-kit/1"})
    digest = hashlib.sha256()
    count = 0
    with opener.open(request, timeout=45) as response, path.open("xb") as stream:
        if getattr(response, "status", 200) != 200:
            raise OmhSetupError(f"OMH 다운로드 HTTP 오류: {response.status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_DOWNLOAD:
                raise OmhSetupError("OMH 아카이브가 허용 크기를 초과했습니다.")
            digest.update(chunk)
            stream.write(chunk)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise OmhSetupError("OMH 아카이브 SHA-256이 고정값과 다릅니다.")


def _extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > MAX_MEMBERS:
            raise OmhSetupError("OMH 아카이브 파일 수가 허용 범위를 초과했습니다.")
        expanded = 0
        for member in members:
            name = member.name.replace("\\", "/")
            parts = Path(name).parts
            if not parts or parts[0] != ARCHIVE_ROOT or name.startswith("/") or ".." in parts:
                raise OmhSetupError(f"안전하지 않은 아카이브 경로: {name}")
            if member.issym() or member.islnk() or member.isdev():
                raise OmhSetupError(f"링크/장치 항목은 설치하지 않습니다: {name}")
            if not (member.isdir() or member.isfile()):
                raise OmhSetupError(f"지원하지 않는 아카이브 항목: {name}")
            expanded += member.size
            if expanded > MAX_EXPANDED:
                raise OmhSetupError("OMH 압축 해제 크기가 허용 범위를 초과했습니다.")
        bundle.extractall(destination, members=members, filter="data")
    source = destination / ARCHIVE_ROOT
    required = [source / "pyproject.toml", source / "src/plugin_bundle/omh/plugin.yaml",
                source / "src/plugin_bundle/omh/hooks/tool_hooks.py"]
    if not all(path.is_file() for path in required):
        raise OmhSetupError("OMH 아카이브의 필수 파일이 없습니다.")
    hook_hash = hashlib.sha256(required[-1].read_bytes()).hexdigest()
    if hook_hash != PLUGIN_HOOK_SHA256:
        raise OmhSetupError("OMH 플러그인 hook 해시가 검토본과 다릅니다.")
    return source


def plan(data: dict, home: str | Path) -> dict:
    root = _safe_home(home)
    runtime = root / ".omh-runtime" / VERSION
    existing_unknown = ((root / ".omh").exists() or (root / "plugins/omh").exists() or runtime.exists()) and not _matching_receipt(root)
    return {
        "schema_version": "hermes_outbound_omh_plan/v1",
        "selected": data.get("omh_enabled", False) is True,
        "home": str(root), "omh_home": str(root / ".omh"), "runtime": str(runtime),
        "source": {"repository": REPOSITORY, "version": VERSION, "commit": COMMIT,
                   "archive_sha256": ARCHIVE_SHA256, "archive_url": ARCHIVE_URL},
        "python_3_11_plus": sys.version_info >= (3, 11),
        "existing_unknown_preserved": existing_unknown,
        "actions": ["verify immutable archive", "create isolated venv", "install pinned source",
                    "run non-interactive core setup", "run OMH doctor", "record receipt"],
        "not_claimed": ["Hermes host loaded the plugin", "route applied", "restart verified", "live delegated task"],
    }


def _run(argv: list[str], *, timeout: int, runner=subprocess.run) -> subprocess.CompletedProcess:
    return runner(argv, capture_output=True, text=True, timeout=timeout, check=False)


def _distribution_version(python: Path, *, runner=subprocess.run) -> str:
    if not python.is_file():
        return ""
    proc = _run([str(python), "-P", "-c",
                 "import importlib.metadata as m; print(m.version('oh-my-hermes'))"],
                timeout=30, runner=runner)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _install_verified_source(source: Path, python: Path, *, runner=subprocess.run) -> None:
    """Materialize the audited pure-Python distribution without build downloads.

    OMH 2.0.5 declares zero runtime dependencies. Reading its pinned setuptools
    package map and copying those directories avoids an unpinned setuptools/wheel
    bootstrap while retaining the package data contained in each source tree.
    """
    metadata = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata.get("project") or {}
    if (project.get("name") != "oh-my-hermes" or project.get("version") != VERSION
            or project.get("dependencies") != [] or project.get("license") != "MIT"):
        raise OmhSetupError("고정 OMH pyproject의 이름/버전/의존성/라이선스가 검토 계약과 다릅니다.")
    package_map = ((metadata.get("tool") or {}).get("setuptools") or {}).get("package-dir")
    if not isinstance(package_map, dict) or not package_map:
        raise OmhSetupError("고정 OMH setuptools package map이 없습니다.")
    proc = _run([str(python), "-P", "-c",
                 "import sysconfig; print(sysconfig.get_paths()['purelib'])"], timeout=30, runner=runner)
    if proc.returncode:
        raise OmhSetupError("격리 환경 site-packages 경로를 확인하지 못했습니다.")
    purelib = Path(proc.stdout.strip())
    if not purelib.is_dir() or runtime_escape(purelib, python):
        raise OmhSetupError("격리 환경 밖의 site-packages 경로를 거부했습니다.")
    source_root = source.resolve()
    for package, relative in sorted(package_map.items(), key=lambda item: item[0].count(".")):
        if not isinstance(package, str) or not re.fullmatch(r"omh(?:\.[A-Za-z_][A-Za-z0-9_]*)*", package):
            raise OmhSetupError(f"지원하지 않는 package map 이름: {package}")
        relative_path = Path(relative)
        origin = (source / relative_path).resolve()
        if source_root not in origin.parents or not origin.is_dir():
            raise OmhSetupError(f"package map 경로가 source 밖이거나 없습니다: {relative}")
        target = purelib.joinpath(*package.split("."))
        shutil.copytree(origin, target, dirs_exist_ok=True)
    dist_info = purelib / f"oh_my_hermes-{VERSION}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: oh-my-hermes\nVersion: {VERSION}\n"
        "License-Expression: MIT\nRequires-Python: >=3.11\n\n",
        encoding="utf-8",
    )
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: hermes-outbound-kit-pinned-source\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n", encoding="utf-8")
    (dist_info / "entry_points.txt").write_text("[console_scripts]\nomh = omh.cli:main\n", encoding="utf-8")
    license_file = source / "LICENSE"
    if not license_file.is_file():
        raise OmhSetupError("고정 OMH LICENSE 파일이 없습니다.")
    licenses = dist_info / "licenses"
    licenses.mkdir()
    shutil.copy2(license_file, licenses / "LICENSE")


def runtime_escape(purelib: Path, python: Path) -> bool:
    """True when a reported purelib is not inside this venv's runtime root."""
    runtime = python.parent.parent.resolve()
    resolved = purelib.resolve()
    return runtime != resolved and runtime not in resolved.parents


def _restore_file(path: Path, before: bytes | None) -> None:
    if before is None:
        if path.exists() and not path.is_symlink() and path.is_file():
            path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(before)


def _remove_created_surface_files(root: Path) -> None:
    for relative in SETUP_SURFACE_FILES:
        path = root / relative
        if path.exists() and not path.is_symlink() and path.is_file():
            path.unlink()
    for directory in (root / "skins", root / "tui-widgets", root / "plugins"):
        try:
            directory.rmdir()
        except OSError:
            pass


def install(data: dict, home: str | Path, *, opener=None, runner=subprocess.run,
            after_receipt=None) -> dict:
    root = _safe_home(home)
    if data.get("omh_enabled", False) is not True:
        return {"selected": False, "installed": False, "status": "skipped"}
    if sys.version_info < (3, 11):
        raise OmhSetupError("OMH 2.0.5는 Python 3.11 이상이 필요합니다.")
    runtime = root / ".omh-runtime" / VERSION
    managed = root / ".omh"
    plugin = root / "plugins/omh"
    if _matching_receipt(root):
        result = check(data, root, runner=runner)
        if result["installed"]:
            result["status"] = "already_installed"
            return result
    if managed.exists() or plugin.exists() or runtime.exists():
        raise OmhSetupError("소유권을 확인할 수 없는 기존 OMH 파일을 보존했습니다. 전용 새 home을 사용하세요.")
    config = root / "config.yaml"
    receipt_path = root / RECEIPT
    surface_paths = [root / relative for relative in SETUP_SURFACE_FILES]
    if (config.is_symlink() or receipt_path.is_symlink() or plugin.is_symlink()
            or managed.is_symlink() or any(path.is_symlink() for path in surface_paths)):
        raise OmhSetupError("OMH 대상에 심볼릭 링크가 있어 설치를 중단했습니다.")
    occupied = [path for path in surface_paths if path.exists()]
    if occupied:
        names = ", ".join(str(path.relative_to(root)) for path in occupied)
        raise OmhSetupError(f"소유권을 확인할 수 없는 기존 OMH skin/widget 파일을 보존했습니다: {names}")
    root.mkdir(parents=True, exist_ok=True)
    config_before = config.read_bytes() if config.exists() else None
    receipt_before = receipt_path.read_bytes() if receipt_path.exists() else None
    created_runtime = False
    created_managed = False
    created_plugin = False
    try:
        with tempfile.TemporaryDirectory(prefix="omh-pinned-", dir=root) as temporary:
            temp = Path(temporary)
            archive = temp / "source.tar.gz"
            _download(archive, opener=opener)
            source = _extract(archive, temp / "source")
            proc = _run([sys.executable, "-m", "venv", str(runtime)], timeout=180, runner=runner)
            if proc.returncode:
                raise OmhSetupError("OMH 격리 환경 생성 실패: " + proc.stderr[-1000:])
            created_runtime = True
            python = _venv_python(runtime)
            _install_verified_source(source, python, runner=runner)
            observed_version = _distribution_version(python, runner=runner)
            if observed_version != VERSION:
                raise OmhSetupError(
                    f"설치된 oh-my-hermes distribution 버전이 {observed_version or 'unknown'}입니다; "
                    f"고정값 {VERSION}과 다릅니다."
                )
            argv = [str(python), "-P", "-m", "omh.cli", "--hermes-home", str(root),
                    "--omh-home", str(managed), "setup", "--core", "--yes",
                    "--no-interactive", "--no-omh-tui", "--no-menubar",
                    "--memory-mode", "off", "--default-executor", "hermes", "--json"]
            # Preflight proved both targets absent. From this point onward the
            # setup subprocess owns anything appearing there, including files
            # left behind when it times out or the runner itself raises.
            created_managed = True
            created_plugin = True
            proc = _run(argv, timeout=600, runner=runner)
            if proc.returncode:
                raise OmhSetupError("OMH core setup 실패: " + (proc.stderr or proc.stdout)[-2000:])
            try:
                payload = json.loads(proc.stdout)
            except ValueError as exc:
                raise OmhSetupError("OMH setup이 유효한 JSON 영수증을 반환하지 않았습니다.") from exc
            distribution = payload.get("plugin_distribution") or {}
            if payload.get("ok") is not True or distribution.get("import_smoke") is not True or distribution.get("register_smoke") is not True:
                raise OmhSetupError("OMH 플러그인 import/register smoke가 통과하지 않았습니다.")
            _write_receipt(root, payload)
            if after_receipt is not None:
                after_receipt(root)
    except Exception:
        _restore_file(config, config_before)
        _restore_file(receipt_path, receipt_before)
        if created_plugin and plugin.exists() and not plugin.is_symlink():
            shutil.rmtree(plugin)
        if created_managed and managed.exists() and not managed.is_symlink():
            shutil.rmtree(managed)
        if created_runtime and runtime.exists() and not runtime.is_symlink():
            shutil.rmtree(runtime)
        _remove_created_surface_files(root)
        raise
    result = check(data, root, runner=runner)
    result["status"] = "installed"
    return result


def _route_state(managed: Path) -> dict:
    result = {"model_chains": "absent", "provider_routes": "absent"}
    chain_path = managed / "routing/model-chains.json"
    provider_path = managed / "routing/model-providers.json"
    if chain_path.exists():
        try:
            raw = json.loads(chain_path.read_text(encoding="utf-8"))
            cats = raw.get("categories", {})
            result["model_chains"] = "valid" if (raw.get("schema_version") == "mixture_chain_overrides/v1" and isinstance(cats, dict) and not set(cats) - MODEL_CATEGORIES) else "invalid"
        except (OSError, ValueError, AttributeError):
            result["model_chains"] = "invalid"
    if provider_path.exists():
        try:
            raw = json.loads(provider_path.read_text(encoding="utf-8"))
            result["provider_routes"] = "valid" if raw.get("schema_version") == "model_provider_routes/v1" and isinstance(raw.get("models"), dict) else "invalid"
        except (OSError, ValueError, AttributeError):
            result["provider_routes"] = "invalid"
    return result


def check(data: dict, home: str | Path, *, runner=subprocess.run) -> dict:
    root = _safe_home(home)
    managed = root / ".omh"
    python = _venv_python(root / ".omh-runtime" / VERSION)
    plugin = root / "plugins/omh"
    hook = plugin / "hooks/tool_hooks.py"
    try:
        plugin_hook_verified = hashlib.sha256(hook.read_bytes()).hexdigest() == PLUGIN_HOOK_SHA256
    except OSError:
        plugin_hook_verified = False
    receipt_ok = _matching_receipt(root)
    distribution_version = _distribution_version(python, runner=runner)
    doctor = {"status": "pending", "ok": False}
    if python.is_file() and managed.is_dir():
        proc = _run([str(python), "-P", "-m", "omh.cli", "--hermes-home", str(root),
                     "--omh-home", str(managed), "doctor", "--json"], timeout=180, runner=runner)
        try:
            doctor_payload = json.loads(proc.stdout)
        except ValueError:
            doctor_payload = {}
        doctor = {"status": "passed" if proc.returncode == 0 and doctor_payload.get("ok") is True else "failed",
                  "ok": proc.returncode == 0 and doctor_payload.get("ok") is True}
    hermes = shutil.which("hermes")
    host = {"status": "pending", "reason": "Hermes executable not found; plugin load cannot be observed"}
    if hermes:
        proc = _run([hermes, "--version"], timeout=30, runner=runner)
        observed = (proc.stdout or proc.stderr).strip()[:300]
        match = re.search(r"(?<!\d)0\.21\.(\d+)(?!\d)", observed)
        declared = bool(match and int(match.group(1)) >= 1)
        host = {"status": "requires_live_restart_and_tool_probe", "executable": hermes,
                "version_output": observed, "declared_range_compatible": declared,
                "verified_baseline": "0.21.2-k18" in observed,
                "plugin_loaded": False, "tool_visible": False}
    routes = _route_state(managed)
    installed = receipt_ok and distribution_version == VERSION and plugin.is_dir() and plugin_hook_verified
    return {
        "schema_version": "hermes_outbound_omh_check/v1", "selected": data.get("omh_enabled", False) is True,
        "installed": installed, "receipt_verified": receipt_ok,
        "distribution_version": distribution_version,
        "plugin_files_present": plugin.is_dir(), "omh_doctor": doctor,
        "plugin_hook_verified": plugin_hook_verified,
        "host_verification": host, "routes": routes,
        "route_applied": False, "restart_verified": False, "live_delegated_task": False,
        "claim": "installed_and_static_smoke_only" if installed else "not_installed",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pinned OMH 2.0.5 installer for a dedicated Hermes home")
    parser.add_argument("action", choices=("plan", "install", "check"))
    parser.add_argument("--config", default="setup.json")
    parser.add_argument("--home", default="~/.hermes-outbound")
    args = parser.parse_args(argv)
    try:
        data = _load_config(args.config)
        if args.action == "plan":
            payload = plan(data, args.home)
        elif args.action == "install":
            payload = install(data, args.home)
        else:
            payload = check(data, args.home)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if args.action != "check" or payload.get("installed") or not payload.get("selected") else 1
    except (OmhSetupError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
