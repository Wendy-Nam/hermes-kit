#!/usr/bin/env python3
"""Patch /opt/hermes/tools/skills_tool.py to cap SKILL.md inline content at 6,000 characters."""
from pathlib import Path

TARGET = Path("/opt/hermes/tools/skills_tool.py")

def main():
    if not TARGET.exists():
        print(f"Target {TARGET} not found!")
        return 1
    content = TARGET.read_text(encoding="utf-8")
    
    old_block = """        result = {
            "success": True, "name": skill_name, "description": frontmatter.get("description", ""),
            "tags": tags, "related_skills": related_skills, "content": header + rendered_content,"""
            
    new_block = """        _MAX_SKILL_INLINE_CHARS = 6000
        full_content = header + rendered_content
        if len(full_content) > _MAX_SKILL_INLINE_CHARS:
            content_payload = full_content[:_MAX_SKILL_INLINE_CHARS] + f"\\n\\n[... Skill content truncated at {_MAX_SKILL_INLINE_CHARS:,} chars ({len(full_content):,} chars total). Call skill_view({skill_name}, file_path=...) for linked files ...]"
        else:
            content_payload = full_content
        result = {
            "success": True, "name": skill_name, "description": frontmatter.get("description", ""),
            "tags": tags, "related_skills": related_skills, "content": content_payload,"""

    if old_block not in content:
        if "_MAX_SKILL_INLINE_CHARS" in content:
            print("Already patched skills_tool.py")
            return 0
        print("Target pattern not found in skills_tool.py!")
        return 1
        
    patched = content.replace(old_block, new_block, 1)
    TARGET.write_text(patched, encoding="utf-8")
    print("Successfully patched skills_tool.py with 6k content cap.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
