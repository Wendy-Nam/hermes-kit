#!/usr/bin/env python3
"""Offline, redacted privacy checks for public release trees and ZIP files.

The report never contains matching text. A clean automated result still requires a human
release review; pattern matching cannot prove that a package has zero privacy risk.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


SCHEMA = "hermes_outbound_privacy_audit/v1"
MAX_TEXT_FILE = 8 * 1024 * 1024
MAX_ARCHIVE_TEXT = 64 * 1024 * 1024
TEXT_SUFFIXES = {
    "", ".bat", ".command", ".csv", ".html", ".ini", ".json", ".md", ".ps1",
    ".py", ".sh", ".toml", ".txt", ".yaml", ".yml",
}
SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__"}
FORBIDDEN_TOP_LEVEL = {
    "planning", "workshop", "output", "outputs", "results", "vault", "profiles",
    ".installer-state", ".official-hermes-docs", ".omh", ".omh-runtime",
}
SENSITIVE_BASENAMES = {
    ".env", "setup.json", "id_rsa", "id_ed25519", "known_hosts", "credentials",
    "credentials.json", "secrets.json", "token.json",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".log", ".sqlite", ".db"}
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
PLACEHOLDER_USERS = {"user", "username", "name", "example", "runner", "home"}


CONTENT_RULES = {
    "private_key_material": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I),
    "known_token_shape": re.compile(
        r"(?:\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|"
        r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b|\b[0-9]{5,}:[A-Za-z0-9_-]{24,}\b|"
        r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b)"),
    "credential_in_url": re.compile(r"https?://[^\s/:@]+:[^\s/@]+@", re.I),
    "private_repository_reference": re.compile(
        r"(?:my-" + r"pri" + r"vate-hermes-er|pri" + r"vate" + r"[-_/ ]hermes|"
        r"github\.com/[^\s)]+/[^\s)]*pri" + r"vate[^\s)]*)",
        re.I),
    "internal_workspace_path": re.compile(
        r"(?:/work" + r"space/|/private/" + r"tmp/|[A-Za-z]:\\work" + r"space\\)"),
    "private_network_url": re.compile(
        r"https?://(?:10(?:\.\d{1,3}){3}|"
        r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?=[:/\s]|$)",
        re.I),
    "phone_number": re.compile(
        r"(?:\b01[016789][ -]?\d{3,4}[ -]?\d{4}\b|(?<!\w)\+\d(?:[ .()-]?\d){8,14}(?!\w))"),
}


def _unsafe_user_path(line: str) -> bool:
    patterns = (
        re.compile(r"/(?:Users|home)/([^/\s]+)/"),
        re.compile(r"[A-Za-z]:\\Users\\([^\\\s]+)\\", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(line):
            if match.group(1).casefold() not in PLACEHOLDER_USERS:
                return True
    return False


def _personal_email(line: str) -> bool:
    for match in re.finditer(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.-])", line):
        if match.group(2).casefold() not in ALLOWED_EMAIL_DOMAINS:
            return True
    return False


def _secret_assignment(line: str) -> bool:
    match = re.search(
        r"(?i)(?:^|[\s{,])(token|password|passwd|secret|api[_-]?key|private[_-]?key)"
        r"\s*(?:=|:)\s*(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_./+=-]{8,}))"
        r"(?=\s*(?:[,}#]|$))", line)
    if not match:
        return False
    value = (match.group(2) or match.group(3) or "").strip().casefold()
    placeholders = {
        "", "none", "null", "redacted", "placeholder", "example", "fixture", "test",
        "<redacted>", "<token>", "<secret>", "your_token", "your-key", "${token}",
    }
    return value not in placeholders and not value.startswith(("${", "<", "fixture", "example", "test-"))


def _path_rule(relative: PurePosixPath) -> str | None:
    parts = tuple(part.casefold() for part in relative.parts)
    if not parts:
        return "invalid_path"
    if parts[0] in FORBIDDEN_TOP_LEVEL:
        return "forbidden_release_tree"
    if any(part in {"userprofiles", "user-profiles", "support-bundle", "support-bundles"}
           for part in parts):
        return "private_runtime_tree"
    name = parts[-1]
    if name in SENSITIVE_BASENAMES or (name.startswith(".env.") and name != ".env.example"):
        return "sensitive_filename"
    if PurePosixPath(name).suffix.casefold() in SENSITIVE_SUFFIXES:
        return "sensitive_filename"
    return None


def _content_findings(text: str) -> Counter:
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        for rule, pattern in CONTENT_RULES.items():
            if pattern.search(line):
                counts[rule] += 1
        if _unsafe_user_path(line):
            counts["personal_home_path"] += 1
        if _personal_email(line):
            counts["personal_email"] += 1
        if _secret_assignment(line):
            counts["secret_assignment"] += 1
    return counts


class Audit:
    def __init__(self):
        self.findings: list[dict] = []
        self.files_scanned = 0
        self.archives_scanned = 0
        self.text_bytes_scanned = 0

    def add(self, file: str, rule: str, line_count: int = 0) -> None:
        self.findings.append({"file": file, "rule": rule, "matching_line_count": line_count})

    def scan_text(self, display: str, raw: bytes) -> None:
        if len(raw) > MAX_TEXT_FILE:
            self.add(display, "text_file_too_large")
            return
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            self.add(display, "non_utf8_text")
            return
        self.files_scanned += 1
        self.text_bytes_scanned += len(raw)
        for rule, count in sorted(_content_findings(text).items()):
            self.add(display, rule, count)

    def scan_root(self, root: Path) -> None:
        root = root.expanduser().absolute()
        if not root.is_dir() or root.is_symlink():
            self.add(".", "invalid_scan_root")
            return
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            relative_dir = current_path.relative_to(root)
            kept = []
            for dirname in sorted(dirs):
                child = current_path / dirname
                relative = PurePosixPath(*(relative_dir / dirname).parts)
                if dirname in SKIP_DIRS:
                    continue
                rule = _path_rule(relative)
                if child.is_symlink():
                    self.add(str(relative), "symlink_not_release_file")
                elif rule:
                    self.add(str(relative), rule)
                else:
                    kept.append(dirname)
            dirs[:] = kept
            for filename in sorted(files):
                path = current_path / filename
                relative = PurePosixPath(*(relative_dir / filename).parts)
                display = str(relative)
                if path.is_symlink():
                    self.add(display, "symlink_not_release_file")
                    continue
                rule = _path_rule(relative)
                if rule:
                    self.add(display, rule)
                    continue
                if path.suffix.casefold() == ".zip":
                    self.scan_zip(path, display)
                    continue
                if path.suffix.casefold() not in TEXT_SUFFIXES:
                    self.add(display, "unsupported_binary_release_file")
                    continue
                try:
                    self.scan_text(display, path.read_bytes())
                except OSError:
                    self.add(display, "unreadable_release_file")

    def scan_zip(self, archive_path: Path, display: str | None = None) -> None:
        label = display or archive_path.name
        self.archives_scanned += 1
        total = 0
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    member = PurePosixPath(info.filename.replace("\\", "/"))
                    member_display = f"{label}!{member}"
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if (member.is_absolute() or ".." in member.parts or not member.parts
                            or stat.S_ISLNK(mode)):
                        self.add(member_display, "unsafe_archive_member")
                        continue
                    relative = PurePosixPath(*member.parts[1:]) if len(member.parts) > 1 else member
                    rule = _path_rule(relative)
                    if rule:
                        self.add(member_display, rule)
                        continue
                    if info.is_dir():
                        continue
                    if info.flag_bits & 0x1:
                        self.add(member_display, "encrypted_archive_member")
                        continue
                    if member.suffix.casefold() not in TEXT_SUFFIXES:
                        self.add(member_display, "unsupported_binary_release_file")
                        continue
                    if info.file_size > MAX_TEXT_FILE:
                        self.add(member_display, "text_file_too_large")
                        continue
                    total += info.file_size
                    if total > MAX_ARCHIVE_TEXT:
                        self.add(label, "archive_text_limit_exceeded")
                        break
                    self.scan_text(member_display, archive.read(info))
        except (OSError, EOFError, zipfile.BadZipFile, RuntimeError):
            self.add(label, "invalid_or_unreadable_archive")

    def report(self) -> dict:
        findings = sorted(self.findings, key=lambda item: (item["file"], item["rule"]))
        return {
            "schema_version": SCHEMA,
            "status": "blocked" if findings else "automated_checks_clear_manual_review_required",
            "summary": {
                "files_scanned": self.files_scanned,
                "archives_scanned": self.archives_scanned,
                "text_bytes_scanned": self.text_bytes_scanned,
                "finding_count": len(findings),
                "manual_review_required": True,
            },
            "findings": findings,
            "notice": "탐지값은 출력하지 않았습니다. 자동 검사는 개인정보·비밀정보 위험이 0임을 증명하지 않습니다.",
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="공개 배포 폴더와 ZIP을 값 노출 없이 검사합니다.")
    parser.add_argument("--root", action="append", default=[], help="검사할 공개 배포 트리")
    parser.add_argument("--archive", action="append", default=[], help="검사할 ZIP")
    args = parser.parse_args(argv)
    if not args.root and not args.archive:
        parser.error("--root 또는 --archive를 하나 이상 지정하세요.")
    audit = Audit()
    for value in args.root:
        audit.scan_root(Path(value))
    for value in args.archive:
        audit.scan_zip(Path(value))
    report = audit.report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
