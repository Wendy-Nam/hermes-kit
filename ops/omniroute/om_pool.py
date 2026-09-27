"""Max-pool Hermes combos for OmniRoute, ranked by the freellmapi premium live catalog and gated by real probes.
Files in /docker/omniroute/migrate: models.txt (om_models.py), fl_catalog.json (fl_catalog.mjs), hermes-tools.json.
usage:
  om_pool.py plan            -> candidates.json (+ counts)            fetch current Cline pricing
  om_pool.py probe [pfx...]  -> probe.json  (Hermes 25-tool call / vision / plain call per unique model, hermes key;
                                             optional provider prefixes limit the run, e.g. `probe zai-web lmarena`)
  om_pool.py apply [--dry]   -> PUT every combo = head + subscription tier + probed pool + reserve   (stdin: admin pw)
Order per combo: curated head (proven 2026-09-26) -> subscription/web accounts (only where volume is low and data is
not private) -> free pool sorted by the premium catalog's intelligence (or speed) rank -> E6-3 reserve last.
Gemini-family ids are kept out of tool-loop combos (OmniRoute drops the Gemini 3 thought_signature)."""
from decimal import Decimal, InvalidOperation
import base64, concurrent.futures as cf, json, os, struct, sys, time, urllib.error, urllib.request, zlib

MIG = "/docker/omniroute/migrate"
BASE = "http://127.0.0.1:20128"
phase = sys.argv[1]
CF_, MI = "cloudflare-ai/@cf/", "mistral/"
RES_CF, RES_XK = CF_ + "openai/gpt-oss-120b", "xkiro/qwen/qwen3.8-max:free"
MIN8, MIN14 = MI + "ministral-8b-latest", MI + "ministral-14b-latest"
# freellmapi platform -> OmniRoute prefix (om_import.py mapping; custom/navy/router9 are not pooled).
# kilo/ovh are keyless nodes: the built-ins demand a key and a bad key makes both upstreams refuse (2026-09-27)
PFX = {"agnes": "agnes", "aion": "aion", "anyapi": "anyapi", "bai": "bai", "groq": "groq", "kilo": "kilo-anon", "llm7": "llm7",
       "longcat": "longcat", "mistral": "mistral", "nara": "nara", "nvidia": "nvidia", "opencode": "opencode-zen",
       "openrouter": "openrouter", "orcarouter": "orcarouter", "reka": "reka", "routeway": "routeway", "sealion": "sealion", "ovh": "ovh-anon", "aihorde": "aihorde",
       "siliconflow": "siliconflow", "cohere": "cohere", "electronhub": "electronhub", "google": "gemini", "logfare": "logfare",
       "pollinations": "pollinations", "airforce": "api-airforce", "ainative": "ainative", "bazaarlink": "bazaarlink",
       "cerebras": "cerebras", "huggingface": "huggingface", "ollama": "ollama-cloud", "requesty": "requesty",
       "unorouter": "unorouter", "cloudflare": "cloudflare-ai", "blaze": "blaze", "clod": "clod", "dreamprompting": "dreamprompting",
       "experiential": "experiential", "lucidity": "lucidity", "moondream": "moondream", "septor": "septor", "waterfall": "waterfall",
       "xkiro": "xkiro", "github": "github-models", "sail": "sail", "zhipu": "zhipu"}
# auggie/devin-cli need their CLI inside the container: left out. zai-web needs Playwright Chromium -> the `-web` image
# Cline: curated candidates only; every phase revalidates all advertised price fields.
# A successful request or a :free suffix is not price evidence. Cache prices, when
# advertised, must also be zero. Missing cache fields are not a zero-price claim.
CLINE_FREE = ["cline/nvidia/nemotron-3-ultra-550b-a55b:free",
              "cline/nvidia/nemotron-3-super-120b-a12b:free", "cline/qwen/qwen3.8-27b:free", "cline/google/gemma-4-31b-it:free",
              "cline/inclusionai/ling-3.0-flash-fin:free", "cline/poolside/laguna-s-2.1:free", "cline/thinkingmachines/inkling:free",
              "cline/nvidia/nemotron-3.5-lightning:free"]
