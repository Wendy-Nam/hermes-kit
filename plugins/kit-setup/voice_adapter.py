"""Lightweight runtime voice adapter for Hermes Agent (v0.21.x - v0.23.x+).

Provides all five hermes-voice-patches capabilities at runtime via plugin hooks
and class-level method wrapping, so an unpatched stock Hermes container gets:
  10  tts.provider: none / off / disabled / false / no (and YAML bool False)
  20  ElevenLabs VoiceSettings forwarding (stability, style, speed, similarity_boost, use_speaker_boost)
  30  Voice-channel delivery ownership & double-TTS suppression (_voice_reply_sent)
  40  /call slash command (join user's VC + voice_mode=all + greeting; /call leave; /call status)
  50  Voice auto-follow (DISCORD_VOICE_AUTO_FOLLOW="uid:chid,..." event listener)

Idempotent: safe to load alongside build-time patches/voice/ or on a clean upstream container.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import functools
import inspect
import logging
import os
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger("gateway.run")

_DISABLED_PROVIDERS = frozenset({"none", "off", "disabled", "false", "no"})


def _normalize_provider(value: Any) -> str:
    name = "none" if value is False else str(value or "").lower().strip()
    return "none" if name in _DISABLED_PROVIDERS else name


def _voice_auto_follow_users() -> dict[int, set[int]]:
    """DISCORD_VOICE_AUTO_FOLLOW="uid:chid,uid2:chid2" -> {int(uid): {int(chid), ...}}."""
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


def install_tts_patches() -> bool:
    """10-tts-provider-none & 20-elevenlabs-voice-settings runtime adapter."""
    changed = False
    try:
        import tools.tts_tool as tm
        if not hasattr(tm, "_DISABLED_PROVIDERS"):
            tm._DISABLED_PROVIDERS = _DISABLED_PROVIDERS
            tm._normalize_provider = _normalize_provider
            orig_get_provider = tm._get_provider

            def _get_provider(tts_config: dict[str, Any]) -> str:
                norm = _normalize_provider((tts_config or {}).get("provider"))
                if norm == "none":
                    return "none"
                return orig_get_provider(tts_config)

            tm._get_provider = _get_provider
            orig_tool = tm.text_to_speech_tool
            sig = inspect.signature(orig_tool)

            @functools.wraps(orig_tool)
            def _wrapped_tts_tool(*args, **kwargs):
                bound = sig.bind_partial(*args, **kwargs)
                prov = bound.arguments.get("provider")
                norm = _normalize_provider(prov) if prov is not None else _get_provider(tm._load_tts_config())
                if norm == "none":
                    err_fn = getattr(tm, "tool_error", None) or getattr(tm, "_error_json", None)
                    if callable(err_fn):
                        try:
                            return err_fn("TTS is disabled (tts.provider: none)", success=False)
                        except TypeError:
                            return err_fn("TTS is disabled (tts.provider: none)")
                    import json
                    return json.dumps({"success": False, "error": "TTS is disabled (tts.provider: none)"})
                return orig_tool(*args, **kwargs)

            tm.text_to_speech_tool = _wrapped_tts_tool
            changed = True
    except Exception as exc:
        logger.debug("voice_adapter: tts_tool patch skipped: %s", exc)

    try:
        import tools.tts_tool_providers as tp
        gen_el = getattr(tp, "_generate_elevenlabs", None)
        if callable(gen_el) and "VoiceSettings" not in inspect.getsource(gen_el):
            orig_import_el = getattr(tp, "_import_elevenlabs", None)
            if callable(orig_import_el) and not getattr(tp, "_kit_el_patched", False):
                def _wrapped_import_el():
                    cls = orig_import_el()
                    if getattr(cls, "_kit_vs_wrapped", False):
                        return cls
                    orig_init = cls.__init__

                    @functools.wraps(orig_init)
                    def _init(self, *a, **kw):
                        orig_init(self, *a, **kw)
                        tts_obj = getattr(self, "text_to_speech", None)
                        orig_conv = getattr(tts_obj, "convert", None)
                        if callable(orig_conv) and not getattr(orig_conv, "_kit_vs", False):
                            def _convert(**ckw):
                                if "voice_settings" not in ckw:
                                    try:
                                        from tools.tts_tool import _load_tts_config
                                        from elevenlabs.types.voice_settings import VoiceSettings
                                        el_cfg = (_load_tts_config() or {}).get("elevenlabs") or {}
                                        vs_kw = {}
                                        for key, src_keys, clamp in (
                                            ("stability", ("stability",), None),
                                            ("style", ("style_exaggeration", "style"), None),
                                            ("speed", ("speed",), (0.7, 1.3)),
                                            ("similarity_boost", ("similarity_boost",), None),
                                        ):
                                            raw = next((el_cfg[k] for k in src_keys if el_cfg.get(k) is not None), None)
                                            if raw is not None:
                                                val = float(raw)
                                                vs_kw[key] = max(clamp[0], min(clamp[1], val)) if clamp else val
                                        vs_kw.setdefault("similarity_boost", 0.75)
                                        vs_kw["use_speaker_boost"] = bool(el_cfg.get("use_speaker_boost", True))
                                        ckw["voice_settings"] = VoiceSettings(**vs_kw)
                                    except Exception:
                                        pass
                                return orig_conv(**ckw)
                            _convert._kit_vs = True
                            tts_obj.convert = _convert
                    cls.__init__ = _init
                    cls._kit_vs_wrapped = True
                    return cls
                tp._import_elevenlabs = _wrapped_import_el
                tp._kit_el_patched = True
                changed = True
    except Exception as exc:
        logger.debug("voice_adapter: elevenlabs patch skipped: %s", exc)
    return changed


def install_gateway_voice_patches() -> bool:
    """30-voice-channel-delivery, 40-call-slash, 50-voice-auto-follow runtime adapter."""
    changed = False
    try:
        from gateway.config import Platform
        from gateway.run_voice import GatewayVoiceMixin
        from tools.tts_tool import _get_provider, _load_tts_config

        # 10 + 30: _should_send_voice_reply & _send_voice_reply
        orig_should = GatewayVoiceMixin._should_send_voice_reply
        if "tts.provider: none" not in (orig_should.__doc__ or ""):
            def _should_send_voice_reply(self, event, response, agent_messages, already_sent=False):
                """False when voice_mode is off for this chat, TTS is disabled (``tts.provider: none``),
                the response is empty/an error, the agent already called text_to_speech this turn, or voice
                input + base adapter auto-TTS handled it — UNLESS streaming consumed the response
                (already_sent): then the runner must do it."""
                if not response or response.startswith("Error:"):
                    return False
                if _get_provider(_load_tts_config()) == "none":
                    return False
                guild_id = self._get_guild_id(event)
                adapter_fn = getattr(self, "_delivery_adapter_for", None) or getattr(self, "_adapter_for_source", None)
                adapter = adapter_fn(event.source) if callable(adapter_fn) else None
                is_in_vc = bool(guild_id and adapter and hasattr(adapter, "is_in_voice_channel")
                                and adapter.is_in_voice_channel(guild_id))
                if is_in_vc:
                    return orig_should(self, event, response, agent_messages, already_sent=True)
                return orig_should(self, event, response, agent_messages, already_sent=already_sent)

            GatewayVoiceMixin._should_send_voice_reply = _should_send_voice_reply
            changed = True

        orig_deliver = GatewayVoiceMixin._deliver_voice_reply
        if not getattr(orig_deliver, "_kit_voice_flagged", False):
            @functools.wraps(orig_deliver)
            async def _deliver_voice_reply(self, event, audio_paths):
                await orig_deliver(self, event, audio_paths)
                event._voice_reply_sent = True

            _deliver_voice_reply._kit_voice_flagged = True
            GatewayVoiceMixin._deliver_voice_reply = _deliver_voice_reply
            changed = True

        # Guard BasePlatformAdapter._wants_auto_tts against double-speaking when _voice_reply_sent is True
        with suppress(Exception):
            from gateway.platforms.base import BasePlatformAdapter
            orig_wants = getattr(BasePlatformAdapter, "_wants_auto_tts", None)
            if callable(orig_wants) and not getattr(orig_wants, "_kit_voice_guarded", False):
                @functools.wraps(orig_wants)
                def _wants_auto_tts(self, event, *a, **kw):
                    if getattr(event, "_voice_reply_sent", False):
                        return False
                    return orig_wants(self, event, *a, **kw)

                _wants_auto_tts._kit_voice_guarded = True
                BasePlatformAdapter._wants_auto_tts = _wants_auto_tts

        # 50: auto-follow methods on GatewayVoiceMixin
        if not hasattr(GatewayVoiceMixin, "_wire_voice_auto_follow"):
            def _wire_voice_auto_follow(self) -> None:
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
                try:
                    pairs = _voice_auto_follow_users()
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
                                        "\u260e\ufe0f Auto-joined **{channel}**. I'll leave when you do.")
                if joined:
                    with suppress(Exception):
                        channel_obj = adapter._client.get_channel(int(chat_id))
                        if channel_obj:
                            await channel_obj.send(joined.replace("{channel}", channel.name))

            async def _voice_auto_follow_leave(self, adapter, guild_id: int) -> None:
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
                                      "\U0001f4de Call ended. I'll follow you in again next time.")
                if left:
                    with suppress(Exception):
                        channel_obj = adapter._client.get_channel(int(chat_id))
                        if channel_obj:
                            await channel_obj.send(left)

            GatewayVoiceMixin._wire_voice_auto_follow = _wire_voice_auto_follow
            GatewayVoiceMixin._handle_voice_auto_follow = _handle_voice_auto_follow
            GatewayVoiceMixin._voice_auto_follow_join = _voice_auto_follow_join
            GatewayVoiceMixin._voice_auto_follow_leave = _voice_auto_follow_leave
            changed = True

        # 40: _handle_call_command on GatewaySlashCommandsMixin
        from gateway.slash_commands import GatewaySlashCommandsMixin
        if not hasattr(GatewaySlashCommandsMixin, "_handle_call_command"):
            async def _handle_call_command(self, event) -> str:
                """One-touch /call: join the user's voice channel and enable call mode (voice_mode=all)."""
                from functools import partial
                args = event.get_command_args().strip().lower()
                if args in {"leave", "off", "end", "stop", "disconnect"}:
                    return await self._handle_voice_channel_leave(event)
                if args == "status":
                    return await self._handle_voice_command(event)

                adapter_fn = getattr(self, "_delivery_adapter_for", None) or getattr(self, "_adapter_for_source", None)
                adapter = adapter_fn(event.source) if callable(adapter_fn) else None
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
                    "\u260e\ufe0f Connected to **{channel}**. Call mode is on; `/call leave` to hang up.")
                return joined.replace("{channel}", voice_channel.name)

            GatewaySlashCommandsMixin._handle_call_command = _handle_call_command
            changed = True

        with suppress(Exception):
            import plugins.platforms.discord.adapter as discord_adapter_mod
            if not hasattr(discord_adapter_mod, "_voice_auto_follow_users"):
                discord_adapter_mod._voice_auto_follow_users = _voice_auto_follow_users
    except Exception as exc:
        logger.debug("voice_adapter: gateway patch skipped: %s", exc)
    return changed


