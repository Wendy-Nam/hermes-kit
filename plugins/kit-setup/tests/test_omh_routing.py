import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import omh_routing


class OmhRouting(unittest.TestCase):
    """The kit owns these patches, so they must survive an OMH update and never
    overwrite what the student declared."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name).resolve()
        self.src = self.data / 'kit-files'
        self.src.mkdir()
        for name in omh_routing.CODE_PATCHES:
            (self.src / name).write_text('# patched ' + name + '\n')
        (self.src / omh_routing.ENTITLEMENT).write_text(
            json.dumps({'schema_version': 'provider_entitlements/v1',
                        'providers': {'omniroute': 'gateway'},
                        'subscription_clis': [], 'excluded_providers': []}) + '\n')
        (self.data / 'plugins/omh').mkdir(parents=True)
        self.patcher = patch.object(omh_routing, 'SOURCE_DIR', self.src)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_absent_until_omh_installed(self):
        import shutil
        shutil.rmtree(self.data / 'plugins/omh')
        self.assertEqual(omh_routing.status(self.data)['status'], 'absent')
        self.assertEqual(omh_routing.apply(self.data)['status'], 'skipped')
        self.assertFalse((self.data / 'plugins/omh/route_readiness.py').exists())

    def test_apply_writes_all_three_and_the_entitlement(self):
        result = omh_routing.apply(self.data)
        self.assertEqual(sorted(result['changed']), sorted(omh_routing.CODE_PATCHES + (omh_routing.ENTITLEMENT,)))
        for name in omh_routing.CODE_PATCHES:
            self.assertEqual((self.data / 'plugins/omh' / name).read_text(), '# patched ' + name + '\n')
        self.assertTrue((self.data / '.omh/routing/providers.json').is_file())
        self.assertEqual(omh_routing.status(self.data)['status'], 'ok')

    def test_apply_is_idempotent(self):
        omh_routing.apply(self.data)
        self.assertEqual(omh_routing.apply(self.data)['changed'], [])
        self.assertEqual(omh_routing.status(self.data)['status'], 'ok')

    def test_upstream_overwrite_is_repaired(self):
        """The reason this module exists: `omh update` restores OMH's own copies."""
        omh_routing.apply(self.data)
        for name in omh_routing.CODE_PATCHES:
            (self.data / 'plugins/omh' / name).write_text('# upstream copy\n')
        self.assertEqual(omh_routing.status(self.data)['status'], 'pending')
        self.assertEqual(sorted(omh_routing.apply(self.data)['changed']), sorted(omh_routing.CODE_PATCHES))
        self.assertEqual(omh_routing.status(self.data)['status'], 'ok')

    def test_stale_bytecode_is_removed(self):
        cache = self.data / 'plugins/omh/__pycache__'
        cache.mkdir()
        stale = cache / 'route_readiness.cpython-311.pyc'
        stale.write_bytes(b'stale')
        omh_routing.apply(self.data)
        self.assertFalse(stale.exists())

    def test_students_own_entitlement_is_never_overwritten(self):
        omh_routing.apply(self.data)
        mine = {'schema_version': 'provider_entitlements/v1',
                'providers': {'omniroute': 'gateway', 'agy': 'subscription'},
                'subscription_clis': ['agy'], 'excluded_providers': []}
        target = self.data / '.omh/routing/providers.json'
        target.write_text(json.dumps(mine))
        self.assertEqual(omh_routing.status(self.data)['files'][omh_routing.ENTITLEMENT], 'student')
        self.assertEqual(omh_routing.apply(self.data)['changed'], [])
        self.assertEqual(json.loads(target.read_text()), mine)

    def test_excluded_provider_declaration_also_counts_as_students_own(self):
        omh_routing.apply(self.data)
        target = self.data / '.omh/routing/providers.json'
        target.write_text(json.dumps({'providers': {'omniroute': 'gateway'},
                                      'subscription_clis': [], 'excluded_providers': ['broken']}))
        self.assertEqual(omh_routing.status(self.data)['files'][omh_routing.ENTITLEMENT], 'student')
        omh_routing.apply(self.data)
        self.assertEqual(json.loads(target.read_text())['excluded_providers'], ['broken'])

    def test_unreadable_entitlement_is_left_alone(self):
        omh_routing.apply(self.data)
        target = self.data / '.omh/routing/providers.json'
        target.write_text('{ this is not json')
        self.assertEqual(omh_routing.status(self.data)['files'][omh_routing.ENTITLEMENT], 'student')
        self.assertEqual(omh_routing.apply(self.data)['changed'], [])
        self.assertEqual(target.read_text(), '{ this is not json')

    def test_originals_are_backed_up_once_and_rollback_restores_them(self):
        original = '# the copy OMH ships\n'
        for name in omh_routing.CODE_PATCHES:
            (self.data / 'plugins/omh' / name).write_text(original)
        omh_routing.apply(self.data)
        # A second upstream overwrite must not overwrite the backup with the patch.
        for name in omh_routing.CODE_PATCHES:
            (self.data / 'plugins/omh' / name).write_text('# drifted again\n')
        omh_routing.apply(self.data)
        omh_routing.rollback(self.data)
        for name in omh_routing.CODE_PATCHES:
            self.assertEqual((self.data / 'plugins/omh' / name).read_text(), original)

    def test_missing_sources_report_unavailable_rather_than_writing(self):
        for name in omh_routing.CODE_PATCHES:
            (self.src / name).unlink()
        self.assertEqual(omh_routing.status(self.data)['status'], 'unavailable')
        self.assertEqual(omh_routing.apply(self.data)['status'], 'skipped')

    def test_status_reports_drift_per_file(self):
        omh_routing.apply(self.data)
        (self.data / 'plugins/omh/public_free_routing.py').unlink()
        rows = omh_routing.status(self.data)['files']
        self.assertEqual(rows['public_free_routing.py'], 'missing')
        self.assertEqual(rows['route_readiness.py'], 'applied')

    def test_verify_reports_a_missing_gateway_instead_of_raising(self):
        omh_routing.apply(self.data)
        report = omh_routing.verify(self.data)
        self.assertIn(report['status'], ('unavailable', 'error', 'degraded'))
        self.assertIsInstance(report['message'], str)


if __name__ == '__main__':
    unittest.main()
