#!/usr/bin/env python3
"""Read-only, pinned official Hermes documentation lookup.

Downloaded Markdown is reference material only. This module never executes commands found
in documentation; executable guidance comes from the installed ``hermes --help`` output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "NousResearch/hermes-agent"
OFFICIAL_REPO = "https://github.com/NousResearch/hermes-agent"
RAW_ORIGIN = "https://raw.githubusercontent.com"
DEFAULT_REF = "71d34bad1045610252eda02ee79549436896e784"  # Hermes v0.21.7
VERSION_PINS = {"0.21.7": DEFAULT_REF, "v0.21.7": DEFAULT_REF}
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_DOCUMENTS = 80
SCHEMA = "hermes_official_docs_cache/v1"

TOPICS = {
    "install": ("install", "installation", "setup", "requirements"),
    "desktop": ("desktop", "macos", "windows", "electron"),
    "model": ("model", "provider", "oauth", "api key"),
    "telegram": ("telegram", "botfather", "allowed users"),
    "discord": ("discord", "bot", "intent", "guild"),
    "cron": ("cron", "schedule", "scheduled", "gateway service"),
    "plugins": ("plugin", "plugins", "skill", "skills"),
    "troubleshooting": ("troubleshoot", "doctor", "debug", "common issues"),
}

HELP_COMMANDS = {
    "install": ("--help",),
    "desktop": ("--help",),
    "model": ("model", "--help"),
    "telegram": ("gateway", "--help"),
    "discord": ("gateway", "--help"),
    "cron": ("cron", "--help"),
    "plugins": ("--help",),
    "troubleshooting": ("doctor", "--help"),
}


class DocsError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _ref(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value or ""):
        raise DocsError("공식 문서는 검토된 40자리 commit으로만 조회합니다.")
    return value


def _doc_path(value: str) -> str:
    value = urllib.parse.unquote(value.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DocsError("공식 저장소 밖의 문서 경로는 사용하지 않습니다.")
    normalized = str(path)
    if normalized != "README.md" and not (normalized.startswith("docs/") and normalized.endswith(".md")):
        raise DocsError("README와 docs/*.md 문서만 조회합니다.")
    return normalized


def raw_url(ref: str, path: str) -> str:
    return f"{RAW_ORIGIN}/{REPOSITORY}/{_ref(ref)}/{_doc_path(path)}"


def citation_url(ref: str, path: str) -> str:
    return f"{OFFICIAL_REPO}/blob/{_ref(ref)}/{_doc_path(path)}"


def discover_readme_docs(markdown: str, ref: str) -> list[str]:
    """Return safe official Markdown paths, preserving README link order."""
    found = ["README.md"]
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", markdown):
        target = target.strip().strip("<>")
        parsed = urllib.parse.urlsplit(target)
        candidate = ""
        if not parsed.scheme and not parsed.netloc:
            candidate = parsed.path
        elif parsed.scheme == "https" and parsed.netloc == "github.com":
            prefix = f"/{REPOSITORY}/blob/"
            if parsed.path.startswith(prefix):
                remainder = parsed.path[len(prefix):]
                _linked_ref, separator, candidate = remainder.partition("/")
                if not separator:
                    continue
        if not candidate:
            continue
        try:
            safe = _doc_path(candidate)
        except DocsError:
            continue
        if safe not in found:
            found.append(safe)
        if len(found) >= MAX_DOCUMENTS:
            break
    return found


def _fetch(url: str, *, opener=None) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "raw.githubusercontent.com":
        raise DocsError("허용된 공식 HTTPS 문서 주소가 아닙니다.")
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "Hermes-Outbound-Docs/1"})
    try:
        with opener.open(request, timeout=30) as response:
            if getattr(response, "status", 200) != 200 or response.geturl() != url:
                raise DocsError("공식 문서 요청이 다른 주소로 이동했거나 실패했습니다.")
            raw = response.read(MAX_FILE_BYTES + 1)
    except DocsError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise DocsError(f"공식 문서를 읽지 못했습니다: {type(exc).__name__}") from None
    if len(raw) > MAX_FILE_BYTES:
        raise DocsError("공식 문서가 허용 크기를 초과했습니다.")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DocsError("공식 문서가 UTF-8 Markdown이 아닙니다.") from None
    return raw


def sync(cache: str | Path, ref: str = DEFAULT_REF, *, opener=None) -> dict:
    """Cache README first, then only official docs discovered from it."""
    ref = _ref(ref)
    root = Path(cache).expanduser().absolute() / ref
    if root.is_symlink() or any(parent.is_symlink() for parent in root.parents):
        raise DocsError("문서 cache에 심볼릭 링크를 사용하지 않습니다.")
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DocsError("기존 공식 문서 cache를 읽을 수 없습니다.") from None
        if old.get("schema_version") != SCHEMA or old.get("ref") != ref:
            raise DocsError("다른 버전의 공식 문서 cache를 덮어쓰지 않습니다.")

    readme = _fetch(raw_url(ref, "README.md"), opener=opener)
    paths = discover_readme_docs(readme.decode("utf-8"), ref)
    payloads = {"README.md": readme}
    total = len(readme)
    for path in paths[1:]:
        raw = _fetch(raw_url(ref, path), opener=opener)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise DocsError("공식 문서 묶음이 허용 크기를 초과했습니다.")
        payloads[path] = raw

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    documents = []
    for path, raw in payloads.items():
        destination = root / path
        if destination.is_symlink():
            raise DocsError("문서 cache 링크는 덮어쓰지 않습니다.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != raw:
            raise DocsError("같은 commit의 기존 문서 bytes가 달라 보존했습니다.")
        if not destination.exists():
            destination.write_bytes(raw)
        documents.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                          "citation": citation_url(ref, path)})
    manifest = {"schema_version": SCHEMA, "repository": REPOSITORY, "ref": ref,
                "readme_first": True, "documents": documents}
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if not manifest_path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".official-docs-", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, manifest_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    elif manifest_path.read_text(encoding="utf-8") != text:
        raise DocsError("기존 공식 문서 manifest를 덮어쓰지 않습니다.")
    return manifest


def _manifest(cache: str | Path, ref: str) -> tuple[Path, dict]:
    root = Path(cache).expanduser().absolute() / _ref(ref)
    try:
        data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DocsError("공식 문서 cache가 없습니다. sync를 먼저 실행하세요.") from None
    if data.get("schema_version") != SCHEMA or data.get("ref") != ref:
        raise DocsError("공식 문서 cache 버전이 현재 선택과 다릅니다.")
    return root, data


def query(cache: str | Path, topic: str, ref: str = DEFAULT_REF, *, limit: int = 8) -> dict:
    if topic not in TOPICS:
        raise DocsError("지원 주제: " + ", ".join(TOPICS))
    root, manifest = _manifest(cache, ref)
    hits = []
    terms = TOPICS[topic]
    for item in manifest.get("documents", []):
        path = _doc_path(item.get("path", ""))
        raw = (root / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
            raise DocsError("cache 문서 hash가 manifest와 다릅니다.")
        lines = raw.decode("utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            folded = line.casefold()
            if any(term in folded for term in terms):
                excerpt = re.sub(r"\s+", " ", line).strip()[:280]
                hits.append({"path": path, "line": number, "excerpt": excerpt,
                             "citation": item["citation"] + f"#L{number}"})
                if len(hits) >= limit:
                    return {"topic": topic, "ref": ref, "hits": hits,
                            "notice": "공식 문서는 참고 자료이며, 실제 명령은 설치된 hermes --help를 우선합니다."}
    return {"topic": topic, "ref": ref, "hits": hits,
            "notice": "일치 항목이 없으면 bundled 설치 문서와 설치된 hermes --help를 사용하세요."}


def installed_version(executable: str | None = None, *, runner=subprocess.run) -> dict:
    executable = executable or shutil.which("hermes")
    if not executable:
        return {"status": "missing", "version": None, "ref": None}
    try:
        result = runner([executable, "--version"], capture_output=True, text=True,
                        timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"status": "unreadable", "version": None, "ref": None}
    output = (result.stdout or result.stderr or "")[:300]
    match = re.search(r"(?<!\d)(?:v)?(0\.\d+\.\d+)(?!\d)", output)
    version = match.group(1) if match else None
    ref = VERSION_PINS.get(version or "")
    return {"status": "matched" if ref else "unsupported_version", "version": version,
            "ref": ref, "executable": executable}


def help_snapshot(topic: str, executable: str | None = None, *, runner=subprocess.run) -> dict:
    if topic not in HELP_COMMANDS:
        raise DocsError("지원 주제: " + ", ".join(HELP_COMMANDS))
    executable = executable or shutil.which("hermes")
    if not executable:
        return {"topic": topic, "status": "missing", "command": None, "output": ""}
    argv = [executable, *HELP_COMMANDS[topic]]
    try:
        result = runner(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"topic": topic, "status": "failed", "command": argv, "output": ""}
    output = ((result.stdout or "") + (result.stderr or ""))[:32 * 1024]
    return {"topic": topic, "status": "ok" if result.returncode == 0 else "failed",
            "command": argv, "output": output}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="고정 버전 공식 Hermes 문서와 설치된 CLI 도움말을 안전하게 조회합니다.")
    sub = parser.add_subparsers(dest="action", required=True)
    sync_p = sub.add_parser("sync", help="README에서 발견한 공식 문서를 고정 commit cache에 저장")
    sync_p.add_argument("--cache", default=".official-hermes-docs")
    sync_p.add_argument("--ref", default=DEFAULT_REF)
    query_p = sub.add_parser("query", help="cache에서 주제별 공식 인용 찾기")
    query_p.add_argument("topic", choices=tuple(TOPICS))
    query_p.add_argument("--cache", default=".official-hermes-docs")
    query_p.add_argument("--ref", default=DEFAULT_REF)
    sub.add_parser("version", help="설치된 Hermes 버전과 검토 문서 pin 매칭")
    help_p = sub.add_parser("help", help="설치된 Hermes의 주제별 --help 확인")
    help_p.add_argument("topic", choices=tuple(HELP_COMMANDS))
    args = parser.parse_args(argv)
    try:
        if args.action == "sync":
            payload = sync(args.cache, args.ref)
        elif args.action == "query":
            payload = query(args.cache, args.topic, args.ref)
        elif args.action == "version":
            payload = installed_version()
        else:
            payload = help_snapshot(args.topic)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("status") not in {"failed", "unreadable"} else 1
    except (DocsError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc),
                          "fallback": "bundled docs와 설치된 hermes --help를 사용하세요."},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
