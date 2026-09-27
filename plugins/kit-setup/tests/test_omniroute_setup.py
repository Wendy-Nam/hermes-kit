import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import omniroute_setup as om
from env_store import get_env


class Router:
    def __init__(self):
        self.providers=[{'id':'user-provider','name':'user owned','provider':'openai'}]
        self.combos=[{'id':'user-combo','name':'user owned','models':['openai/original']}]
        self.keys=[{'id':'user-key','name':'user owned'}]
        self.calls=[]; self.fail_probe=False; self.counter=0
    def request(self, method,path,body=None,key=None):
        self.calls.append((method,path,copy.deepcopy(body)))
        if path=='/api/auth/login':return {},{}
        groups={'providers':self.providers,'combos':self.combos,'keys':self.keys}
        if path=='/v1/chat/completions':
            if self.fail_probe:raise om.SetupError('도구 시험 실패')
            if body['tool_choice']=='none':return {'choices':[{'message':{'role':'assistant','content':'KIT_READY'}}]},{}
            return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                {'id':'call-1','type':'function','function':{'name':'kit_echo','arguments':'{"value":"KIT_READY"}'}}]}}]},{}
        pieces=path.split('/'); kind=pieces[2]; items=groups[kind]
        if method=='GET':return {('connections' if kind=='providers' else kind):copy.deepcopy(items)},{}
        if method=='DELETE':items[:]=[x for x in items if x['id']!=pieces[3]];return {},{}
        if method=='PUT':
            row=next(x for x in items if x['id']==pieces[3]);row.update(body);return {},{}
        self.counter+=1
        item=dict(body,id='id-'+str(self.counter));items.append(item)
        if kind=='keys':return dict(item,key='new-inference-key'),{}
        return {('connection' if kind=='providers' else 'combo'):copy.deepcopy(item)},{}


class OmniRouteSetup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)
        self.config={'model':{'default':'direct-model','provider':'direct-provider'},
            'providers':{'user-custom':{'api':'https://example.org/v1'}},
            'delegation':{'provider':'direct-provider','model':'direct-worker','max_iterations':10}}
        (self.data/'config.yaml').write_text(yaml.safe_dump(self.config))
        (self.data/'.env').write_text('USER_SECRET=keep\n')
        self.router=Router()
        self.patcher=patch.object(om,'Client',return_value=self.router);self.patcher.start();self.addCleanup(self.patcher.stop)
    def configure(self,model='example-model'):
        return om.configure(self.data,'admin-test-password','openai','provider-test-key',model)
    def test_two_turn_probe_then_only_delegation_switches(self):
        ok,msg=self.configure();self.assertTrue(ok,msg)
        config=yaml.safe_load((self.data/'config.yaml').read_text())
        self.assertEqual(config['model'],self.config['model'])
        self.assertEqual(config['providers']['user-custom'],self.config['providers']['user-custom'])
        self.assertEqual(config['delegation']['provider'],'kit-omniroute')
        self.assertEqual(config['delegation']['max_iterations'],10)
        self.assertNotIn('api_key',config['delegation'])
        self.assertNotIn('base_url',config['delegation'])
        env=get_env(self.data/'.env');self.assertEqual(env['USER_SECRET'],'keep')
        self.assertEqual(env[om.KEY_ENV],'new-inference-key')
        self.assertEqual(stat.S_IMODE((self.data/'.env').stat().st_mode),0o600)
        self.assertEqual(len([p for m,p,b in self.router.calls if p=='/v1/chat/completions']),2)
        journal=(self.data/om.STATE).read_text()
        self.assertNotIn('provider-test-key',journal);self.assertNotIn('admin-test-password',journal)
        self.assertNotIn('new-inference-key',journal)
    def test_failed_probe_preserves_local_env_and_model_config(self):
        before=(self.data/'config.yaml').read_bytes();env=(self.data/'.env').read_bytes()
        self.router.fail_probe=True
        ok,msg=self.configure();self.assertFalse(ok)
        self.assertEqual((self.data/'config.yaml').read_bytes(),before)
        self.assertEqual((self.data/'.env').read_bytes(),env)
        self.assertNotIn('provider-test-key',msg)
    def test_retry_reuses_connection_combo_and_key(self):
        self.assertTrue(self.configure()[0]);counts=[len(self.router.providers),len(self.router.combos),len(self.router.keys)]
        self.assertTrue(self.configure()[0]);self.assertEqual(counts,[len(self.router.providers),len(self.router.combos),len(self.router.keys)])
    def test_failed_attempt_retry_reuses_resources_without_duplicates(self):
        self.router.fail_probe=True;self.assertFalse(self.configure()[0])
        self.router.fail_probe=False;self.assertTrue(self.configure()[0])
        self.assertEqual([len(self.router.providers),len(self.router.combos),len(self.router.keys)],[2,2,2])
    def test_new_model_removes_only_old_recorded_kit_resources(self):
        self.assertTrue(self.configure()[0]);self.assertTrue(self.configure('another-model')[0])
        self.assertEqual([len(self.router.providers),len(self.router.combos),len(self.router.keys)],[2,2,2])
        for rows in (self.router.providers,self.router.combos,self.router.keys):
            self.assertTrue(any(x['name']=='user owned' for x in rows))
    def test_user_modified_combo_is_preserved(self):
        self.assertTrue(self.configure()[0])
        self.router.combos[-1]['models'][0]['model']='user-change'
        before=(self.data/'config.yaml').read_bytes()
        self.assertFalse(self.configure()[0]);self.assertEqual((self.data/'config.yaml').read_bytes(),before)
        self.assertEqual(self.router.combos[-1]['models'][0]['model'],'user-change')
    def test_no_implicit_model_or_unapproved_provider(self):
        for provider,model in [('openai',''),('cline','example')]:
            self.assertFalse(om.configure(self.data,'pw',provider,'key',model)[0])
        self.assertFalse(self.router.calls)
    def test_text_only_response_is_not_tool_success(self):
        original=self.router.request
        def text_only(method,path,body=None,key=None):
            if path=='/v1/chat/completions':return {'choices':[{'message':{'content':'KIT_READY'}}]},{}
            return original(method,path,body,key)
        with patch.object(self.router,'request',side_effect=text_only):self.assertFalse(self.configure()[0])
        self.assertNotIn(om.KEY_ENV,get_env(self.data/'.env'))
    def test_partial_lists_do_not_create_duplicate_objects(self):
        with patch.object(self.router,'request',return_value=({'connections':[],'total':2},{})):
            self.assertFalse(self.configure()[0])
        self.assertEqual(len(self.router.providers),1)
    def test_local_write_failure_rolls_back_environment(self):
        original=om._atomic
        def fail_config(path,blob,mode=0o600):
            if path.name=='config.yaml' and b'kit-omniroute' in blob:raise OSError('disk')
            return original(path,blob,mode)
        before=(self.data/'config.yaml').read_bytes();env=(self.data/'.env').read_bytes()
        with patch.object(om,'_atomic',side_effect=fail_config):self.assertFalse(self.configure()[0])
        self.assertEqual((self.data/'config.yaml').read_bytes(),before)
        self.assertEqual((self.data/'.env').read_bytes(),env)


if __name__=='__main__':unittest.main()
