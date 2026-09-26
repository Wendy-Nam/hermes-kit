#!/usr/bin/env python3
"""NousResearch/hermes-agent PR #118048 — ``tts.provider`` set to none/off/disabled/false/no (or the
YAML bool ``False``) must mean *no TTS*. On v0.21.x it silently became the Edge default, so a chat
with ``voice.auto_tts: true`` or ``/voice tts`` got an edge-tts voice message in front of every reply.

Touches: tools/tts_tool.py, gateway/run_voice.py, hermes_cli/config_defaults.py (comment only).
"""
from _patchlib import replace_blocks, root_from_args

TTS_EDITS = [
    ('DEFAULT_PROVIDER = "edge"\n',
     'DEFAULT_PROVIDER = "edge"\n'
     '# ``tts.provider`` spellings that mean "no TTS". PyYAML reads a bare ``off``/``false``/``no`` as the\n'
     '# bool False, so that arrives here as ``False``, not a string. All resolve to ``"none"`` (the STT\n'
     '# convention) so a disabled provider never reaches the "unknown name -> Edge default" branch.\n'
     '_DISABLED_PROVIDERS = frozenset({"none", "off", "disabled", "false", "no"})\n'),
    ('def _get_provider(tts_config: Dict[str, Any]) -> str:\n',
     'def _normalize_provider(value: Any) -> str:\n'
     '    """Lowercased provider name; ``""`` when unset. Disabled spellings (see ``_DISABLED_PROVIDERS``)\n'
     '    and YAML\'s bool ``False`` become ``"none"``."""\n'
     '    name = "none" if value is False else str(value or "").lower().strip()\n'
     '    return "none" if name in _DISABLED_PROVIDERS else name\n'
     '\n'
     '\n'
     'def _get_provider(tts_config: Dict[str, Any]) -> str:\n'),
    ('    provider = (tts_config.get("provider") or DEFAULT_PROVIDER).lower().strip()\n',
     '    provider = _normalize_provider(tts_config.get("provider")) or DEFAULT_PROVIDER\n'),
    ('    return tts_config, provider.lower().strip() if provider else _get_provider(tts_config)\n',
     '    return tts_config, _normalize_provider(provider) or _get_provider(tts_config)\n'),
    ('    tts_config, provider = _apply_call_overrides(_load_tts_config(), speed, provider)\n',
     '    tts_config, provider = _apply_call_overrides(_load_tts_config(), speed, provider)\n'
     '    if provider == "none":\n'
     '        return tool_error("TTS is disabled (tts.provider: none)", success=False)\n'),
]

RUN_VOICE_EDITS = [
    ('        """False when voice_mode is off for this chat, the response is empty/an error, the agent\n'
     '        already called text_to_speech this turn, or voice input + base adapter auto-TTS handled it\n'
     '        — UNLESS streaming consumed the response (already_sent): then the runner must do it."""\n'
     '        if not response or response.startswith("Error:"):\n'
     '            return False\n',
     '        """False when voice_mode is off for this chat, TTS is disabled (``tts.provider: none``),\n'
     '        the response is empty/an error, the agent already called text_to_speech this turn, or voice\n'
     '        input + base adapter auto-TTS handled it — UNLESS streaming consumed the response\n'
     '        (already_sent): then the runner must do it."""\n'
     '        if not response or response.startswith("Error:"):\n'
     '            return False\n'
     '        from tools.tts_tool import _get_provider, _load_tts_config\n'
     '        if _get_provider(_load_tts_config()) == "none":\n'
     '            return False\n'),
]

DEFAULTS_EDITS = [
    ('        # "gemini" | "deepinfra" | "neutts" (local) | "kittentts" (local) | "piper" (local)\n'
     '        "provider": "edge",\n',
     '        # "gemini" | "deepinfra" | "neutts" (local) | "kittentts" (local) | "piper" (local)\n'
     '        # | "none" (TTS off: no text_to_speech tool, no gateway auto voice replies)\n'
     '        "provider": "edge",\n'),
]

if __name__ == "__main__":
    root = root_from_args()
    replace_blocks(root / "tools/tts_tool.py", TTS_EDITS, "_DISABLED_PROVIDERS")
    replace_blocks(root / "gateway/run_voice.py", RUN_VOICE_EDITS, '_get_provider(_load_tts_config()) == "none"')
    replace_blocks(root / "hermes_cli/config_defaults.py", DEFAULTS_EDITS, '# | "none" (TTS off', optional=True)
