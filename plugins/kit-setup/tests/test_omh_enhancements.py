import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import omh_enhancements as enhance

ROUTE={'model':'gpt-6-sol','provider':'openai','reasoning_effort':'high','kind':'model'}
COMBO={'model':'classroom-fast','provider':'omniroute','reasoning_effort':'medium','kind':'combo'}

class Validation(unittest.TestCase):
    def test_requires_declared_identity_and_provider(self):
        for change in ({'kind':'guess'},{'provider':'auto'},{'model':'x;curl nope'},{'reasoning_effort':'none'}):
            with self.assertRaises(ValueError):enhance.validate_categories({'deep':[{**ROUTE,**change}]})
    def test_rejects_conflicting_identity_and_duplicate_chain(self):
        with self.assertRaises(ValueError):enhance.validate_categories({'deep':[ROUTE,dict(ROUTE)]})
        with self.assertRaises(ValueError):enhance.validate_categories({'deep':[ROUTE],'quick':[{**ROUTE,'kind':'combo'}]})
    def test_preserves_explicit_task_choices_and_medium(self):
        x=enhance.validate_categories({'deep':[ROUTE],'quick':[COMBO]})
        self.assertEqual(x['quick'][0]['reasoning_effort'],'medium');self.assertEqual(x['deep'][0]['model'],'gpt-6-sol')

class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        (self.home/'config.yaml').write_text('model: {default: original-model}\ndelegation: {model: pinned-parent}\n')
        self.config=(self.home/'config.yaml').read_bytes()
        self.base={}
        for i,name in enumerate(enhance.PINNED_FILES):
            data=f'# synthetic upstream source {i}\n'.encode();p=self.home/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);self.base[name]=data
        self.pin=patch.dict(enhance.PINNED_FILES,{n:hashlib.sha256(b).hexdigest() for n,b in self.base.items()},clear=True);self.pin.start()
        venv=self.home/'.kit-tools/basic/venv/bin';venv.mkdir(parents=True);(venv/'python').touch();(venv/'omh').touch()
        launcher=self.home/'.local/bin/omh';launcher.parent.mkdir(parents=True);launcher.symlink_to(venv/'omh')
    def tearDown(self):self.pin.stop();self.tmp.cleanup()
    def enable(self):return enhance.enable_enhanced_omh(self.home,category_routes={'deep':[ROUTE],'quick':[COMBO]})
    def test_enable_idempotent_and_disable_exact_restoration(self):
        self.assertEqual(self.enable()['status'],'enabled')
        first={n:(self.home/n).read_bytes() for n in enhance.PINNED_FILES}
        self.assertEqual(self.enable()['status'],'enabled')
        self.assertEqual(first,{n:(self.home/n).read_bytes() for n in enhance.PINNED_FILES})
        self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)
        doc=json.loads((self.home/enhance.ROUTE_FILES[0]).read_text());self.assertEqual(doc['models']['kit-enhanced-deep-0']['model'],'gpt-6-sol')
        self.assertEqual(enhance.disable_enhanced_omh(self.home)['status'],'disabled')
        self.assertEqual({n:(self.home/n).read_bytes() for n in self.base},self.base)
        self.assertFalse((self.home/enhance.RUNTIME).exists());self.assertFalse((self.home/enhance.ROUTE_FILES[0]).exists())
        self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)
    def test_modified_upstream_refused(self):
        (self.home/next(iter(self.base))).write_text('operator edits')
        self.assertEqual(self.enable()['status'],'failed');self.assertFalse((self.home/enhance.RUNTIME).exists())
    def test_post_install_edits_preserved_on_disable(self):
        self.enable();p=self.home/enhance.ROUTE_FILES[0];p.write_text('operator edits')
        self.assertEqual(enhance.disable_enhanced_omh(self.home)['status'],'conflict');self.assertEqual(p.read_text(),'operator edits')
    def test_write_failure_rolls_back_basic_plugin(self):
        original=enhance._write;failed=False
        def fail_once(path,blob):
            nonlocal failed
            if str(path).endswith('model-chains.json') and not failed:failed=True;raise OSError('synthetic disk error')
            return original(path,blob)
        with patch.object(enhance,'_write',side_effect=fail_once):self.assertEqual(self.enable()['status'],'failed')
        self.assertEqual({n:(self.home/n).read_bytes() for n in self.base},self.base)
        self.assertFalse((self.home/enhance.RUNTIME).exists());self.assertFalse((self.home/enhance.RECEIPT).exists())
    def test_linked_plugin_refused(self):
        p=self.home/enhance.RUNTIME;p.symlink_to(self.home/'config.yaml')
        self.assertEqual(self.enable()['status'],'failed');self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)