KIMI_FREE = ["unorouter/kimi-k3:free"]
# Nous stays a direct Hermes provider: free tier = OAuth only, no API key, and OmniRoute nous-research is key-only
# Antigravity: agy = Antigravity CLI Pro account (hanzoom2000, first), antigravity = second account (sharedwendy999).
# Its Gemini is allowed in tool tiers: OmniRoute's antigravity signature cache round-trips the Gemini 3 thought
# signature (multi-turn loops passed 2026-09-27); plain gemini/* stays out of tool combos.
AG_MAIN = ["agy/claude-sonnet-4-6", "agy/gemini-3.8-flash-medium", "antigravity/claude-sonnet-4-6", "antigravity/gemini-3.8-flash-tiered"]
AG_SMART = ["agy/gemini-3.1-pro-high", "agy/claude-sonnet-4-6", "agy/gemini-3.8-flash-medium",
            "antigravity/gemini-3.1-pro-high", "antigravity/claude-sonnet-4-6", "antigravity/gemini-3.8-flash-tiered"]
AG_BRAIN = ["agy/gemini-3.1-pro-high", "agy/claude-opus-4-6-thinking", "antigravity/gemini-3.1-pro-high", "antigravity/claude-opus-4-6-thinking"]
# Copilot (every model "not supported for this integration") and zai-web (browser transport 502) dropped 2026-09-27
SUB_MAIN = ["codex/gpt-6-luna", "claude/claude-sonnet-5"] + AG_MAIN + ["deepseek-web/deepseek-v4-pro"] + KIMI_FREE + CLINE_FREE
SUB_SMART = (["codex/gpt-6-sol", "codex/gpt-5.6-terra", "claude/claude-sonnet-5"] + AG_SMART
             + KIMI_FREE + ["codex/gpt-6-luna", "deepseek-web/deepseek-v4-pro"] + CLINE_FREE
             + ["agy/gpt-oss-120b-medium", "antigravity/gpt-oss-120b-medium"])
SUB_BRAIN = (["codex/gpt-6-astra", "codex/gpt-6-sol"] + AG_BRAIN[:2] + ["claude/claude-opus-5-5", "claude/claude-opus-5"]
             + AG_BRAIN[2:] + KIMI_FREE + ["deepseek-web/deepseek-v4-pro-think"])
# public profile answers other people: no paid-subscription quota, but lmarena/web sessions are fine there
SUB_PUBLIC = KIMI_FREE + CLINE_FREE + ["deepseek-web/deepseek-v4-flash", "lmarena/claude-sonnet-5", "lmarena/gpt-5.5-instant", "lmarena/qwen3.7-max", "lmarena/kimi-k2.6", "lmarena/glm-5.1",
              "lmarena/deepseek-v4-pro-thinking", "lmarena/mistral-large-3", "lmarena/minimax-m3"]
SUB_VISION = ["codex/gpt-6-luna", "agy/gemini-3.8-flash-medium", "claude/claude-sonnet-5", "antigravity/gemini-3.8-flash-tiered",
              "antigravity/claude-sonnet-4-6"]
# free routes that log prompts for training / publish arena chats: public profile only
TRAINS = {"kilo-gateway", "kilo-anon", "lmarena", "aihorde"}   # aihorde: volunteer workers see the prompt

