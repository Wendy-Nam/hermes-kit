"""Tell a student when a newer kit image exists — no LLM, once a week.

Version comparison is the fiddly part: "0.21.3-k2" against "0.21.2-k1" is not a string
comparison, and a wrong "you are up to date" is worse than saying nothing, so an
unparsable tag returns "unknown" rather than a guess.
"""
import json
import re
import urllib.error
import urllib.request

RELEASES_URL = "https://api.github.com/repos/Wendy-Nam/hermes-kit/releases/latest"
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-k(\d+))?$")


def parse_version(tag: str):
    m = _TAG.match((tag or "").strip())
    if not m:
        return None
    major, minor, patch, kit = m.groups()
    return int(major), int(minor), int(patch), int(kit or 0)


def latest_release() -> tuple[str | None, str]:
    """(tag, release notes). (None, reason) when GitHub is unreachable or the tag is unreadable."""
    try:
        req = urllib.request.Request(RELEASES_URL, headers={
            "User-Agent": "hermes-kit", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return None, f"GitHub 응답 {e.code}"
    except Exception:
        return None, "GitHub에 연결하지 못했습니다"
    tag = d.get("tag_name")
    if not tag or parse_version(tag) is None:
        return None, "릴리스 정보를 읽지 못했습니다"
    return tag, (d.get("body") or "").strip()


def check(current: str) -> tuple[bool, str, str]:
    """(update_available, latest_tag, message_to_post)."""
    mine = parse_version(current)
    if mine is None:
        return False, "", f"현재 버전({current})을 읽지 못했습니다"
    tag, note = latest_release()
    if tag is None:
        return False, "", note
    theirs = parse_version(tag)
    if theirs is None or theirs <= mine:
        return False, tag, ""
    bullets = [l.strip("-* \t") for l in note.splitlines() if l.strip()][:3]
    body = "\n".join(f"· {b}" for b in bullets) or \
        "Hostinger Docker Manager에서 이미지 태그를 바꾸고 Redeploy 하세요 (1분)"
    return True, tag, f"🆕 업데이트 있습니다: {current} → {tag.lstrip('v')}\n{body}"


def install_cron(data_dir) -> tuple[bool, str]:
    from pathlib import Path
    from maintenance import install_job
    return install_job(data_dir, "kit-update-check", "hermes-kit 업데이트 확인",
                       "0 9 * * 1", Path(__file__), deliver="auto")


def main():
    import os
    import sys
    from pathlib import Path
    home = Path(os.environ.get("HERMES_HOME") or "/opt/data")
    version_file = Path("/opt/kit/RELEASE_VERSION")
    try:
        current = version_file.read_text().strip() if version_file.exists() else (home / ".kit-release-version").read_text().strip()
    except OSError:
        print("업데이트 확인 실패: 키트 릴리스 버전을 읽지 못했습니다", file=sys.stderr)
        return 1
    available, tag, message = check(current)
    if available:
        print(message)
    elif not tag:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
