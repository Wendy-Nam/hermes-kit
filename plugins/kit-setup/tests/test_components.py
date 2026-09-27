import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import components as c
import fetch_packs as fp


class ComponentInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.seed = self.root / 'seed'
        self.package('job', 'first')

    def package(self, cid, text, version='1.0.0'):
        d = self.seed / 'kits' / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / 'SKILL.md').write_text(text)
        (d / 'manifest.json').write_text(json.dumps({'schema_version': 'kit-component/v1',
            'id': cid, 'version': version, 'files': {'SKILL.md': hashlib.sha256(text.encode()).hexdigest()}}))
        return d

    def retry(self, selected=None):
        return c.retry_components(self.data, selected_kits=selected, seed_dir=self.seed)

    def test_offline_selected_job_installs_and_retry_keeps_selection(self):
        self.assertEqual(self.retry(['job'])[0]['status'], 'installed')
        self.assertEqual(self.retry()[0]['status'], 'installed')
        self.assertEqual((self.data / 'skills/kit/job/SKILL.md').read_text(), 'first')

    def test_failed_missing_component_recovers_without_core_version_change(self):
        self.assertEqual(self.retry(['sales'])[0]['status'], 'failed')
        self.package('sales', 'ready')
        self.assertEqual(self.retry()[0]['status'], 'installed')

    def test_user_edit_is_not_overwritten(self):
        self.retry(['job'])
        target = self.data / 'skills/kit/job/SKILL.md'
        target.write_text('my notes')
        self.package('job', 'new', '1.0.1')
        self.assertEqual(self.retry()[0]['status'], 'preserved')
        self.assertEqual(target.read_text(), 'my notes')

    def test_bad_checksum_cannot_replace_working_skill(self):
        self.retry(['job'])
        (self.seed / 'kits/job/SKILL.md').write_text('tampered')
        self.assertEqual(self.retry()[0]['status'], 'failed')
        self.assertEqual((self.data / 'skills/kit/job/SKILL.md').read_text(), 'first')

    def test_failed_swap_rolls_back(self):
        self.retry(['job'])
        self.package('job', 'next', '1.0.1')
        original = c.os.replace
        def fail_staging(src, dst):
            if Path(src).name.startswith('.kit-stage-') and not str(src).endswith('-previous'):
                raise OSError('simulated disk error')
            return original(src, dst)
        with patch.object(c.os, 'replace', side_effect=fail_staging):
            self.assertEqual(self.retry()[0]['status'], 'failed')
        self.assertEqual((self.data / 'skills/kit/job/SKILL.md').read_text(), 'first')
        self.assertEqual(self.retry()[0]['status'], 'installed')

    def test_same_version_mutation_and_downgrade_rejected(self):
        self.retry(['job'])
        self.package('job', 'changed')
        self.assertEqual(self.retry()[0]['status'], 'failed')
        self.package('job', 'older', '0.9.0')
        self.assertEqual(self.retry()[0]['status'], 'failed')

    def test_target_parent_symlink_refused(self):
        self.data.mkdir()
        outside = self.root / 'outside'; outside.mkdir()
        (self.data / 'skills').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.retry(['job'])[0]['status'], 'failed')
        self.assertEqual(list(outside.iterdir()), [])

    def test_optional_omh_unavailable_without_trust_registry(self):
        for name in ('omh',):
            self.assertEqual(c.install_optional(name, self.data)['status'], 'unavailable')
        self.assertFalse((self.data / 'plugins').exists())

    def test_optional_pinned_package_is_staged_without_enabling(self):
        p = self.root / 'omh'; p.mkdir()
        files = {'plugin.yaml': 'name: omh\n', '__init__.py': ''}
        for name, content in files.items(): (p / name).write_text(content)
        manifest = {'schema_version': 'kit-component/v1', 'id': 'omh', 'version': '2.0.5',
                    'files': {k: hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()}}
        (p / 'manifest.json').write_text(json.dumps(manifest))
        reg = {'omh': {'path': p, 'manifest_sha256': c._digest(p / 'manifest.json')}}
        self.assertEqual(c.install_optional('omh', self.data, trusted_registry=reg)['status'], 'installed')
        self.assertTrue((self.data / 'plugins/omh/plugin.yaml').exists())
        self.assertFalse((self.data / 'config.yaml').exists())

    def archive(self, manifest=True):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as t:
            root = tarfile.TarInfo('repo/'); root.type = tarfile.DIRTYPE; t.addfile(root)
            if manifest:
                raw = json.dumps({'schema_version':'kit-bundle/v1','version':'1.0.0','components':['job']}).encode()
                i=tarfile.TarInfo('repo/manifest.json');i.size=len(raw);t.addfile(i,io.BytesIO(raw))
                for p in (self.seed / 'kits/job').iterdir():
                    t.add(p, arcname='repo/kits/job/'+p.name)
        return buf.getvalue()

    def test_private_fetch_requires_pin_and_manifest(self):
        with patch.object(fp, '_download', return_value=self.archive(False)) as download:
            self.assertFalse(fp.fetch('o/r', 'main', 'token', self.data)[0])
            download.assert_not_called()
            self.assertFalse(fp.fetch('o/r', 'a'*40, 'token', self.data)[0])
        with patch.object(fp, '_download', return_value=self.archive()):
            self.assertTrue(fp.fetch('o/r', 'a'*40, 'token', self.data)[0])

    def test_private_redirect_refuses_cross_host_and_http(self):
        import urllib.request
        handler = fp._ArchiveRedirect()
        req = urllib.request.Request('https://api.github.com/repos/o/r/tarball/'+'a'*40,
                                     headers={'Authorization':'Bearer test-only'})
        for target in ('https://example.org/steal','http://codeload.github.com/o/r'):
            with self.assertRaises(ValueError):
                handler.redirect_request(req,None,302,'redirect',{},target)
        target = handler.redirect_request(req,None,302,'redirect',{},'https://codeload.github.com/o/r/tar.gz/'+'a'*40)
        self.assertEqual(target.host,'codeload.github.com')

    def test_rollback_failure_retains_backup_for_recovery(self):
        self.retry(['job'])
        self.package('job','next','1.0.1')
        original = c.os.replace
        def broken(src,dst):
            if Path(src).name.startswith('.kit-stage-'):
                raise OSError('simulated replacement and restore failure')
            return original(src,dst)
        with patch.object(c.os,'replace',side_effect=broken):
            self.assertEqual(self.retry()[0]['status'],'failed')
        backups=list((self.data/'skills/kit').glob('.kit-stage-*-previous/SKILL.md'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_text(),'first')

    def test_bundled_seed_manifests_all_verify(self):
        seed = Path(__file__).resolve().parents[3] / 'seed/kits'
        for cid in c.KITS:
            self.assertEqual(c._manifest(seed / cid, cid)['id'], cid)



class UpstreamOmh(unittest.TestCase):
    def test_conditions_reject_auto_provider_and_wrong_host(self):
        import upstream_omh as u
        with self.assertRaises(ValueError): u.validate_routing({'model':'x','provider':'auto'})
        with tempfile.TemporaryDirectory() as d:
            result = u.install_upstream_omh(d, routing={'model':'x','provider':'openai'}, host_version='0.22.0')
            self.assertEqual(result['status'], 'failed')
            self.assertFalse((Path(d) / '.kit-tools').exists())

    def test_existing_omh_preserved(self):
        import upstream_omh as u
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / '.omh').mkdir()
            result = u.install_upstream_omh(d, routing={'model':'x','provider':'openai'}, host_version='0.21.2')
            self.assertEqual(result['status'], 'preserved')

    def test_upstream_source_checksum_required(self):
        import upstream_omh as u
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): u._source(b'changed', Path(d))

    def test_failed_setup_restores_activation_config(self):
        import upstream_omh as u
        with tempfile.TemporaryDirectory() as d:
            data = Path(d); config = data / 'config.yaml'; config.write_text('model: original\n')
            def run(argv, env):
                if 'setup' in argv:
                    config.write_text('plugins: changed\n')
                    (data / 'plugins/omh').mkdir(parents=True)
                    (data / '.omh').mkdir()
                    raise RuntimeError('setup failed')
                return ''
            with patch.object(u.urllib.request,'urlopen',return_value=io.BytesIO(b'source')), \
                 patch.object(u,'_source',side_effect=lambda b,p:p), patch.object(u,'_run',side_effect=run):
                result=u.install_upstream_omh(data,routing={'model':'x','provider':'openai'},host_version='0.21.2')
            self.assertEqual(result['status'],'failed')
            self.assertEqual(config.read_text(),'model: original\n')
            self.assertFalse((data / 'plugins/omh').exists())
            self.assertTrue(list((data / '.kit-tools').glob('*/failed-omh-plugin')))

if __name__ == '__main__': unittest.main()
