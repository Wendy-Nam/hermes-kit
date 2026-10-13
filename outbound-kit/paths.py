#!/usr/bin/env python3
"""Canonical, installation-scoped paths for Hermes Outbound Kit."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Mapping
import json


def target_platform(requested: str = "auto") -> str:
    if requested not in {"auto", "posix", "windows"}:
        raise ValueError("platform은 auto/posix/windows 중 하나여야 합니다.")
    return ("windows" if os.name == "nt" else "posix") if requested == "auto" else requested


def default_home(target: str = "auto", *, env: Mapping[str, str] | None = None,
                 user_home: str | Path | None = None) -> Path:
    target = target_platform(target)
    environment = os.environ if env is None else env
    if target == "windows":
        base = environment.get("LOCALAPPDATA")
        if not base:
            raise ValueError("LOCALAPPDATA가 없어 Windows Hermes home을 정할 수 없습니다.")
        return Path(base) / "hermes-outbound"
    return Path(user_home) / ".hermes-outbound" if user_home is not None else Path.home() / ".hermes-outbound"


def normalize_home(home: str | Path | None = None, target: str = "auto") -> Path:
    path = Path(home).expanduser().absolute() if home is not None else default_home(target).absolute()
    if path == Path(path.anchor):
        raise ValueError("Hermes home에 파일시스템 루트를 사용할 수 없습니다.")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Hermes home 경로에 심볼릭 링크가 있습니다.")
    return path


def install_dir(home: str | Path) -> Path:
    return Path(home).absolute() / "hermes-agent"


def _scoped_file(candidate: Path, home: Path, *, executable: bool) -> bool:
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        candidate.resolve().relative_to(home.resolve())
    except ValueError:
        return False
    return os.name == "nt" or not executable or os.access(candidate, os.X_OK)


def resolve_hermes(home: str | Path, target: str = "auto", *, required: bool = True) -> Path | None:
    """Resolve only a launcher owned by *home*, never an ambient PATH command."""
    target = target_platform(target)
    root = normalize_home(home, target)
    if target == "windows":
        candidates = (root / "bin/hermes.exe", root / "bin/hermes.cmd",
                      install_dir(root) / ".hermes/bin/hermes.exe")
    else:
        candidates = (install_dir(root) / ".hermes/bin/hermes", root / "bin/hermes")
    for candidate in candidates:
        if _scoped_file(candidate, root, executable=target != "windows"):
            return candidate
    if required:
        raise FileNotFoundError(f"전용 Hermes launcher를 찾지 못했습니다: {root}")
    return None


def resolve_python(home: str | Path, target: str = "auto", *, required: bool = True) -> Path | None:
    """Resolve the installation-owned Python; never fall back to sys.executable/PATH."""
    target = target_platform(target)
    root = normalize_home(home, target)
    checkout_runtime = install_dir(root) / ".hermes"
    candidates = ([checkout_runtime / "Scripts/python.exe", checkout_runtime / "bin/python.exe"]
                  if target == "windows" else
                  [checkout_runtime / "bin/python3", checkout_runtime / "bin/python"])
    facts = root / "tools/facts.json"
    if not facts.is_symlink() and facts.is_file() and facts.stat().st_size <= 1024 * 1024:
        try:
            data = json.loads(facts.read_text(encoding="utf-8-sig"))
            entry = ((data.get("packages") or {}).get("python") or {}).get("entry")
        except (OSError, ValueError, AttributeError):
            entry = None
        if isinstance(entry, str):
            relative = Path(entry)
            if not relative.is_absolute() and ".." not in relative.parts:
                managed = root / "tools" / relative
                candidates.extend(([managed / "python.exe"] if target == "windows" else
                                   [managed / "bin/python3", managed / "bin/python"]))
    for candidate in candidates:
        if _scoped_file(candidate, root, executable=target != "windows"):
            return candidate
    if required:
        raise FileNotFoundError(f"전용 Hermes managed Python을 찾지 못했습니다: {root}")
    return None


def _desktop_candidates(root: Path, target: str) -> list[Path]:
    release = install_dir(root) / "apps/desktop/release"
    if target == "windows":
        return [release / folder / "Hermes.exe"
                for folder in ("win-unpacked", "win-ia32-unpacked", "win-arm64-unpacked")]
    if sys.platform == "darwin":
        return sorted(release.glob("mac*/Hermes.app/Contents/MacOS/Hermes"))
    return [release / folder / name for folder in ("linux-unpacked", "linux-arm64-unpacked")
            for name in ("hermes", "Hermes")]


def resolve_desktop_app(home: str | Path, target: str = "auto", *, required: bool = True) -> Path | None:
    target = target_platform(target)
    root = normalize_home(home, target)
    for candidate in _desktop_candidates(root, target):
        if _scoped_file(candidate, root, executable=target != "windows"):
            return candidate
    if required:
        raise FileNotFoundError(f"전용 Hermes Desktop 산출물을 찾지 못했습니다: {install_dir(root)}")
    return None


def desktop_command(home: str | Path, target: str = "auto") -> list[str]:
    """Official CLI entry for launching an already-built desktop product."""
    resolve_desktop_app(home, target, required=True)
    return [str(resolve_hermes(home, target, required=True)), "desktop", "--skip-build"]
