import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config_store
import env_store
import roles

FAKE = '''#!/bin/sh
# hermes profile create <role> ... : make the profile home like the real CLI does
mkdir -p "$HERMES_HOME/profiles/$3" && printf 'model:\\n  default: stale\\n' > "$HERMES_HOME/profiles/$3/config.yaml"
cp "$HERMES_HOME/SOUL.md" "$HERMES_HOME/profiles/$3/SOUL.md"   # --clone copies the default SOUL
'''


class Roles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hermes = self.root / 'hermes'; self.hermes.write_text(FAKE); self.hermes.chmod(0o755)
        env_store.set_env(self.root / '.env', {'GEMINI_API_KEY': 'g', 'DISCORD_BOT_TOKEN': 'bot', 'DISCORD_HOME_CHANNEL': '1'})
        config_store.write(self.root, {'model.provider': 'openai-codex', 'model.default': 'gpt-6-luna'}, remember=False)
        (self.root / 'SOUL.md').write_text('# 나의 AI 비서\n')

    def test_roles_get_the_main_model_and_keys_but_never_the_bot_token(self):
        with (self.root / '.env').open('a') as f:
            f.write('export\tDISCORD_TOKEN_ALT=leak\nexport  DISCORD_X=leak\n')
        rows = roles.ensure_roles(self.root, hermes=str(self.hermes))
        self.assertEqual(rows, [f'{r}: 준비됨' for r in roles.ROLES])
        for role in roles.ROLES:
            home = self.root / 'profiles' / role
            self.assertEqual(config_store.read(home)['model'], {'provider': 'openai-codex', 'default': 'gpt-6-luna'})
            env = env_store.get_env(home / '.env')
            self.assertEqual(env, {'GEMINI_API_KEY': 'g'})
            self.assertEqual(stat.S_IMODE(os.stat(home / '.env').st_mode), 0o600)
            self.assertIn(roles.MARK, (home / 'SOUL.md').read_text())
        soul = (self.root / 'SOUL.md').read_text()
        self.assertEqual(soul.count('<!-- kit: roles -->'), 1)
        roles.ensure_roles(self.root, hermes=str(self.hermes))
        self.assertEqual((self.root / 'SOUL.md').read_text(), soul)  # rule appended once

    def test_model_change_reaches_roles_and_custom_role_soul_is_kept(self):
        roles.ensure_roles(self.root, hermes=str(self.hermes))
        (self.root / 'profiles/coder/SOUL.md').write_text('my own coder')
        config_store.write(self.root, {'model.provider': 'commandcode', 'model.default': 'x'}, remember=False)
        roles.ensure_roles(self.root, hermes=str(self.hermes))
        self.assertEqual(config_store.read(self.root / 'profiles/research')['model']['default'], 'x')
        self.assertEqual((self.root / 'profiles/coder/SOUL.md').read_text(), 'my own coder')

    def test_roles_follow_delegation_and_kanban_cap_follows_memory(self):
        low = self.root / 'meminfo-4g'; low.write_text('MemTotal:        3995000 kB\n')
        high = self.root / 'meminfo-8g'; high.write_text('MemTotal:        8120000 kB\n')
        roles.ensure_roles(self.root, hermes=str(self.hermes))
        config_store.write(self.root, {'delegation.provider': 'kit-omniroute', 'delegation.model': 'hermes-kit-x-strong',
                                       'fallback_providers': [{'provider': 'openai-codex', 'model': 'gpt-6-luna'}]}, remember=False)
        roles.sync_roles(self.root, meminfo=str(low))
        coder = config_store.read(self.root / 'profiles/coder')
        self.assertEqual(coder['model'], {'provider': 'kit-omniroute', 'default': 'hermes-kit-x-strong'})
        self.assertEqual(coder['fallback_providers'], [{'provider': 'openai-codex', 'model': 'gpt-6-luna'}])
        self.assertEqual(config_store.read(self.root)['kanban']['max_spawn'], 1)
        roles.sync_roles(self.root, meminfo=str(high))
        self.assertEqual(config_store.read(self.root)['kanban']['max_spawn'], 3)

    def test_failed_create_is_reported_not_raised(self):
        bad = self.root / 'bad'; bad.write_text('#!/bin/sh\nexit 1\n'); bad.chmod(0o755)
        self.assertTrue(all('못했' in r for r in roles.ensure_roles(self.root, hermes=str(bad))))
        self.assertNotIn('<!-- kit: roles -->', (self.root / 'SOUL.md').read_text())


if __name__ == '__main__':
    unittest.main()
