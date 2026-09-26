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
    """Weekly no-agent job. Idempotent, like the backup job."""
    import json
    from pathlib import Path

    jobs_file = Path(data_dir) / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True, exist_ok=True)
    jobs = json.loads(jobs_file.read_text()) if jobs_file.exists() else []
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", [])
    if any(j.get("id") == "kit-update-check" for j in jobs):
        return False, "업데이트 확인 크론이 이미 있습니다"
    jobs.append({"id": "kit-update-check", "name": "hermes-kit 업데이트 확인",
                 "schedule": "0 9 * * 1", "no_agent": True,
                 "command": str(Path(__file__).resolve())})
    jobs_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2))
    return True, "주간 업데이트 확인 크론을 등록했습니다"
