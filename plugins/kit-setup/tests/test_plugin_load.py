"""The plugin must load the way Hermes loads it: as a package, without our folder on sys.path.

Every other test inserts the plugin folder into sys.path, which hid k4-k10's
"No module named 'discord_ui'" — /setup and /doctor never registered on a real install.
"""
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent.parent

LOADER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "hermes_plugins.kit_setup", sys.argv[1] + "/__init__.py", submodule_search_locations=[sys.argv[1]])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
got = []
class Ctx:
    def register_platform_handler(self, platform, fn): got.append((platform, fn.__name__))
mod.register(Ctx())
assert got == [("discord", "build")], got
"""


class PluginLoad(unittest.TestCase):
    def test_registers_through_the_package_loader(self):
        r = subprocess.run([sys.executable, "-I", "-c", LOADER, str(HERE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class WebshareCheck(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HERE))
        import importlib
        import validators
        self.v = importlib.reload(validators)   # test_core swaps _get without restoring it

    def test_tests_the_rotating_username_and_names_a_407(self):
        seen = []

        def fake(url, headers, proxy=None):
            seen.append(proxy)
            return 407, b""
        with patch.object(self.v, "_get", fake):
            ok, msg = self.v.webshare_credentials(" abc ", "pw")
        self.assertFalse(ok)
        self.assertIn("abc-rotate:pw@p.webshare.io", seen[0])
        self.assertIn("거부", msg)

    def test_tunnel_407_is_not_reported_as_no_internet(self):
        err = urllib.error.URLError(OSError("Tunnel connection failed: 407 Proxy Authentication Required"))
        with patch("urllib.request.OpenerDirector.open", side_effect=err):
            self.assertEqual(self.v._get("https://x", {}, proxy="http://u:p@h:1")[0], 407)


if __name__ == "__main__":
    unittest.main()
