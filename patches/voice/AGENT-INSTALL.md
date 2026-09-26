# Handing this bundle to an agent

Copy-paste prompts for an AI session that will do the install for you. Facts the agent needs are
inline so it does not have to guess. Upload the zip first:

```sh
scp hermes-voice-patches.zip <ssh-alias-into-container>:/opt/data/tmp/
```

The Docker image has no `unzip`; the prompts use `python3 -m zipfile`. `/opt/hermes` is a root-owned
image layer — writing it needs `docker exec -u 0` on the host. The Hermes user (and Hermes itself)
can stage, check and verify, but not apply.

---

## A. Claude Code / Codex session with container SSH **and** host root (`docker exec`)

> Install `hermes-voice-patches` on my Hermes Agent container.
>
> Facts: container `<container-name>`, host SSH alias `<host>`, container SSH alias `<hermes>`
> (lands inside as user `hermes`, no sudo). Hermes v0.21.2 at `/opt/hermes` (root-owned image layer),
> data volume `/opt/data`, venv python `/opt/hermes/.venv/bin/python`. The zip is at
> `/opt/data/tmp/hermes-voice-patches.zip`. The gateway is supervised by s6: SIGTERM restarts it.
>
> Steps, in order, stop and report on the first failure:
> 1. `ssh <hermes> 'cd /opt/data && python3 -m zipfile -e tmp/hermes-voice-patches.zip . && ls hermes-voice-patches'`
> 2. Read `hermes-voice-patches/README.md` and tell me which of the 5 patches apply to me
>    (I use TTS provider `<edge|elevenlabs|...>`; skip 20 unless it is elevenlabs).
> 3. Apply as root: `ssh <host> 'docker exec -u 0 <container-name> sh /opt/data/hermes-voice-patches/apply.sh [--skip 20]'`
>    — it must end with `OK ... targets compile, ... imports load`. If a patch aborts on "anchor found
>    Nx", do NOT hand-edit `/opt/hermes`; show me the message.
> 4. Verify as the hermes user: `ssh <hermes> 'cd /opt/hermes && /opt/hermes/.venv/bin/python /opt/data/hermes-voice-patches/verify.py'`
> 5. Config: set `voice.auto_tts: false` in `/opt/data/config.yaml` (back it up first, validate YAML
>    after) and add to `/opt/data/.env`: `DISCORD_VOICE_AUTO_FOLLOW="<my user id>:<voice channel id>"`.
>    Do not touch any other `.env` line.
> 6. Restart: `ssh <host> 'docker exec -u 0 <container-name> sh -c "kill -TERM \$(pgrep -f \"hermes gateway run\" | head -1)"'`,
>    wait 30 s, then confirm in `/opt/data/logs/gateway.log`: `Connected as`, `Voice auto-follow armed (Discord)`, `Gateway running`.
> 7. Persistence: the image layer resets on container re-creation. Add
>    `sh /opt/data/hermes-voice-patches/apply.sh` to whatever boot hook re-applies patches
>    (on this box: `<path of your boot patch script, if any>`), or tell me it needs a derived image.
>
> Report: what was patched, skipped, the check/verify output, and the three log lines.

## B. Session that only has container SSH (hermes user, no root)

> Stage and verify `hermes-voice-patches` on my Hermes container; the root step I will run myself.
>
> Facts: `ssh <hermes>` lands in the container as user `hermes` (no sudo, no docker). Hermes v0.21.2,
> `/opt/hermes` is root-owned, `/opt/data` is mine. Zip at `/opt/data/tmp/hermes-voice-patches.zip`.
>
> 1. Extract to `/opt/data/hermes-voice-patches` (`python3 -m zipfile -e`), read README.md.
> 2. Dry-check compatibility without writing: for each `patches/[0-9]*.py`, confirm the anchor
>    strings exist exactly once in the target files under `/opt/hermes` (just grep/read — no writes).
> 3. Prepare config: back up `/opt/data/config.yaml`, set `voice.auto_tts: false`, validate YAML;
>    append `DISCORD_VOICE_AUTO_FOLLOW="<uid>:<chid>"` to `/opt/data/.env` without touching other lines.
> 4. Print for me, verbatim, the one root command to run on the host:
>    `docker exec -u 0 <container-name> sh /opt/data/hermes-voice-patches/apply.sh [--skip 20]`
>    and the restart command, then stop. After I say "applied", run
>    `/opt/hermes/.venv/bin/python /opt/data/hermes-voice-patches/verify.py` from `/opt/hermes` and
>    check `logs/gateway.log` for `Voice auto-follow armed (Discord)`.

## C. Telling Hermes itself (Discord / CLI)

Hermes runs as the `hermes` user inside the container, so on Docker it can do everything except the
root apply. On a bare (non-Docker) install where the same user owns the code, it can do all of it.

Docker:

> `/opt/data/tmp/hermes-voice-patches.zip` is a set of source patches for you (voice call + TTS fixes).
> Extract it to `/opt/data/hermes-voice-patches` with `python3 -m zipfile -e`, read its README.md,
> and check — read-only — that each patch's anchor text occurs exactly once in the matching file under
> `/opt/hermes`. Then set `voice.auto_tts: false` in config.yaml (backup first) and add
> `DISCORD_VOICE_AUTO_FOLLOW="<uid>:<chid>"` to .env. Do not edit anything under `/opt/hermes` and do
> not try to escalate; the apply step is root-only and I will run it. Reply with: anchors ok/not ok per
> patch, and the exact `docker exec -u 0 ... apply.sh` line for me.

Bare install (code owned by the Hermes user):

> Same as above, then run `sh /opt/data/hermes-voice-patches/apply.sh --root <hermes checkout> --python <venv python>`
> yourself, then `verify.py`, then `hermes gateway restart`, and report the check/verify output.

---

Things to tell any agent explicitly: never hand-edit files under the Hermes install (use `apply.sh`,
`apply.sh rollback` undoes it); never print or move `.env` secrets; don't restart the gateway while a
voice call is in progress.
