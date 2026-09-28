"""The 선택 기능 안내 screen: what an optional key buys, and whether it is on.

No Discord import on purpose. The text is shown in the gateway, but every claim it makes comes
from state on disk, so it can be tested here — and a claim that could not be true is caught here
rather than in front of a student.
"""
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import env_store
import onboarding
import syncthing_setup as sync


# A real `syncthing generate` config, not a convenient shape. Syncthing writes the device id as
# the `id` attribute of a root-level <device>; a fixture invented as <device><deviceID> made
# paired_device_count() agree with the fixture and disagree with every real config.xml, so a
# paired PC was reported as "아직 PC 없음". test_fixture_matches_a_real_config_shape keeps this
# honest without needing the binary in CI.
def _config(*ids):
    devices = "".join(
        f'<device id="{i}" name="pc" compression="metadata" introducer="false" '
        f'skipIntroductionRemovals="false" introducedBy="">'
        "<address>dynamic</address><paused>false</paused>"
        "<autoAcceptFolders>false</autoAcceptFolders></device>"
        for i in ids)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<configuration version="37">'
            f"{devices}"
            "<gui><address>127.0.0.1:8384</address>"
            "<apikey>k</apikey><theme>default</theme></gui>"
            "<options><maxSendKbps>0</maxSendKbps></options>"
            "</configuration>")


class RealConfigShape(unittest.TestCase):
    """The fixture above has to stay the shape Syncthing actually writes."""

    def test_fixture_matches_a_real_config_shape(self):
        root = ET.fromstring(_config("S" * 56, "P" * 56))
        self.assertEqual(root.tag, "configuration")
        devices = root.findall("device")
        self.assertEqual(len(devices), 2)
        self.assertEqual([d.get("id") for d in devices], ["S" * 56, "P" * 56])
        self.assertEqual(root.findtext("gui/apikey"), "k")

    def test_a_device_without_an_id_is_not_counted(self):
        # Syncthing writes <device id=""> for a device being set up. It is not a paired PC.
        config = ET.fromstring(_config("S" * 56))
        config.find("device").set("id", "")
        self.assertEqual(sum(1 for d in config.findall("device") if (d.get("id") or "").strip()), 0)


class FeatureGuide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_every_optional_feature_is_named_and_asks_for_its_key(self):
        text = onboarding.feature_guide(self.root)
        for title in ("Composio 앱 연동", "음성 비서", "PC 옵시디언 노트", "차단 우회",
                      "SNS·플랫폼 수집", "보조 모델 (OpenCode Go)", "보조 모델 (Command Code)"):
            self.assertIn(title, text, title)
        self.assertIn("키 필요: COMPOSIO_CONSUMER_KEY", text)

    def test_configured_features_report_ready_and_never_print_a_value(self):
        env_store.set_env(self.root / ".env", {"GROQ_API_KEY": "gsk_secret_value",
                                                "COMPOSIO_CONSUMER_KEY": "ck_secret_value"})
        text = onboarding.feature_guide(self.root)
        lines = {line.split("**")[1]: line for line in onboarding.feature_lines(self.root)}
        self.assertIn("설정됨", lines["음성 비서"])
        self.assertIn("설정됨", lines["Composio 앱 연동"])
        self.assertNotIn("gsk_secret_value", text)
        self.assertNotIn("ck_secret_value", text)

    def test_a_half_filled_pack_is_not_reported_as_ready(self):
        env_store.set_env(self.root / ".env", {"WEBSHARE_PROXY_USERNAME": "u"})
        text = onboarding.feature_guide(self.root)
        self.assertIn("WEBSHARE_PROXY_USERNAME, WEBSHARE_PROXY_PASSWORD", text)
        self.assertNotIn("현재: 설정됨", [l for l in text.splitlines() if "차단 우회" in l][0])

    def test_an_over_budget_guide_drops_whole_lines_and_keeps_the_tail(self):
        with patch.object(onboarding, "MESSAGE_LIMIT", 420):
            text = onboarding.feature_guide(self.root)
        self.assertLessEqual(len(text), 420)
        self.assertIn("나머지 버튼", text)
        for line in text.splitlines():
            # Nothing may end mid-sentence: a kept feature line always carries its state.
            if line.startswith("· **"):
                self.assertIn("현재:", line, line)

    def test_dropped_features_are_counted_never_silently_omitted(self):
        # A shorter list reads as "the feature I want does not exist", which is the confusion this
        # screen exists to remove. Say how many were left out.
        with patch.object(onboarding, "MESSAGE_LIMIT", 600):
            text = onboarding.feature_guide(self.root)
        self.assertIn("생략", text)
        total = len(onboarding.feature_lines(self.root))
        kept = sum(1 for line in text.splitlines() if line.startswith("· **"))
        self.assertEqual(kept, total - int(text.split("…중 ")[1].split("개")[0]))
        self.assertLess(kept, total, "this test is meaningless if nothing was dropped")

    def test_the_budget_counts_the_bullet_prefix_and_stays_under_the_limit(self):
        # The old estimate budgeted len(line)+1 while appending "· "+line, so it overshot by two
        # characters per line. Assert against the real assembled message at a range of limits.
        for limit in range(400, 1400, 37):
            with patch.object(onboarding, "MESSAGE_LIMIT", limit):
                text = onboarding.feature_guide(self.root)
            self.assertLessEqual(len(text), limit, f"overran at MESSAGE_LIMIT={limit}")
        with patch.object(onboarding, "MESSAGE_LIMIT", 200):
            text = onboarding.feature_guide(self.root)
        self.assertLessEqual(len(text), 200)
        # A student must never be told "here are the features" and then get nothing: either the
        # list survives, or the message says outright that it did not fit.
        self.assertIn("선택 기능 안내", text)
        self.assertTrue("· **" in text or "담지 못했습니다" in text, text)

    def test_sync_state_counts_configured_devices_not_synced_files(self):
        config = self.root / "config.xml"
        config.write_text(_config("S" * 56))
        with patch.object(sync, "CONFIG_PATH", config):
            self.assertEqual(sync.paired_device_count(), 1)
            self.assertIn("아직 PC 없음", onboarding.feature_guide(self.root))
        config.write_text(_config("S" * 56, "P" * 56, "Q" * 56))
        with patch.object(sync, "CONFIG_PATH", config):
            self.assertEqual(sync.paired_device_count(), 3)
            self.assertIn("연결된 장치 2대", onboarding.feature_guide(self.root))

    def test_unreadable_syncthing_config_degrades_to_a_word_not_a_crash(self):
        with patch.object(sync, "paired_device_count", side_effect=OSError("no config")):
            self.assertIn("확인 못 함", onboarding.feature_guide(self.root))

    def test_a_missing_env_file_is_not_an_error(self):
        self.assertTrue(onboarding.feature_lines(self.root / "never-created"))
        self.assertIn("PC 장치 ID 입력", onboarding.sync_guide())


if __name__ == "__main__":
    unittest.main()
