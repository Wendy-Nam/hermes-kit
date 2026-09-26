#!/usr/bin/env python3
"""``/call`` — one slash command that joins the user's current voice channel, turns voice mode to
``all`` for the invoking text chat, and speaks a greeting. ``/call leave`` / ``/call status`` map to
the existing ``/voice`` handlers. Stock v0.21.x needs ``/voice channel`` + ``/voice tts`` for the same.

Texts come from .env (all optional):
  DISCORD_CALL_GREETING   spoken on join           (default: "Connected. I'm listening.")
  DISCORD_CALL_JOINED     text reply on join       ({channel} placeholder)

Touches: hermes_cli/commands.py, plugins/platforms/discord/adapter.py, gateway/run_busy.py,
gateway/slash_commands.py.
"""
from _patchlib import replace_blocks, root_from_args

HANDLER = '''
    async def _handle_call_command(self, event: MessageEvent) -> str:
        """One-touch /call: join the user's voice channel and enable call mode (voice_mode=all)."""
        from functools import partial  # slash_commands.py does not import functools at module level
        args = event.get_command_args().strip().lower()
        if args in {"leave", "off", "end", "stop", "disconnect"}:
            return await self._handle_voice_channel_leave(event)
        if args == "status":
            return await self._handle_voice_command(event)

        adapter = self._adapter_for_source(event.source)
        if not hasattr(adapter, "join_voice_channel"):
            return "Voice calls are not supported on this platform."
        guild_id = self._get_guild_id(event)
        if not guild_id:
            return "This command only works in a Discord server."
        voice_channel = await adapter.get_user_voice_channel(guild_id, event.source.user_id)
        if not voice_channel:
            return "Join a voice channel first, then run /call."

        self._bind_voice_input_callback(adapter)
        voice_profile = self._adapter_profile_for_source(event.source)
        if hasattr(adapter, "_on_voice_disconnect"):
            adapter._on_voice_disconnect = partial(self._handle_voice_timeout_cleanup, adapter=adapter)
        if hasattr(adapter, "_voice_mode_getter"):
            adapter._voice_mode_getter = lambda chat_id: self._voice_mode.get(
                self._voice_key(Platform.DISCORD, str(chat_id), profile=voice_profile), "off")
        try:
            success = await adapter.join_voice_channel(voice_channel)
        except Exception as e:
            logger.warning("Failed to join voice channel: %s", e)
            adapter._voice_input_callback = None
            return f"Failed to join voice channel: {e}"
        if not success:
            adapter._voice_input_callback = None
            return "Failed to join voice channel. Check bot permissions (Connect + Speak)."

        adapter._voice_text_channels[guild_id] = int(event.source.chat_id)
        if hasattr(adapter, "_voice_sources"):
            adapter._voice_sources[guild_id] = event.source.to_dict()
        self._apply_voice_mode(adapter, self._voice_key_for_source(event.source),
                               event.source.chat_id, "all")

        greeting = os.environ.get("DISCORD_CALL_GREETING", "Connected. I'm listening.")
        if greeting:
            try:
                tts_paths, _ = await adapter._synthesize_auto_tts(greeting)
                if tts_paths:
                    asyncio.create_task(adapter.play_in_voice_channel(guild_id, tts_paths[0]))
            except Exception as e:
                logger.warning("Greeting playback failed: %s", e)

        joined = os.environ.get(
            "DISCORD_CALL_JOINED",
            "\\u260e\\ufe0f Connected to **{channel}**. Call mode is on; `/call leave` to hang up.")
        return joined.replace("{channel}", voice_channel.name)
'''

if __name__ == "__main__":
    root = root_from_args()
    replace_blocks(root / "hermes_cli/commands.py", [(
        '    CommandDef("voice", "Toggle voice mode", "Configuration",',
        '    CommandDef("call", "Start voice call mode in voice channel", "Actions",\n'
        '               args_hint="[leave|status]", subcommands=("leave", "status"), desktop="composer-voice"),\n'
        '    CommandDef("voice", "Toggle voice mode", "Configuration",')], 'CommandDef("call"')
    replace_blocks(root / "plugins/platforms/discord/adapter.py", [(
        '    ("voice", "Toggle voice reply mode",',
        '    ("call", "Join voice channel and start voice call mode immediately",\n'
        '     (("action", str, "", "Action: leave to disconnect, or leave empty to start call",\n'
        '       (("leave — leave voice call", "leave"), ("status — check call status", "status"))),),\n'
        '     "/call {action}", None),\n'
        '    ("voice", "Toggle voice reply mode",')], '("call", "Join voice channel')
    replace_blocks(root / "gateway/run_busy.py", [(
        '        "loop", "refine", "review", "voice",',
        '        "loop", "refine", "review", "voice", "call",')], '"voice", "call",')
    replace_blocks(root / "gateway/slash_commands.py", [(
        "    async def _handle_voice_command(self, event: MessageEvent) -> str:",
        HANDLER + "\n    async def _handle_voice_command(self, event: MessageEvent) -> str:")],
        "async def _handle_call_command")
