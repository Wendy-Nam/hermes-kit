"""Chat settings for the live Hermes root profile (2026-09-27). Runs on the VPS host as root; backup config.yaml.bak-chat-<ts>.
- main conversation -> hermes-chat combo (Codex gpt-6-luna first, 99% cache; GOAT deepseek; then solar-pro4)
- RP channel stays on solar-pro4 (frontier models refuse there; a refusal is a 200, so fallback never fires)
- summary channel (public profile) -> hermes-chat (codestral-first hermes-public asked back and took the user's name)
- compression later: prune/rewrite history less often so the provider prompt cache survives (cached input ~1/10 price)
- agent.service_tier removed: "fast" is sent to OpenAI as priority processing and burns Codex limits faster"""
import os, shutil, time, yaml

p = "/docker/hermes-agent-ywj7/data/config.yaml"
c = yaml.safe_load(open(p))
c["model"]["default"] = "hermes-chat"
c.setdefault("context_lengths", {})["hermes-chat@http://omniroute:20128/v1"] = 131072
c.setdefault("discord", {})["channel_overrides"] = {
    "1534345246790516817": {"provider": "omniroute", "model": "solar-pro4"},    # RP channel
    "1552203400479907850": {"provider": "omniroute", "model": "hermes-chat"},   # summary channel
}
c["compression"]["proactive_prune_tokens"] = 40000
c["compression"]["threshold_tokens"] = 80000
c["agent"].pop("service_tier", None)
st = os.stat(p)
shutil.copy2(p, p + ".bak-chat-" + time.strftime("%Y%m%d-%H%M%S"))
tmp = p + ".tmp-chat"
open(tmp, "w").write(yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=4096))
os.chown(tmp, st.st_uid, st.st_gid); os.chmod(tmp, st.st_mode & 0o7777); os.replace(tmp, p)
c2 = yaml.safe_load(open(p))
print("main:", c2["model"]["default"], "| overrides:", c2["discord"]["channel_overrides"],
      "| compression:", c2["compression"]["threshold_tokens"], c2["compression"]["proactive_prune_tokens"], "| agent:", c2["agent"])
