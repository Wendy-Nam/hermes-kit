import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import components
import proactive
import backup

class ReviewRegressions(unittest.TestCase):
    def test_backup_scrubs_url_credentials_but_keeps_safe_urls_and_env_refs(self):
        doc={'servers':[
            {'url':'https://name:TEST_SECRET@example.com/mcp'},
            {'url':'https://example.com/mcp?api_key=TEST_SECRET&user_id=student'},
            {'url':'https://example.com/mcp#access_token=TEST_SECRET'},
            {'url':'https://example.com/mcp?%74oken=TEST_SECRET'},
            {'url':'https://example.com/mcp?user_id=student'},
            {'url':'https://example.com/mcp?key=${API_KEY}'}]}
        clean=backup._scrub(doc)
        self.assertNotIn('TEST_SECRET',json.dumps(clean))
        self.assertEqual(clean['servers'][4],doc['servers'][4])
        self.assertEqual(clean['servers'][5],doc['servers'][5])
        self.assertEqual(clean['servers'][0]['url'],'[REENTER VIA SETUP]')
    def test_failed_publish_and_failed_rollback_preserve_only_original(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td).resolve(); source=root/'source';source.mkdir()
            (source/'SKILL.md').write_text('new')
            (source/'manifest.json').write_text(json.dumps({'schema_version':'kit-component/v1','id':'job',
                'version':'1.1.0','files':{'SKILL.md':hashlib.sha256(b'new').hexdigest()}}))
            target=root/'target';target.mkdir();(target/'SKILL.md').write_text('original')
            state={'components':{'job':{'version':'1.0.0','files':{'SKILL.md':hashlib.sha256(b'original').hexdigest()}}}}
            original_replace=components.os.replace
            calls=[]
            def fail(a,b):
                calls.append((a,b))
                if len(calls)>1:
                    # Another writer appearing must not justify deleting backup.
                    target.mkdir(exist_ok=True)
                    raise OSError('simulated publication/rollback failure')
                return original_replace(a,b)
            with patch.object(components.os,'replace',side_effect=fail):
                with self.assertRaises(OSError):components._install(source,target,'job',state)
            backups=list(root.glob('.kit-stage-*-previous'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'SKILL.md').read_text(),'original')
            self.assertEqual(state['components']['job']['version'],'1.0.0')
    def test_modern_19_digit_discord_channel_passes_id_validation(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td);(home/'config.yaml').write_text('model: {}\n')
            ok,message=proactive.enable(home,'1' * 19,'12:00','topic')
            self.assertFalse(ok)
            self.assertIn('모델',message) # reached the next gate; no schedule mutation
            for channel in ('1'*16,'1'*21,'١'*18):
                self.assertIn('채널 ID',proactive.enable(home,channel,'12:00','topic')[1])

    def test_disconnect_plan_includes_derived_and_omniroute_keys(self):
        import disconnect, env_store, packs
        with tempfile.TemporaryDirectory() as td:
            home=Path(td); env_file=home/'.env'
            env_store.set_env(env_file,{
                'WEBSHARE_API_KEY':'ws-key',
                'WEBSHARE_PROXY_USERNAME':'ws-user',
                'WEBSHARE_PROXY_PASSWORD':'ws-pass',
                'KIT_OMNIROUTE_API_KEY':'or-key',
                'OMNIROUTE_API_KEY':'or-key',
                'DISCORD_BOT_TOKEN':'keep-me',
            })
            keys,_=disconnect.plan(home,env_file,packs.load_packs())
            for expected in ('WEBSHARE_API_KEY','WEBSHARE_PROXY_USERNAME','WEBSHARE_PROXY_PASSWORD',
                             'KIT_OMNIROUTE_API_KEY','OMNIROUTE_API_KEY'):
                self.assertIn(expected,keys)
            self.assertNotIn('DISCORD_BOT_TOKEN',keys)

    def test_doctor_components_handles_preserved_and_optional_statuses(self):
        import doctor, bootstrap
        rows=[
            {'id':'youtube-summary','required':True,'status':'installed','message':'ok'},
            {'id':'job','required':True,'status':'preserved','message':'user modified'},
            {'id':'k-skill','required':False,'status':'failed','message':'retry later'},
            {'id':'pm','required':True,'status':'failed','message':'missing'},
        ]
        with patch.object(bootstrap,'component_status',return_value=rows):
            findings={f.name:f.status for f in doctor.check_components(Path('/tmp'))}
        self.assertEqual(findings['스킬 youtube-summary'],doctor.OK)
        self.assertEqual(findings['스킬 job'],doctor.OK)
        self.assertEqual(findings['스킬 k-skill'],doctor.WARN)
        self.assertEqual(findings['스킬 pm'],doctor.BAD)

    def test_env_store_rejects_cr_in_key_name(self):
        import env_store
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                env_store.set_env(Path(td)/'.env',{'FOO\rBAR':'val'})

    def test_fs_util_atomic_write_preserves_mode_and_cleans_up(self):
        import fs_util, os, stat
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'state.json'
            fs_util.atomic_write(p,'{"ok":true}\n',mode=0o600,fsync=True)
            self.assertEqual(p.read_text(),'{"ok":true}\n')
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode),0o600)
            self.assertEqual(list(Path(td).glob('.kit-*')),[])

    def test_omh_quota_exhausted_multi_account_pool(self):
        import importlib.util
        root=Path(__file__).resolve().parents[3]/'patches'/'omh-routing'/'files'
        for mod_name in ('omh_provider_mapper','route_readiness'):
            spec=importlib.util.spec_from_file_location(mod_name,root/f'{mod_name}.py')
            mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            partial={'codexAccountPool':{'aggregate':{'status':'available'},'children':[
                {'quota':{'windows':{'5h':{'usedPercentage':100.0}}}},
                {'quota':{'windows':{'5h':{'usedPercentage':25.0}}}},
            ]}}
            all_spent={'codexAccountPool':{'aggregate':{'status':'available'},'children':[
                {'quota':{'windows':{'5h':{'usedPercentage':100.0}}}},
                {'unavailable':True},
            ]}}
            self.assertFalse(mod._quota_exhausted(partial),mod_name)
            self.assertTrue(mod._quota_exhausted(all_spent),mod_name)

if __name__=='__main__':unittest.main()