# name: (kind, sort, min_ctx, head, subscription tier, pool platforms (None=all, []=none), reserve, cap, extra)
C = {
    "solar-pro4": ("tools", "ir", 128000, ["upstage/solar-pro4"], SUB_MAIN, None, [RES_CF], 40, {"context_length": 131072}),
    # general chat (default profile): user prefers DeepSeek conversation style; Codex fallback, then the old
    # main. The RP channel stays on solar-pro4 via discord.channel_overrides (frontier models refuse there, a refusal is a 200)
    "hermes-chat": ("tools", "ir", 128000, ["command-code/deepseek/deepseek-v4.1-flash", "codex/gpt-6-luna", "upstage/solar-pro4"],
                    ["claude/claude-sonnet-5"] + AG_MAIN + ["deepseek-web/deepseek-v4-pro"] + CLINE_FREE, None, [RES_CF], 30,
                    {"context_length": 131072}),
    # free-only lane for omh delegation (owner: free models used actively, 2026-09-27); paid combos follow in the omh chain
    "hermes-free": ("tools", "ir", 64000, ["unorouter/kimi-k3:free", "experiential/gpt-5.6-luna",
                                           "cline/nvidia/nemotron-3-ultra-550b-a55b:free", "cline/nvidia/nemotron-3-super-120b-a12b:free",
                                           "nvidia/nvidia/nemotron-3-ultra-550b-a55b"], CLINE_FREE, None, [RES_XK], 40, {}),
    "hermes-fast": ("tools", "sr", 32000, [MIN8, MIN14, "groq/openai/gpt-oss-120b", "cerebras/gpt-oss-120b"], [], None, [RES_CF], 30, {}),
    "hermes-private": ("tools", "ir", 32000, [MI + "codestral-latest", MIN8, MIN14], [], ["mistral", "cloudflare-ai"], [RES_CF], 30,
                       {"allowedProviders": ["mistral", "cloudflare-ai"]}),
    "hermes-ops-fast": ("plain", "sr", 8000, ["groq/openai/gpt-oss-20b", "groq/qwen/qwen3.8-27b", CF_ + "openai/gpt-oss-20b",
                                              "gemini/gemini-2.5-flash-lite"], [], None, [], 20, {}),
    "hermes-compress": ("plain", "ir", 128000, ["upstage/solar-pro4", MIN8, MIN14], [], None, [], 20, {}),
    "hermes-vision": ("vision", "ir", 0, ["command-code/google/gemini-3.8-flash", MI + "ministral-8b-2512", MI + "ministral-14b-2512"],
                      SUB_VISION, None, [], 20, {}),
    "hermes-coding": ("tools", "ir", 64000, ["experiential/gpt-5.6-luna", "electronhub/gpt-5.6-luna", "huggingface/moonshotai/Kimi-K2.7-Code",
                                             "nvidia/nvidia/nemotron-3-ultra-550b-a55b", MI + "codestral-latest"], SUB_SMART, None, [RES_XK], 40, {}),
    "hermes-coding-worker": ("tools", "ir", 64000, [CF_ + "deepseek-ai/deepseek-r1-distill-qwen-32b", CF_ + "qwen/qwen3-30b-a3b-fp8",
                                                    MIN14, "openrouter/google/gemma-4-31b-it:free", MI + "codestral-latest"], [], None, [RES_CF], 40, {}),
    # free models only (the public profile exists to burn free quota). codestral first made the summary channel ask back,
    # hunt for the skill in the tool list and give up (2026-09-27): chat-capable free models lead
    "hermes-public": ("tools", "ir", 32000, ["experiential/gpt-5.6-luna", "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
                                             "cline/nvidia/nemotron-3-ultra-550b-a55b:free", MI + "codestral-latest",
                                             "cohere/command-a-03-2025"], SUB_PUBLIC, None, [RES_CF], 40, {}),
    "hermes-commandcode": ("tools", "ir", 64000, ["command-code/deepseek/deepseek-v4.1-flash", "command-code/moonshotai/Kimi-K2.7-Code",
                                                  "command-code/Qwen/Qwen3.8-Flash", "command-code/deepseek/deepseek-v4-flash"], SUB_SMART, None, [], 40, {}),
    "hermes-ultrabrain": ("tools", "ir", 64000, [], SUB_BRAIN + ["command-code/deepseek/deepseek-v4.1-flash", "command-code/moonshotai/Kimi-K2.7-Code"], None, [RES_XK], 40, {}),
    "hermes-writing": ("tools", "ir", 64000, ["upstage/solar-pro4"], SUB_SMART, None, [RES_CF], 40, {}),
    "hermes-visual-engineering": ("tools", "ir", 64000, ["command-code/moonshotai/Kimi-K2.7-Code", "command-code/deepseek/deepseek-v4.1-flash"],
                                  SUB_SMART, None, [RES_CF], 40, {}),
}
UNLISTED_OK = {"upstage/solar-pro4"} | set(CLINE_FREE)   # Upstage /models omits solar-pro4; OmniRoute's Cline list is curated (13) but ids pass through


CLINE_CATALOG_URL = "https://api.cline.bot/api/v1/ai/cline/models"


def cline_zero_price(row):
    """Require input/output prices and reject any advertised nonzero/unknown price."""
    prices = row.get("pricing")
    if not isinstance(prices, dict) or not {"prompt", "completion"} <= prices.keys():
        return False
    try:
        # Reject bool/null/NaN/infinity and malformed values, including cache prices.
        return all(not isinstance(v, bool) and Decimal(str(v)).is_finite()
                   and Decimal(str(v)) == 0 for v in prices.values())
    except (InvalidOperation, ValueError, TypeError):
        return False


