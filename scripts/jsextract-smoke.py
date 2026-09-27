"""Opt-in JS page extractor installs on the shipped image, reuses its Chromium and
refuses internal addresses. Network is used only by pip."""
import http.server, os, subprocess, sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, '/opt/kit/plugins/kit-setup')
import crawl4ai_setup as c

with tempfile.TemporaryDirectory(prefix='kit-jsextract-') as directory:
    data = Path(directory)
    ok, message = c.install(data)
    assert ok, message
    assert c.status(data)['installed'] and (data / c.SKILL).is_file()
    again = c.install(data)
    assert again[0] and '이미' in again[1], again
    tool = str(data / c.TOOL)
    for url in ('http://127.0.0.1:1/', 'http://omniroute:20128/v1', 'file:///etc/passwd', 'http://169.254.169.254/'):
        result = subprocess.run([tool, url], capture_output=True, text=True, timeout=60)
        assert result.returncode == 2 and 'refused' in result.stderr, (url, result.returncode, result.stderr[-200:])
    page = ('<html><head><meta charset="utf-8"><title>Shop</title></head><body><main><ul id=l></ul></main><script>'
            'for(let i=0;i<40;i++){const li=document.createElement("li");li.innerText="item "+i+" rendered by script "+i*7;'
            'document.getElementById("l").appendChild(li)}</script></body></html>')
    root = data / 'www'; root.mkdir(); (root / 'index.html').write_text(page)
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Local pages are refused by jsextract itself; exercise the same engine directly.
    script = ('import asyncio,sys\nfrom crawl4ai import AsyncWebCrawler,BrowserConfig,CrawlerRunConfig\n'
              'async def go():\n async with AsyncWebCrawler(config=BrowserConfig(headless=True,verbose=False)) as w:\n'
              '  r=await w.arun(sys.argv[1],config=CrawlerRunConfig(wait_until="domcontentloaded",delay_before_return_html=1.0))\n'
              '  print(r.success, "rendered by script 273" in (r.markdown.raw_markdown or ""))\nasyncio.run(go())')
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=c.BROWSERS, CRAWL4_AI_BASE_DIRECTORY=str(data / '.kit-tools/crawl4ai-cache'))
    out = subprocess.run([str(data / c.ENV_DIR / 'bin/python'), '-c', script, f'http://127.0.0.1:{server.server_port}/'],
                         capture_output=True, text=True, timeout=180, env=env)
    assert out.stdout.strip().endswith('True True'), (out.stdout[-300:], out.stderr[-500:])
    server.shutdown()
    assert c.uninstall(data)[0] and not (data / c.ENV_DIR).exists() and not (data / c.TOOL).exists()
print('jsextract: pinned install on the image Chromium, internal URLs refused, JS rendered, removal passed')
