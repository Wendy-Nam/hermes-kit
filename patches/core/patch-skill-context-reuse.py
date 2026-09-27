"""Preserve skill loading requirements while avoiding redundant same-context reads."""
import argparse
import ast
import os
from pathlib import Path
import shutil
import tempfile

OLD = '''        "Before replying, scan the skills below. If a skill matches or is even partially relevant to your "
        "task, you MUST load it with skill_view(name) and follow its instructions. Err on the side of "
        "loading — it is always better to have context you don't need than to miss critical steps, pitfalls, "
        "or established workflows. Skills contain specialized knowledge — API endpoints, tool-specific "'''
NEW = '''        "Before replying, scan the skills below. For a matching skill, first check whether its full "
        "instructions were successfully loaded and remain available in the current conversation context. "
        "If they are present, apply them directly without calling skill_view again merely because a new "
        "message arrived. If they are absent, incomplete, pruned by compression, explicitly updated, or "
        "the task requires an unread reference file, load the needed content with skill_view(name). "
        "A skill name, summary, or old loaded marker alone is not its full instructions. If a skill "
        "matches or is even partially relevant, you MUST obtain and follow its instructions using this "
        "reuse-or-load rule. Skills contain specialized knowledge — API endpoints, tool-specific "'''

def patched(source):
    if source.count(NEW) == 1 and OLD not in source:
        ast.parse(source)
        return source, False
    if source.count(OLD) != 1 or NEW in source:
        raise ValueError('skill-context-reuse anchor drift; refusing ambiguous edit')
    result = source.replace(OLD, NEW, 1)
    ast.parse(result)
    return result, True

RUNTIME_OLD = ast.literal_eval('(' + OLD + ')')
RUNTIME_NEW = ast.literal_eval('(' + NEW + ')')
HELPER = f'''def refresh_stored_skills_reuse_prompt(prompt: str) -> tuple[str, bool]:
    """Migrate only the exact generated Skills introduction; preserve all other bytes."""
    old = {('## Skills'+chr(10)+ast.literal_eval('('+OLD+')'))!r}
    new = {('## Skills'+chr(10)+ast.literal_eval('('+NEW+')'))!r}
    if not isinstance(prompt, str) or prompt.count(old) != 1 or new in prompt:
        return prompt, False
    start = prompt.index(old)
    end = prompt.find("<available_skills>", start + len(old))
    # Never replace a prose quotation without the generated roster section.
    if end < 0 or "\\n## " in prompt[start + len(old):end]:
        return prompt, False
    return prompt[:start] + new + prompt[start + len(old):], True


'''
RESTORE_OLD = """        agent._cached_system_prompt = stored_prompt
        # The reused bytes may describe"""
RESTORE_NEW = """        from agent.prompt_builder import refresh_stored_skills_reuse_prompt
        stored_prompt, _skills_reuse_migrated = refresh_stored_skills_reuse_prompt(stored_prompt)
        agent._cached_system_prompt = stored_prompt
        if _skills_reuse_migrated:
            _persist_system_prompt(agent, "Skills reuse prompt migration could not persist (session=%s): %s")
        # The reused bytes may describe"""

def patched_builder(source):
    result, changed = patched(source)
    anchor = 'def _render_skills_index('
    if HELPER not in result:
        if 'def refresh_stored_skills_reuse_prompt(' in result or result.count(anchor) != 1:
            raise ValueError('stored skills helper anchor drift')
        result = result.replace(anchor, HELPER + anchor, 1); changed = True
    ast.parse(result)
    return result, changed

def patched_restore(source):
    if RESTORE_NEW in source and RESTORE_OLD not in source:
        ast.parse(source); return source, False
    if source.count(RESTORE_OLD) != 1 or RESTORE_NEW in source:
        raise ValueError('stored prompt restore anchor drift')
    result = source.replace(RESTORE_OLD, RESTORE_NEW, 1)
    ast.parse(result)
    return result, True

def apply(root, apply_changes=False):
    edits = []
    for filename, transform in [('prompt_builder.py', patched_builder), ('conversation_loop.py', patched_restore)]:
        target = Path(root) / 'agent' / filename
        result, changed = transform(target.read_text())
        if changed: edits.append((target, result))
    if not edits: print('already patched'); return
    if not apply_changes: print('patch ready (dry run)'); return
    for target, result in edits:
        fd, name = tempfile.mkstemp(prefix='.skills-reuse-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(result); f.flush(); os.fsync(f.fileno())
            shutil.copymode(target, name); os.replace(name, target)
        finally:
            if os.path.exists(name): os.unlink(name)
    print('skill-context-reuse applied (stored prompt restore included)')

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='/opt/hermes');p.add_argument('--check',action='store_true');a=p.parse_args()
    apply(a.root,not a.check)
