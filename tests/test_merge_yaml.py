import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location("merge_yaml", Path(__file__).parent.parent / "bin" / "merge_yaml.py")
merge_yaml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_yaml)


class MergeYaml(unittest.TestCase):
    def test_dicts_merge_recursively_lists_and_scalars_replace(self):
        base = {"agent": {"max_turns": 90, "keep": 1}, "plugins": {"enabled": ["a"]}, "x": 1}
        over = {"agent": {"max_turns": 20}, "plugins": {"enabled": ["b", "c"]}, "y": 2}
        self.assertEqual(
            merge_yaml.deep_merge(base, over),
            {"agent": {"max_turns": 20, "keep": 1}, "plugins": {"enabled": ["b", "c"]}, "x": 1, "y": 2},
        )

    def test_merge_file_in_place_keeps_mode(self):
        d = Path(tempfile.mkdtemp())
        target, overlay = d / "config.yaml", d / "overlay.yaml"
        target.write_text("# comment\nagent:\n  max_turns: 90\n  keep: 1\n")
        os.chmod(target, 0o640)
        overlay.write_text("agent:\n  max_turns: 20\ntimezone: Asia/Seoul\n")
        merge_yaml.merge_file(target, overlay)
        self.assertEqual(yaml.safe_load(target.read_text()),
                         {"agent": {"max_turns": 20, "keep": 1}, "timezone": "Asia/Seoul"})
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o640)

    def test_non_mapping_overlay_is_rejected(self):
        d = Path(tempfile.mkdtemp())
        (d / "c.yaml").write_text("a: 1\n")
        (d / "o.yaml").write_text("- not\n- a mapping\n")
        with self.assertRaises(ValueError):
            merge_yaml.merge_file(d / "c.yaml", d / "o.yaml")
        self.assertEqual((d / "c.yaml").read_text(), "a: 1\n")


if __name__ == "__main__":
    unittest.main()
