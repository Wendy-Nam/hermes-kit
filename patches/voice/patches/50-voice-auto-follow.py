#!/usr/bin/env python3
"""Voice auto-follow — when a configured user joins a configured voice channel the bot joins too,
binds the call to that voice channel's own text chat (voice_mode=all) and speaks a greeting; when
the user leaves (and nobody else is left) the bot leaves and turns voice mode off. Driven by the
gateway-local ``on_voice_state_update`` event, so it does not depend on slash-command sync.

Configure in .env (feature is inert until DISCORD_VOICE_AUTO_FOLLOW is set):
  DISCORD_VOICE_AUTO_FOLLOW="<user_id>:<voice_channel_id>[,<user_id>:<voice_channel_id>...]"
  DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL   bind the call to this text channel instead of the
                                           voice channel's built-in chat (optional)
  DISCORD_VOICE_AUTO_FOLLOW_GREETING       spoken on join   (default "I'm here. Go ahead.")
  DISCORD_VOICE_AUTO_FOLLOW_JOINED         text on join, {channel} placeholder ("" = silent)
  DISCORD_VOICE_AUTO_FOLLOW_LEFT           text on leave                      ("" = silent)

Touches: plugins/platforms/discord/adapter.py, gateway/run_voice.py, gateway/run_startup.py.
"""
from _patchlib import replace_blocks, root_from_args

ADAPTER_EDITS = [
    ('''            @self._client.event
            async def on_voice_state_update(member, before, after):
                """Track voice channel join/leave events."""
                bot_guild_ids = set(adapter_self._voice_clients.keys())''',
     '''            @self._client.event
            async def on_voice_state_update(member, before, after):
                """Track voice channel join/leave events."""
                # Voice auto-follow: hand the configured users' join/leave to the gateway callback
                # BEFORE the bot_guild_ids guard (the bot is not connected yet when it must join).
                _af_cb = getattr(adapter_self, "_voice_auto_follow_callback", None)
                if _af_cb is not None and member != adapter_self._client.user:
                    if member.id in _voice_auto_follow_users():
                        asyncio.create_task(_af_cb(member, before, after))
                bot_guild_ids = set(adapter_self._voice_clients.keys())'''),
]
ADAPTER_APPEND = '''

def _voice_auto_follow_users() -> dict:
    """DISCORD_VOICE_AUTO_FOLLOW="uid:chid,uid2:chid2" -> {int(uid): {int(chid), ...}}.

    Empty/unset disables the feature. Malformed tokens are ignored."""
    pairs: dict[int, set[int]] = {}
    for tok in os.environ.get("DISCORD_VOICE_AUTO_FOLLOW", "").split(","):
        tok = tok.strip()
        if ":" not in tok:
            continue
        uid, chid = tok.split(":", 1)
        try:
            pairs.setdefault(int(uid.strip()), set()).add(int(chid.strip()))
        except ValueError:
            continue
    return pairs
'''

