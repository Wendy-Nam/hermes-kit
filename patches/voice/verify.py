#!/usr/bin/env python3
"""Behavioural checks against a patched install (stdlib only, no pytest in the Docker image).
Read-only; run as the Hermes user:  python verify.py [--root /opt/hermes]"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ap = argparse.ArgumentParser(); ap.add_argument("--root", default="/opt/hermes"); a = ap.parse_args()
sys.path.insert(0, a.root)

from gateway.config import Platform                      # noqa: E402
from gateway.platforms.event import MessageEvent, MessageType  # noqa: E402
from gateway.run_voice import GatewayVoiceMixin           # noqa: E402
from gateway.session import SessionSource                 # noqa: E402
from tools.tts_tool import DEFAULT_PROVIDER, _get_provider, text_to_speech_tool  # noqa: E402

# 1. PR #118048: disabled spellings -> "none", tool refuses, gateway voice reply skipped
for v in ["none", "off", "disabled", "false", "no", " None ", False]:
    assert _get_provider({"provider": v}) == "none", v
assert _get_provider({}) == DEFAULT_PROVIDER and _get_provider({"provider": "elevenlabs"}) == "elevenlabs"
r = json.loads(text_to_speech_tool(text="Hello world", provider="off"))
assert r.get("success") is False and "disabled" in r.get("error", ""), r
with tempfile.TemporaryDirectory() as d:
    Path(d, "config.yaml").write_text("tts:\n  provider: off\n", encoding="utf-8")
    prev = os.environ.get("HERMES_HOME"); os.environ["HERMES_HOME"] = d
    try:
        import hermes_cli.config as hc; hc._LOAD_CONFIG_CACHE.clear()
        m = object.__new__(GatewayVoiceMixin)
        m._voice_mode = {"discord:chat": "all"}; m._voice_key_for_source = lambda s: "discord:chat"
        m._adapter_for_source = lambda s: SimpleNamespace(_should_auto_tts_for_chat=lambda c: True)
        ev = MessageEvent(text="hi", source=SessionSource(platform=Platform.DISCORD, chat_id="chat", chat_type="dm"))
        assert m._should_send_voice_reply(ev, "Hello world", []) is False
    finally:
        os.environ.pop("HERMES_HOME", None) if prev is None else os.environ.__setitem__("HERMES_HOME", prev)
        hc._LOAD_CONFIG_CACHE.clear()
print("ok  10-tts-provider-none")

# 2. /call handler present and importable
from gateway.slash_commands import GatewaySlashCommandsMixin as _S  # noqa: E402
assert hasattr(_S, "_handle_call_command"), "/call handler missing"
print("ok  40-call-slash")

# 3. auto-follow binds the call to the voice channel's own text chat (not a fixed channel)
class _Adapter:
    def __init__(self):
        self._voice_text_channels, self._voice_clients = {}, {}
        self._voice_mode_getter = self._on_voice_disconnect = self._voice_input_callback = None
        self._client = SimpleNamespace(get_channel=lambda _cid: None); self.join_kwargs = None
    def is_in_voice_channel(self, g): return False
    async def join_voice_channel(self, channel, **kw): self.join_kwargs = kw; return True
    async def _synthesize_auto_tts(self, text): return [], None

class _Runner(GatewayVoiceMixin):
    def __init__(self, ad): self._voice_mode, self.applied, self.adapters = {}, [], {Platform.DISCORD: ad}
    def _apply_voice_mode(self, adapter, key, chat_id, mode): self.applied.append((chat_id, mode))

os.environ.pop("DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL", None)
ad = _Adapter(); rn = _Runner(ad)
ch = SimpleNamespace(id=222, name="Phone booth", guild=SimpleNamespace(id=1))
asyncio.run(rn._voice_auto_follow_join(ad, 1, SimpleNamespace(id=111), ch))
assert ad.join_kwargs.get("text_channel_id") == 222 and rn.applied == [("222", "all")], (ad.join_kwargs, rn.applied)
assert rn._should_send_voice_reply.__doc__ and hasattr(rn, "_wire_voice_auto_follow")
print("ok  50-voice-auto-follow")
print("verify: all checks passed")
