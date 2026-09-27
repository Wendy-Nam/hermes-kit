"""Download the private packs repo at boot.

The repo behind KIT_ACCESS_CODE holds the curated skills that make a kit feel like the
author's own server. Everything here is best effort: a student's first boot must succeed
even when the repo is unreachable, when the token expired (cohort over), or when the
network is down. Failure returns a message and the seed continues.

Two properties are deliberate:
- The tarball is unpacked to a temporary directory and only then copied into place, so a
  truncated download cannot leave a half-replaced skills tree.
- A symlink anywhere in the tarball aborts the whole thing. A tarball that can point at
  /opt/data would be able to overwrite the student's own .env through the fetch path.
"""
import io
import logging
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

TARBALL_URL = "https://api.github.com/repos/{repo}/tarball/{ref}"
MAX_BYTES = 60 * 1024 * 1024      # a packs repo is text; anything larger is not what we expect
# Copied only when absent — these are the author's own config, and a student may have edited theirs.
COPY_IF_ABSENT = ("soul", "omniroute")


def _download(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "hermes-kit",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError("팩 아카이브가 예상보다 큽니다")
    return blob


def _safe_extract(blob: bytes, dest: Path) -> None:
    """Extract, refusing symlinks and absolute paths before anything touches the disk."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            if m.issym() or m.islnk():
                raise ValueError(f"팩 아카이브에 링크가 있어 중단합니다: {m.name}")
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise ValueError(f"팩 아카이브에 안전하지 않은 경로가 있습니다: {m.name}")
        # filter="data" also strips setuid/setgid and device bits.
        tf.extractall(dest, members=members, filter="data")


def fetch(repo: str, ref: str, token: str, data_dir: Path) -> tuple[bool, str]:
    """Fetch and install packs. Returns (ok, message); never raises."""
    if not token:
        return False, "KIT_ACCESS_CODE 없음 — 비공개 팩을 건너뜁니다"
    data_dir = Path(data_dir)
    tmp = None
    try:
        tmp = Path(tempfile.mkdtemp(prefix=".kit-packs."))
        _safe_extract(_download(TARBALL_URL.format(repo=repo, ref=ref), token), tmp)
        roots = [p for p in tmp.iterdir() if p.is_dir()]
        if not roots:
            return False, "팩 아카이브가 비어 있습니다"
        root = roots[0]

        # skills/kit is kit-owned: replacing it is how a student gets pack updates.
        src_skills = root / "skills" / "kit"
        if src_skills.is_dir():
            dst_skills = data_dir / "skills" / "kit"
            shutil.rmtree(dst_skills, ignore_errors=True)
            dst_skills.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_skills, dst_skills)

        for name in COPY_IF_ABSENT:
            src, dst = root / name, data_dir / name
            if src.is_dir() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst)
        return True, "팩 설치 완료"
    except urllib.error.HTTPError as e:
        return False, f"팩 다운로드 실패 (HTTP {e.code})" + \
            (" — 코드가 만료되었을 수 있습니다" if e.code in (401, 403) else "")
    except Exception as e:
        log.warning("packs fetch failed: %s", e)
        return False, f"팩 다운로드 실패 ({type(e).__name__})"
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
