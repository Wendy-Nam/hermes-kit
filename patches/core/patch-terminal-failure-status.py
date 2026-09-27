#!/usr/bin/env python3
"""Apply the v0.21.2 terminal provider-status de-duplication patch.

This is a local, version-pinned, idempotent patch helper.  It does not restart
Hermes or send any requests.  Use --check for a read-only preflight; --apply is
explicit because the parent deployment process owns the live change.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import tempfile


VERSION = "0.21.2"
RELATIVE_PATH = Path("gateway/run.py")
ORIGINAL_SHA256 = "ab619aa0dc193c6d8741f3cabc9a028c2fb7459c22262c69597b0e872091bde5"

OLD = '''    if _looks_like_gateway_provider_error(text):
        return _gateway_provider_error_reply(text)
    return text
'''

NEW = '''    if _looks_like_gateway_provider_error(text):
        # Terminal retry exhaustion is followed by the gateway's final failed-turn
        # response.  Messaging adapters without status editing (including Discord)
        # would otherwise send the same generic provider notice twice.  Keep this
        # narrow to lifecycle messages whose existing provider-error matcher also
        # identifies a completed retry budget; intermediate errors remain visible.
        if (
            event_type == "lifecycle"
            and re.search(
                r"(?:\\bapi(?:\\s+call)?\\s+failed\\s+after\\s+\\d+\\s+retries\\b|"
                r"\\brate\\s+limited\\s+after\\s+\\d+\\s+retries\\b)",
                text,
                re.IGNORECASE,
            )
        ):
            return None
        return _gateway_provider_error_reply(text)
    return text
'''


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_matches(root: Path) -> bool:
    marker = root / "hermes_agent.egg-info" / "PKG-INFO"
    try:
        return any(line.strip() == f"Version: {VERSION}" for line in marker.read_text(encoding="utf-8").splitlines())
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not version_matches(root):
        raise SystemExit(f"refusing: expected Hermes {VERSION}")
    path = root / RELATIVE_PATH
    raw = path.read_bytes()
    current = sha256(raw)
    if current == ORIGINAL_SHA256:
        if raw.count(OLD.encode()) != 1:
            raise SystemExit("refusing: expected one exact terminal-status block")
        patched = raw.replace(OLD.encode(), NEW.encode())
        expected = sha256(patched)
        state = "original"
    else:
        # This branch is deliberately exact so arbitrary drift cannot be accepted.
        expected = PATCHED_SHA256
        if current != expected:
            raise SystemExit(f"refusing unknown drift: sha256={current}")
        patched = raw
        state = "already patched"
    print({"path": str(path), "version": VERSION, "state": state, "sha256": current, "patched_sha256": expected})
    if not args.apply or state == "already patched":
        return 0
    st = path.stat()
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
        temporary = Path(tmp.name)
        tmp.write(patched)
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(temporary, st.st_mode & 0o7777)
        try:
            os.chown(temporary, st.st_uid, st.st_gid)
        except PermissionError:
            pass
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    print({"state": "applied", "sha256": sha256(path.read_bytes())})
    return 0


PATCHED_SHA256 = "5095909192763e79fd40dc973ab97ba6e50ee9e270fc62dd6e81a82f0141b860"


if __name__ == "__main__":
    raise SystemExit(main())
