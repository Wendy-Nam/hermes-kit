"""Build patch compatibility, drift rejection, and actual default CLI application."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PATCH = Path(__file__).resolve().parents[1] / 'patches/core/patch-cron-iteration-outcome.py'
spec = importlib.util.spec_from_file_location('cron_outcome', PATCH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SOURCE = 'def fixture(max_iteration_summary):\n' + module.OLD

class CronOutcomePatchTests(unittest.TestCase):
    def test_patch_preserves_partial_report_and_compiles(self):
        updated = module.patch(SOURCE)
        compile(updated, '<scheduler fixture>', 'exec')
        self.assertIn('raise RuntimeError(', updated)
        self.assertIn('Partial report: {final_response_text}', updated)
        self.assertEqual(updated, module.patch(updated))

    def test_drift_duplicate_or_partial_patch_fails(self):
        for source in ('def changed(): pass', SOURCE + SOURCE, '# ' + module.MARKER):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                module.patch(source)

    def test_default_cli_applies_and_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'cron/scheduler.py'
            target.parent.mkdir()
            target.write_text(SOURCE)
            target.chmod(0o640)
            command = [sys.executable, str(PATCH), '--root', directory]
            subprocess.run(command + ['--check'], check=True, capture_output=True)
            self.assertEqual(target.read_text(), SOURCE)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(target.read_text(), module.patch(SOURCE))
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            backup = list(target.parent.glob('*.bak-*-iteration-outcome'))
            self.assertEqual(len(backup), 1)
            self.assertEqual(backup[0].read_text(), SOURCE)
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(len(list(target.parent.glob('*.bak-*'))), 1)

if __name__ == '__main__':
    unittest.main()
