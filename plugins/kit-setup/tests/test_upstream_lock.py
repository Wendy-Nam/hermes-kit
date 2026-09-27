"""Concurrent UI edits must survive both upstream setup and its rollback."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config_store
import upstream_omh


class UpstreamConfigurationLock(unittest.TestCase):
    def test_concurrent_ui_write_waits_for_success_or_rollback(self):
        for fails in (False, True):
            with self.subTest(setup_fails=fails), tempfile.TemporaryDirectory() as directory:
                data = Path(directory)
                config = data / 'config.yaml'
                config.write_text('model:\n  default: original\n')
                setup_entered = threading.Event()
                finish_setup = threading.Event()
                writer_started = threading.Event()
                writer_finished = threading.Event()
                results, errors = [], []

                def run(argv, env):
                    if 'setup' not in argv:
                        return ''
                    config.write_text('model:\n  default: original\nplugins:\n  enabled: [omh]\n')
                    (data / '.omh').mkdir()
                    (data / 'plugins/omh').mkdir(parents=True)
                    setup_entered.set()
                    if not finish_setup.wait(5):
                        raise TimeoutError('test coordination timed out')
                    if fails:
                        raise RuntimeError('simulated setup failure')
                    return json.dumps({'ok': True, 'plugin_distribution': {'import_smoke': True}})

                def install():
                    try:
                        results.append(upstream_omh.install_upstream_omh(data,
                            routing={'model': 'selected', 'provider': 'openai'}, host_version='0.21.2'))
                    except Exception as exc:
                        errors.append(exc)

                def change_model():
                    writer_started.set()
                    try:
                        config_store.write(data, {'model.default': 'new-user-choice'}, remember=False)
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        writer_finished.set()

                with patch.object(upstream_omh.urllib.request, 'urlopen', return_value=io.BytesIO(b'archive')), \
                     patch.object(upstream_omh, '_source', side_effect=lambda blob, destination: destination), \
                     patch.object(upstream_omh, '_run', side_effect=run):
                    installer = threading.Thread(target=install, daemon=True)
                    writer = threading.Thread(target=change_model, daemon=True)
                    installer.start()
                    try:
                        self.assertTrue(setup_entered.wait(5))
                        writer.start()
                        self.assertTrue(writer_started.wait(5))
                        self.assertFalse(writer_finished.wait(0.05), 'UI write raced active upstream setup')
                    finally:
                        finish_setup.set()
                        installer.join(5)
                        if writer.ident is not None:
                            writer.join(5)
                    self.assertFalse(installer.is_alive())
                    self.assertFalse(writer.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(results[0]['status'], 'failed' if fails else 'installed')
                self.assertEqual(config_store.read(data)['model']['default'], 'new-user-choice')


if __name__ == '__main__':
    unittest.main()
