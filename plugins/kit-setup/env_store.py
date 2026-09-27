"""Atomic, permission-preserving .env updates.

The .env file is the only place student keys live, so the two properties that
matter are: never lose or reorder what is already there, and never leave a
half-written file behind if the process dies mid-write.
"""
import os
import fcntl
from functools import wraps
import tempfile
from pathlib import Path



def _serialized(fn):
    @wraps(fn)
    def wrapped(path, *args, **kwargs):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        with path.with_name('.kit-env.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            return fn(path,*args,**kwargs)
    return wrapped

def get_env(path: Path) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text().splitlines() if Path(path).exists() else []:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v
    return out


@_serialized
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


@_serialized
def drop_env(path: Path, names) -> list[str]:
    """Remove keys from .env, leaving every other line byte-identical (comments included).

    Rewritten rather than edited in place, and atomically like set_env — a disconnect that
    dies halfway must not leave a truncated credentials file behind.
    """
    path = Path(path)
    if not path.exists():
        return []
    want = set(names)
    lines, removed = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() in want:
            removed.append(s.split("=", 1)[0].strip())
            continue
        lines.append(line)
    if not removed:
        return []
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n" if lines else "")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return removed


def is_secure(path: Path) -> bool:
    """True when the file exists and is not group/other readable."""
    p = Path(path)
    return p.exists() and not (os.stat(p).st_mode & 0o077)
