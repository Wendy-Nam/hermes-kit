import base64
import hashlib
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
from upstream_omh import CATEGORIES

BASE={'provider':'gemini','model':'gemini-3-flash'}
DEEP=[{'provider':'openai-codex','model':'gpt-6-astra','reasoning_effort':'high'},
      {'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'}]

class Validation(unittest.TestCase):
    def test_requires_explicit_identity_and_supported_effort(self):
        entry={'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'}
        for change in ({'provider':'auto'},{'provider':'custom'},{'model':'x;curl nope'},{'model':'a:b'},{'reasoning_effort':'none'}):
            with self.assertRaises(ValueError):enhance.validate_categories({'deep':[{**entry,**change}]})
        with self.assertRaises(ValueError):enhance.validate_categories({'deep':[{**entry,'kind':'model'}]})
        with self.assertRaises(ValueError):enhance.validate_categories({'nope':[entry]})
    def test_rejects_duplicate_and_oversized_chain(self):
        entry={'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'}
        with self.assertRaises(ValueError):enhance.validate_chain([entry,dict(entry,reasoning_effort='low')])
        with self.assertRaises(ValueError):enhance.validate_chain([dict(entry,model=f'm{i}') for i in range(6)])

class Compose(unittest.TestCase):
    def test_base_covers_every_task_type_at_recommended_effort(self):
        providers,chains=enhance.compose(BASE,{})
        self.assertEqual(providers['models'],{enhance.BASE_ALIAS:BASE})
        self.assertEqual(set(chains['categories']),set(CATEGORIES))
        self.assertEqual(chains['categories']['ultrabrain'],[{'model':enhance.BASE_ALIAS,'reasoning_effort':'high'}])
        self.assertEqual(chains['categories']['quick'],[{'model':enhance.BASE_ALIAS,'reasoning_effort':'low'}])
        self.assertEqual(set(enhance.DEFAULT_EFFORTS),set(CATEGORIES))
    def test_one_alias_per_identity_so_fallback_is_unambiguous(self):
        writing=[{'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'medium'},{**BASE,'reasoning_effort':'medium'}]
        providers,chains=enhance.compose(BASE,{'deep':DEEP,'writing':writing})
        identities=[(v['provider'],v['model']) for v in providers['models'].values()]
        self.assertEqual(len(identities),len(set(identities)))
        self.assertEqual(chains['categories']['deep'][1]['model'],chains['categories']['writing'][0]['model'])
        self.assertEqual(chains['categories']['writing'][1]['model'],enhance.BASE_ALIAS)
        self.assertEqual(len(chains['categories']['deep']),2)
    def test_basic_documents_recognized_only_when_kit_written(self):
        providers,chains=enhance.compose(BASE,{})
        self.assertEqual(enhance._base_from_documents(enhance._encode(providers),enhance._encode(chains)),BASE)
        chains['categories']['deep'].append({'model':'other','reasoning_effort':'high'})
        self.assertIsNone(enhance._base_from_documents(enhance._encode(providers),enhance._encode(chains)))
        legacy={'schema_version':enhance.CHAIN_SCHEMA,'categories':{c:[{'model':enhance.BASE_ALIAS,'reasoning_effort':'medium'}] for c in CATEGORIES}}
        self.assertEqual(enhance._base_from_documents(enhance._encode(providers),enhance._encode(legacy)),BASE)

class Installer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        (self.home/'config.yaml').write_text('model: {default: original-model}\ndelegation: {model: pinned-parent}\n')
        self.config=(self.home/'config.yaml').read_bytes()
        self.hook=b'def pre_tool_call(**kwargs):\n    return None\n'
        p=self.home/enhance.HOOK_FILE;p.parent.mkdir(parents=True);p.write_bytes(self.hook)
        self.pin=patch.dict(enhance.PINNED_FILES,{enhance.HOOK_FILE:hashlib.sha256(self.hook).hexdigest()});self.pin.start()
        venv=self.home/'.kit-tools/basic/venv/bin';venv.mkdir(parents=True);(venv/'python').touch();(venv/'omh').touch()
        launcher=self.home/'.local/bin/omh';launcher.parent.mkdir(parents=True);launcher.symlink_to(venv/'omh')
        providers,chains=enhance.compose(BASE,{})
        for name,doc in zip(enhance.ROUTE_FILES,(providers,chains)):
            path=self.home/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(enhance._encode(doc))
        self.basic={name:(self.home/name).read_bytes() for name in enhance.ROUTE_FILES}
    def tearDown(self):self.pin.stop();self.tmp.cleanup()
    def chains(self):return json.loads((self.home/enhance.ROUTE_FILES[1]).read_text())['categories']
    def test_saves_accumulate_across_task_types(self):
        self.assertEqual(enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})['status'],'enabled')
        writing=[{'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'medium'}]
        self.assertEqual(enhance.enable_enhanced_omh(self.home,category_routes={'writing':writing})['status'],'enabled')
        chains=self.chains()
        self.assertEqual(len(chains['deep']),2);self.assertEqual(chains['writing'][0]['reasoning_effort'],'medium')
        self.assertEqual(chains['quick'],[{'model':enhance.BASE_ALIAS,'reasoning_effort':'low'}])
        self.assertEqual(set(enhance.describe(self.home)['categories']),{'deep','writing'})
        self.assertEqual(enhance.enable_enhanced_omh(self.home,remove=('deep',))['status'],'enabled')
        self.assertEqual(self.chains()['deep'],[{'model':enhance.BASE_ALIAS,'reasoning_effort':'high'}])
        self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)
    def test_disable_restores_exact_hook_and_basic_routes(self):
        enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})
        self.assertIn(b'kit-enhanced-omh/v3',(self.home/enhance.HOOK_FILE).read_bytes())
        self.assertEqual(enhance.disable_enhanced_omh(self.home)['status'],'disabled')
        self.assertEqual((self.home/enhance.HOOK_FILE).read_bytes(),self.hook)
        self.assertEqual({n:(self.home/n).read_bytes() for n in enhance.ROUTE_FILES},self.basic)
        for name in (enhance.RUNTIME,enhance.SETTINGS,enhance.RECEIPT):self.assertFalse((self.home/name).exists(),name)
        self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)
    def test_aux_change_follows_into_unassigned_task_types(self):
        enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})
        self.assertEqual(enhance.sync_base_route(self.home,'kit-omniroute','hermes-kit-abc')['status'],'synced')
        models=json.loads((self.home/enhance.ROUTE_FILES[0]).read_text())['models']
        self.assertEqual(models[enhance.BASE_ALIAS],{'model':'hermes-kit-abc','provider':'kit-omniroute'})
        self.assertEqual(len(self.chains()['deep']),2)
        enhance.disable_enhanced_omh(self.home)
        self.assertEqual(json.loads((self.home/enhance.ROUTE_FILES[0]).read_text())['models'][enhance.BASE_ALIAS]['provider'],'kit-omniroute')
    def test_sync_without_calibration_rewrites_only_kit_documents(self):
        self.assertEqual(enhance.sync_base_route(self.home,'opencode-go','kimi-k3')['status'],'synced')
        self.assertEqual(enhance.describe(self.home)['base'],{'provider':'opencode-go','model':'kimi-k3'})
        (self.home/enhance.ROUTE_FILES[1]).write_text('{"schema_version":"mixture_chain_overrides/v1","categories":{}}\n')
        custom=(self.home/enhance.ROUTE_FILES[1]).read_bytes()
        self.assertEqual(enhance.sync_base_route(self.home,'gemini','gemini-3-pro')['status'],'preserved')
        self.assertEqual((self.home/enhance.ROUTE_FILES[1]).read_bytes(),custom)
    def test_modified_upstream_hook_refused(self):
        (self.home/enhance.HOOK_FILE).write_text('operator edits')
        self.assertEqual(enhance.enable_enhanced_omh(self.home)['status'],'failed');self.assertFalse((self.home/enhance.RUNTIME).exists())
    def test_customized_routes_preserved(self):
        (self.home/enhance.ROUTE_FILES[1]).write_text('{"custom":true}')
        self.assertEqual(enhance.enable_enhanced_omh(self.home)['status'],'conflict');self.assertFalse((self.home/enhance.RUNTIME).exists())
    def test_post_install_edits_preserved(self):
        enhance.enable_enhanced_omh(self.home);p=self.home/enhance.ROUTE_FILES[0];p.write_text('operator edits')
        self.assertEqual(enhance.disable_enhanced_omh(self.home)['status'],'conflict');self.assertEqual(p.read_text(),'operator edits')
        self.assertEqual(enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})['status'],'conflict')
    def test_write_failure_rolls_back(self):
        original=enhance._write;failed=False
        def fail_once(path,blob):
            nonlocal failed
            if str(path).endswith('model-chains.json') and not failed:failed=True;raise OSError('synthetic disk error')
            return original(path,blob)
        with patch.object(enhance,'_write',side_effect=fail_once):self.assertEqual(enhance.enable_enhanced_omh(self.home)['status'],'failed')
        self.assertEqual((self.home/enhance.HOOK_FILE).read_bytes(),self.hook)
        self.assertEqual({n:(self.home/n).read_bytes() for n in enhance.ROUTE_FILES},self.basic)
        for name in (enhance.RUNTIME,enhance.SETTINGS,enhance.RECEIPT):self.assertFalse((self.home/name).exists(),name)
    def test_linked_plugin_refused(self):
        (self.home/enhance.RUNTIME).symlink_to(self.home/'config.yaml')
        self.assertEqual(enhance.enable_enhanced_omh(self.home)['status'],'failed');self.assertEqual((self.home/'config.yaml').read_bytes(),self.config)
    def test_v1_receipt_migrates_to_upstream_routing(self):
        tool=self.home/enhance.ROUTE_TOOL;tool.parent.mkdir(parents=True,exist_ok=True);tool.write_bytes(b'# upstream tool\n')
        patched={enhance.ROUTE_TOOL:b'# upstream tool\n# v1 patch\n',enhance.HOOK_FILE:self.hook+b'# v1 patch\n',
                 enhance.RUNTIME:b'# v1 runtime\n',enhance.SETTINGS:b'{"enabled": true, "require_route": true}\n'}
        before={enhance.ROUTE_TOOL:base64.b64encode(b'# upstream tool\n').decode(),enhance.HOOK_FILE:base64.b64encode(self.hook).decode(),
                enhance.RUNTIME:None,enhance.SETTINGS:None,**{n:base64.b64encode(self.basic[n]).decode() for n in enhance.ROUTE_FILES}}
        for name,blob in patched.items():(self.home/name).write_bytes(blob)
        after={n:hashlib.sha256((self.home/n).read_bytes()).hexdigest() for n in before}
        (self.home/enhance.RECEIPT).write_text(json.dumps({'version':1,'before':before,'after':after}))
        self.assertEqual(enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})['status'],'enabled')
        self.assertEqual(tool.read_bytes(),b'# upstream tool\n')
        self.assertEqual(len(self.chains()['deep']),2)
        self.assertEqual(json.loads((self.home/enhance.RECEIPT).read_text())['version'],enhance.VERSION)

    def test_v2_receipt_upgrades_keeping_task_chains(self):
        enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})
        receipt=json.loads((self.home/enhance.RECEIPT).read_text());receipt['version']=2
        (self.home/enhance.RECEIPT).write_text(json.dumps(receipt))
        self.assertEqual(enhance.upgrade_enhanced_omh(self.home)['status'],'enabled')
        self.assertEqual(len(self.chains()['deep']),2)
        self.assertTrue(json.loads((self.home/enhance.SETTINGS).read_text())['require_route'])
        self.assertEqual(json.loads((self.home/enhance.RECEIPT).read_text())['version'],enhance.VERSION)
        self.assertEqual((self.home/enhance.HOOK_FILE).read_bytes().count(b'kit-enhanced-omh/'),1)
        self.assertIsNone(enhance.upgrade_enhanced_omh(self.home))
    def test_upgrade_leaves_students_without_calibration_alone(self):
        self.assertIsNone(enhance.upgrade_enhanced_omh(self.home))
        self.assertFalse((self.home/enhance.RECEIPT).exists())
    def test_soul_rule_appended_once_and_only_when_missing(self):
        soul=self.home/'SOUL.md';soul.write_text('# 나의 비서\n')
        enhance.enable_enhanced_omh(self.home);enhance.enable_enhanced_omh(self.home,category_routes={'deep':DEEP})
        text=soul.read_text();self.assertTrue(text.startswith('# 나의 비서\n'));self.assertEqual(text.count('omh_delegate_route'),1)
        soul.write_text('직접 쓴 omh_delegate_route 규칙\n');enhance.enable_enhanced_omh(self.home)
        self.assertEqual(soul.read_text(),'직접 쓴 omh_delegate_route 규칙\n')

