"""Point Hermes (all profiles, cron, omh routing) from freellmapi to OmniRoute. Runs on the VPS host as root.
usage: hermes_to_omniroute.py --scope aux|all [--apply]
  aux  auxiliary.*, delegation, fallback_providers, cron jobs, omh routing (main conversation stays on freellmapi)
  all  + model.* (main conversation)
Backups: <file>.bak-omniroute-<ts> next to each file. Rollback: copy them back and restart Hermes.
The OmniRoute key is copied from /docker/omniroute/hermes-api-key into OMNIROUTE_API_KEY in every .env (never printed)."""
import glob, json, os, re, shutil, sys, time
import yaml

DATA = "/docker/hermes-agent-ywj7/data"
OMNI = "http://omniroute:20128/v1"
FL_HOST = "freellmapi-freellmapi-1:3001"
scope = sys.argv[sys.argv.index("--scope") + 1]
apply = "--apply" in sys.argv
TS = time.strftime("%Y%m%d-%H%M%S")
# freellmapi name -> OmniRoute name. Bare names not listed pass through (combo "solar-pro4" or an OmniRoute alias).
RENAME = {"auto": "hermes-public", "auto:hermes-fast": "hermes-fast",
          "deepseek/deepseek-v4.1-flash": "command-code/deepseek/deepseek-v4.1-flash",
          "deepseek/deepseek-v4-pro": "command-code/deepseek/deepseek-v4-pro",
          "moonshotai/Kimi-K2.7-Code": "command-code/moonshotai/Kimi-K2.7-Code",
          "moonshotai/Kimi-K3": "command-code/moonshotai/Kimi-K3",
          "openai/gpt-oss-120b": "hermes-fast",   # the cloudflare id has "@", which omh rejects (whole file ignored)
          # bare names freellmapi resolved itself; OmniRoute aliases match the model part of ANY prefix
          # (an alias hijacked claude/claude-sonnet-5 on 2026-09-27), so omh gets combo names instead
          "claude-sonnet-5": "hermes-ultrabrain", "gpt-5.3-codex": "hermes-coding", "gemini-2.5-flash": "hermes-writing",
          "gpt-5.6-luna": "hermes-coding"}   # omh proxy-luna (codex-review stays on openai-codex)


def rename(model):
    m = str(model)
    return RENAME.get(m) or ("hermes-" + m[5:] if m.startswith("auto:") else m)


def retarget(d):
    """Rewrite one {provider, model, base_url} route dict in place; True if it pointed at freellmapi."""
    if not isinstance(d, dict) or not (d.get("provider") == "freellmapi" or FL_HOST in str(d.get("base_url", ""))):
        return False
    d["provider"] = "omniroute"
    if "base_url" in d:
        d["base_url"] = OMNI
    for k in ("model", "default"):
        if d.get(k):
            d[k] = rename(d[k])
    for fc in d.get("fallback_chain") or []:
        retarget(fc)
    return True


def save(path, text, changes):
    if not changes:
        return
    print(f"  {path.replace(DATA + '/', '')}: {changes}")
    if apply:
        st = os.stat(path)
        shutil.copy2(path, f"{path}.bak-omniroute-{TS}")
        tmp = f"{path}.tmp-omniroute"
        with open(tmp, "w") as f:
            f.write(text)
        os.chown(tmp, st.st_uid, st.st_gid); os.chmod(tmp, st.st_mode & 0o777)
        os.replace(tmp, path)


def config(path):
    c = yaml.safe_load(open(path)) or {}
    n = 0
    for k, v in (c.get("auxiliary") or {}).items():
        n += retarget(v)
    n += retarget(c.get("delegation"))
    for fp in c.get("fallback_providers") or []:
        n += retarget(fp)
    if scope == "all":
        n += retarget(c.get("model"))
    if n:
        c.setdefault("providers", {})["omniroute"] = {"api": OMNI, "key_env": "OMNIROUTE_API_KEY",
                                                      "name": "OmniRoute", "transport": "openai_chat"}
        cl = c.get("context_lengths") or {}
        for k in [k for k in cl if FL_HOST in k]:
            model, _, _ = k.partition("@")
            cl[f"{rename(model)}@{OMNI}"] = cl[k]    # keep the freellmapi key too: rollback-safe, harmless
    save(path, yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=4096), f"{n} routes")


def cron(path):
    raw = json.load(open(path))
    jobs = raw.get("jobs", raw) if isinstance(raw, dict) else raw
    n = sum(retarget(j) for j in jobs)
    save(path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n", f"{n} jobs")


def omh():
    p = f"{DATA}/.omh/routing/model-providers.json"
    d = json.load(open(p)); n = 0
    for alias, r in list(d.get("models", {}).items()):
        if r.get("provider") == "freellmapi":
            r["provider"], r["model"] = "omniroute", rename(r["model"]); n += 1
            # model-chains.json below is renamed to hermes-*, so the new names need their own route keys
            d["models"].setdefault(r["model"], {"model": r["model"], "provider": "omniroute"})
    bad = [k for k, r in d["models"].items() if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}", r["model"])]
    assert not bad, f"omh would ignore the whole routes file; non-token models: {bad}"
    save(p, json.dumps(d, ensure_ascii=False, indent=2) + "\n", f"{n} model routes")
    p = f"{DATA}/.omh/routing/model-chains.json"
    d = json.load(open(p)); n = 0
    for chain in d.get("categories", {}).values():
        for step in chain:
            if str(step.get("model", "")).startswith("auto"):
                step["model"] = rename(step["model"]); n += 1
    save(p, json.dumps(d, ensure_ascii=False, indent=2) + "\n", f"{n} chain steps")


def env_files():
    key = open("/docker/omniroute/hermes-api-key").read().strip()
    for p in [f"{DATA}/.env"] + sorted(glob.glob(f"{DATA}/profiles/*/.env")):
        text = open(p).read()
        if re.search(r"^OMNIROUTE_API_KEY=", text, re.M):
            continue
        save(p, text.rstrip("\n") + f"\nOMNIROUTE_API_KEY={key}\n", "add OMNIROUTE_API_KEY")


def session_sticky():
    p = f"{DATA}/plugins/session-sticky/escalation.py"
    t = open(p).read()
    t2 = t.replace('ESCALATION_MODEL = "auto:commandcode"', 'ESCALATION_MODEL = "hermes-commandcode"') \
          .replace('ESCALATION_PROVIDER = "freellmapi"', 'ESCALATION_PROVIDER = "omniroute"')
    save(p, t2, "escalation -> hermes-commandcode" if t2 != t else "")
    p = f"{DATA}/plugins/session-sticky/middleware.py"
    t = open(p).read()
    old = 'or "freellmapi" in str(base_url).lower()\n    )'
    new = 'or "freellmapi" in str(base_url).lower()\n        # OmniRoute reads X-Session-Id natively (sessionManager) and serves the escalation combo\n        or provider.lower() == "omniroute"\n        or "omniroute" in str(base_url).lower()\n    )'
    save(p, t.replace(old, new), "gate +omniroute" if old in t else "")


print("scope:", scope, "mode:", "APPLY" if apply else "DRY-RUN")
env_files()
for p in [f"{DATA}/config.yaml"] + sorted(glob.glob(f"{DATA}/profiles/*/config.yaml")):
    config(p)
cron(f"{DATA}/cron/jobs.json")
omh()
if scope == "all":   # escalation rewrites only the model name, so it must move together with the main route
    session_sticky()
print("next: docker restart hermes-agent-ywj7-hermes-agent-1" if apply else "dry run only")
