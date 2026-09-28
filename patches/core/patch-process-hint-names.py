#!/usr/bin/env python3
"""Patch stale model-facing ``process(action=...)`` hints to ``process_manage``.

The patch is deliberately narrow:

* only the three terminal-facing source files are eligible;
* only Python string tokens are edited (comments, identifiers, and executable
  code are untouched);
* AST inspection must find exactly the same number of string-literal matches as
  tokenization before an edit is allowed;
* a second apply is a no-op; and
* the default mode is a report. Use ``--apply`` to write files.

The canonical process tool is ``process_manage``. ``process`` is not an alias.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import stat
import tempfile
import tokenize
from pathlib import Path


OLD = "process(action"
NEW = "process_manage(action"
TARGETS = {
    "tools/terminal_tool.py": {
        "original_sha256": "2fdfdb2d10b23d7cdf0db2e7eb981fd8d185a3534adf3f81fbad5750be4feebe",
        "patched_sha256": "d7e2143f4b588dbc5fe599f6d8a982defa4ea1985c77917e7bf06d08dc07e1fb",
        "matches": 6,
    },
    "tools/terminal_tool_background.py": {
        "original_sha256": "e1739ef57721d8a364f2b80319caab1b3da1269cc35281f97c4e321959e13de5",
        "patched_sha256": "6648f6dfef28d54137b565ff5b6758ec34c97bb8efa5fb93f39df4a38466332d",
        "matches": 6,
    },
    "tools/close_terminal_tool.py": {
        "original_sha256": "22d8ca59a20b219f8f96d775c59092a2d6e1057cb21c278e1bd3b6d51f0763e3",
        "patched_sha256": "108c5b09c95f732b7a4329a1467b1ca8f65631f1a008074a96cd2f8a74a0929e",
        "matches": 2,
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ast_string_match_count(source: str, filename: str) -> int:
    tree = ast.parse(source, filename=filename)
    return sum(
        node.value.count(OLD)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _string_token_matches(source: str, filename: str) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.STRING:
                continue
            start = offsets[token.start[0] - 1] + token.start[1]
            end = offsets[token.end[0] - 1] + token.end[1]
            text = source[start:end]
            for at in range(0, text.count(OLD)):
                # Locate each occurrence without interpreting or reserializing
                # the Python literal; this preserves quotes, prefixes, and layout.
                pos = -1
                for _ in range(at + 1):
                    pos = text.find(OLD, pos + 1)
                matches.append((start + pos, start + pos + len(OLD)))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ValueError(f"cannot tokenize {filename}: {exc}") from exc
    return matches


def _replace_file(path: Path, rel: str, *, apply: bool, enforce_hash: bool) -> dict:
    meta = TARGETS[rel]
    raw = path.read_bytes()
    before_hash = _sha256(raw)
    if enforce_hash and before_hash not in {meta["original_sha256"], meta["patched_sha256"]}:
        raise ValueError(f"unexpected hash for {rel}: {before_hash}")
    source = raw.decode("utf-8")
    ast_count = _ast_string_match_count(source, rel)
    token_matches = _string_token_matches(source, rel)
    if ast_count != len(token_matches):
        raise ValueError(f"AST/token scope mismatch for {rel}: ast={ast_count}, tokens={len(token_matches)}")
    if not enforce_hash and ast_count not in (0, meta["matches"]):
        # hermes-kit: without the author's file hashes, require the exact recorded count.
        raise ValueError(f"unexpected hint count in {rel}: {ast_count} != {meta['matches']}")
    if ast_count > meta["matches"]:
        raise ValueError(f"unexpected new hint matches in {rel}: {ast_count} > {meta['matches']}")
    if before_hash == meta["patched_sha256"]:
        if ast_count:
            raise ValueError(f"patched hash but stale literal remains in {rel}")
        return {"file": rel, "changed": False, "matches": 0, "sha256": before_hash}
    if before_hash != meta["original_sha256"] and enforce_hash:
        raise ValueError(f"unrecognized pre-patch state for {rel}: {before_hash}")
    if ast_count == 0:
        if enforce_hash or apply:  # hermes-kit: nothing to patch at build time is drift
            raise ValueError(f"no eligible stale hint in expected original file {rel}")
        return {"file": rel, "changed": False, "matches": 0, "sha256": before_hash}
    if not apply:
        return {"file": rel, "changed": True, "matches": ast_count, "sha256": before_hash}
    out = source
    for start, end in reversed(token_matches):
        out = out[:start] + NEW + out[end:]
    ast.parse(out, filename=rel)
    after = out.encode("utf-8")
    if _ast_string_match_count(out, rel):
        raise ValueError(f"old hint remains in a Python string after patch in {rel}")
    if sum(node.value.count(NEW) for node in ast.walk(ast.parse(out, filename=rel))
           if isinstance(node, ast.Constant) and isinstance(node.value, str)) < ast_count:
        raise ValueError(f"new hint count is short after patch in {rel}")
    return {"file": rel, "changed": True, "matches": ast_count, "sha256": _sha256(after), "before": raw, "after": after}


def run(root: Path, *, apply: bool, enforce_hash: bool = False) -> list[dict]:
    # Inspect every file first. No target is written if any target fails its
    # hash, AST, token-scope, or syntax precondition.
    results = []
    for rel in TARGETS:
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(path)
        results.append(_replace_file(path, rel, apply=apply, enforce_hash=enforce_hash))
    if apply:
        for result in results:
            if not result.get("changed"):
                continue
            path = root / result["file"]
            before = result.pop("before")
            after = result.pop("after")
            st = path.stat()
            fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            try:
                os.fchmod(fd, stat.S_IMODE(st.st_mode))
                with os.fdopen(fd, "wb") as stream:
                    stream.write(after)
                    stream.flush()
                    os.fsync(stream.fileno())
                if hasattr(os, "chown"):
                    try:
                        os.chown(temp_name, st.st_uid, st.st_gid)
                    except PermissionError:
                        pass
                os.replace(temp_name, path)
                try:
                    dir_fd = os.open(path.parent, os.O_DIRECTORY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except (AttributeError, OSError):
                    pass
            except Exception:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                raise
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Hermes source root")
    parser.add_argument("--apply", action="store_true", help="write the targeted replacements")
    parser.add_argument("--enforce-hash", dest="enforce_hash", action="store_true", default=True,
                        help="require the recorded live source or exact patched hashes (default)")
    parser.add_argument("--no-enforce-hash", dest="enforce_hash", action="store_false",
                        help="disable source hash preconditions for fixture use only")
    args = parser.parse_args()
    print(json.dumps({"apply": args.apply, "results": run(args.root, apply=args.apply, enforce_hash=args.enforce_hash)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