class Runtime(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();home=Path(self.tmp.name)
        package=types.ModuleType('kit_omh_test');package.__path__=[]
        routing=types.ModuleType('kit_omh_test.delegation_routing')
        self.route={}
        routing.read_delegation_route=lambda home:dict(self.route)
        restore=types.ModuleType('kit_omh_test.delegation_route_restore')
        self.record={}
        restore.load_route_restore_record=lambda home:dict(self.record)
        self.modules=patch.dict(sys.modules,{'kit_omh_test':package,routing.__name__:routing,restore.__name__:restore});self.modules.start()
        self.r=types.ModuleType('kit_omh_test.kit_enhanced');self.r.__file__=str(home/'plugins/omh/kit_enhanced.py');self.r.__package__='kit_omh_test'
        exec(compile(enhance.RUNTIME_SOURCE,'kit_enhanced.py','exec'),self.r.__dict__)
        self.r.settings=lambda:{'enabled':True,'python':'/unused'}
        self.calls=[]
        def calibration(model,effort,config):
            self.calls.append((model,effort))
            return {'guidance':'NATIVE CALIBRATION' if effort=='high' else '','family':'unknown' if model.startswith('combo') else 'gpt'}
        self.r.calibrate=calibration
        self.state=home/'.kit-omniroute.json';self.r.OMNIROUTE_STATE=self.state
    def tearDown(self):self.modules.stop();self.tmp.cleanup()
    def test_calibrates_the_route_upstream_prepared(self):
        self.route={'provider':'openai-codex','model':'gpt-6-astra','reasoning_effort':'high'}
        args={'tasks':[{'goal':'g','context':'original'},{'goal':'h'}]}
        change=self.r.guard('delegate_task',args)
        self.assertEqual(change['action'],'modify');self.assertEqual(args['tasks'][0]['context'],'original')
        self.assertTrue(all(t['context'].endswith('NATIVE CALIBRATION') for t in change['args']['tasks']))
        self.assertIsNone(self.r.guard('delegate_task',{**args,**change['args']}))
        self.assertEqual(self.calls[-1],('gpt-6-astra','high'))
        single=self.r.guard('delegate_task',{'goal':'g'});self.assertEqual(single['args']['context'],'NATIVE CALIBRATION')
    def test_kit_omniroute_combo_calibrates_its_single_model(self):
        self.state.write_text(json.dumps({'active':{'name':'hermes-kit-abc','model':'gemini-3-pro'}}))
        self.route={'provider':'kit-omniroute','model':'hermes-kit-abc','reasoning_effort':'high'}
        self.r.guard('delegate_task',{'goal':'g'});self.assertEqual(self.calls[-1],('gemini-3-pro','high'))
    def test_unknown_family_gets_floor_at_any_effort(self):
        self.route={'provider':'kit-omniroute','model':'combo-mixed','reasoning_effort':'low'}
        change=self.r.guard('delegate_task',{'goal':'g'})
        self.assertEqual(change['args']['context'],self.r.FLOOR)
        self.route['reasoning_effort']='high'
        context=self.r.guard('delegate_task',{'goal':'g'})['args']['context']
        self.assertTrue(context.startswith('NATIVE CALIBRATION') and context.endswith(self.r.FLOOR))
    def test_in_process_calibration_is_cached(self):
        calls=[]
        protocol=types.SimpleNamespace(calibration_for_route=lambda route:calls.append(route) or 'X')
        runtime=types.ModuleType('kit_omh_test.kit_enhanced2');runtime.__file__=self.r.__file__;runtime.__package__='kit_omh_test'
        exec(compile(enhance.RUNTIME_SOURCE,'kit_enhanced.py','exec'),runtime.__dict__)
        runtime._MODULES.append((protocol,lambda model:'gpt'))
        with patch.object(runtime.subprocess,'run',side_effect=AssertionError('subprocess not expected')):
            for _ in range(3):self.assertEqual(runtime.calibrate('gpt-6-astra','high',{'python':'/unused'})['guidance'],'X')
        self.assertEqual(len(calls),1)
    def test_medium_borrows_family_calibration_low_does_not(self):
        seen=[]
        def calibration_for_route(route):
            seen.append(route['selected_reasoning_effort'])
            return 'FAMILY' if route['selected_reasoning_effort']=='high' else ''
        runtime=types.ModuleType('kit_omh_test.kit_enhanced3');runtime.__file__=self.r.__file__;runtime.__package__='kit_omh_test'
        exec(compile(enhance.RUNTIME_SOURCE,'kit_enhanced.py','exec'),runtime.__dict__)
        runtime._MODULES.append((types.SimpleNamespace(calibration_for_route=calibration_for_route),lambda model:'gpt'))
        self.assertEqual(runtime.calibrate('gpt-6-sol','medium',{})['guidance'],'FAMILY')
        self.assertEqual(runtime.calibrate('gpt-6-sol','low',{})['guidance'],'')
        self.assertEqual(seen,['medium','high','low'])
    def test_never_blocks(self):
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'}))  # parent inheritance: nothing prepared
        self.route={'provider':'gemini','model':'gemini-3-flash','reasoning_effort':'low'}
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'}))
        self.route['reasoning_effort']='high'
        self.r.calibrate=lambda *args:(_ for _ in ()).throw(RuntimeError('synthetic'))
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'}))
        self.r.current_route=lambda:(_ for _ in ()).throw(OSError('synthetic'))
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'}))
    def test_unrouted_spawn_sent_back_once_per_turn(self):
        self.r.settings=lambda:{'enabled':True,'require_route':True,'python':'/unused'}
        self.route={'provider':'gemini','model':'gemini-3-flash'}  # student baseline, nothing routed
        first=self.r.guard('delegate_task',{'goal':'g'},session_id='s1',turn_id='t1')
        self.assertEqual(first['action'],'block');self.assertIn('omh_delegate_route',first['message'])
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'},session_id='s1',turn_id='t1'))  # retry dispatches
        self.assertEqual(self.r.guard('delegate_task',{'goal':'g'},session_id='s1',turn_id='t2')['action'],'block')
        for a in ('list','stop','steer'):self.assertIsNone(self.r.guard('delegate_task',{'action':a},session_id='s9',turn_id='t'))
    def test_route_written_for_this_session_dispatches_with_calibration(self):
        self.r.settings=lambda:{'enabled':True,'require_route':True,'python':'/unused'}
        self.route={'provider':'openai-codex','model':'gpt-6-astra','reasoning_effort':'high'}
        self.record={'written':dict(self.route),'writer_session_id':'s1'}
        change=self.r.guard('delegate_task',{'goal':'g'},session_id='s1',turn_id='t1')
        self.assertEqual(change,{'action':'modify','args':{'context':'NATIVE CALIBRATION'}})
        other=self.r.guard('delegate_task',{'goal':'g'},session_id='s2',turn_id='t1')  # another session's route
        self.assertEqual(other['action'],'block')
        self.record={'written':{'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'},'writer_session_id':'s1'}
        self.assertEqual(self.r.guard('delegate_task',{'goal':'g'},session_id='s1',turn_id='t3')['action'],'block')
    def test_route_check_failure_dispatches(self):
        self.r.settings=lambda:{'enabled':True,'require_route':True,'python':'/unused'}
        self.r.routed_here=lambda *a:(_ for _ in ()).throw(ImportError('synthetic'))
        self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'},session_id='s',turn_id='t'))
    def test_unrelated_and_management_actions_unchanged(self):
        self.route={'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'}
        self.assertIsNone(self.r.guard('terminal',{'command':'true'}))
        for a in ('list','stop','steer'):self.assertIsNone(self.r.guard('delegate_task',{'action':a}))
    def test_opt_out_preserves_basic_behavior(self):
        self.route={'provider':'gemini','model':'gemini-3-pro','reasoning_effort':'high'}
        self.r.settings=lambda:None;self.assertIsNone(self.r.guard('delegate_task',{'goal':'g'}))

class Hook(unittest.TestCase):
    def setUp(self):self.seen=[];self.directive={'action':'modify','args':{'context':'C'}}
    def load(self,upstream):
        package=types.ModuleType('kit_hook_test');package.__path__=[]
        runtime=types.ModuleType('kit_hook_test.kit_enhanced');runtime.guard=lambda name,args,**kw:self.seen.append(kw) or self.directive
        hooks=types.ModuleType('kit_hook_test.hooks');hooks.__package__='kit_hook_test.hooks';hooks.__path__=[]
        module=types.ModuleType('kit_hook_test.hooks.tool_hooks');module.__package__='kit_hook_test.hooks'
        with patch.dict(sys.modules,{'kit_hook_test':package,runtime.__name__:runtime,hooks.__name__:hooks}):
            package.kit_enhanced=runtime
            exec(compile(upstream+enhance.HOOK_APPEND,'tool_hooks.py','exec'),module.__dict__)
        return module.pre_tool_call
    def test_upstream_block_and_other_directives_win(self):
        hook=self.load("def pre_tool_call(**kwargs):\n    return {'action':'block','message':'rule'}\n")
        self.assertEqual(hook(tool_name='delegate_task',args={})['action'],'block')
        hook=self.load("def pre_tool_call(**kwargs):\n    return {'action':'approve','message':'ask'}\n")
        self.assertEqual(hook(tool_name='delegate_task',args={})['action'],'approve')
    def test_upstream_modify_merged(self):
        hook=self.load("def pre_tool_call(**kwargs):\n    return {'action':'modify','args':{'goal':'G'}}\n")
        self.assertEqual(hook(tool_name='delegate_task',args={}),{'action':'modify','args':{'goal':'G','context':'C'}})
        hook=self.load("def pre_tool_call(**kwargs):\n    return None\n")
        self.assertEqual(hook(tool_name='delegate_task',args={}),{'action':'modify','args':{'context':'C'}})
    def test_route_request_passes_through_with_session(self):
        self.directive={'action':'block','message':'route first'}
        hook=self.load("def pre_tool_call(**kwargs):\n    return {'action':'modify','args':{'goal':'G'}}\n")
        self.assertEqual(hook(tool_name='delegate_task',args={},session_id='s',turn_id='t'),{'action':'block','message':'route first'})
        self.assertEqual(self.seen[-1],{'session_id':'s','turn_id':'t'})

if __name__=='__main__':unittest.main()
