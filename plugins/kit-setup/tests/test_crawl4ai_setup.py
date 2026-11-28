import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import crawl4ai_setup as c


def _browser(root, name, complete=True):
    path = Path(root) / name
    path.mkdir()
    if complete:
        (path / 'INSTALLATION_COMPLETE').write_text('')


class ImageBrowserTest(unittest.TestCase):
    def test_pins_move_together(self):
        self.assertTrue(c.CRAWL4AI.startswith('crawl4ai=='))
        self.assertTrue(c.PLAYWRIGHT.startswith('playwright=='))
        self.assertRegex(c.REVISION, r'^chromium-\d+$')

    def test_accepts_the_pinned_revision(self):
        with tempfile.TemporaryDirectory() as root:
            _browser(root, c.REVISION)
            _browser(root, 'ffmpeg-9.0.1-linux-x64')
            self.assertIsNone(c.check_image_browser(root))
            self.assertEqual(c.image_revisions(root), [c.REVISION])

    def test_names_both_revisions_on_a_base_bump(self):
        with tempfile.TemporaryDirectory() as root:
            _browser(root, 'chromium-9999')
            _browser(root, 'chromium_headless_shell-9999')
            message = c.check_image_browser(root)
            self.assertIn('chromium-9999', message)
            self.assertIn(c.REVISION, message)

    def test_incomplete_or_missing_store_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            _browser(root, c.REVISION, complete=False)
            self.assertIn('없음', c.check_image_browser(root))
            self.assertIn('없음', c.check_image_browser(Path(root) / 'missing'))

    def test_reads_the_installed_playwright_revision(self):
        with tempfile.TemporaryDirectory() as venv:
            package = Path(venv) / 'lib/python3.14/site-packages/playwright/driver/package'
            package.mkdir(parents=True)
            (package / 'browsers.json').write_text(json.dumps({'browsers': [
                {'name': 'chromium', 'revision': '1248'},
                {'name': 'chromium-headless-shell', 'revision': '1248'}]}))
            self.assertEqual(c.playwright_revision(venv), 'chromium-1248')


if __name__ == '__main__':
    unittest.main()
