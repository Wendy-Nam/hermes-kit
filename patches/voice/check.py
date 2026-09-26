#!/usr/bin/env python3
"""Post-apply gate: every touched file compiles and the gateway import chain still loads.
Read-only; safe to run as the Hermes user.  usage: python check.py [--root /opt/hermes]"""
import argparse
import subprocess
import sys
from pathlib import Path

TARGETS = ["tools/tts_tool.py", "tools/tts_tool_providers.py", "gateway/run_voice.py", "gateway/run_startup.py",
           "gateway/run_busy.py", "gateway/slash_commands.py", "hermes_cli/commands.py",
           "hermes_cli/config_defaults.py", "plugins/platforms/discord/adapter.py"]
IMPORT_SMOKE = ["gateway.run_voice", "gateway.slash_commands", "tools.tts_tool"]

ap = argparse.ArgumentParser(); ap.add_argument("--root", default="/opt/hermes"); ap.add_argument("--python", default=sys.executable)
a = ap.parse_args(); root = Path(a.root); fails = []
for rel in TARGETS:
    p = root / rel
    if not p.exists():
        continue
    try:
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
    except SyntaxError as e:
        fails.append(f"SYNTAX {rel}:{e.lineno}: {e.msg}")
for mod in IMPORT_SMOKE:
    r = subprocess.run([a.python, "-c", f"import {mod}"], cwd=root, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        fails.append(f"IMPORT {mod}: {(r.stderr or r.stdout).strip().splitlines()[-1][:160]}")
print("\n".join(fails) if fails else f"OK {len(TARGETS)} targets compile, {len(IMPORT_SMOKE)} imports load")
sys.exit(1 if fails else 0)
