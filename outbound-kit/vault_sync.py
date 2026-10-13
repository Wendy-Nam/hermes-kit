#!/usr/bin/env python3
"""Read-only SSH pull for generated Hermes Outbound Markdown notes.

The remote side is never modified.  A manifest is enumerated without shell
globs, every file is fetched individually into staging, and local human notes
or differing human-managed review files are preserved with a conflict report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from operations import load_config


ROOT = Path(__file__).resolve().parent
ALLOWED_ROOT_FILES = {"Dashboard.md"}
ALLOWED_DIRS = {"Inbox", "Accounts", "Evidence", "Scores", "Drafts", "Review", "Runs"}
MACHINE_MARKER = "<!-- hermes-outbound:machine-owned:v1 -->"
USER_START = "<!-- user-notes:start -->"
USER_END = "<!-- user-notes:end -->"
MAX_FILES = 10_000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f"상태 경로의 심볼릭 링크는 허용하지 않습니다: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".vault-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts)
            or path.suffix.lower() != ".md"):
        raise ValueError(f"허용되지 않는 remote manifest 경로: {value}")
    allowed = len(path.parts) == 1 and path.name in ALLOWED_ROOT_FILES
    allowed = allowed or len(path.parts) >= 2 and path.parts[0] in ALLOWED_DIRS
    if not allowed:
        raise ValueError(f"허용되지 않는 remote note 범위: {value}")
    return path


def _validate_connection(host: str, user: str, port: int, key: str | Path,
                         remote_vault: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", host or ""):
        raise ValueError("host: URL이나 shell 표현이 아닌 SSH 호스트/IP가 필요합니다.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", user or ""):
        raise ValueError("user: SSH 사용자명이 필요합니다.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port: 1~65535 정수가 필요합니다.")
    if not remote_vault or len(remote_vault) > 4096 or any(ord(c) < 32 for c in remote_vault):
        raise ValueError("remote-vault: 제어문자 없는 경로가 필요합니다.")
    key_path = Path(key).expanduser().absolute()
    if key_path.is_symlink() or any(parent.is_symlink() for parent in key_path.parents) or not key_path.is_file():
        raise ValueError("key: 기존 SSH 개인키 파일 경로가 필요합니다.")
    if os.name == "posix" and key_path.stat().st_mode & 0o077:
        raise ValueError("SSH 개인키 권한이 너무 넓습니다. 소유자만 읽도록 조정하세요.")
    return key_path


REMOTE_MANIFEST_SCRIPT = r'''
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).expanduser().resolve(strict=True)
root_files = {"Dashboard.md"}
dirs = {"Inbox", "Accounts", "Evidence", "Scores", "Drafts", "Review", "Runs"}
rows = []
def walk_markdown(directory):
    pending = [directory]
    found = []
    while pending:
        current = pending.pop()
        for item in sorted(current.iterdir(), key=lambda p: p.name, reverse=True):
            if item.is_symlink():
                continue
            if item.is_dir():
                pending.append(item)
            elif item.is_file() and item.suffix.lower() == ".md":
                found.append(item)
    return sorted(found)
for child in sorted(root.iterdir(), key=lambda p: p.name):
    candidates = [child] if child.name in root_files else (
        walk_markdown(child) if child.name in dirs and child.is_dir() and not child.is_symlink() else [])
    for path in candidates:
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".md":
            continue
        resolved = path.resolve(strict=True)
        try: resolved.relative_to(root)
        except ValueError: continue
        data = resolved.read_bytes()
        rel = resolved.relative_to(root).as_posix()
        rows.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                     "machine_owned": data.startswith(b"<!-- hermes-outbound:machine-owned:v1 -->")})
print(json.dumps({"schema_version": 1, "files": rows}, separators=(",", ":")))
'''.strip()


class SSHTransport:
    """OpenSSH transport with strict host checking and an existing key only."""

    def __init__(self, host: str, user: str, port: int, key: str | Path,
                 remote_vault: str, *, runner=subprocess.run):
        self.key = _validate_connection(host, user, port, key, remote_vault)
        self.remote_vault = remote_vault
        self.runner = runner
        self.base = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes", "-i", str(self.key), "-p", str(port),
            f"{user}@{host}",
        ]

    def _run(self, remote_argv: list[str], *, binary: bool = False):
        # OpenSSH passes one remote command string. shlex.join makes every
        # argument literal; no untrusted value becomes an option or glob.
        command = [*self.base, shlex.join(remote_argv)]
        completed = self.runner(
            command, check=False, capture_output=True, text=not binary, timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"read-only SSH command failed (exit {completed.returncode})")
        return completed.stdout

    def manifest(self) -> list[dict]:
        raw = self._run(["python3", "-c", REMOTE_MANIFEST_SCRIPT, self.remote_vault])
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("files"), list):
            raise ValueError("remote manifest 형식이 잘못되었습니다.")
        return value["files"]

    def fetch(self, relative: str) -> bytes:
        rel = _safe_relative(relative)
        # Let remote pathlib expand '~' exactly as the manifest did, then emit
        # bytes. Re-check containment and symlinks to close a manifest/fetch
        # race. This remains read-only and avoids scp glob rules.
        script = (
            "import pathlib,sys;"
            "r=pathlib.Path(sys.argv[1]).expanduser().resolve(strict=True);"
            "p=r.joinpath(*pathlib.PurePosixPath(sys.argv[2]).parts);"
            "assert not p.is_symlink() and p.is_file() and p.suffix.lower()=='.md';"
            "q=p.resolve(strict=True);q.relative_to(r);"
            "sys.stdout.buffer.write(q.read_bytes())"
        )
        return self._run(["python3", "-c", script, self.remote_vault, rel.as_posix()], binary=True)


def sync_plan(config: str | Path, remote_vault: str, local_vault: str | Path,
              host: str, user: str, port: int, key: str | Path,
              state_dir: str | Path) -> dict:
    data = load_config(config)
    key_path = _validate_connection(host, user, port, key, remote_vault)
    return {
        "schema_version": 1,
        "action": "plan",
        "changes_applied": False,
        "direction": "pull_only",
        "config": str(Path(config).expanduser().resolve()),
        "config_sha256": _sha(Path(config).expanduser().resolve().read_bytes()),
        "remote": {"host": host, "user": user, "port": port, "vault": remote_vault,
                   "strict_host_key_checking": True, "batch_mode": True,
                   "existing_key_path": str(key_path)},
        "local_vault": str(Path(local_vault).expanduser().resolve()),
        "state_dir": str(Path(state_dir).expanduser().resolve()),
        "allowed": ["Dashboard.md", *[f"{name}/**/*.md" for name in sorted(ALLOWED_DIRS)]],
        "excluded": [".env", "keys", "credentials", "setup/config JSON", "symlinks", "all non-Markdown files"],
        "merge": "replace machine-owned sections while preserving local user-notes; preserve differing human-managed notes",
        "configured_vault_mode": data.get("vault_mode", "none"),
    }


def _extract_user_notes(text: str) -> str | None:
    start = text.find(USER_START)
    end = text.find(USER_END, start + len(USER_START))
    if start < 0 or end < 0 or end < start:
        return None
    return text[start + len(USER_START):end].strip("\n")


def _inject_user_notes(remote: str, notes: str) -> str:
    start = remote.find(USER_START)
    end = remote.find(USER_END, start + len(USER_START))
    if start < 0 or end < 0:
        return remote
    before = remote[:start + len(USER_START)]
    after = remote[end:]
    return before + ("\n" + notes + "\n" if notes else "\n") + after


def _write_new_or_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f"로컬 vault 링크를 보존했습니다: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".vault-note-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def pull_vault(plan: dict, *, transport=None) -> dict:
    state_dir = Path(plan["state_dir"])
    state_path = state_dir / "vault-sync.json"
    state = {"schema_version": 1}
    if state_path.exists():
        if state_path.is_symlink() or any(parent.is_symlink() for parent in state_path.parents):
            raise ValueError("vault sync 상태 경로의 심볼릭 링크는 허용하지 않습니다.")
        state = json.loads(state_path.read_text(encoding="utf-8"))
    attempt = {"at": _now(), "status": "running", "config_sha256": plan["config_sha256"]}
    state["last_attempt"] = attempt
    _atomic_json(state_path, state)
    if transport is None:
        remote = plan["remote"]
        transport = SSHTransport(remote["host"], remote["user"], remote["port"],
                                 remote["existing_key_path"], remote["vault"])
    try:
        manifest = transport.manifest()
        if len(manifest) > MAX_FILES:
            raise ValueError("remote note 개수가 안전 한도를 넘었습니다.")
        normalized: list[tuple[PurePosixPath, dict]] = []
        seen: set[str] = set()
        total = 0
        for entry in manifest:
            if not isinstance(entry, dict):
                raise ValueError("remote manifest entry 형식이 잘못되었습니다.")
            rel = _safe_relative(entry.get("path", ""))
            name = rel.as_posix()
            if name in seen:
                raise ValueError(f"remote manifest 중복 경로: {name}")
            seen.add(name)
            size = entry.get("size")
            digest = entry.get("sha256")
            if type(size) is not int or size < 0 or size > MAX_FILE_BYTES or not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
                raise ValueError(f"remote manifest 크기/hash가 잘못되었습니다: {name}")
            total += size
            normalized.append((rel, entry))
        if total > MAX_TOTAL_BYTES:
            raise ValueError("remote notes 전체 크기가 안전 한도를 넘었습니다.")

        staging_root = state_dir / "staging"
        staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        stage = Path(tempfile.mkdtemp(prefix="pull-", dir=staging_root))
        fetched: list[tuple[PurePosixPath, bytes, dict]] = []
        for rel, entry in normalized:
            data = transport.fetch(rel.as_posix())
            if len(data) != entry["size"] or _sha(data) != entry["sha256"]:
                raise ValueError(f"staged note hash mismatch: {rel.as_posix()}")
            data.decode("utf-8")
            target = stage.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            fetched.append((rel, data, entry))

        local_root = Path(plan["local_vault"])
        if local_root.is_symlink() or any(parent.is_symlink() for parent in local_root.parents):
            raise ValueError("local vault 경로의 심볼릭 링크는 허용하지 않습니다.")
        local_root.mkdir(parents=True, exist_ok=True)
        conflicts: list[dict] = []
        counts = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": 0}
        for rel, remote_bytes, entry in fetched:
            local = local_root.joinpath(*rel.parts)
            unsafe_link = local.is_symlink() or any(parent.is_symlink() for parent in local.parents)
            if unsafe_link:
                reason = "local_symlink_preserved"
            elif not local.exists():
                _write_new_or_atomic(local, remote_bytes)
                counts["created"] += 1
                continue
            else:
                local_bytes = local.read_bytes()
                if local_bytes == remote_bytes:
                    counts["unchanged"] += 1
                    continue
                remote_text = remote_bytes.decode("utf-8")
                local_text = local_bytes.decode("utf-8")
                if remote_text.startswith(MACHINE_MARKER) and local_text.startswith(MACHINE_MARKER):
                    notes = _extract_user_notes(local_text)
                    if notes is not None and _extract_user_notes(remote_text) is not None:
                        merged = _inject_user_notes(remote_text, notes).encode()
                        if merged == local_bytes:
                            counts["unchanged"] += 1
                        else:
                            _write_new_or_atomic(local, merged)
                            counts["updated"] += 1
                        continue
                    reason = "user_note_markers_missing"
                else:
                    reason = "human_managed_or_unrecognized_local_preserved"
            counts["conflicts"] += 1
            local_digest = _sha(local.read_bytes()) if local.exists() and not unsafe_link else None
            conflicts.append({"path": rel.as_posix(), "reason": reason,
                              "local_sha256": local_digest, "remote_sha256": entry["sha256"],
                              "staged": str(stage.joinpath(*rel.parts))})
        report = {"schema_version": 1, "at": _now(), "staging": str(stage),
                  "counts": counts, "conflicts": conflicts}
        _atomic_json(state_dir / "conflicts.json", report)
        attempt = {**attempt, "finished_at": _now(), "status": "succeeded",
                   "counts": counts, "staging": str(stage)}
        state["last_attempt"] = attempt
        state["last_success"] = attempt
        _atomic_json(state_path, state)
        return report
    except Exception as exc:
        attempt = {**attempt, "finished_at": _now(), "status": "failed",
                   "error_type": type(exc).__name__}
        state["last_attempt"] = attempt
        _atomic_json(state_path, state)
        raise


def sync_status(state_dir: str | Path) -> dict:
    path = Path(state_dir).expanduser().resolve() / "vault-sync.json"
    if not path.exists():
        return {"schema_version": 1, "status": "never_run"}
    if path.is_symlink():
        raise ValueError("vault sync 상태 파일이 심볼릭 링크입니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only server-to-local generated Markdown vault sync")
    parser.add_argument("action", choices=["plan", "pull", "status"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--remote-vault", required=True)
    parser.add_argument("--local-vault", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--key", required=True, help="existing SSH private-key path; key content is never read or logged")
    parser.add_argument("--state-dir")
    args = parser.parse_args(argv)
    state_dir = args.state_dir or str(Path(args.local_vault).expanduser().resolve() / ".hermes-outbound-sync")
    try:
        plan = sync_plan(args.config, args.remote_vault, args.local_vault,
                         args.host, args.user, args.port, args.key, state_dir)
        result = plan if args.action == "plan" else (
            sync_status(state_dir) if args.action == "status" else pull_vault(plan))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
