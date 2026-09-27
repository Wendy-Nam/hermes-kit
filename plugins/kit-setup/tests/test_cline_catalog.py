import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cline_catalog as c


def row(mid='vendor/free', **prices):
    return {'id': mid, 'pricing': {'prompt': '0', 'completion': '0', **prices}}


def snapshot(*rows):
    return c.make_snapshot({'data': list(rows or [row()])}, 1000)


class ClineCatalogTests(unittest.TestCase):
    def test_explicit_zero_requires_no_suffix(self):
        result = c.inspect_catalog(snapshot(row('no-suffix')), now=1000)
        self.assertEqual(result['no-suffix']['status'], 'zero_advertised')

    def test_free_suffix_does_not_override_positive_price(self):
        self.assertEqual(c.price_status(row('model:free', completion='0.000001')), 'positive')

    def test_missing_prompt_or_completion_is_unknown(self):
        for prices in ({}, {'prompt': 0}, {'completion': 0}):
            self.assertEqual(c.price_status({'pricing': prices}), 'unknown')

    def test_any_extra_price_including_cache_blocks_zero(self):
        for field in ('input_cache_read', 'input_cache_write', 'request', 'image'):
            self.assertEqual(c.price_status(row(**{field: '1e-15'})), 'positive')

    def test_cache_absence_is_explicitly_unknown(self):
        evidence = c.inspect_catalog(snapshot(), now=1000)['vendor/free']
        self.assertEqual(evidence['cache_price_status'], 'unknown')
        self.assertEqual(c.cache_price_status(row(input_cache_read=0)), 'unknown')
        self.assertEqual(c.cache_price_status(row(input_cache_read=0, input_cache_write=0)), 'zero_advertised')

    def test_invalid_prices_fail_closed(self):
        for value in (None, True, False, 'NaN', 'Infinity', '-1', {}, [], '', 'not a price'):
            with self.subTest(value=value):
                self.assertEqual(c.price_status(row(prompt=value)), 'unknown')

    def test_duplicate_conflict_cannot_admit_paid(self):
        for rows in ([row(), row(completion=1)], [row(completion=1), row()]):
            self.assertEqual(c.inspect_catalog(snapshot(*rows), now=1000)['vendor/free']['status'], 'positive')
        self.assertEqual(c.inspect_catalog(snapshot(row(), row(completion=None)), now=1000)['vendor/free']['status'], 'unknown')

    def test_stale_future_and_invalid_timestamps_rejected(self):
        for now in (999, 1901, float('nan'), True):
            with self.subTest(now=now), self.assertRaises(c.CatalogError):
                c.inspect_catalog(snapshot(), now=now)
        self.assertTrue(c.inspect_catalog(snapshot(), now=1900))
        for checked in (None, True, float('inf')):
            with self.assertRaises(c.CatalogError):
                c.make_snapshot({'data': [row()]}, checked)

    def test_maximum_age_cannot_be_disabled(self):
        for age in (0, -1, 3601, float('inf'), True, '900'):
            with self.assertRaises(c.CatalogError):
                c.inspect_catalog(snapshot(), now=1000, max_age=age)

    def test_proposal_preserves_free_other_providers_and_metadata(self):
        models = [{'model': 'cline/vendor/free', 'weight': 3, 'id': 'original'},
                  'cline/vendor/paid', 'cline/vendor/unknown', 'other/vendor/paid']
        before = copy.deepcopy(models)
        result = c.propose_removals(models, snapshot(row(), row('vendor/paid', prompt=1)), now=1000)
        self.assertEqual(result['retained'], [models[0], models[3]])
        self.assertEqual([r['reason'] for r in result['proposed_removals']], ['positive', 'unknown'])
        self.assertFalse(result['applied'])
        result['retained'][0]['weight'] = 90
        self.assertEqual(models, before)

    def test_fetch_is_fixed_public_bounded_unauthenticated(self):
        class Opener:
            def open(self, req, timeout):
                self.req, self.timeout = req, timeout
                return io.BytesIO(json.dumps({'data': [row()]}).encode())
        opener = Opener()
        with patch.object(c.urllib.request, 'build_opener', return_value=opener), patch.object(c.time, 'time', return_value=1000):
            value = c.fetch_catalog()
        self.assertEqual(opener.req.full_url, c.CATALOG_URL)
        self.assertEqual(opener.req.method, 'GET') if hasattr(opener.req, 'method') else self.assertEqual(opener.req.get_method(), 'GET')
        self.assertIsNone(opener.req.get_header('Authorization'))
        self.assertEqual(value['checked_at'], 1000)
        self.assertLessEqual(opener.timeout, 20)

    def test_fetch_failure_scrubs_message_and_refuses_redirect(self):
        with patch.object(c.urllib.request, 'build_opener', side_effect=RuntimeError('private-secret')):
            with self.assertRaises(c.CatalogError) as caught:
                c.fetch_catalog()
        self.assertNotIn('private-secret', str(caught.exception))
        with self.assertRaises(c.CatalogError):
            c._NoRedirect().redirect_request(None, None, None, None, None, 'https://other.example')

    def test_malformed_oversize_and_unknown_source_rejected(self):
        for data in ({}, {'data': []}, {'data': [None]}, {'data': [{'id': ''}]}):
            with self.assertRaises(c.CatalogError):
                c.make_snapshot(data, 1000)
        bad = snapshot(); bad['source'] = 'https://other.example'
        with self.assertRaises(c.CatalogError):
            c.inspect_catalog(bad, now=1000)
        with patch.object(c, 'MAX_RESPONSE_BYTES', 5), patch.object(c.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b'123456')
            with self.assertRaises(c.CatalogError):
                c.fetch_catalog()

    def test_stale_proposal_does_not_suggest_deleting_everything(self):
        with self.assertRaises(c.CatalogError):
            c.propose_removals(['cline/vendor/free'], snapshot(), now=999999)

    def test_native_cline_provider_fields_classified(self):
        for field in ('provider', 'providerId'):
            models = [{field: 'cline', 'model': 'vendor/paid'},
                      {field: 'cline', 'model': 'vendor/free'},
                      {field: 'cline', 'model': 'vendor/missing'}]
            result = c.propose_removals(models, snapshot(row(), row('vendor/paid', completion=1)), now=1000)
            self.assertEqual(result['retained'], [models[1]])
            self.assertEqual([x['reason'] for x in result['proposed_removals']], ['positive', 'unknown'])

    def test_matching_provider_metadata_and_routed_cline_supported(self):
        models = [{'provider': 'cline', 'providerId': 'cline', 'model': 'cline/vendor/free'}]
        self.assertEqual(c.propose_removals(models, snapshot(), now=1000)['retained'], models)

    def test_conflicting_provider_metadata_rejected(self):
        entries = [{'provider': 'other', 'model': 'cline/vendor/free'},
                   {'providerId': 'other', 'model': 'cline/vendor/free'},
                   {'provider': 'cline', 'providerId': 'other', 'model': 'vendor/free'},
                   {'provider': 'other', 'providerId': 'cline', 'model': 'vendor/free'}]
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(c.CatalogError):
                c.propose_removals([entry], snapshot(), now=1000)

    def test_noncline_native_entries_preserved(self):
        models = [{'provider': 'other', 'model': 'vendor/paid', 'weight': 4},
                  {'providerId': 'other', 'model': 'other/vendor/free'}, 'other/vendor/paid']
        before = copy.deepcopy(models)
        result = c.propose_removals(models, snapshot(row('vendor/paid', completion=1)), now=1000)
        self.assertEqual(result['retained'], models)
        self.assertEqual(result['proposed_removals'], [])
        result['retained'][0]['weight'] = 5
        self.assertEqual(models, before)

    def test_native_model_namespace_is_not_inferred_as_provider(self):
        models = [{'provider': 'cline', 'model': 'openrouter/free'},
                  {'provider': 'cline', 'model': 'other/unknown'}]
        result = c.propose_removals(models, snapshot(row('openrouter/free')), now=1000)
        self.assertEqual(result['retained'], [models[0]])
        self.assertEqual(result['proposed_removals'][0]['reason'], 'unknown')

    def test_invalid_provider_and_model_metadata_rejected(self):
        entries = [{'provider': '', 'model': 'vendor/free'},
                   {'providerId': 1, 'model': 'vendor/free'},
                   {'provider': 'cline', 'model': 'cline/'},
                   {'provider': 'cline', 'model': ' vendor/free'}]
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(c.CatalogError):
                c.propose_removals([entry], snapshot(), now=1000)


if __name__ == '__main__':
    unittest.main()
