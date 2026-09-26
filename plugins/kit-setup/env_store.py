"""Atomic, permission-preserving .env updates.

The .env file is the only place student keys live, so the two properties that
matter are: never lose or reorder what is already there, and never leave a
half-written file behind if the process dies mid-write.
"""
import os
import tempfile
from pathlib import Path


def get_env(path: Path) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text().splitlines() if Path(path).exists() else []:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v
    return out


def set_env(path: Path, updates: dict[str, str]) -> None:
    path = Path(path)
    for k, v in updates.items():
        # A newline in a value would let a modal submit forge extra env lines; an "=" in a key
        # would silently redirect the write. Both are rejected rather than escaped.
        if not k or "\n" in v or "\r" in v or "\n" in k or "=" in k:
            raise ValueError(f"invalid env entry: {k!r}")
    lines = path.read_text().splitlines() if path.exists() else []
    todo = dict(updates)
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k in todo:
            lines[i] = f"{k}={todo.pop(k)}"
    lines += [f"{k}={v}" for k, v in todo.items()]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)   # atomic: a crash never leaves a half-written .env
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def is_secure(path: Path) -> bool:
    """True when the file exists and is not group/other readable."""
    p = Path(path)
    return p.exists() and not (os.stat(p).st_mode & 0o077)
