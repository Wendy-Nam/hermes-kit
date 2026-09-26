#!/usr/bin/env python3
"""ElevenLabs provider only: pass ``VoiceSettings`` (stability / style / speed / similarity_boost /
use_speaker_boost) from ``tts.elevenlabs.*`` in config.yaml. Stock v0.21.x only forwards voice_id and
model_id, so those keys are silently ignored.

Inert unless ``tts.provider: elevenlabs`` — the changed code is inside the ElevenLabs synth function
and the SDK import is local to it, so edge/openai/… users can apply it or skip it (``apply.sh --skip 20``).

Touches: tools/tts_tool_providers.py.
"""
from _patchlib import replace_blocks, root_from_args

OLD = '''    audio_generator = client.text_to_speech.convert(
        text=text, voice_id=el_config.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID),
        model_id=el_config.get("model_id", DEFAULT_ELEVENLABS_MODEL_ID),
        output_format="opus_48000_64" if output_path.endswith(".ogg") else "mp3_44100_128")'''

NEW = '''    try:
        from elevenlabs.types.voice_settings import VoiceSettings
    except ImportError:  # SDK without VoiceSettings: keep stock behaviour rather than fail the call
        VoiceSettings = None
    convert_kwargs = {
        "text": text,
        "voice_id": el_config.get("voice_id", DEFAULT_ELEVENLABS_VOICE_ID),
        "model_id": el_config.get("model_id", DEFAULT_ELEVENLABS_MODEL_ID),
        "output_format": "opus_48000_64" if output_path.endswith(".ogg") else "mp3_44100_128",
    }
    # tts.elevenlabs.{stability,style|style_exaggeration,speed,similarity_boost,use_speaker_boost}
    vs_kwargs = {}
    for key, src_keys, clamp in (
        ("stability", ("stability",), None),
        ("style", ("style_exaggeration", "style"), None),
        ("speed", ("speed",), (0.7, 1.3)),
        ("similarity_boost", ("similarity_boost",), None),
    ):
        raw = next((el_config[k] for k in src_keys if el_config.get(k) is not None), None)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        vs_kwargs[key] = max(clamp[0], min(clamp[1], val)) if clamp else val
    vs_kwargs.setdefault("similarity_boost", 0.75)
    vs_kwargs["use_speaker_boost"] = bool(el_config.get("use_speaker_boost", True))
    if VoiceSettings is not None:
        convert_kwargs["voice_settings"] = VoiceSettings(**vs_kwargs)
    audio_generator = client.text_to_speech.convert(**convert_kwargs)'''

if __name__ == "__main__":
    replace_blocks(root_from_args() / "tools/tts_tool_providers.py", [(OLD, NEW)], "VoiceSettings(**vs_kwargs)")
