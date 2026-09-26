"""Shared helper for the voice/TTS patch set.

Every patch is: exact-string block replacement, applied to a temp file, ``py_compile``d, backed up
as ``<file>.bak-<ts>-hvp``, then swapped in. Idempotent via a marker string that only the patched
file contains. A non-unique anchor aborts *before* anything is written (wrong Hermes version).
"""
import argparse
import py_compile
import shutil
import time
from pathlib import Path


def root_from_args() -> Path:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/opt/hermes", help="Hermes install (the dir that holds gateway/, tools/)")
    return Path(ap.parse_args().root)


def replace_blocks(path: Path, edits, marker: str, *, optional: bool = False) -> bool:
    """Apply ``[(old, new), ...]`` to ``path``. Returns True when the file changed."""
    if not path.exists():
        if optional:
            print(f"{path.name}: absent — skipped"); return False
        raise SystemExit(f"{path}: missing (is --root the Hermes install dir?)")
    src = path.read_text(encoding="utf-8")
    if marker in src:
        print(f"{path.name}: already patched"); return False
    for old, new in edits:
        n = src.count(old)
        if n != 1:
            raise SystemExit(f"{path}: anchor found {n}x, expected 1 — unsupported Hermes version?\n"
                             f"  anchor: {old.strip().splitlines()[0][:100]!r}")
        src = src.replace(old, new, 1)
    tmp = path.with_name(path.name + ".tmp-hvp")
    tmp.write_text(src, encoding="utf-8")
    py_compile.compile(str(tmp), doraise=True)          # never leave a broken file in place
    bak = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}-hvp")
    n = 0
    while bak.exists():  # two patches in the same second must not clobber the earlier (pristine) backup
        n += 1; bak = bak.with_name(f"{bak.name.rsplit('.', 1)[0] if n > 1 else bak.name}.{n}")
    shutil.copy2(path, bak)
    tmp.replace(path)
    print(f"{path.name}: patched")
    return True
