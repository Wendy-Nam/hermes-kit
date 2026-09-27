"""Public image discovery must not mistake unpublished/prerelease tags for latest."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updates

A = 'sha256:' + 'a' * 64
B = 'sha256:' + 'b' * 64

class RegistryTests(unittest.TestCase):
    def registry(self, tags=None, digests=None, pages=None, latest=None):
        tags = ['0.21.2-k2'] if tags is None else tags
        digests = {'0.21.2-k2': A} if digests is None else digests
        latest = iter(latest or [A, A])
        calls = []
        def request(url, *, token=None, method='GET', deadline):
            calls.append((url, token, method))
            self.assertGreater(deadline, 0)
            if '/token?' in url:
                self.assertIsNone(token)
                return b'{"token":"anonymous-fixture"}', {}
            self.assertEqual(token, 'anonymous-fixture')
            if '/manifests/' in url:
                self.assertEqual(method, 'HEAD')
                tag = url.rsplit('/', 1)[1]
                return b'', {'docker-content-digest': next(latest) if tag == 'latest' else digests[tag]}
            if pages:
                return pages(url)
            return json.dumps({'name': updates.REPOSITORY, 'tags': tags}).encode(), {}
        return request, calls

    def test_selects_latest_digest_not_highest_or_prerelease(self):
        request, calls = self.registry(['0.21.2-k2', '0.21.2-k3', '99.0.0-rc1', 'latest'],
                                       {'0.21.2-k2': A, '0.21.2-k3': B})
        with patch.object(updates, '_request', side_effect=request):
            self.assertEqual(updates.latest_release(), ('0.21.2-k2', ''))
        self.assertFalse(any('rc1' in call[0] for call in calls))
        self.assertFalse(any('api.github.com' in call[0] for call in calls))

    def test_no_matching_version_is_unknown(self):
        request, _ = self.registry(['0.21.2-k3'], {'0.21.2-k3': B})
        with patch.object(updates, '_request', side_effect=request):
            self.assertIsNone(updates.latest_release()[0])

    def test_latest_race_is_unknown(self):
        request, _ = self.registry(latest=[A, B])
        with patch.object(updates, '_request', side_effect=request):
            self.assertIsNone(updates.latest_release()[0])

    def test_missing_digest_is_unknown(self):
        request, _ = self.registry(latest=[''])
        with patch.object(updates, '_request', side_effect=request):
            self.assertIsNone(updates.latest_release()[0])

    def test_follows_bounded_same_registry_pagination(self):
        def pages(url):
            if 'last=' in url:
                return json.dumps({'name':updates.REPOSITORY, 'tags':['0.21.2-k2']}).encode(), {}
            return json.dumps({'name':updates.REPOSITORY, 'tags':['0.21.2-k1']}).encode(), {
                'link':'<' + updates.TAGS_PATH + '?n=100&last=0.21.2-k1>; rel="next"'}
        request, _ = self.registry(pages=pages)
        with patch.object(updates, '_request', side_effect=request):
            self.assertEqual(updates.latest_release()[0], '0.21.2-k2')

    def test_unsafe_links_and_page_limit_fail_closed(self):
        for link in ['<https://evil.example/tags>; rel="next"',
                     '<' + updates.TAGS_PATH + '?n=100>; rel="next"']:
            def pages(url):
                return json.dumps({'name':updates.REPOSITORY,'tags':['0.21.2-k2']}).encode(), {'link':link}
            request, calls = self.registry(pages=pages)
            with patch.object(updates, '_request', side_effect=request):
                self.assertIsNone(updates.latest_release()[0])
            self.assertLessEqual(len(calls), updates.MAX_PAGES + 2)
            self.assertFalse(any('evil.example' in c[0] for c in calls))

    def test_unique_pagination_limit(self):
        count = 0
        def pages(url):
            nonlocal count
            count += 1
            return json.dumps({'name':updates.REPOSITORY,'tags':[]}).encode(), {
                'link':'<' + updates.TAGS_PATH + '?last=' + str(count) + '>; rel="next"'}
        request, _ = self.registry(pages=pages)
        with patch.object(updates, '_request', side_effect=request):
            self.assertIsNone(updates.latest_release()[0])
        self.assertEqual(count, updates.MAX_PAGES)

    def test_manifest_probe_limit(self):
        tags = ['0.21.2-k' + str(i) for i in range(20)]
        request, calls = self.registry(tags, {tag:B for tag in tags})
        with patch.object(updates, '_request', side_effect=request):
            self.assertIsNone(updates.latest_release()[0])
        self.assertEqual(sum(c[2] == 'HEAD' for c in calls), 1 + updates.MAX_MANIFESTS)

    def test_http_error_returns_safe_reason(self):
        error = urllib.error.HTTPError('fixture', 403, 'private response', {}, None)
        with patch.object(updates, '_request', side_effect=error):
            tag, reason = updates.latest_release()
        self.assertIsNone(tag)
        self.assertIn('403', reason)
        self.assertNotIn('private response', reason)

    def test_expired_deadline_makes_no_request(self):
        with patch.object(updates.time, 'monotonic', return_value=100), patch.object(updates.urllib.request, 'build_opener') as opener:
            with self.assertRaises(TimeoutError):
                updates._request('https://ghcr.io/token', deadline=99)
            opener.assert_not_called()

    def test_check_api_preserved(self):
        request, _ = self.registry()
        with patch.object(updates, '_request', side_effect=request):
            available, tag, message = updates.check('0.21.2-k1')
        self.assertTrue(available)
        self.assertEqual(tag, '0.21.2-k2')
        self.assertIn('Redeploy', message)

if __name__ == '__main__':
    unittest.main()
