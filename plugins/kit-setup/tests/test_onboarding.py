"""The 선택 기능 안내 screen: what an optional key buys, and whether it is on.

No Discord import on purpose. The text is shown in the gateway, but every claim it makes comes
from state on disk, so it can be tested here — and a claim that could not be true is caught here
rather than in front of a student.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import env_store
import onboarding
import syncthing_setup as sync


def _config(*ids):
    devices = "".join(f"<device><deviceID>{i}</deviceID></device>" for i in ids)
    return f"<configuration><gui><apikey>k</apikey></gui>{devices}</configuration>"


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
