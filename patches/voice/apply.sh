#!/bin/sh
# hermes-voice-patches — apply every patch (idempotent) then run the compile/import gate.
#   sh apply.sh [--root /opt/hermes] [--python /opt/hermes/.venv/bin/python] [--skip 20[,40]]
#   sh apply.sh rollback [--root ...]     # restore the earliest .bak-*-hvp of every touched file
# Docker (image layer is root-owned):
#   docker exec -u 0 <container> sh /opt/data/hermes-voice-patches/apply.sh
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=/opt/hermes; PY=""; MODE=apply; SKIP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2 ;;
    --python) PY=$2; shift 2 ;;
    --skip) SKIP=",$2,"; shift 2 ;;
    rollback) MODE=rollback; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PY" ] || { if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi; }
[ -d "$ROOT/gateway" ] || { echo "not a Hermes install: $ROOT (pass --root)" >&2; exit 2; }

if [ "$MODE" = rollback ]; then
  for f in tools/tts_tool.py tools/tts_tool_providers.py gateway/run_voice.py gateway/run_startup.py \
           gateway/run_busy.py gateway/slash_commands.py hermes_cli/commands.py hermes_cli/config_defaults.py \
           plugins/platforms/discord/adapter.py; do
    first=$(ls "$ROOT/$f".bak-*-hvp 2>/dev/null | sort | head -1)
    [ -n "$first" ] && cp -p "$first" "$ROOT/$f" && echo "restored $f <- $(basename "$first")"
  done
  exec "$PY" "$HERE/check.py" --root "$ROOT" --python "$PY"
fi

rc=0
for p in "$HERE"/patches/[0-9]*.py; do
  n=$(basename "$p" | cut -c1-2)
  case "$SKIP" in *",$n,"*) echo "== $(basename "$p") (skipped)"; continue ;; esac
  echo "== $(basename "$p")"
  "$PY" "$p" --root "$ROOT" || { rc=1; echo "FAILED: $(basename "$p") — nothing written for that file; fix or rollback" >&2; break; }
done
"$PY" "$HERE/check.py" --root "$ROOT" --python "$PY" || rc=1
[ $rc -eq 0 ] && echo "applied. restart the gateway to load it (Docker/s6: kill -TERM \$(pgrep -f 'hermes gateway run'); bare: hermes gateway restart)"
exit $rc
