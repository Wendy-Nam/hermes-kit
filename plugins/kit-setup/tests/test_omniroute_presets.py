import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import omniroute_presets as op


class OmniRoutePresetsTest(unittest.TestCase):
    def test_plan_presets_filters_to_active_connections(self):
        connections = {
            'codex': {'id': 'conn-codex', 'provider': 'codex', 'defaultModel': 'gpt-6.2-sol', 'isActive': True},
            'sail': {'id': 'conn-sail', 'provider': 'sail', 'defaultModel': 'moonshotai/Kimi-K3', 'isActive': True},
            'cline': {'id': 'conn-cline', 'provider': 'cline', 'isActive': True},
        }
        catalog = {
            'codex': {'gpt-6.2-sol', 'gpt-6.2-astra', 'gpt-6-luna'},
            'sail': {'moonshotai/Kimi-K3', 'zai-org/GLM-5.3', 'zai-org/GLM-5.3-Flash'},
            'cline': set(),  # pass-through free pool
        }
        planned = op.plan_presets(connections, catalog)
        self.assertIn('hermes-chat', planned)
        self.assertIn('hermes-free', planned)
        self.assertIn('hermes-coding', planned)
        self.assertIn('hermes-ultrabrain', planned)
        self.assertEqual(planned['hermes-chat']['steps'][0]['id_'], 'codex/gpt-6-luna')
        self.assertEqual(planned['hermes-ultrabrain']['steps'][0]['id_'], 'codex/gpt-6.2-astra')
        self.assertTrue(any(s['id_'].startswith('cline/') for s in planned['hermes-free']['steps']))

    def test_apply_presets_wires_combos_and_omh_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / 'config.yaml').write_text('model:\n  provider: openai-codex\n  default: gpt-6-luna\n')
            (data / '.env').write_text('DISCORD_BOT_TOKEN=dummy\n')
            (data / 'plugins/omh/hooks').mkdir(parents=True)
            # Write a valid OMH 5.0.0 hook stub with known hash or mock enable_enhanced_omh
            requests = []

            class FakeClient:
                def request(self, method, path, body=None, key=None):
                    requests.append((method, path))
                    if path == '/api/auth/login':
                        return {'ok': True}, {}
                    if path == '/api/providers':
                        return {'connections': [
                            {'id': 'cid1', 'provider': 'codex', 'name': 'my-codex', 'isActive': True,
                             'defaultModel': 'gpt-6.2-sol', 'providerSpecificData': {'prefix': 'codex'}},
                            {'id': 'cid2', 'provider': 'cline', 'name': 'my-cline', 'isActive': True,
                             'providerSpecificData': {'prefix': 'cline'}},
                        ]}, {}
                    if path.endswith('/models'):
                        return {'models': [{'id': 'gpt-6.2-sol', 'name': 'GPT-6.2 Sol'},
                                           {'id': 'gpt-6.2-astra', 'name': 'GPT-6.2 Astra'},
                                           {'id': 'gpt-6-luna', 'name': 'GPT-6 Luna'}]}, {}
                    if path == '/api/keys' and method == 'POST':
                        return {'id': 'kid1', 'key': 'sk-omni-synthetic'}, {}
                    if path == '/api/keys' and method == 'GET':
                        return {'keys': []}, {}
                    if path == '/api/combos' and method == 'GET':
                        return {'combos': []}, {}
                    if path == '/api/combos' and method == 'POST':
                        return {'combo': {'id': 'combo-1'}}, {}
                    return {}, {}

            with patch.object(op, 'Client', FakeClient), \
                 patch('omh_enhancements.enable_enhanced_omh', return_value={'status': 'enabled'}) as mock_omh, \
                 patch('omh_enhancements.sync_base_route', return_value={'status': 'synced'}), \
                 patch('omh_routing.apply', return_value={'status': 'ok', 'changed': []}):
                res = op.apply_presets(data, 'secret-pw')
            self.assertEqual(res['status'], 'ok', res)
            self.assertTrue(res['omh_wired'])
            self.assertIn('hermes-coding', res['combos'])
            called_routes = mock_omh.call_args.kwargs.get('category_routes') or {}
            self.assertEqual(len(called_routes), 12)
            self.assertEqual(called_routes['ultrabrain'][0]['model'], 'hermes-ultrabrain')


if __name__ == '__main__':
    unittest.main()
