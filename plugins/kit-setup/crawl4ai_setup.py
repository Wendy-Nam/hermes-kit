"""Opt-in local extractor for JavaScript-rendered pages (crawl4ai), like the author's server.

Default page extraction stays Hermes' keyless `web_extract`. This adds a fallback
command, `/opt/data/bin/jsextract <url>`, and a skill telling the agent to use it
only when `web_extract` comes back empty on a script-heavy page.

crawl4ai 0.9.4 pins Playwright 1.63.0, whose chromium-headless-shell revision (1243)
is the one the Hermes image already ships at PLAYWRIGHT_BROWSERS_PATH, so no
browser is downloaded. The virtualenv (~850 MB) lives on the data volume.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

CRAWL4AI = 'crawl4ai==0.9.4'
PLAYWRIGHT = 'playwright==1.63.0'
BROWSERS = '/opt/hermes/.playwright'
REVISION = 'chromium_headless_shell-1243'
ENV_DIR = 'crawl4ai-env'
TOOL = 'bin/jsextract'
SKILL = 'skills/kit-tools/js-page-extract/SKILL.md'
RECEIPT = '.kit-tools/crawl4ai.json'
MIN_FREE = 2 * 1024 ** 3

JSEXTRACT = r'''#!{python}
"""jsextract <url> [max_chars] - render a JavaScript-heavy public page and print markdown.

hermes-kit fallback for when web_extract returns empty text. Public http(s) only:
private, loopback and internal hosts are refused, like web_extract.
"""
import asyncio, ipaddress, os, socket, sys
from urllib.parse import urlsplit
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "{browsers}")
os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", "{cache}")

def public(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)

async def main():
    if len(sys.argv) < 2:
        print("usage: jsextract <url> [max_chars]", file=sys.stderr); return 2
    url, limit = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12000
    if not public(url):
        print("refused: public http(s) URLs only", file=sys.stderr); return 2
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
        result = await crawler.arun(url, config=CrawlerRunConfig(
            wait_until="domcontentloaded", delay_before_return_html=2.0, page_timeout=60000))
    markdown = getattr(result, "markdown", None)
    text = markdown.raw_markdown if hasattr(markdown, "raw_markdown") else (markdown or "")
    if not getattr(result, "success", False) or not text.strip():
        print("extract failed: " + str(getattr(result, "error_message", "") or "empty page")[:300], file=sys.stderr)
        return 1
    title = ((getattr(result, "metadata", None) or {{}}).get("title") or "").strip()
    print(("# " + title + "\n\n" if title else "") + text[:limit])
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
'''

SKILL_TEXT = '''---
name: js-page-extract
description: web_extract가 빈 결과나 오류를 준 JavaScript 렌더링 페이지(SPA, 쇼핑몰 목록 등)를 로컬 브라우저로 다시 읽는다.
---

# JS 페이지 다시 읽기

`web_extract`가 빈 본문·오류를 돌려줬고 페이지가 스크립트로 내용을 그리는 것으로 보일 때만 쓴다.
일반 페이지에는 쓰지 않는다. 한 번에 한 URL, 공개 http(s) 주소만 가능하다.

```bash
/opt/data/bin/jsextract "<url>" 12000
```

- 출력은 마크다운 본문이다. 실패하면 종료 코드가 1이고 원인이 stderr에 나온다.
- 로그인이 필요한 페이지, CAPTCHA, 봇 차단은 우회하지 않는다. 실패 사실을 사용자에게 알린다.
- 한 번에 몇 초~1분 걸리고 CPU를 쓴다. 같은 페이지를 반복해서 긁지 않는다.
'''


def status(data_dir):
    data = Path(data_dir)
    try:
        receipt = json.loads((data / RECEIPT).read_text())
    except (OSError, ValueError):
        return {'installed': False}
    return {'installed': (data / TOOL).is_file() and (data / ENV_DIR / 'bin/python').is_file(), **receipt}


def _run(argv, timeout, env=None):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError('command failed')
    return result.stdout


def install(data_dir):
    """Returns (ok, message). Never touches Hermes config; safe to retry."""
    from components import _locked
    data = Path(data_dir).resolve()
    try:
        with _locked(data):
            current = status(data)
            if current.get('installed') and current.get('crawl4ai') == CRAWL4AI:
                return True, 'JS 페이지 추출기가 이미 설치되어 있습니다.'
            if not (Path(BROWSERS) / REVISION).is_dir():
                return False, '이 이미지의 브라우저 버전이 달라 설치하지 않았습니다. 키트 업데이트 후 다시 시도해 주세요.'
            if shutil.disk_usage(data).free < MIN_FREE:
                return False, '디스크 여유 공간이 2GB 미만이라 설치하지 않았습니다.'
            if any(p.is_symlink() for p in (data / ENV_DIR, data / 'bin', data / 'skills')):
                return False, '설치 경로 링크를 허용하지 않습니다.'
            (data / '.kit-tools').mkdir(exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='crawl4ai-', dir=data / '.kit-tools'))
            try:
                venv = staging / 'env'
                env = dict(os.environ, PIP_CACHE_DIR=str(staging / 'pip-cache'))
                _run([sys.executable, '-m', 'venv', str(venv)], 120, env)
                _run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--disable-pip-version-check',
                      '--no-input', CRAWL4AI, PLAYWRIGHT], 1500, env)
                check = ('import importlib.metadata as m, crawl4ai, playwright;'
                         'print(m.version("crawl4ai"), m.version("playwright"))')
                versions = _run([str(venv / 'bin/python'), '-c', check], 120, env).split()
                if versions != [CRAWL4AI.split('==')[1], PLAYWRIGHT.split('==')[1]]:
                    raise RuntimeError('unexpected versions')
                target = data / ENV_DIR
                if target.exists(): shutil.rmtree(target)
                # Only bin/python is used, and it resolves its prefix from its own location.
                shutil.move(str(venv), str(target))
                _run([str(target / 'bin/python'), '-c', check], 120, env)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            tool = data / TOOL
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_text(JSEXTRACT.format(python=target / 'bin/python', browsers=BROWSERS,
                                             cache=data / '.kit-tools/crawl4ai-cache'))
            tool.chmod(0o755)
            skill = data / SKILL
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(SKILL_TEXT)
            (data / RECEIPT).write_text(json.dumps({'crawl4ai': CRAWL4AI, 'playwright': PLAYWRIGHT}) + '\n')
        return True, 'JS 페이지 추출기를 설치했습니다. 적용하기(재시작) 후 web_extract가 빈 결과를 줄 때 자동으로 사용합니다.'
    except subprocess.TimeoutExpired:
        return False, '설치 시간이 초과되었습니다. 네트워크 확인 후 다시 시도해 주세요.'
    except Exception as exc:
        return False, f'JS 페이지 추출기 설치 실패 ({type(exc).__name__}). 기존 설정은 바뀌지 않았습니다.'


def uninstall(data_dir):
    from components import _locked
    data = Path(data_dir).resolve()
    with _locked(data):
        for path in (data / TOOL, data / SKILL, data / RECEIPT):
            path.unlink(missing_ok=True)
        for path in (data / ENV_DIR, data / '.kit-tools/crawl4ai-cache', (data / SKILL).parent):
            shutil.rmtree(path, ignore_errors=True)
    return True, 'JS 페이지 추출기를 제거했습니다.'
