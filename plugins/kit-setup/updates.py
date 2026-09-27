"""Tell a student when a newer kit image exists — no LLM, once a week.

Version comparison is the fiddly part: "0.21.3-k2" against "0.21.2-k1" is not a string
comparison, and a wrong "you are up to date" is worse than saying nothing, so an
unparsable tag returns "unknown" rather than a guess.
"""
import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request

REGISTRY = "https://ghcr.io"
REPOSITORY = "wendy-nam/hermes-kit"
TAGS_PATH = "/v2/" + REPOSITORY + "/tags/list"
MANIFEST_ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json"))
MAX_PAGES = 5
MAX_TAGS = 500
MAX_MANIFESTS = 10
MAX_SECONDS = 30
MAX_BYTES = 1024 * 1024
_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-k(\d+))?$")


def parse_version(tag: str):
    m = _TAG.match((tag or "").strip())
    if not m:
        return None
    major, minor, patch, kit = m.groups()
    return int(major), int(minor), int(patch), int(kit or 0)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url, *, token=None, method="GET", deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("registry lookup deadline")
    headers = {"User-Agent": "hermes-kit", "Accept": MANIFEST_ACCEPT}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers, method=method)
    # No local Docker/GitHub credentials and no redirects to third-party hosts.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=min(5, remaining)) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES or time.monotonic() > deadline:
            raise ValueError("registry response limit")
        return body, {k.lower(): v for k, v in response.headers.items()}


def _next_page(link, current):
    if not link:
        return None
    match = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="?next"?\s*', link)
    if not match:
        raise ValueError("unsupported registry pagination")
    url = urllib.parse.urljoin(current, match.group(1))
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "ghcr.io"
            or parsed.path != TAGS_PATH or parsed.fragment):
        raise ValueError("unsafe registry pagination")
    return url


def latest_release() -> tuple[str | None, str]:
    """Resolve a version tag matching public GHCR latest; never use private GitHub APIs.

    Registry v2 tags pagination and manifest HEAD use identical Accept headers so
    multi-platform indexes are compared in the same representation. Any incomplete
    listing, unknown digest, timeout or moving latest returns unknown, not up-to-date.
    """
    try:
        deadline = time.monotonic() + MAX_SECONDS
        auth_url = REGISTRY + "/token?" + urllib.parse.urlencode({
            "service": "ghcr.io", "scope": "repository:" + REPOSITORY + ":pull"})
        body, _ = _request(auth_url, deadline=deadline)
        auth = json.loads(body)
        token = auth.get("token") or auth.get("access_token")
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise ValueError("missing anonymous registry token")

        def digest(tag):
            _, headers = _request(REGISTRY + "/v2/" + REPOSITORY + "/manifests/" + tag,
                                  token=token, method="HEAD", deadline=deadline)
            value = headers.get("docker-content-digest", "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError("missing manifest digest")
            return value

        latest = digest("latest")
        url = REGISTRY + TAGS_PATH + "?n=100"
        seen, tags = set(), set()
        for _ in range(MAX_PAGES):
            if url in seen:
                raise ValueError("registry pagination loop")
            seen.add(url)
            body, headers = _request(url, token=token, deadline=deadline)
            page = json.loads(body)
            values = page.get("tags")
            if page.get("name") != REPOSITORY or not isinstance(values, list):
                raise ValueError("invalid tag listing")
            if any(not isinstance(tag, str) or len(tag) > 128 for tag in values):
                raise ValueError("invalid tag")
            tags.update(values)
            if len(values) > 100 or len(tags) > MAX_TAGS:
                raise ValueError("registry tag limit")
            url = _next_page(headers.get("link"), url)
            if url is None:
                break
        if url is not None:
            raise ValueError("incomplete registry tag listing")
        # Prerelease/unversioned tags are ignored. A higher candidate must match
        # latest's digest; publishing a version tag alone does not announce it.
        candidates = sorted((t for t in tags if parse_version(t) is not None),
                            key=lambda t: (parse_version(t), t), reverse=True)
        for tag in candidates[:MAX_MANIFESTS]:
            if digest(tag) == latest:
                if digest("latest") != latest:
                    raise ValueError("latest changed during lookup")
                return tag, ""
        return None, "공개 이미지의 최신 버전 태그를 확인하지 못했습니다"
    except urllib.error.HTTPError as exc:
        return None, f"공개 이미지 저장소 응답 {exc.code}"
    except Exception:
        return None, "공개 이미지 업데이트 정보를 확인하지 못했습니다. 잠시 후 다시 확인해 주세요"


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
        "데이터를 백업한 뒤 Hostinger Docker Manager에서 이미지 태그를 바꾸고 Redeploy 하세요"
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
