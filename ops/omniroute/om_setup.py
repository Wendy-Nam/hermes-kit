"""OmniRoute setup for Hermes (step A). stdin line 1: admin password. Never prints a key.
usage: om_setup.py <base> <phase>...   phases: settings prune sync key models
  settings  skills injection off, semantic response cache off
  prune     delete fl-ovh / fl-aihorde (anonymous services, invalid key), deactivate cline connections
  sync      autoSync=true on every connection + one sync now (live /models, then every MODEL_SYNC_INTERVAL_HOURS)
  key       create inference key "hermes" once -> /docker/omniroute/hermes-api-key (600)
  models    list /v1/models ids (canonical prefix) -> /docker/omniroute/migrate/models.txt"""
import http.cookiejar, json, os, sys, urllib.error, urllib.request

base, phases = sys.argv[1], sys.argv[2:]
pw = sys.stdin.readline().strip()
KEY_FILE = "/docker/omniroute/hermes-api-key"
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def req(method, path, body=None, headers=None, timeout=120):
    r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with op.open(r, timeout=timeout) as x:
            return x.status, json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:   # timeouts on slow upstream /models
        return 0, {"error": type(e).__name__}


def err(d):
    e = d.get("error") if isinstance(d, dict) else None
    return str((e.get("message") if isinstance(e, dict) else e) or "")[:120]


def connections():
    s, d = req("GET", "/api/providers")
    return (d.get("connections") or d.get("data") or []) if isinstance(d, dict) else d


print("login:", req("POST", "/api/auth/login", {"password": pw})[0])

if "settings" in phases:
    print("memory.skillsEnabled=false:", req("PUT", "/api/settings/memory", {"skillsEnabled": False})[0])
    for m in ("PUT", "PATCH", "POST"):
        s, d = req(m, "/api/settings/cache-config", {"semanticCacheEnabled": False})
        if s != 405:
            break
    print(f"cache-config semanticCacheEnabled=false: {m} {s} {err(d)}")
    s, d = req("GET", "/api/settings/memory"); print("  now skillsEnabled =", d.get("skillsEnabled"), "memory enabled =", d.get("enabled"))
    s, d = req("GET", "/api/settings/cache-config"); print("  now semanticCacheEnabled =", d.get("semanticCacheEnabled"))

if "prune" in phases:
    for c in connections():
        if c.get("name") in ("fl-ovh", "fl-aihorde"):
            s, d = req("DELETE", f"/api/providers/{c['id']}")
            print(f"delete {c['name']}: {s} {err(d)}")
        elif c.get("provider") == "cline" and c.get("isActive", True):
            s, d = req("PUT", f"/api/providers/{c['id']}", {"isActive": False})
            print(f"deactivate cline ({c.get('name') or c['id'][:8]}): {s} {err(d)}")

if "sync" in phases:
    tot = {"ok": 0, "fail": 0}
    for c in sorted(connections(), key=lambda c: c.get("name") or ""):
        if not c.get("isActive", True):
            continue
        name = c.get("name") or c.get("provider")
        s1, d1 = req("PUT", f"/api/providers/{c['id']}", {"providerSpecificData": {"autoSync": True}})
        s2, d2 = req("POST", f"/api/providers/{c['id']}/sync-models", {}, timeout=180)
        ok = s1 == 200 and s2 == 200
        tot["ok" if ok else "fail"] += 1
        info = {k: d2.get(k) for k in ("added", "removed", "updated", "total", "count", "modelCount") if isinstance(d2, dict) and k in d2}
        ch = d2.get("changes") if isinstance(d2, dict) else None
        print(f"  {name:24} autoSync={s1} sync={s2} {info or ''} {ch if isinstance(ch, dict) else ''} {'' if ok else err(d2) or err(d1)}")
    print("sync summary:", tot)

if "key" in phases:
    if os.path.exists(KEY_FILE):
        print("hermes key: exists, skip")
    else:
        s, d = req("POST", "/api/keys", {"name": "hermes"})
        k = (d.get("key") or "") if isinstance(d, dict) else ""
        if s in (200, 201) and k:
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, k.encode()); os.close(fd)
            print("hermes key: created ->", KEY_FILE)
        else:
            print("hermes key: FAILED", s, err(d))

if "models" in phases:
    k = open(KEY_FILE).read().strip()
    s, d = req("GET", "/v1/models?prefix=canonical", headers={"Authorization": f"Bearer {k}"}, timeout=300)
    ids = sorted(m["id"] for m in d.get("data", [])) if s == 200 else []
    with open("/docker/omniroute/migrate/models.txt", "w") as f:
        f.write("\n".join(ids) + "\n")
    print(f"/v1/models: {s} {len(ids)} ids -> migrate/models.txt {err(d)}")