RUN_VOICE_METHODS = '''
    # ------------------------------------------------------------------
    # Voice auto-follow (hermes-voice-patches): follow configured users into their voice channel,
    # bind the call to that channel's own text chat, leave + voice off when they leave.
    # ------------------------------------------------------------------
    def _wire_voice_auto_follow(self) -> None:
        """Install the auto-follow callback on the Discord adapter once (startup)."""
        adapter = self.adapters.get(Platform.DISCORD)
        if adapter is None or not hasattr(adapter, "join_voice_channel"):
            return
        if getattr(adapter, "_voice_auto_follow_wired", False):
            return
        adapter._voice_auto_follow_callback = functools.partial(
            self._handle_voice_auto_follow, adapter=adapter)
        adapter._voice_auto_follow_wired = True
        logger.info("Voice auto-follow armed (Discord)")

    async def _handle_voice_auto_follow(self, member, before, after, *, adapter) -> None:
        """Translate the configured user's join/leave/move into call on/off."""
        try:
            pairs = {}
            try:
                from plugins.platforms.discord import adapter as _adapter_mod
                pairs = _adapter_mod._voice_auto_follow_users()
            except Exception:
                pass
            if not pairs:
                return
            targets = pairs.get(member.id) or set()
            guild_id = member.guild.id
            joined_channel = after.channel if after.channel else None
            left_channel = before.channel if before.channel else None
            joined_target = bool(joined_channel) and joined_channel.id in targets
            left_target = bool(left_channel) and left_channel.id in targets
            in_voice = hasattr(adapter, "is_in_voice_channel") and adapter.is_in_voice_channel(guild_id)
            if joined_target and not in_voice:
                await self._voice_auto_follow_join(adapter, guild_id, member, joined_channel)
            elif left_target and not joined_target and in_voice:
                await self._voice_auto_follow_leave(adapter, guild_id)
        except Exception as e:
            logger.warning("Voice auto-follow failed: %s", e, exc_info=True)

    async def _voice_auto_follow_join(self, adapter, guild_id: int, member, channel) -> None:
        """join + voice_mode=all. Binding: existing /voice channel binding > env override > the
        voice channel's own text chat (Discord text-in-voice shares the voice channel id)."""
        self._bind_voice_input_callback(adapter)
        if hasattr(adapter, "_on_voice_disconnect"):
            adapter._on_voice_disconnect = functools.partial(
                self._handle_voice_timeout_cleanup, adapter=adapter)
        chat_id = str(
            adapter._voice_text_channels.get(guild_id)
            or os.environ.get("DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL")
            or channel.id)
        if hasattr(adapter, "_voice_mode_getter"):
            profile = getattr(adapter, "_owner_profile", None)
            adapter._voice_mode_getter = lambda cid: self._voice_mode.get(
                self._voice_key(Platform.DISCORD, str(cid), profile=profile), "off")
        success = await adapter.join_voice_channel(channel, text_channel_id=int(chat_id))
        if not success:
            logger.warning("Voice auto-follow: join failed (guild %d)", guild_id)
            adapter._voice_input_callback = None
            return
        self._apply_voice_mode(adapter, self._voice_key(Platform.DISCORD, chat_id), chat_id, "all")
        logger.info("Voice auto-follow: joined %s (user %s)", channel.name, member.id)
        greeting = os.environ.get("DISCORD_VOICE_AUTO_FOLLOW_GREETING", "I'm here. Go ahead.")
        if greeting:
            try:
                tts_paths, _ = await adapter._synthesize_auto_tts(greeting)
                if tts_paths:
                    asyncio.create_task(adapter.play_in_voice_channel(guild_id, tts_paths[0]))
            except Exception as e:
                logger.debug("Auto-follow greeting playback skipped: %s", e)
        joined = os.environ.get("DISCORD_VOICE_AUTO_FOLLOW_JOINED",
                                "\\u260e\\ufe0f Auto-joined **{channel}**. I'll leave when you do.")
        if joined:
            with suppress(Exception):
                channel_obj = adapter._client.get_channel(int(chat_id))
                if channel_obj:
                    await channel_obj.send(joined.replace("{channel}", channel.name))

    async def _voice_auto_follow_leave(self, adapter, guild_id: int) -> None:
        """leave + voice_mode=off. Stays if anyone other than the bot is still in the channel."""
        vc = adapter._voice_clients.get(guild_id)
        try:
            ch = getattr(vc, "channel", None) if vc else None
            if ch is not None and any(m != adapter._client.user for m in ch.members):
                return
        except Exception:
            pass
        chat_id = str(adapter._voice_text_channels.get(guild_id)
                      or os.environ.get("DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL")
                      or getattr(getattr(vc, "channel", None), "id", None) or guild_id)
        try:
            await adapter.leave_voice_channel(guild_id)
        except Exception as e:
            logger.warning("Voice auto-follow: leave error: %s", e)
        self._apply_voice_mode(adapter, self._voice_key(Platform.DISCORD, chat_id), chat_id, "off")
        if hasattr(adapter, "_voice_input_callback"):
            adapter._voice_input_callback = None
        logger.info("Voice auto-follow: left guild %d", guild_id)
        left = os.environ.get("DISCORD_VOICE_AUTO_FOLLOW_LEFT",
                              "\\U0001f4de Call ended. I'll follow you in again next time.")
        if left:
            with suppress(Exception):
                channel_obj = adapter._client.get_channel(int(chat_id))
                if channel_obj:
                    await channel_obj.send(left)
'''

if __name__ == "__main__":
    root = root_from_args()
    replace_blocks(root / "plugins/platforms/discord/adapter.py",
                   ADAPTER_EDITS + [("# ---- END PLUGIN-COMPAT ----\n", "# ---- END PLUGIN-COMPAT ----\n" + ADAPTER_APPEND)],
                   "_voice_auto_follow_callback")
    replace_blocks(root / "gateway/run_voice.py", [(
        "    async def _handle_voice_channel_input(",
        RUN_VOICE_METHODS + "\n    async def _handle_voice_channel_input(")], "_wire_voice_auto_follow")
    replace_blocks(root / "gateway/run_startup.py", [(
        "        self._wire_teams_pipeline_runtime()\n",
        "        self._wire_teams_pipeline_runtime()\n        self._wire_voice_auto_follow()\n")],
        "_wire_voice_auto_follow()")
