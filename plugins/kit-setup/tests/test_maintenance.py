import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import backup
import maintenance
import restore
import updates


class Maintenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        (self.home / 'memories').mkdir()
        (self.home / 'memories/note.md').write_text('student note')
        self.dest = self.home / 'vaults/personal/_backup'

    def test_backup_excludes_old_archives_and_secret_variants(self):
        self.dest.mkdir(parents=True)
        (self.dest / 'old.tar.gz').write_bytes(b'old archive')
        (self.home / 'profiles/a').mkdir(parents=True)
        for n in ['.env.old', 'auth.json.bak', 'cookies.json']:
            (self.home / 'profiles/a' / n).write_text('sensitive')
        (self.home / 'config.yaml').write_text('model: ok\napi_key: sensitive\nref_token: ${TOKEN}\n')
        self.assertTrue(backup.build(self.home, self.dest)[0])
        with tarfile.open(next(p for p in self.dest.glob('*.tar.gz') if p.name != 'old.tar.gz')) as tf:
            self.assertEqual(set(tf.getnames()), {'config.yaml', 'memories/note.md'})
            text = tf.extractfile('config.yaml').read().decode()
            self.assertNotIn('sensitive', text)
            self.assertIn('${TOKEN}', text)

    def test_failure_does_not_publish_and_entrypoint_fails(self):
        with patch.object(backup, 'archive_bytes', side_effect=OSError):
            self.assertFalse(backup.build(self.home, self.dest)[0])
        self.assertEqual(list(self.dest.glob('*.tar.gz')), [])
        empty = self.root / 'empty'; empty.mkdir()
        result = subprocess.run([sys.executable, str(HERE / 'backup.py')],
                                env={**os.environ, 'HERMES_HOME': str(empty)}, capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_real_backup_restore_and_no_overwrite(self):
        self.assertTrue(backup.build(self.home, self.dest)[0])
        archive = next(self.dest.glob('*.tar.gz'))
        target = self.root / 'restored'
        self.assertTrue(restore.restore(archive, target)[0])
        self.assertEqual((target / 'memories/note.md').read_text(), 'student note')
        self.assertFalse(restore.restore(archive, target)[0])
        self.assertFalse(backup.build(self.home, self.dest)[0])

    def test_restore_rejects_secret_traversal_and_links_before_publishing(self):
        for name, kind in [('memories/../escape', tarfile.REGTYPE),
                           ('profiles/a/.env', tarfile.REGTYPE), ('memories/link', tarfile.SYMTYPE)]:
            archive = self.root / 'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as tf:
                item = tarfile.TarInfo(name); item.type = kind
                item.size = 1 if kind == tarfile.REGTYPE else 0
                item.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                tf.addfile(item, io.BytesIO(b'x') if item.size else None)
            self.assertFalse(restore.restore(archive, self.root / 'result')[0])
            self.assertFalse((self.root / 'result').exists())

    def test_hermes_api_normalizes_jobs_and_registration_is_idempotent(self):
        jobs, registered = [], []
        api = types.ModuleType('cron.jobs')
        api.use_cron_store = lambda home: contextlib.nullcontext()
        api.list_jobs = lambda **kwargs: jobs
        scheduler = types.ModuleType('cron.scheduler')
        def create(**kw):
            self.assertEqual(kw['script'], str(self.home.resolve() / 'scripts/kit-backup.py'))
            self.assertTrue(kw['no_agent'])
            self.assertNotIn('command', kw)
            jobs.append({'id': 'generated', 'enabled': True, **kw})
            return jobs[-1]
        scheduler.create_job_with_scheduler_registration = create
        provider = types.ModuleType('cron.scheduler_provider')
        provider.resolve_cron_scheduler = lambda: types.SimpleNamespace(register_job=registered.append)
        with patch.dict(sys.modules, {'cron': types.ModuleType('cron'), 'cron.jobs': api,
                                      'cron.scheduler': scheduler, 'cron.scheduler_provider': provider}):
            self.assertTrue(backup.install_cron(self.home)[0])
            self.assertFalse(backup.install_cron(self.home)[0])
            self.assertEqual(len(jobs), 1)
            self.assertEqual(len(registered), 1)
        self.assertFalse((self.home / 'cron/jobs.json').exists())  # no raw write fallback

    def test_api_unavailable_is_explicit_failure(self):
        with patch.dict(sys.modules, {'cron.jobs': None}):
            ok, message = backup.install_cron(self.home)
        self.assertFalse(ok)
        self.assertIn('실패', message)
        self.assertFalse((self.home / 'cron/jobs.json').exists())

    def test_update_entrypoint_prints_only_new_release(self):
        (self.home / '.kit-release-version').write_text('0.21.2-k1')
        with patch.dict(os.environ, {'HERMES_HOME': str(self.home)}), patch.object(updates, 'check', return_value=(True, '0.21.3-k1', 'update ready')), patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(updates.main(), 0)
            self.assertEqual(out.getvalue().strip(), 'update ready')

    def test_restore_keeps_cron_paused(self):
        (self.home / 'cron').mkdir()
        (self.home / 'cron/jobs.json').write_text(json.dumps([{'id': 'a', 'enabled': True}]))
        self.assertTrue(backup.build(self.home, self.dest)[0])
        target = self.root / 'restored'
        self.assertTrue(restore.restore(next(self.dest.glob('*.tar.gz')), target)[0])
        self.assertFalse(json.loads((target / 'cron/jobs.json').read_text())[0]['enabled'])

    def test_proactive_input_and_worker_protocol(self):
        import proactive
        self.assertFalse(proactive.enable(self.home, 'invalid', '12:00', 'joke')[0])
        self.assertFalse(proactive.enable(self.home, '1' * 18, '25:00', 'joke')[0])
        self.assertFalse(proactive.enable(self.home, '1' * 18, '12:00', 'x' * 201)[0])
        (self.home / 'config.yaml').write_text('model:\n  provider: test\n  default: test-model\n')
        proactive._save(self.home, {'enabled': True, 'topic': 'fun science', 'provider': 'test', 'model': 'test-model'})
        reply = types.SimpleNamespace(returncode=0, stdout=json.dumps({'kit_event': 'proactive', 'text': 'hi @everyone'}))
        with patch.dict(os.environ, {'HERMES_HOME': str(self.home)}), patch.object(proactive.subprocess, 'run', return_value=reply) as run, patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(proactive.main(), 0)
            self.assertNotIn('@everyone', out.getvalue())
            self.assertEqual(json.loads(run.call_args.kwargs['input']), {'topic': 'fun science'})
            self.assertNotIn('shell', run.call_args.kwargs)
        reply.stdout = 'internal log containing sensitive data'
        with patch.dict(os.environ, {'HERMES_HOME': str(self.home)}), patch.object(proactive.subprocess, 'run', return_value=reply), patch('sys.stdout', new_callable=io.StringIO) as out, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(proactive.main(), 1)
            self.assertEqual(out.getvalue(), '')

    def test_snapshot_failure_preserves_baseline_and_propagates(self):
        import disconnect
        disconnect.snapshot(self.home, {'model.default': 'new'}, {'model.default': 'old'})
        before = (self.home / disconnect.SNAPSHOT).read_bytes()
        with patch.object(disconnect.os, 'replace', side_effect=OSError):
            with self.assertRaises(OSError):
                disconnect.snapshot(self.home, {'other': 'new'}, {'other': 'old'})
        self.assertEqual((self.home / disconnect.SNAPSHOT).read_bytes(), before)
        self.assertEqual(list(self.home.glob('.kit-snapshot-*')), [])
        (self.home / disconnect.SNAPSHOT).write_text('{broken')
        with self.assertRaises(ValueError):
            disconnect.snapshot(self.home, {'third': 'new'}, {})


if __name__ == '__main__':
    unittest.main()
