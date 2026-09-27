"""Fetch optional, commit-pinned private skill bundles.

Basic job skills ship in the image. Private access is never required to boot.
Validate inventory and content hashes before installation; components preserve
user edits and stage replacements with rollback. No scripts or plugins execute.
"""
import io
import logging
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

log = logging.getLogger(__name__)

TARBALL_URL = "https://api.github.com/repos/{repo}/tarball/{ref}"
MAX_BYTES = 60 * 1024 * 1024      # a packs repo is text; anything larger is not what we expect


class _ArchiveRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != 'https' or target.hostname not in {'api.github.com', 'codeload.github.com'} or target.username or target.password:
            raise ValueError('archive redirect refused')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "hermes-kit",
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _ArchiveRedirect())
    with opener.open(req, timeout=60) as r:
        blob = r.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError("팩 아카이브가 예상보다 큽니다")
    return blob


def _safe_extract(blob: bytes, dest: Path) -> None:
    """Extract, refusing symlinks and absolute paths before anything touches the disk."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        members = tf.getmembers()
        if len(members) > 5000 or sum(m.size for m in members) > MAX_BYTES:
            raise ValueError("팩 압축 해제 크기가 제한을 넘습니다")
        for m in members:
            if m.issym() or m.islnk():
                raise ValueError(f"팩 아카이브에 링크가 있어 중단합니다: {m.name}")
            if m.name.startswith("/") or ".." in Path(m.name).parts:
                raise ValueError(f"팩 아카이브에 안전하지 않은 경로가 있습니다: {m.name}")
        # filter="data" also strips setuid/setgid and device bits.
        tf.extractall(dest, members=members, filter="data")


def fetch(repo: str, ref: str, token: str, data_dir: Path) -> tuple[bool, str]:
    """Download an explicitly pinned bundle; validate all components before installing.

    A commit SHA is required: credentials authorize access, not arbitrary code updates.
    Only skill packages are accepted; plugin installation has a separate trust registry.
    """
    import json
    import re
    from components import KITS, _manifest, install_component
    if not token:
        return False, "KIT_ACCESS_CODE 없음 — 비공개 팩을 건너뜁니다"
    if not re.fullmatch(r"[a-fA-F0-9]{40}", ref or ""):
        return False, "팩 버전을 고정한 커밋이 필요합니다 — 기본 직무 팩은 계속 사용할 수 있습니다"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return False, "팩 저장소 주소가 올바르지 않습니다"
    tmp = None
    installed = []
    try:
        tmp = Path(tempfile.mkdtemp(prefix=".kit-packs."))
        _safe_extract(_download(TARBALL_URL.format(repo=repo, ref=ref), token), tmp)
        roots = list(tmp.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError("invalid archive root")
        root = roots[0]
        manifest = json.loads((root / "manifest.json").read_text())
        if manifest.get("schema_version") != "kit-bundle/v1" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(manifest.get("version", ""))):
            raise ValueError("invalid bundle manifest")
        ids = manifest.get("components")
        if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids) or any(k not in KITS for k in ids):
            raise ValueError("invalid bundle components")
        for cid in ids:
            _manifest(root / "kits" / cid, cid)
        results = []
        for cid in ids:
            result = install_component(root / "kits" / cid, data_dir, cid)
            results.append(result)
            if result["status"] == "installed": installed.append(cid)
        preserved = [r["id"] for r in results if r["status"] == "preserved"]
        if preserved:
            return False, "사용자 변경을 보존했습니다: " + ", ".join(preserved)
        return True, "팩 설치 완료 · " + manifest["version"]
    except urllib.error.HTTPError as e:
        return False, f"팩 다운로드 실패 (HTTP {e.code})" + (" — 코드가 만료되었을 수 있습니다" if e.code in (401, 403) else "")
    except Exception as e:
        return False, f"팩 설치 실패 ({type(e).__name__}); 이번 실행에서 설치된 구성요소: " + (", ".join(installed) or "없음") + ". 설치 상태를 확인한 뒤 재시도할 수 있습니다"
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
