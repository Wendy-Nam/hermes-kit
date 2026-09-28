"""Role profiles against the shipped Hermes CLI: real `hermes profile create`, no model requests.

Checks the roles exist where kanban looks for them, run on the main model, and never receive
the Discord bot token (two profiles holding one token collide).
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

KIT_ROOT = Path('/opt/kit/plugins/kit-setup')
sys.path.insert(0, str(KIT_ROOT if KIT_ROOT.is_dir() else Path(__file__).resolve().parents[1] / 'plugins/kit-setup'))
import config_store
import env_store
import roles

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    os.environ.update(HERMES_HOME=str(root), HOME=str(root))
    env_store.set_env(root / '.env', {'GEMINI_API_KEY': 'smoke', 'DISCORD_BOT_TOKEN': 'smoke-bot'})
    config_store.write(root, {'model.provider': 'openai-codex', 'model.default': 'gpt-6-luna'}, remember=False)
    (root / 'SOUL.md').write_text('# 나의 AI 비서\n')
    rows = roles.ensure_roles(root)
    assert rows == [f'{r}: 준비됨' for r in roles.ROLES], rows
    for role in roles.ROLES:
        home = root / 'profiles' / role
        assert config_store.read(home)['model']['default'] == 'gpt-6-luna', role
        text = (home / '.env').read_text()
        assert 'smoke-bot' not in text and 'GEMINI_API_KEY' in text, role
        assert roles.MARK in (home / 'SOUL.md').read_text(), role
    listed = subprocess.run([roles.HERMES, 'profile', 'list'], capture_output=True, text=True, timeout=60).stdout
    assert all(r in listed for r in roles.ROLES), listed
    assert '<!-- kit: roles -->' in (root / 'SOUL.md').read_text()
    print('roles smoke: ok', ', '.join(roles.ROLES))
