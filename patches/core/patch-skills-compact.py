#!/usr/bin/env python3
"""Patch system_prompt.py to support skills.compact_categories from config.yaml."""

from pathlib import Path
import re

TARGET = Path("/opt/hermes/agent/system_prompt.py")

if not TARGET.exists():
    print(f"Target {TARGET} not found; skipping patch.")
    raise SystemExit(0)

content = TARGET.read_text(encoding="utf-8")

# Pattern in _skills_prompt
OLD_PATTERN = """    try:
        from agent.coding_context import coding_compact_skill_categories
        _compact_cats = coding_compact_skill_categories(platform=agent.platform, cwd=resolve_context_cwd())
    except Exception:
        _compact_cats = frozenset()
    return _pb.build_skills_system_prompt(available_tools=agent.valid_tool_names, available_toolsets=avail_toolsets,
                                         compact_categories=_compact_cats or None, skills_dir_override=_agent_skills_dir(agent))"""

NEW_PATTERN = """    try:
        from agent.coding_context import coding_compact_skill_categories
        _compact_cats = set(coding_compact_skill_categories(platform=agent.platform, cwd=resolve_context_cwd()))
    except Exception:
        _compact_cats = set()
    try:
        from hermes_constants import get_hermes_home
        import yaml
        _home = _agent_home(agent) or get_hermes_home()
        _cfg_path = _home / "config.yaml" if _home else None
        if _cfg_path and _cfg_path.exists():
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                _cfg = yaml.safe_load(_f) or {}
            _cfg_compact = _cfg.get("skills", {}).get("compact_categories", [])
            _compact_cats.update(_cfg_compact)
    except Exception:
        pass
    return _pb.build_skills_system_prompt(available_tools=agent.valid_tool_names, available_toolsets=avail_toolsets,
                                         compact_categories=frozenset(_compact_cats) if _compact_cats else None,
                                         skills_dir_override=_agent_skills_dir(agent))"""

if "skills.compact_categories" in content:
    print("skills.compact_categories already patched in system_prompt.py.")
elif OLD_PATTERN in content:
    content = content.replace(OLD_PATTERN, NEW_PATTERN)
    TARGET.write_text(content, encoding="utf-8")
    print("Successfully patched system_prompt.py with skills.compact_categories support.")
else:
    print("Warning: Target pattern not found in system_prompt.py; trying regex match.")
    # Anchor past skills_dir_override — bare .*?\) stops at frozenset(_compact_cats)
    # and spliced a broken tail (IndentationError, 2026-09-24 incident).
    reg = re.compile(
        r"    try:\s+from agent\.coding_context import coding_compact_skill_categories.*?return _pb\.build_skills_system_prompt\(.*?skills_dir_override=_agent_skills_dir\(agent\)\)",
        re.DOTALL
    )
    if reg.search(content):
        content = reg.sub(NEW_PATTERN, content, count=1)
        TARGET.write_text(content, encoding="utf-8")
        print("Successfully regex-patched system_prompt.py.")
    else:
        print("Error: Could not find target pattern in system_prompt.py.")
        raise SystemExit(1)
