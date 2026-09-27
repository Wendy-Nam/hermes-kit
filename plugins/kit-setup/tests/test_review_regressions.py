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

if __name__=='__main__':unittest.main()