class Runtime(unittest.TestCase):
    def setUp(self):
        package=types.ModuleType('kit_omh_test');package.__path__=[]
        obs=types.ModuleType('kit_omh_test.host_observation');obs.host_session_id=lambda kw:str(kw.get('session_id',''))
        paths=types.ModuleType('kit_omh_test.runtime_paths');paths.tool_home_error=lambda args:None
        self.modules=patch.dict(sys.modules,{'kit_omh_test':package,obs.__name__:obs,paths.__name__:paths});self.modules.start()
        self.r=types.ModuleType('kit_omh_test.kit_enhanced');self.r.__file__='/tmp/data/plugins/omh/kit_enhanced.py';self.r.__package__='kit_omh_test'
        exec(compile(enhance.RUNTIME_SOURCE,'kit_enhanced.py','exec'),self.r.__dict__)
        self.config={'enabled':True,'require_route':True,'categories':{'deep':[dict(ROUTE),{**ROUTE,'model':'claude-sonnet-5','provider':'anthropic'}],'quick':[dict(COMBO)]}}
        self.r.settings=lambda:self.config;self.r.native_supported=lambda:True
        self.calls=[]
        def calibration(entry,config):
            self.calls.append(dict(entry));return {'guidance':'NATIVE CALIBRATION' if entry['reasoning_effort']=='high' else '', 'family':'unknown' if entry['kind']=='combo' else 'gpt'}
        self.r.calibrate=calibration
    def tearDown(self):self.modules.stop()
    def prepare(self,category='deep',**args):return json.loads(self.r.route_handler({'category':category,**args},session_id='s1'))
    def test_route_resolves_real_model_before_calibration(self):
        result=self.prepare();self.assertEqual(result['routing']['model'],'gpt-6-sol');self.assertEqual(self.calls[-1]['model'],'gpt-6-sol');self.assertEqual(result['routing'],result['delegate_args']['routing']);self.assertNotIn('kind',result['routing'])
    def test_requires_omh_receipt_in_same_host_session(self):
        route=self.r.native_route(ROUTE)
        self.assertEqual(self.r.guard('delegate_task',{'routing':route},session_id='s1')['action'],'block')
        self.prepare()
        self.assertEqual(self.r.guard('delegate_task',{'routing':route},session_id='other')['action'],'block')
        self.assertEqual(self.r.guard('delegate_task',{'routing':route},session_id='s1')['action'],'modify')
    def test_guard_idempotent_and_does_not_mutate_task_input(self):
        route=self.prepare()['routing'];args={'routing':route,'tasks':[{'goal':'test','context':'original'}]};change=self.r.guard('delegate_task',args,session_id='s1')
        self.assertEqual(args['tasks'][0]['context'],'original');self.assertIsNone(self.r.guard('delegate_task',{**args,**change['args']},session_id='s1'))
    def test_medium_combo_empty_calibration_is_valid(self):
        result=self.prepare('quick');self.assertEqual(result['calibration']['guidance'],'');self.assertEqual(self.calls[-1]['kind'],'combo');self.assertIsNone(self.r.guard('delegate_task',{'routing':result['routing']},session_id='s1'))
    def test_fallback_uses_exact_previous_route_and_exhausts(self):
        first=self.prepare()['routing'];next_=self.prepare(action='fallback',previous_routing=first)
        self.assertEqual(next_['routing']['model'],'claude-sonnet-5');self.assertEqual(self.prepare(action='fallback',previous_routing=next_['routing'])['status'],'exhausted')
    def test_unrelated_and_management_actions_unchanged(self):
        self.assertIsNone(self.r.guard('terminal',{'command':'true'}))
        for a in ('list','stop','steer'):self.assertIsNone(self.r.guard('delegate_task',{'action':a}))
    def test_opt_out_preserves_basic_behavior(self):
        self.r.settings=lambda:None;self.assertIsNone(self.r.guard('delegate_task',{}))
    def test_native_routing_unavailable_fails_without_dispatch(self):
        self.r.native_supported=lambda:False;self.assertEqual(self.prepare()['error'],'native_delegate_routing_unavailable')
    def test_calibration_failure_blocks_not_silent_downgrade(self):
        self.prepare();self.r.calibrate=lambda *args:(_ for _ in ()).throw(RuntimeError('synthetic'))
        self.assertEqual(self.r.guard('delegate_task',{'routing':self.r.native_route(ROUTE)},session_id='s1')['action'],'block')

if __name__=='__main__':unittest.main()
