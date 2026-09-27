"""Point the non-config freellmapi callers on the live Hermes volume at OmniRoute (2026-09-27 audit).
Runs on the VPS host as root. usage: hermes_leftovers.py [--apply]
Each changed file gets <file>.bak-omniroute-leftovers-<ts> (owner and mode kept); freellmapi-only tools move to
_quarantine/. Rollback: copy the .bak files back, move the quarantined tools back."""
import os, re, shutil, sys, time

D = "/docker/hermes-agent-ywj7/data"
apply = "--apply" in sys.argv
TS = time.strftime("%Y%m%d-%H%M%S")
FL, OM = "http://freellmapi-freellmapi-1:3001/v1", "http://omniroute:20128/v1"
COMMON = [(FL, OM), ("FREELLMAPI_API_KEY", "OMNIROUTE_API_KEY")]
PROFILE_RE = r"auto:(private|coding-worker|coding|fast|compress|vision|public|commandcode|ultrabrain|writing|visual-engineering|ops-fast)\b"
SKILL_DOC = [(f"{FL}/models", f"{OM}/models"), ("$FREELLMAPI_API_KEY", "$OMNIROUTE_API_KEY"),
             ("로 전체 카탈로그 확인.", "로 전체 카탈로그 확인 — 8천 개가 넘어 시간 초과가 잦으니 콤보 이름(`hermes-*`)을 우선 쓴다."),
             ("auto:hermes-fast", "hermes-fast"), ("auto:continuity", "hermes-private"), ("`auto:*`", "`hermes-*`"),
             ("re:" + PROFILE_RE, r"hermes-\1"), ("freellmapi", "OmniRoute"), ("FreeLLMAPI", "OmniRoute")]

EDITS = {
    "plugins/hermes-self/config.yaml": [("provider: freellmapi", "provider: omniroute"), ("model: auto:coding", "model: hermes-coding")],
    "plugins/hermes-self/dispatch.py": [('"provider", "freellmapi")', '"provider", "omniroute")'),
                                        ('"model", "auto:coding")', '"model", "hermes-coding")')],
    "scripts/selfie_sunteok_runner.py": COMMON + [('"auto:vision"', '"hermes-vision"')],
    # memory content is personal: the private combo (no-training providers only)
    "scripts/memory-condense.py": COMMON + [('MODELS = ("deepseek/deepseek-v4.1-flash", "google/gemini-3.8-flash")',
                                             'MODELS = ("hermes-private",)')],
    "scripts/self-arch-audit.py": [('FREE_CHAIN_PROVIDERS = ("freellmapi", "gemini")', 'FREE_CHAIN_PROVIDERS = ("omniroute", "freellmapi", "gemini")')],
    "bin/llm_oneshot.py": [('os.environ.get("FREELLMAPI_BASE_URL", "http://freellmapi-freellmapi-1:3001/v1")',
                            'os.environ.get("HERMES_LLM_BASE_URL", "http://omniroute:20128/v1")'),
                           ("FREELLMAPI_API_KEY", "OMNIROUTE_API_KEY"),
                           ('        headers["X-Hermes-Request-Profile"] = model\n',
                            '        headers["X-Hermes-Request-Profile"] = model\n'
                            '        # freellmapi profile names -> OmniRoute combos (2026-09-27); bare "auto" was its Default pool\n'
                            '        model = {"auto": "hermes-public", "auto:hermes-fast": "hermes-fast",\n'
                            '                 "auto:continuity": "hermes-private"}.get(model, "hermes-" + model[5:])\n')],
    "bin/evo-pilot.sh": COMMON + [("openai/auto:private", "openai/hermes-private"), ("openai/auto:continuity", "openai/hermes-private")],
    "bin/evo-run.sh": COMMON + [("openai/auto:private", "openai/hermes-private"), ("openai/auto:continuity", "openai/hermes-private")],
    "bin/health-monitor.py": [('"http://freellmapi-freellmapi-1:3001/"', '"http://omniroute:20128/healthz"')],
    "bin/public-model-runner.py": [("('freellmapi','auto:public',25.0)", "('omniroute','hermes-public',25.0)"),
                                   ("('freellmapi','auto:public')", "('omniroute','hermes-public')"),
                                   ("('freellmapi','auto:hermes-fast')", "('omniroute','hermes-fast')"),
                                   ("chosen[0]!='freellmapi'", "chosen[0]!='omniroute'")],
    "plugins/CONTRACT.md": [("`auto:commandcode` 에스컬레이션(요청이 FreeLLMAPI 를 탈 때만 동작)",
                             "`hermes-commandcode` 에스컬레이션(요청이 OmniRoute(구 FreeLLMAPI)를 탈 때만 동작)")],
    "skills/cron/evening-record/SKILL.md": SKILL_DOC,
    "skills/autonomous-ai-agents/resource-routing/SKILL.md": SKILL_DOC,
    "skills/autonomous-ai-agents/delegation-failure-recovery/SKILL.md": SKILL_DOC,
    "skills/tools/free-cli-worker/SKILL.md": SKILL_DOC,
    "skills/software-development/product-design-to-frontend-delivery/SKILL.md": SKILL_DOC,
}
QUARANTINE = ["scripts/probe-freellm.py", "bin/freellmapi-audit.sh", "bin/freellmapi-update.sh"]

print("mode:", "APPLY" if apply else "DRY-RUN")
for rel, reps in EDITS.items():
    p = f"{D}/{rel}"
    if not os.path.exists(p):
        print(f"  MISSING {rel}"); continue
    old = text = open(p, encoding="utf-8").read()
    hits = []
    for a, b in reps:
        n = len(re.findall(a[3:], text)) if a.startswith("re:") else text.count(a)
        if n:
            text = re.sub(a[3:], b, text) if a.startswith("re:") else text.replace(a, b)
            hits.append(n)
    left = len(re.findall(r"freellmapi-freellmapi-1|FREELLMAPI_API_KEY", text))
    print(f"  {rel:70} {sum(hits):3} changes{'' if not left else f'  (still {left} freellmapi refs)'}")
    if apply and text != old:
        st = os.stat(p)
        shutil.copy2(p, f"{p}.bak-omniroute-leftovers-{TS}")
        tmp = p + ".tmp-leftovers"
        open(tmp, "w", encoding="utf-8").write(text)
        os.chown(tmp, st.st_uid, st.st_gid); os.chmod(tmp, st.st_mode & 0o7777)
        os.replace(tmp, p)
q = f"{D}/_quarantine/freellmapi-tools-{TS}"
for rel in QUARANTINE:
    if os.path.exists(f"{D}/{rel}"):
        print(f"  quarantine {rel}")
        if apply:
            os.makedirs(q, exist_ok=True)
            shutil.move(f"{D}/{rel}", f"{q}/{os.path.basename(rel)}")
