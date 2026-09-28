import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bootstrap
import config_store
import env_store
import model_setup
import readiness

class SetupFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        env_store.set_env(self.root/'.env',{'GEMINI_API_KEY':'test'})
        config_store.write(self.root,{'model.provider':'gemini','model.default':'working'},remember=False)
    def test_upgrade_enables_setup_and_preserves_other_plugins(self):
        config_store.write(self.root,{'plugins.enabled':['rtk-rewrite']},remember=False)
        bootstrap.ensure_setup_enabled(self.root)
        bootstrap.ensure_setup_enabled(self.root)
        self.assertEqual(config_store.read(self.root)['plugins']['enabled'],['rtk-rewrite','kit-setup'])
    def test_bad_new_model_does_not_replace_working_configuration(self):
        before=(self.root/'config.yaml').read_bytes()
        with patch.object(model_setup,'probe',return_value=(False,'rejected')):
            ok,_=model_setup.select_model(self.root,'gemini','bad-model')
        self.assertFalse(ok);self.assertEqual((self.root/'config.yaml').read_bytes(),before)
    def test_successful_selection_records_restore_baseline(self):
        with patch.object(model_setup,'probe',return_value=(True,'ok')):
            self.assertTrue(model_setup.select_model(self.root,'gemini','new-model')[0])
        self.assertEqual(config_store.read(self.root)['model']['default'],'new-model')
        snap=json.loads((self.root/'.kit-config-snapshot.json').read_text())
        self.assertEqual(snap['model.default'],'working')
    def test_env_concurrent_writers_preserve_all_keys(self):
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda i:env_store.set_env(self.root/'.env',{f'TEST_{i}':str(i)}),range(20)))
        self.assertEqual(len(env_store.get_env(self.root/'.env')),21)
    def test_model_check_never_surfaces_raw_worker_errors(self):
        result=subprocess.CompletedProcess([],1,'raw-secret','another-secret')
        with patch.object(model_setup.subprocess,'run',return_value=result):
            ok,msg=model_setup.probe(self.root)
        self.assertFalse(ok);self.assertNotIn('secret',msg)
    def test_readiness_checks_the_aux_model_only_when_one_is_set(self):
        skill=self.root/'skills/media/youtube-summary/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('skill')
        with patch.object(model_setup,'probe',return_value=(True,'main')) as check:
            self.assertTrue(readiness.check(self.root)[0])  # no aux: the main model delegates
        self.assertEqual(check.call_count,1)
        config_store.write(self.root,{'delegation.provider':'gemini','delegation.model':'aux'},remember=False)
        with patch.object(model_setup,'probe',side_effect=[(True,'main'),(False,'aux missing')]) as check:
            ok,rows=readiness.check(self.root)
        self.assertFalse(ok);self.assertIn('aux missing',rows[0]);self.assertEqual(check.call_count,2)
    def test_delegation_route_falls_back_to_the_main_model(self):
        self.assertEqual(model_setup.delegation_route(config_store.read(self.root)),({'provider':'gemini','model':'working'},False))
        config_store.write(self.root,{'delegation.provider':'opencode-go','delegation.model':'kimi-k3'},remember=False)
        self.assertEqual(model_setup.delegation_route(config_store.read(self.root)),({'provider':'opencode-go','model':'kimi-k3'},True))
    def test_failed_public_install_is_retried_without_core_version_change(self):
        (self.root/'.kit-version').write_text('2')
        with patch.object(bootstrap.subprocess,'run',side_effect=TimeoutError):
            first=bootstrap.retry_installation(self.root,seed_dir=self.root/'seed')
        self.assertEqual(first[-1]['status'],'failed')
        def install(*args,**kwargs):
            skill=self.root/'skills/media/youtube-summary/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('ready')
        with patch.object(bootstrap.subprocess,'run',side_effect=install) as runner:
            second=bootstrap.retry_installation(self.root,seed_dir=self.root/'seed')
        self.assertEqual(second[-1]['status'],'installed');self.assertEqual(runner.call_count,1)
    def test_proxy_is_verified_as_one_credential_pair(self):
        import discord_ui,validators,packs
        proxy=next(p for p in packs.load_packs() if p.id=='proxy')
        with patch.object(validators,'webshare_credentials',return_value=(True,'connected')) as verify:
            rows=asyncio.run(discord_ui._verify(list(zip(proxy.keys,['username','password']))))
        verify.assert_called_once_with('username','password');self.assertTrue(all(r[1] for r in rows))
    def test_selected_kit_failed_upgrade_is_not_ready(self):
        folder=self.root/'skills/kit/job';folder.mkdir(parents=True);(folder/'SKILL.md').write_text('old')
        (self.root/'.kit-components.json').write_text(json.dumps({'schema_version':'kit-components/v1','selected_kits':['job'],'components':{},'last_results':{'job':{'status':'failed'}}}))
        row=next(r for r in bootstrap.component_status(self.root) if r['id']=='job')
        self.assertEqual(row['status'],'failed')

class DiscordLayout(unittest.IsolatedAsyncioTestCase):
    async def test_layout_and_modal_limits(self):
        try:import discord
        except ImportError:self.skipTest('Discord SDK is tested inside the kit image')
        import views,packs
        view=views.HomeView(packs.load_packs(),owner_id=123,channel_id=456)
        self.assertLessEqual(len(view.children),25)
        ids=[c.custom_id for c in view.children if getattr(c,'custom_id',None)]
        self.assertEqual(len(ids),len(set(ids)))
        for cls in (views.ModelModal,views.OmniModal):
            self.assertLessEqual(len(cls().children),5)
        view.stop()

if __name__=='__main__':unittest.main()
