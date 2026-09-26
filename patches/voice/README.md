# hermes-voice-patches

Discord voice-call and TTS fixes for [Hermes Agent](https://github.com/NousResearch/hermes-agent)
**v0.21.2** (upstream tag `v2026.9.11`), applied as idempotent source patches. One command installs all
of them; each one compiles the result before touching the original and leaves a `.bak-<ts>-hvp`.
Works with any TTS provider Hermes supports (edge is the free default); nothing here needs ElevenLabs.

| # | Patch | What it fixes / adds | Files |
|---|-------|----------------------|-------|
| 10 | `tts-provider-none` | Upstream [PR #118048](https://github.com/NousResearch/hermes-agent/pull/118048): `tts.provider: none` (also `off`/`disabled`/`false`/`no`, incl. the YAML bool) really disables TTS — no more edge-tts voice message in front of every reply | `tools/tts_tool.py`, `gateway/run_voice.py`, `hermes_cli/config_defaults.py` |
| 20 | `elevenlabs-voice-settings` | *(ElevenLabs users only — inert for every other provider, or `--skip 20`)* `tts.elevenlabs.{stability,style,speed,similarity_boost,use_speaker_boost}` are forwarded as `VoiceSettings`; stock ignores them | `tools/tts_tool_providers.py` |
| 30 | `voice-channel-delivery` | While the bot is in a voice channel the runner always plays the reply there, and never double-speaks it through auto-TTS | `gateway/run_voice.py` |
| 40 | `call-slash` | `/call` = join my voice channel + voice mode `all` + spoken greeting; `/call leave`, `/call status` | `hermes_cli/commands.py`, `gateway/run_busy.py`, `gateway/slash_commands.py`, `plugins/platforms/discord/adapter.py` |
| 50 | `voice-auto-follow` | The bot follows configured users into a voice channel and leaves (voice off) when they leave — event-driven, independent of Discord slash-command sync | `plugins/platforms/discord/adapter.py`, `gateway/run_voice.py`, `gateway/run_startup.py` |

## Install

```sh
# Docker (/opt/hermes is a root-owned image layer, data volume at /opt/data)
docker cp hermes-voice-patches <container>:/opt/data/hermes-voice-patches
docker exec -u 0 <container> sh /opt/data/hermes-voice-patches/apply.sh          # add --skip 20 if you don't use ElevenLabs
docker exec -u 0 <container> sh -c 'kill -TERM $(pgrep -f "hermes gateway run")'   # s6 restarts it

# Bare install (git checkout / pip)
sh apply.sh --root ~/hermes-agent            # add --python <venv python> if it is not <root>/.venv
hermes gateway restart
```

`apply.sh` runs the patches in order, then `check.py` (compile + import gate). A patch whose anchor
does not match your Hermes version aborts **before writing** and tells you which file — that is the
signal you are not on v0.21.2 (see *Other versions*). Re-running is a no-op ("already patched").

Optional behaviour check as the Hermes user (no pytest needed):

```sh
python verify.py --root /opt/hermes
```

### Docker: surviving container re-creation

`/opt/hermes` is an image layer, so the patches vanish when the container is re-created. Keep the
directory on the data volume and re-run `apply.sh` from a boot hook (`/etc/cont-init.d/`), or bake
it into a derived image:

```Dockerfile
FROM <your hermes-agent image>          # e.g. the v0.21.2 build you already run
COPY hermes-voice-patches /opt/hermes-voice-patches
RUN sh /opt/hermes-voice-patches/apply.sh --root /opt/hermes
```

## Configuration

`config.yaml` — only two keys matter; everything else is stock Hermes TTS/STT config.

```yaml
tts:
  provider: edge              # free default. openai / gemini / mistral / piper / … work the same;
                              # "none" switches TTS off entirely (patch 10)
voice:
  auto_tts: false             # keep false: `true` makes every NEW chat/thread speak by default,
                              # which is what looks like "TTS stays on after I left the call"
```

Optional, ElevenLabs only (patch 20):

```yaml
tts:
  provider: elevenlabs
  elevenlabs:
    voice_id: <voice>
    model_id: eleven_multilingual_v2
    stability: 0.5            # all optional
    style: 0.3
    speed: 1.15               # clamped to 0.7–1.3 by ElevenLabs
    similarity_boost: 0.75
```

`.env` (all optional except the first line if you want auto-follow)

```sh
DISCORD_VOICE_AUTO_FOLLOW="<discord_user_id>:<voice_channel_id>"   # comma-separate more pairs
DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL=                            # default: the voice channel's own text chat
DISCORD_VOICE_AUTO_FOLLOW_GREETING="I'm here. Go ahead."           # spoken on join
DISCORD_VOICE_AUTO_FOLLOW_JOINED="☎️ Auto-joined **{channel}**. I'll leave when you do."   # "" = silent
DISCORD_VOICE_AUTO_FOLLOW_LEFT="📞 Call ended. I'll follow you in again next time."         # "" = silent
DISCORD_CALL_GREETING="Connected. I'm listening."                  # /call
DISCORD_CALL_JOINED="☎️ Connected to **{channel}**. Call mode is on; `/call leave` to hang up."
```

How a call is bound: the voice session (transcripts in, spoken replies out) lives in **one text
chat**. `/call` binds it to the chat you typed the command in; auto-follow binds it to the voice
channel's built-in text chat (Discord text-in-voice shares the voice channel id) unless you set
`DISCORD_VOICE_AUTO_FOLLOW_TEXT_CHANNEL`. Leaving turns voice mode `off` for that chat only, so keep
`voice.auto_tts: false` or other chats will keep speaking.

## Rollback

```sh
sh apply.sh rollback --root /opt/hermes     # restores the earliest .bak-*-hvp of each file, then re-runs check.py
```

## Other versions

Anchors are exact source blocks from v0.21.2. On v0.21.3/0.21.4 most still match, but run
`apply.sh` and read the first failure; PR #118048 (patch 10) may already be merged upstream, in which
case that patch reports "already patched" and the rest still apply. Patches are plain Python with the
old/new blocks side by side — adjusting an anchor is a one-line edit.

## Layout

```
apply.sh          install / rollback entry point (root for Docker)
check.py          compile + import gate (read-only)
verify.py         behaviour checks, stdlib only (read-only)
patches/_patchlib.py            shared replace-compile-backup-swap helper
patches/10-tts-provider-none.py …  one file per fix, ordered
```

No IDs, tokens, names or persona text ship in this bundle — every user/channel/greeting comes from your own `.env`.

License: same as Hermes Agent (MIT). Patch 10 is upstream PR #118048.
