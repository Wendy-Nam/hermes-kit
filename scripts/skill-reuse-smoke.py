"""Offline shipped-runtime regression: normalized stored prompts survive upgrade."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3

spec = importlib.util.spec_from_file_location('reuse_patch', '/opt/kit/patches/core/patch-skill-context-reuse.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
from hermes_state import SessionDB
from agent.conversation_loop import _restore_or_build_system_prompt
from agent.prompt_builder import build_skills_system_prompt

old = 'Student overlay stays unchanged\n## Skills\n'+p.RUNTIME_OLD+'commands.\n<available_skills>\n example\n</available_skills>\nStudent tail stays unchanged'
expected = old.replace(p.RUNTIME_OLD,p.RUNTIME_NEW,1)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)/'state.db'
    db = SessionDB(path)
    db.create_session('upgrade-fixture',source='discord',system_prompt=old)
    # This is the exact case missed during the original diagnosis.
    with sqlite3.connect(path) as raw:
        row = raw.execute('SELECT system_prompt,system_prompt_hash FROM sessions WHERE id=?',('upgrade-fixture',)).fetchone()
    assert row[0] is None and row[1]
    assert db.get_session('upgrade-fixture')['system_prompt'] == old
    agent = SimpleNamespace(_session_db=db,session_id='upgrade-fixture',_cached_system_prompt=None)
    with patch('agent.conversation_loop._stored_prompt_matches_runtime',return_value=True), \
         patch('agent.conversation_loop._bot_chat_prompt_stale',return_value=False), \
         patch('agent.conversation_loop.stage_surface_switch_note',return_value=False), \
         patch('agent.system_prompt.restore_plugin_prompt_sections'), \
         patch('agent.system_prompt.reconstruct_static_prefix'):
        for _ in range(2):
            _restore_or_build_system_prompt(agent,None,[{'role':'user','content':'synthetic test'}])
            assert agent._cached_system_prompt == expected
            assert db.get_session('upgrade-fixture')['system_prompt'] == expected
    db.close()
    # Process recreation must resolve the new content-addressed prompt, not the old one.
    reopened = SessionDB(path,read_only=True)
    assert reopened.get_session('upgrade-fixture')['system_prompt'] == expected
    reopened.close()
with tempfile.TemporaryDirectory() as directory:
    skills = Path(directory)/'skills'
    sample = skills/'example'
    sample.mkdir(parents=True)
    (sample/'SKILL.md').write_text('---\nname: example\ndescription: Synthetic test workflow\n---\nUse the fixture.\n')
    new_prompt = build_skills_system_prompt(available_tools={'skill_view'},available_toolsets={'skills'},skills_dir_override=skills)
    assert 'reuse-or-load rule' in new_prompt
    assert 'task, you MUST load it with skill_view' not in new_prompt
print('skill reuse: fresh prompt, normalized old-session restore, persistence and reopen passed')