def wire_discord_voice(bot, adapter) -> None:
    """Attach the auto-follow listener and /call command to a live Discord bot & adapter."""
    install_tts_patches()
    install_gateway_voice_patches()
    runner = getattr(adapter, "gateway_runner", None)
    if runner is not None and hasattr(runner, "_wire_voice_auto_follow"):
        with suppress(Exception):
            runner._wire_voice_auto_follow()

    if not getattr(bot, "_kit_voice_auto_follow_listener", False):
        async def _on_voice_state_update(member, before, after):
            if getattr(bot, "user", None) and member == bot.user:
                return
            pairs = _voice_auto_follow_users()
            if member.id not in pairs:
                return
            cb = getattr(adapter, "_voice_auto_follow_callback", None)
            if cb is None and getattr(adapter, "gateway_runner", None) is not None:
                r = adapter.gateway_runner
                if hasattr(r, "_handle_voice_auto_follow"):
                    cb = functools.partial(r._handle_voice_auto_follow, adapter=adapter)
                    adapter._voice_auto_follow_callback = cb
            if cb is not None:
                asyncio.create_task(cb(member, before, after))

        # Only add listener if build-time patch isn't already invoking _voice_auto_follow_callback in adapter.py
        import plugins.platforms.discord.adapter as discord_adapter_mod
        src = ""
        with suppress(Exception):
            src = inspect.getsource(discord_adapter_mod)
        if "_voice_auto_follow_callback" not in src:
            bot.add_listener(_on_voice_state_update, "on_voice_state_update")
        bot._kit_voice_auto_follow_listener = True


def install_all() -> dict[str, bool]:
    """Install all runtime voice patches idempotently and report availability."""
    install_tts_patches()
    install_gateway_voice_patches()
    return {
        "tts": True,
        "gateway": True,
    }