def cline_free_catalog():
    """Fetch fresh public prices; failure aborts before probes or combo mutations."""
    try:
        with urllib.request.urlopen(CLINE_CATALOG_URL, timeout=30) as response:
            rows = json.load(response)["data"]
        if not isinstance(rows, list) or not rows or any(
                not isinstance(r, dict) or not isinstance(r.get("id"), str) for r in rows):
            raise ValueError("invalid catalog")
        # Duplicate IDs must not allow a free row to shadow a paid/unknown row.
        grouped = {}
        for row in rows:
            grouped.setdefault(row["id"], []).append(row)
        return {"cline/" + mid for mid, versions in grouped.items()
                if all(cline_zero_price(row) for row in versions)}
    except Exception:
        raise RuntimeError("Cline pricing unavailable: refusing to probe or change combos") from None


def cline_allowed(model, free):
    return not model.startswith("cline/") or model in free


def gemini(m):
    return "gemini" in m.lower() or m.startswith("gemini/")


def plan():
    free = cline_free_catalog()
    known = {l.replace("\t", "/", 1).strip() for l in open(f"{MIG}/models.txt") if l.strip()} | UNLISTED_OK
    known = {m for m in known if cline_allowed(m, free)}
    cat = json.load(open(f"{MIG}/fl_catalog.json"))["models"]
    out = {}
    for name, (kind, sort, min_ctx, head, sub, plats, reserve, cap, extra) in C.items():
        fixed = set(head + sub + reserve) | {RES_CF, RES_XK}   # E6-3 reserves never float up into a pool
        pool = []
        for r in cat:
            p = PFX.get(r["platform"])
            m = f"{p}/{r['id']}" if p else None
            if not m or m not in known or m in fixed or not r["enabled"] or (r["pin"] or 0) > 0:
                continue
            if plats is not None and p not in plats:
                continue
            if p in TRAINS and name != "hermes-public":
                continue
            if kind == "tools" and (not r["tools"] or gemini(m)):
                continue
            if kind == "vision" and not r["vision"]:
                continue
            if r["ctx"] and r["ctx"] < min_ctx:
                continue
            if p == "openrouter" and not m.endswith(":free"):
                continue
            key = (r["ir"] or 999, r["sr"] or 999) if sort == "ir" else (r["sr"] or 999, r["ir"] or 999)
            pool.append((key, bool(r["ctx"]) is False, m))
        pool = [m for _, _, m in sorted(set(pool))]
        missing = [m for m in head + sub + reserve if m not in known]
        out[name] = {"kind": kind, "head": [m for m in head if m in known], "sub": [m for m in sub if m in known],
                     "pool": pool[: cap * 2], "reserve": [m for m in reserve if m in known], "cap": cap, "extra": extra}
        print(f"{name:26} head={len(out[name]['head'])} sub={len(out[name]['sub'])} pool={len(pool)} (probe {len(out[name]['pool'])})"
              + (f" missing={missing}" if missing else ""))
    json.dump(out, open(f"{MIG}/candidates.json", "w"), indent=1)


def png_red():
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 16 for _ in range(16))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
                            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")).decode()


def call(key, body, timeout=90):
    r = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(), method="POST",
                               headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                        "X-OmniRoute-No-Cache": "true"})
    t = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return time.time() - t, json.load(x), None
    except urllib.error.HTTPError as e:
        return time.time() - t, None, f"{e.code} {e.read().decode('utf-8', 'replace')[:160]}"
    except Exception as e:
        return time.time() - t, None, type(e).__name__


