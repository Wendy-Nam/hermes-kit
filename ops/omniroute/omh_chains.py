"""omh delegation: shipped per-category recommendations with concrete OmniRoute ids (2026-09-27).
omh picks its per-model calibration prompt from routing.model; a combo name ("hermes-free") resolves to family "unknown",
so every alias below points at one real model. Free routes wherever the recommended model is free (kimi, deepseek, glm).
Runs on the VPS host as root; backups *.bak-omh-rec-<ts>."""
import json, os, shutil, time

B = "/docker/hermes-agent-ywj7/data/.omh/routing/"
O = "omniroute"
ROUTES = {  # alias (omh shipped vocabulary) -> OmniRoute id, all passed a multi-turn Hermes tool loop 2026-09-27
    "gpt-6-astra": "codex/gpt-6-astra", "gpt-6-sol": "codex/gpt-6-sol", "gpt-6-luna": "codex/gpt-6-luna",
    "deepseek-flash": "cline/deepseek/deepseek-v4.1-flash",          # free
    "kimi-k3": "sail/moonshotai/Kimi-K3",                            # free (unorouter kimi-k3:free rate-limits on turn 2)
    "glm-5.3": "sail/zai-org/GLM-5.3", "glm-5.3-flash": "sail/zai-org/GLM-5.3-Flash",   # free
    "gemini-3.1-pro": "agy/gemini-3.1-pro-high",                     # Antigravity Pro; its signature cache keeps tool loops sane
    "claude-fable-5-1": "claude/claude-opus-5",                      # Fable 5.1 needs usage credits on this plan (429)
    "claude-opus-5-5": "claude/claude-opus-5",                       # 5.5 answers 400 on this account
    "claude-haiku-4-5": "claude/claude-haiku-4-5-20251001",
    "qwen3-coder": "command-code/Qwen/Qwen3.8-Max",                  # xkiro qwen3.8-max:free answered 403
}
CHAINS = {  # omh shipped order, plus a cross-ecosystem free fallback; writing leads with Gemini (owner, 2026-09-27)
    "ultrabrain": [("gpt-6-astra", "xhigh"), ("claude-fable-5-1", "xhigh"), ("kimi-k3", "xhigh")],
    "deep": [("gpt-6-sol", "high"), ("deepseek-flash", "high"), ("kimi-k3", "high")],
    "architect": [("claude-fable-5-1", "xhigh"), ("gpt-6-astra", "xhigh"), ("kimi-k3", "xhigh")],
    "unspecified-high": [("kimi-k3", "medium"), ("claude-opus-5-5", "medium"), ("deepseek-flash", "medium")],
    "unspecified-low": [("glm-5.3", "low"), ("deepseek-flash", "low"), ("claude-opus-5-5", "low")],
    "quick": [("glm-5.3-flash", "low"), ("kimi-k3", "low"), ("gpt-6-luna", "low"), ("claude-fable-5-1", "low")],
    "writing": [("gemini-3.1-pro", "medium"), ("kimi-k3", "medium"), ("qwen3-coder", "medium")],
    "visual-engineering": [("claude-fable-5-1", "high"), ("kimi-k3", "high"), ("gemini-3.1-pro", "high")],
    "artistry": [("gemini-3.1-pro", "high"), ("claude-fable-5-1", "high"), ("kimi-k3", "high")],
    # fable and opus-5-5 both land on claude-opus-5 here, and a fallback onto the same wire model is no fallback
    "capable": [("claude-fable-5-1", "medium"), ("kimi-k3", "medium"), ("glm-5.3", "medium")],
    "simple-work": [("gpt-6-luna", "low"), ("deepseek-flash", "low"), ("claude-haiku-4-5", "low")],
    "deep-work": [("gpt-6-astra", "high"), ("deepseek-flash", "high"), ("kimi-k3", "high")],
}
ts = time.strftime("%Y%m%d-%H%M%S")


def save(p, d):
    st = os.stat(p)
    shutil.copy2(p, f"{p}.bak-omh-rec-{ts}")
    open(p + ".tmp", "w").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    os.chown(p + ".tmp", st.st_uid, st.st_gid); os.chmod(p + ".tmp", st.st_mode & 0o7777); os.replace(p + ".tmp", p)


mp = json.load(open(B + "model-providers.json"))
mp["models"].update({a: {"model": m, "provider": O} for a, m in ROUTES.items()})
save(B + "model-providers.json", mp)
mc = json.load(open(B + "model-chains.json"))
mc["categories"] = {cat: [{"model": a, "reasoning_effort": e} for a, e in chain] for cat, chain in CHAINS.items()}
save(B + "model-chains.json", mc)
for cat, chain in CHAINS.items():
    print(f"{cat:18}", " -> ".join(f"{a}({ROUTES[a]})" for a, _ in chain))
