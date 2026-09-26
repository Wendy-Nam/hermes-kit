#!/usr/bin/env python3
"""Patch /opt/hermes/cron/scheduler.py to support job-level max_turns field in jobs.json."""
from pathlib import Path

TARGET = Path("/opt/hermes/cron/scheduler.py")

def main():
    if not TARGET.exists():
        print(f"Target {TARGET} not found!")
        return 1
    content = TARGET.read_text(encoding="utf-8")
    
    old_block = """    from hermes_cli.config import resolve_turn_limit as _resolve_turn_limit
    _mt = _cfg.get("agent", {}).get("max_turns")
    if _mt is None:
        _mt = _cfg.get("max_turns")
    setup.max_iterations = _resolve_turn_limit(_mt)"""

    new_block = """    from hermes_cli.config import resolve_turn_limit as _resolve_turn_limit
    _mt = job.get("max_turns")
    if _mt is None:
        _mt = _cfg.get("agent", {}).get("max_turns")
    if _mt is None:
        _mt = _cfg.get("max_turns")
    setup.max_iterations = _resolve_turn_limit(_mt)"""

    if old_block not in content:
        if "job.get(\"max_turns\")" in content:
            print("Already patched scheduler.py")
            return 0
        print("Target pattern not found in scheduler.py!")
        return 1
        
    patched = content.replace(old_block, new_block, 1)
    TARGET.write_text(patched, encoding="utf-8")
    print("Successfully patched scheduler.py with job-level max_turns.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