def probe_one(key, tools, img, m, kinds):
    res = {}
    for k in kinds:
        if k == "tools":
            body = {"model": m, "max_tokens": 300, "tools": tools, "tool_choice": "auto",
                    "messages": [{"role": "user", "content": "read_file 도구로 /etc/hostname 파일을 읽어줘."}]}
        elif k == "vision":
            body = {"model": m, "max_tokens": 200, "messages": [{"role": "user", "content": [
                {"type": "text", "text": "이 이미지는 무슨 색이야? 한 단어로."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}]}
        else:
            body = {"model": m, "max_tokens": 400, "messages": [{"role": "user", "content": "한 단어로만 답해: 대한민국의 수도는?"}]}
        dt, d, err = call(key, body)
        if err and err[:3] in ("403", "429", "500", "502", "503", "504", "Tim"):   # transient: upstream burst limits, cooldowns
            time.sleep(20)
            dt, d, err = call(key, body)
        msg = ((d or {}).get("choices") or [{}])[0].get("message") or {}
        if k == "tools":
            names = [c.get("function", {}).get("name") for c in msg.get("tool_calls") or []]
            ok = "read_file" in names
            why = err or ("no tool call: " + str(msg.get("content") or "")[:60] if not ok else "")
        else:
            text = str(msg.get("content") or "")
            ok = bool(text.strip()) and (k != "vision" or any(w in text.lower() for w in ("빨", "red", "적색", "붉")))
            why = err or ("" if ok else "answer: " + text[:60])
        res[k] = {"ok": ok, "s": round(dt, 1), "why": why}
    return m, res


def probe():
    free = cline_free_catalog()
    cand = json.load(open(f"{MIG}/candidates.json"))
    old = json.load(open(f"{MIG}/probe.json")) if os.path.exists(f"{MIG}/probe.json") else {}
    need = {}
    for c in cand.values():
        for m in c["head"] + c["sub"] + c["pool"] + c["reserve"]:
            if not cline_allowed(m, free):
                continue
            if not (old.get(m, {}).get(c["kind"]) or {}).get("ok"):   # incremental: passed (model, kind) pairs are kept
                need.setdefault(m, set()).add(c["kind"])
    only = set(sys.argv[2:])
    if only:
        need = {m: k for m, k in need.items() if m.split("/", 1)[0] in only}
    key = open("/docker/omniroute/hermes-api-key").read().strip()
    tools = json.load(open(f"{MIG}/hermes-tools.json"))
    img = png_red()
    by_prov = {}
    for m, kinds in need.items():
        by_prov.setdefault(m.split("/", 1)[0], []).append((m, sorted(kinds)))
    results = old
    print(f"probing {len(need)} models ({sum(map(len, need.values()))} checks), keeping {len(old)} earlier results", flush=True)

    def run_provider(items):   # providers in parallel, models of one provider sequential + spaced
        out = []
        for m, kinds in items:
            out.append(probe_one(key, tools, img, m, kinds))
            time.sleep(1.5)
        return out

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for batch in ex.map(run_provider, by_prov.values()):
            for m, r in batch:
                results[m] = {**results.get(m, {}), **r}
                print(f"  {m:60} " + " ".join(f"{k}={'OK' if v['ok'] else 'X'}({v['s']}s)" for k, v in r.items())
                      + "".join(f"  [{v['why'][:70]}]" for v in r.values() if not v["ok"]), flush=True)
    json.dump(results, open(f"{MIG}/probe.json", "w"), indent=1, ensure_ascii=False)
    ok = sum(any(v["ok"] for v in r.values()) for r in results.values())
    print(f"probed {len(results)} models, passing at least one check: {ok}")


def apply(dry):
    import http.cookiejar
    free = cline_free_catalog()
    cand, pr = json.load(open(f"{MIG}/candidates.json")), json.load(open(f"{MIG}/probe.json"))
    passed = lambda m, k: cline_allowed(m, free) and bool((pr.get(m, {}).get(k) or {}).get("ok"))
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(meth, p, b=None):
        r = urllib.request.Request(BASE + p, data=None if b is None else json.dumps(b).encode(), method=meth,
                                   headers={"Content-Type": "application/json"})
        try:
            with op.open(r, timeout=180) as x:
                return x.status, json.loads(x.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
    print("login:", req("POST", "/api/auth/login", {"password": sys.stdin.readline().strip()})[0])
    s, d = req("GET", "/api/combos")
    existing = {c["name"]: c for c in ((d.get("combos") if isinstance(d, dict) else d) or [])}
    for name, c in cand.items():
        k = c["kind"]
        pool = [m for m in c["pool"] if passed(m, k)][: c["cap"]]
        models = []
        for m in c["head"] + c["sub"] + pool + c["reserve"]:
            if m not in models and passed(m, k):   # heads too: a polite refusal is a 200, so fallback never fires
                models.append(m)
        if len(models) < 3:   # a bad probe run (router down, network blip) must not empty a live combo
            print(f"  skip {name}: only {len(models)} passing models, keeping the current combo"); continue
        body = {"name": name, "strategy": "priority", "models": models, **c["extra"],
                "description": (existing.get(name) or {}).get("description")}
        if not body["description"]:
            body.pop("description")   # the schema takes a string or nothing, not null (new combos have none)
        tag = f"{name:26} {len(models):3} models (head {sum(passed(m, k) for m in c['head'])}/{len(c['head'])}, sub {sum(passed(m, k) for m in c['sub'])}/{len(c['sub'])}, pool {len(pool)})"
        if dry:
            print("  plan", tag); continue
        s, _ = req("PUT", f"/api/combos/{existing[name]['id']}", body) if name in existing else req("POST", "/api/combos", body)
        print(f"  {tag} -> {s}")


if phase == "plan":
    plan()
elif phase == "probe":
    probe()
elif phase == "apply":
    apply("--dry" in sys.argv)
