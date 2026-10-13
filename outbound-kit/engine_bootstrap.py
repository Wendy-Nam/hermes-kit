#!/usr/bin/env python3
"""Plan, verify, and explicitly execute the reviewed pinned Hermes installer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.request

import paths as runtime_paths


UPSTREAM = "https://github.com/NousResearch/hermes-agent"
TAG = "v0.21.7"
COMMIT = "71d34bad1045610252eda02ee79549436896e784"
BRANCH = "main"
MAX_INSTALLER_BYTES = 256 * 1024
ARTIFACTS = {
    "posix": {
        "filename": "hermes-install-0.21.7.sh",
        "upstream_path": "scripts/install.sh",
        "sha256": "034845e34289813ff5fb7fd3e071ec69f6b14aee8ba297a477b31dda6374cb86",
    },
    "windows": {
        "filename": "hermes-install-0.21.7.ps1",
        "upstream_path": "scripts/install.ps1",
        "sha256": "61824d6b47be29ab793d0e72872cf56cd7a3e99cbe40abeb177a6c9eef52f485",
    },
}
for _artifact in ARTIFACTS.values():
    _artifact["url"] = (
        f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{COMMIT}/"
        f"{_artifact['upstream_path']}"
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def target_platform(requested: str = "auto") -> str:
    return runtime_paths.target_platform(requested)


def platform_detail(target: str) -> str:
    if target == "windows":
        return "windows-native"
    if sys.platform == "darwin":
        return "macos"
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        version = ""
    return "wsl2" if "microsoft" in version.casefold() else "linux"


def default_home(target: str) -> Path:
    return runtime_paths.default_home(target)


def resolve_paths(target: str, home: str | None, install_dir: str | None) -> tuple[Path, Path]:
    resolved_home = runtime_paths.normalize_home(home, target)
    resolved_install = (Path(install_dir).expanduser().absolute() if install_dir
                        else resolved_home / "hermes-agent")
    if resolved_home == Path(resolved_home.anchor):
        raise ValueError("Hermes home에 파일시스템 루트를 사용할 수 없습니다.")
    try:
        resolved_install.relative_to(resolved_home)
    except ValueError:
        raise ValueError("install-dir는 전용 Hermes home 안에 있어야 합니다.") from None
    return resolved_home, resolved_install


def _path_state(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if not path.exists():
        return "missing"
    if path.is_dir():
        try:
            return "empty_directory" if not any(path.iterdir()) else "nonempty_directory"
        except OSError:
            return "unreadable_directory"
    return "file"


def has_symlink_component(path: Path) -> bool:
    current = path.absolute()
    return any(candidate.is_symlink() or
               (callable(getattr(candidate, "is_junction", None)) and candidate.is_junction())
               for candidate in (current, *current.parents))


def build_plan(target: str, home: Path, install_dir: Path,
               desktop_mode: str = "terminal") -> dict[str, Any]:
    if desktop_mode not in {"app", "terminal"}:
        raise ValueError("desktop_mode은 app 또는 terminal이어야 합니다.")
    home_state = _path_state(home)
    install_state = _path_state(install_dir)
    checkout = install_state == "nonempty_directory" and (install_dir / ".git").is_dir()
    scoped_launcher = runtime_paths.resolve_hermes(home, target, required=False)
    conflicts: list[str] = []
    if (home_state in {"symlink", "file", "unreadable_directory"} or
            has_symlink_component(home) or has_symlink_component(install_dir)):
        conflicts.append("dedicated_home_is_not_a_safe_directory")
    if install_state not in {"missing", "empty_directory"}:
        conflicts.append("install_dir_already_exists")
    if scoped_launcher:
        conflicts.append("scoped_hermes_launcher_exists")
    artifact = ARTIFACTS[target]
    return {
        "schema_version": 1,
        "action": "plan_only",
        "python_3_11_plus": sys.version_info >= (3, 11),
        "supported": platform_detail(target) in {"linux", "macos", "wsl2", "windows-native"},
        "platform": platform_detail(target),
        "architecture": platform.machine(),
        "upstream": UPSTREAM,
        "release_tag": TAG,
        "commit": COMMIT,
        "installer": {"url": artifact["url"], "sha256": artifact["sha256"],
                      "complete_file_reviewed": True},
        "paths": {"hermes_home": str(home), "install_dir": str(install_dir),
                  "home_state": home_state, "install_state": install_state,
                  "existing_checkout": checkout,
                  "scoped_launcher": str(scoped_launcher) if scoped_launcher else None},
        "conflicts": conflicts,
        "desktop_mode": desktop_mode,
        "ready_to_download": not conflicts and sys.version_info >= (3, 11),
        "will_not_execute": True,
        "would_modify_if_user_executes": [
            str(home), str(install_dir),
            "dedicated-home .local/bin and shell files" if target == "posix"
            else "Windows User PATH registry value for the dedicated-home bin",
        ],
        "installer_behavior_reviewed": [
            "clones the pinned commit from main into install_dir",
            "downloads hash-pinned uv and a managed Python 3.14 runtime",
            "installs lockfile-selected Python/Node/npm/ripgrep/FFmpeg dependencies",
            "creates missing .env/config.yaml but preserves existing files",
            "publishes launchers under the effective HOME; install action isolates POSIX HOME",
            "non-interactive mode skips model setup and gateway service installation",
            "browser and computer-use payloads are omitted by the generated command",
            "desktop product is built only when desktop_mode=app",
        ],
    }


def verify_artifact(path: str | Path, target: str) -> dict[str, Any]:
    artifact_path = Path(path).expanduser().absolute()
    if has_symlink_component(artifact_path) or not artifact_path.is_file():
        raise ValueError("installer artifact는 심볼릭 링크가 아닌 일반 파일이어야 합니다.")
    raw = artifact_path.read_bytes()
    if len(raw) > MAX_INSTALLER_BYTES:
        raise ValueError("installer artifact가 예상 크기 제한을 넘었습니다.")
    actual = sha256_bytes(raw)
    expected = ARTIFACTS[target]["sha256"]
    if actual != expected:
        raise ValueError(f"installer SHA-256 불일치: expected {expected}, got {actual}")
    return {"path": str(artifact_path), "sha256": actual, "verified": True,
            "commit": COMMIT, "target": target}


def installer_capabilities(path: str | Path, target: str) -> dict[str, bool]:
    verify_artifact(path, target)
    text = Path(path).read_text(encoding="utf-8-sig")
    if target == "posix":
        capabilities = {
            "home": "--hermes-home" in text, "install_dir": "--dir" in text,
            "commit": "--commit" in text, "non_interactive": "--non-interactive" in text,
            "desktop": "--include-desktop" in text,
            "skip_browser": "--skip-browser" in text,
            "skip_computer_use": "--skip-computer-use" in text,
        }
    else:
        capabilities = {
            "home": "HermesHome" in text, "install_dir": "InstallDir" in text,
            "commit": "Commit" in text, "non_interactive": "NonInteractive" in text,
            "desktop": "IncludeDesktop" in text,
            "skip_browser": "SkipBrowser" in text,
            "skip_computer_use": "SkipComputerUse" in text,
        }
    return capabilities


def installer_argv(target: str, artifact_path: str | Path, home: Path, install_dir: Path,
                   desktop_mode: str, *, which=shutil.which) -> list[str]:
    if desktop_mode not in {"app", "terminal"}:
        raise ValueError("desktop_mode은 app 또는 terminal이어야 합니다.")
    capabilities = installer_capabilities(artifact_path, target)
    required = {"home", "install_dir", "commit", "non_interactive",
                "skip_browser", "skip_computer_use"}
    if desktop_mode == "app":
        required.add("desktop")
    missing = sorted(name for name in required if not capabilities.get(name))
    if missing:
        raise ValueError("고정 installer가 필요한 옵션을 지원하지 않습니다: " + ", ".join(missing))
    artifact = str(Path(artifact_path).expanduser().absolute())
    if target == "posix":
        argv = [which("bash") or "bash", artifact, "--branch", BRANCH, "--commit", COMMIT,
                "--hermes-home", str(home), "--dir", str(install_dir),
                "--non-interactive", "--skip-browser", "--skip-computer-use"]
        if desktop_mode == "app":
            argv.append("--include-desktop")
        return argv
    powershell = which("powershell.exe") or which("powershell")
    if not powershell:
        raise ValueError("Windows PowerShell을 찾을 수 없습니다.")
    argv = [powershell, "-NoProfile", "-File", artifact,
            "-Branch", BRANCH, "-Commit", COMMIT, "-HermesHome", str(home),
            "-InstallDir", str(install_dir), "-NonInteractive", "-SkipBrowser", "-SkipComputerUse"]
    if desktop_mode == "app":
        argv.append("-IncludeDesktop")
    return argv


def install_engine(target: str, artifact_path: str | Path, home: Path, install_dir: Path,
                   desktop_mode: str, *, runner=subprocess.run, which=shutil.which) -> dict[str, Any]:
    """Explicit mutation: install only into a new dedicated home and verify its scoped runtime."""
    if sys.version_info < (3, 11):
        raise ValueError("설치 도우미는 Python 3.11 이상이 필요합니다.")
    plan = build_plan(target, home, install_dir, desktop_mode)
    if plan["conflicts"]:
        raise ValueError("기존 전용 설치를 보존했습니다: " + ", ".join(plan["conflicts"]))
    argv = installer_argv(target, artifact_path, home, install_dir, desktop_mode, which=which)
    environment = os.environ.copy()
    environment["HERMES_HOME"] = str(home)
    environment["HERMES_RUNTIME_DIR"] = str(home / "tools")
    # POSIX upstream publishes ~/.local launchers and shell lines. Point HOME at the
    # dedicated root so it cannot modify the operator's shared shell configuration.
    if target == "posix":
        environment["HOME"] = str(home)
    installed = runner(argv, check=False, env=environment)
    if installed.returncode != 0:
        raise ValueError(f"고정 Hermes installer가 실패했습니다 (exit {installed.returncode}).")
    git = which("git")
    if not git:
        raise ValueError("설치 결과 commit 검증에 필요한 git을 찾을 수 없습니다.")
    revision = runner([git, "-C", str(install_dir), "rev-parse", "HEAD"], check=False,
                      capture_output=True, text=True, timeout=30)
    if revision.returncode != 0 or revision.stdout.strip() != COMMIT:
        raise ValueError("설치 결과 checkout commit이 검토한 고정값과 다릅니다.")
    launcher = runtime_paths.resolve_hermes(home, target, required=True)
    managed_python = runtime_paths.resolve_python(home, target, required=True)
    python_checked = runner([str(managed_python), "--version"], check=False,
                            capture_output=True, text=True, timeout=30)
    if python_checked.returncode != 0:
        raise ValueError("전용 Hermes managed Python 검증이 실패했습니다.")
    checked = runner([str(launcher), "--help"], check=False, capture_output=True,
                     text=True, timeout=60, env={**environment, "HERMES_HOME": str(home)})
    if checked.returncode != 0:
        raise ValueError("전용 Hermes launcher 검증이 실패했습니다.")
    desktop = None
    if desktop_mode == "app":
        desktop = runtime_paths.resolve_desktop_app(home, target, required=True)
    return {"status": "installed_verified", "commit": COMMIT, "hermes_home": str(home),
            "install_dir": str(install_dir), "launcher": str(launcher),
            "managed_python": str(managed_python),
            "desktop_mode": desktop_mode, "desktop_app": str(desktop) if desktop else None,
            "model_verified": False, "gateway_verified": False}


def download(target: str, output: str) -> dict[str, Any]:
    folder = Path(output).expanduser().absolute()
    if has_symlink_component(folder) or (folder.exists() and not folder.is_dir()):
        raise ValueError("download 출력은 심볼릭 링크가 아닌 디렉터리여야 합니다.")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact = ARTIFACTS[target]
    destination = folder / artifact["filename"]
    receipt = destination.with_suffix(destination.suffix + ".verified.json")
    if destination.is_symlink():
        raise ValueError("기존 installer artifact 심볼릭 링크를 덮어쓰지 않습니다.")
    if receipt.is_symlink():
        raise ValueError("검증 receipt 심볼릭 링크를 덮어쓰지 않습니다.")
    if destination.exists():
        return {**verify_artifact(destination, target), "downloaded": False,
                "message": "기존 검증 완료 artifact를 재사용합니다."}
    request = urllib.request.Request(artifact["url"], headers={"User-Agent": "Hermes-Outbound-Kit/0.1"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            raw = response.read(MAX_INSTALLER_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise ValueError(f"pinned installer download 실패: {type(exc).__name__}") from None
    if len(raw) > MAX_INSTALLER_BYTES:
        raise ValueError("downloaded installer가 예상 크기 제한을 넘었습니다.")
    actual = sha256_bytes(raw)
    if actual != artifact["sha256"]:
        raise ValueError(f"downloaded installer SHA-256 불일치: expected {artifact['sha256']}, got {actual}")
    fd, temporary = tempfile.mkstemp(prefix=".engine-installer-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    receipt_body = json.dumps({
        "schema_version": 1, "upstream": UPSTREAM, "release_tag": TAG,
        "commit": COMMIT, "source_url": artifact["url"], "sha256": actual,
        "complete_file_reviewed": True, "executed": False,
    }, indent=2) + "\n"
    receipt_fd, receipt_tmp = tempfile.mkstemp(prefix=".engine-receipt-", dir=folder)
    try:
        with os.fdopen(receipt_fd, "w", encoding="utf-8") as stream:
            stream.write(receipt_body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(receipt_tmp, 0o600)
        os.replace(receipt_tmp, receipt)
    finally:
        if os.path.exists(receipt_tmp):
            os.unlink(receipt_tmp)
    os.chmod(receipt, 0o600)
    return {"path": str(destination), "receipt": str(receipt), "sha256": actual,
            "verified": True, "downloaded": True, "executed": False}


def shell_command(target: str, artifact_path: str, home: Path, install_dir: Path,
                  desktop_mode: str = "terminal") -> str:
    plan = build_plan(target, home, install_dir, desktop_mode)
    if plan["conflicts"]:
        raise ValueError("기존 설치/launcher 충돌이 있어 실행 명령을 만들지 않습니다: " +
                         ", ".join(plan["conflicts"]))
    values = installer_argv(target, artifact_path, home, install_dir, desktop_mode,
                            which=lambda name: "powershell.exe" if name.startswith("powershell") else name)
    if target == "posix":
        return " ".join(shlex.quote(value) for value in values)
    quote = lambda value: "'" + value.replace("'", "''") + "'"
    return "& " + " ".join(quote(value) if not value.startswith("-") else value
                             for value in values)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Plan/download/install the reviewed pinned Hermes engine")
    sub = ap.add_subparsers(dest="action", required=True)
    for action in ("plan", "command", "install", "app-command"):
        command = sub.add_parser(action)
        command.add_argument("--platform", choices=("auto", "posix", "windows"), default="auto")
        command.add_argument("--home")
        command.add_argument("--install-dir")
        command.add_argument("--desktop-mode", choices=("app", "terminal"), default="terminal")
        if action in {"command", "install"}:
            command.add_argument("--artifact", required=True)
    download_parser = sub.add_parser("download")
    download_parser.add_argument("--platform", choices=("auto", "posix", "windows"), default="auto")
    download_parser.add_argument("--output", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--platform", choices=("auto", "posix", "windows"), default="auto")
    verify_parser.add_argument("--artifact", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        target = target_platform(args.platform)
        if args.action == "download":
            result = download(target, args.output)
        elif args.action == "verify":
            result = verify_artifact(args.artifact, target)
        else:
            home, install_dir = resolve_paths(target, args.home, args.install_dir)
            result = build_plan(target, home, install_dir, args.desktop_mode)
            if args.action == "command":
                result = {"private_terminal_command": shell_command(
                    target, args.artifact, home, install_dir, args.desktop_mode),
                    "executed": False, "next": "사용자가 비공개 터미널에서 직접 실행하세요."}
            elif args.action == "install":
                result = install_engine(target, args.artifact, home, install_dir, args.desktop_mode)
            elif args.action == "app-command":
                result = {"argv": runtime_paths.desktop_command(home, target),
                          "executed": False, "desktop_app": str(
                              runtime_paths.resolve_desktop_app(home, target))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
