import copy
import json
import unittest
from unittest.mock import patch
import yaml
import test_omniroute_setup as base
import omniroute_setup as om


class VisionSetup(unittest.TestCase):
    configure = base.OmniRouteSetup.configure
    def setUp(self):
        base.OmniRouteSetup.setUp(self)
        self.assertTrue(self.configure()[0])
        self.settings = {'modalityBridgeVisionEnabled': True, 'unrelated': 'keep'}
        self.vision_ok = True
        self.fail_restore = False
        original = self.router.request
        def request(method, path, body=None, key=None):
            if path == '/api/settings':
                self.router.calls.append((method, path, copy.deepcopy(body)))
                if method == 'GET': return copy.deepcopy(self.settings), {}
                if self.fail_restore and body['modalityBridgeVisionEnabled']: raise om.SetupError('복원 오류')
                self.settings.update(body)
                return {}, {}
            if path == '/v1/chat/completions' and 'tools' not in body:
                self.router.calls.append((method, path, copy.deepcopy(body)))
                colors = ['RED', 'GREEN', 'BLUE', 'YELLOW', 'BLUE', 'RED']
                content = json.dumps(colors) if self.vision_ok else 'No image supplied'
                return {'choices': [{'message': {'content': content}}]}, {}
            return original(method, path, body, key)
        self.router.request = request
        mock = patch.object(om, '_vision_sample', return_value=('data:image/png;base64,test', ['RED','GREEN','BLUE','YELLOW','BLUE','RED']))
        mock.start(); self.addCleanup(mock.stop)

    def test_vision_is_explicit_and_global_change_requires_choice(self):
        before = (self.data / 'config.yaml').read_bytes()
        self.assertFalse(om.connect_vision(self.data, 'pw')[0])
        self.assertEqual((self.data / 'config.yaml').read_bytes(), before)
        self.assertTrue(self.settings['modalityBridgeVisionEnabled'])

    def test_success_registers_only_tested_vision_and_bounded_route(self):
        before = yaml.safe_load((self.data / 'config.yaml').read_text())
        ok, msg = om.connect_vision(self.data, 'pw', disable_shared_bridge=True)
        self.assertTrue(ok, msg)
        config = yaml.safe_load((self.data / 'config.yaml').read_text())
        self.assertEqual(config['model'], before['model'])
        self.assertEqual(config['delegation'], before['delegation'])
        self.assertEqual(config['auxiliary']['vision'], {'provider':om.PROVIDER_NAME,
            'model':config['delegation']['model'], 'base_url':om.BASE+'/v1', 'key_env':om.KEY_ENV,
            'timeout':30, 'configured_routes_only':True, 'fallback_chain':[]})
        self.assertFalse(self.settings['modalityBridgeVisionEnabled'])
        self.assertEqual(self.settings['unrelated'], 'keep')
        self.assertEqual(self.router.timeout, 25)
        self.assertEqual(len([x for x in self.router.calls if x[1]=='/v1/chat/completions']), 5)

    def test_failed_image_preserves_local_and_restores_shared_setting(self):
        before = (self.data / 'config.yaml').read_bytes()
        self.vision_ok = False
        self.assertFalse(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        self.assertEqual((self.data / 'config.yaml').read_bytes(), before)
        self.assertTrue(self.settings['modalityBridgeVisionEnabled'])

    def test_restore_failure_reported_honestly(self):
        self.vision_ok = False; self.fail_restore = True
        ok, msg = om.connect_vision(self.data, 'pw', disable_shared_bridge=True)
        self.assertFalse(ok); self.assertIn('복원도 실패', msg)

    def test_existing_other_vision_is_preserved(self):
        config = yaml.safe_load((self.data / 'config.yaml').read_text())
        config['auxiliary'] = {'vision': {'provider':'direct','model':'my-vision'}}
        (self.data / 'config.yaml').write_text(yaml.safe_dump(config))
        before = (self.data / 'config.yaml').read_bytes()
        self.assertFalse(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        self.assertEqual((self.data / 'config.yaml').read_bytes(), before)
        self.assertTrue(self.settings['modalityBridgeVisionEnabled'])

    def test_changing_delegation_cannot_break_attached_vision_key(self):
        self.assertTrue(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        before = (self.data / 'config.yaml').read_bytes()
        self.assertFalse(self.configure('different-model')[0])
        self.assertEqual((self.data / 'config.yaml').read_bytes(), before)

    def test_disabled_bridge_needs_no_global_write(self):
        self.settings['modalityBridgeVisionEnabled'] = False
        self.assertTrue(om.connect_vision(self.data, 'pw')[0])
        self.assertFalse(any(m=='PATCH' and p=='/api/settings' for m,p,b in self.router.calls))

    def test_modified_combo_never_runs_image(self):
        self.router.combos[-1]['models'][0]['connectionId'] = 'other'
        self.assertFalse(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        self.assertTrue(self.settings['modalityBridgeVisionEnabled'])

    def test_failed_tool_roundtrip_never_registers_vision(self):
        self.router.fail_probe = True
        self.assertFalse(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        self.assertNotIn('auxiliary', yaml.safe_load((self.data / 'config.yaml').read_text()))
        self.assertTrue(self.settings['modalityBridgeVisionEnabled'])


    def test_stock_auto_vision_defaults_allow_explicit_connection(self):
        config = yaml.safe_load((self.data / 'config.yaml').read_text())
        config['auxiliary'] = {'vision': {'provider':'auto','model':'','timeout':60}}
        (self.data / 'config.yaml').write_text(yaml.safe_dump(config))
        ok, msg = om.connect_vision(self.data, 'pw', disable_shared_bridge=True)
        self.assertTrue(ok, msg)
        vision = yaml.safe_load((self.data / 'config.yaml').read_text())['auxiliary']['vision']
        self.assertEqual(vision['provider'], om.PROVIDER_NAME)
        self.assertEqual(vision['timeout'], 30)

    def test_auto_provider_with_explicit_model_or_auth_is_preserved(self):
        for fields in ({'model':'my-vision'}, {'key_env':'MY_VISION_KEY'}, {'base_url':'https://my.example/v1'}, {'fallback_chain':[{'model':'mine'}]}):
            with self.subTest(fields=fields):
                config = yaml.safe_load((self.data / 'config.yaml').read_text())
                config['auxiliary'] = {'vision': {'provider':'auto','model':'',**fields}}
                (self.data / 'config.yaml').write_text(yaml.safe_dump(config))
                before = (self.data / 'config.yaml').read_bytes()
                self.assertFalse(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
                self.assertEqual((self.data / 'config.yaml').read_bytes(), before)

    def test_disconnect_restores_stock_defaults_without_touching_other_services(self):
        config = yaml.safe_load((self.data / 'config.yaml').read_text())
        original = {'provider':'auto','model':'','timeout':60,'download_timeout':90}
        config['auxiliary'] = {'vision': original.copy(), 'web_extract': {'provider':'keep'}}
        (self.data / 'config.yaml').write_text(yaml.safe_dump(config))
        self.assertTrue(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        env = (self.data / '.env').read_bytes()
        calls = len(self.router.calls)
        before = yaml.safe_load((self.data / 'config.yaml').read_text())
        ok, msg = om.disconnect_vision(self.data)
        self.assertTrue(ok, msg)
        after = yaml.safe_load((self.data / 'config.yaml').read_text())
        self.assertEqual(after['auxiliary']['vision'], original)
        self.assertEqual(after['delegation'], before['delegation'])
        self.assertEqual(after['auxiliary']['web_extract'], {'provider':'keep'})
        self.assertEqual((self.data / '.env').read_bytes(), env)
        self.assertEqual(len(self.router.calls), calls)
        self.assertFalse(self.settings['modalityBridgeVisionEnabled'])
        self.assertTrue(self.configure('another-model')[0])

    def test_disconnect_preserves_user_replaced_vision_provider_or_model(self):
        self.assertTrue(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        original = yaml.safe_load((self.data / 'config.yaml').read_text())
        for changed in ({'provider':'user'}, {'model':'user-model'}):
            config = copy.deepcopy(original)
            config['auxiliary']['vision'].update(changed)
            (self.data / 'config.yaml').write_text(yaml.safe_dump(config))
            before = (self.data / 'config.yaml').read_bytes()
            self.assertFalse(om.disconnect_vision(self.data)[0])
            self.assertEqual((self.data / 'config.yaml').read_bytes(), before)

    def test_disconnect_without_recovery_snapshot_preserves_connection(self):
        self.assertTrue(om.connect_vision(self.data, 'pw', disable_shared_bridge=True)[0])
        (self.data / '.kit-config-snapshot.json').unlink()
        before = (self.data / 'config.yaml').read_bytes()
        self.assertFalse(om.disconnect_vision(self.data)[0])
        self.assertEqual((self.data / 'config.yaml').read_bytes(), before)
