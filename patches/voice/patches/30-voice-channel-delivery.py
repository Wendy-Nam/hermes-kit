#!/usr/bin/env python3
"""While the bot is connected to a Discord voice channel, the gateway runner must always deliver the
spoken reply there (stock v0.21.x dedups it away when the input was voice and streaming did not send
it), and a delivered voice reply is flagged on the event so the base adapter's auto-TTS does not
speak it a second time.

Touches: gateway/run_voice.py.
"""
from _patchlib import replace_blocks, root_from_args

EDITS = [
    ('''        # Dedup: base adapter auto-TTS already handles voice input (play_tts plays in VC when
        # connected) — unless streaming consumed the text (already_sent): then the runner must.
        return not (is_voice_input and not already_sent)''',
     '''        # Connected to a voice channel: the runner owns delivery (play_in_voice_channel).
        guild_id = self._get_guild_id(event)
        is_in_vc = bool(guild_id and adapter and hasattr(adapter, "is_in_voice_channel")
                        and adapter.is_in_voice_channel(guild_id))
        if is_in_vc:
            return True
        # Dedup: base adapter auto-TTS already handles voice input (play_tts plays in VC when
        # connected) — unless streaming consumed the text (already_sent): then the runner must.
        return not (is_voice_input and not already_sent)'''),
    ('''            actual_paths = paths
            await self._deliver_voice_reply(event, actual_paths)''',
     '''            actual_paths = paths
            await self._deliver_voice_reply(event, actual_paths)
            event._voice_reply_sent = True'''),
]

if __name__ == "__main__":
    replace_blocks(root_from_args() / "gateway/run_voice.py", EDITS, "event._voice_reply_sent = True")
