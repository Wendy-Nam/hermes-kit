"""Dump synced model ids per connection -> migrate/models.txt as '<prefix>/<model>' (no secrets). stdin: admin password."""
import http.cookiejar, json, sys, urllib.error, urllib.request
base = sys.argv[1]; pw = sys.stdin.readline().strip()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def req(p, b=None):
    r = urllib.request.Request(base + p, data=None if b is None else json.dumps(b).encode(), method="POST" if b else "GET",
                               headers={"Content-Type": "application/json"})
    try:
        with op.open(r, timeout=180) as x: return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, {}
    except Exception as e: return 0, {"error": type(e).__name__}
req("/api/auth/login", {"password": pw})
_, nd = req("/api/provider-nodes")
prefix = {n["id"]: n.get("prefix") for n in ((nd.get("nodes") if isinstance(nd, dict) else nd) or [])}
_, d = req("/api/providers")
out, shape = [], None
for c in (d.get("connections") or d.get("data") or []):
    if not c.get("isActive", True): continue
    s, m = req(f"/api/providers/{c['id']}/models")
    lst = m.get("models") or m.get("data") or [] if isinstance(m, dict) else m
    if shape is None and lst: shape = sorted(lst[0].keys()) if isinstance(lst[0], dict) else type(lst[0]).__name__
    p = prefix.get(c["provider"], c["provider"])
    ids = [(x.get("id") or x.get("model") or x.get("name")) if isinstance(x, dict) else x for x in lst]
    out += [f"{p}\t{i}" for i in ids if i]
    print(f"{p:22} {c.get('name')!s:26} {s} {len(ids)}")
open("/docker/omniroute/migrate/models.txt", "w").write("\n".join(out) + "\n")
print("model entry fields:", shape, "total:", len(out))
