"""Shared atomic file-write helper for kit-setup state and config files."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(
    path: Path | str,
    content: str | bytes,
    *,
    mode: int | None = None,
    fsync: bool = False,
    prefix: str = ".kit-",
) -> None:
    """Write ``content`` to ``path`` atomically via a same-directory temp file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    is_bytes = isinstance(content, (bytes, bytearray))
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=target.parent)
    try:
        with os.fdopen(fd, "wb" if is_bytes else "w", encoding=None if is_bytes else "utf-8") as f:
            f.write(content)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
