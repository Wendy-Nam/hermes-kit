#!/usr/bin/env bash
# Real end-to-end test on Linux: two actual Syncthing instances, the actual scripts.
#
# Real here: Syncthing itself on both sides, the REST calls, the folder definitions,
# the file round trip, and all three scripts including 02-verify.sh.
# Simulated: the SSH hop to the VPS and the container boundary (tests/stubs.sh).
#
# Why this exists: the previous scripts passed a mock test while assuming a Syncthing
# the kit image does not run and a single "wiki" folder the kit does not create. The
# bug was structural, so a fake of Syncthing would have passed again. This runs the
# real binary on both ends and lets files actually move.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$HERE/.." && pwd)"
WORK="$(mktemp -d)"
SERVER_PID=""; PC_PID=""
cleanup() {
  # Syncthing starts a child of its own, so killing only the recorded pid used to leave listeners
  # behind on every failed run — the next run then found its ports taken and failed for a
  # reason that had nothing to do with the code. Match on --home, which is unique to this run,
  # and wait until the processes are actually gone.
  for pid in "$SERVER_PID" "$PC_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  pkill -f -- "--home=$WORK" 2>/dev/null || true
  i=0
  while [ $i -lt 15 ] && pgrep -f -- "--home=$WORK" >/dev/null 2>&1; do
    i=$((i+1)); sleep 1
  done
  # SIGTERM is ignored by a wedged daemon; do not leave it bound to the port.
  pkill -KILL -f -- "--home=$WORK" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT
pass() { echo "  ✅ $*"; }
fail() { echo "  ❌ $*" >&2; exit 1; }

ST="$(command -v syncthing || true)"
[ -n "$ST" ] || { echo "syncthing binary not found — install it before running this test"; exit 1; }
command -v curl >/dev/null || { echo "curl not found"; exit 1; }

# ── the fake VPS ─────────────────────────────────────────────────────────────
FAKE_DATA="$WORK/opt/data"           # the hermes container's /opt/data
FAKE_VAULTS="$WORK/var/syncthing/vaults"
FAKE_STCONF="$WORK/opt/syncthing-config"
STUB_BIN="$WORK/bin"
SERVER_PORT=8391
PC_PORT=8392
ST_KEY="e2e-test-key"   # written into both configs; see start_st
export FAKE_DATA FAKE_VAULTS FAKE_STCONF STUB_BIN
# plugins/kit-setup must exist or 00-preflight.sh fails for a reason that has nothing to do with
# sync. The kit image provides it; the fake tree has to as well.
mkdir -p "$FAKE_DATA/tmp" "$FAKE_VAULTS/work" "$FAKE_VAULTS/personal" "$FAKE_STCONF" "$STUB_BIN" \
         "$FAKE_DATA/plugins/kit-setup" "$FAKE_DATA/scripts"
cp "$SKILL/scripts/remote/st_pair.py" "$FAKE_DATA/scripts/st_pair.py"
# Guards against exactly the failure this suite had: the fake tree is built correctly, but a later
# step changes the environment and the scripts then look somewhere else. Assert the tree first.
[ -d "$FAKE_DATA/plugins/kit-setup" ] || { echo "fake data tree is missing kit-setup ($FAKE_DATA)" >&2; exit 1; }
# shellcheck source=tests/stubs.sh
. "$HERE/stubs.sh"
export PATH="$STUB_BIN:$PATH"
# st_pair.py runs inside the container in production; the test points the same script
# at the real Syncthing running on this machine instead of the compose network.
export HERMES_ST_CONFIG="$FAKE_STCONF/config.xml"
export HERMES_ST_API="http://127.0.0.1:$SERVER_PORT"
export HERMES_ST_WORK="$FAKE_VAULTS/work"
export HERMES_ST_PERSONAL="$FAKE_VAULTS/personal"

start_st() {                        # name port -> sets ST_HOME_<name>, ST_PID_<name>, ST_CFG_<name>
  # Split declarations: `local a=$1 home=$a` is a use-before-assignment under set -u
  # on bash 3.2, which is the /bin/bash a student on macOS actually runs.
  local name="$1" port="$2"
  local home="$WORK/st-$name"
  mkdir -p "$home"
  # `--no-default-folder` exists in the 1.27.x the kit pins but was removed in v2, and a
  # developer machine may have either. The stray default folder is removed over the REST
  # API below instead, which works on both.
  "$ST" generate --home="$home" >/dev/null 2>&1 || "$ST" generate --no-default-folder --home="$home" >/dev/null 2>&1
  # Syncthing v2 probes for a free port on first start, so the generated GUI address is a
  # random high port, never 127.0.0.1:8384. A sed that looks for 8384 therefore matches
  # nothing and every later request goes to a port nobody is listening on — which is what
  # made this test wait out its retries in silence. Write the address in with the XML parser
  # and read it back afterwards instead of assuming a default.
  python3 - "$home/config.xml" "$port" <<'PY'
import sys, xml.etree.ElementTree as ET
path, port = sys.argv[1], sys.argv[2]
tree = ET.parse(path)
root = tree.getroot()
gui = root.find("gui")
if gui is None:
    gui = ET.SubElement(root, "gui")
for tag, value in (("enabled", "true"), ("tls", "false"), ("address", f"127.0.0.1:{port}")):
    node = gui.find(tag)
    if node is None:
        node = ET.SubElement(gui, tag)
    node.text = value
# The key is set here rather than read from the generated file, so the value is known before the
# process starts. Syncthing v2 answers an unauthenticated /rest call with "CSRF Error" and a 403,
# which is what made the readiness probe below fail forever against a perfectly healthy instance.
apikey = gui.find("apikey")
if apikey is None:
    apikey = ET.SubElement(gui, "apikey")
apikey.text = "e2e-test-key"
# No global discovery and no NAT traversal: this test only needs the two instances to find each
# other on loopback, and announcing a throwaway device id to public relays is not something a test
# should do on a student's machine.
options = root.find("options")
if options is None:
    options = ET.SubElement(root, "options")
for tag, value in (("globalAnnounceEnabled", "false"), ("localAnnounceEnabled", "true"),
                   ("natEnabled", "false"), ("relaysEnabled", "false"),
                   ("crashReportingEnabled", "false")):
    node = options.find(tag)
    if node is None:
        node = ET.SubElement(options, tag)
    node.text = value
tree.write(path, encoding="UTF-8", xml_declaration=True)
PY
  # Launched with stdout and stderr on the log file and stdin closed. A backgrounded
  # Syncthing that inherits the shell's stdout keeps the pipe open, and any command
  # substitution reading that pipe never returns — the hang this test had.
  "$ST" --no-browser --home="$home" >"$home/log" 2>&1 </dev/null &
  local pid=$!
  local i=0
  # The API key travels with every call; without it Syncthing answers 403 and a probe loop
  # against a live instance looks exactly like one against a dead port.
  until curl -fsS -H "X-API-Key: $ST_KEY" "http://127.0.0.1:$port/rest/system/status" >/dev/null 2>&1; do
    i=$((i+1))
    if [ $i -ge 60 ]; then
      # Without this the `until` loop used to spin against a port nobody owned until the
      # outer timeout killed the whole run, printing nothing about why.
      echo "  ❌ syncthing($name) never answered on :$port" >&2
      tail -20 "$home/log" >&2
      return 1
    fi
    kill -0 "$pid" 2>/dev/null || { echo "  ❌ syncthing($name) exited early" >&2; tail -20 "$home/log" >&2; return 1; }
    sleep 1
  done
  # The address actually in force, read from the file Syncthing rewrote on startup. Trusting
  # the port we asked for is exactly the assumption that broke the previous version.
  # Dynamic assignment (`ST_CFG_$name=…`) is a command name in bash 3.2 — the /bin/bash a student on
  # macOS runs — and it fails with "command not found" plus a `set -u` error on the next line, long
  # after start_st returned. printf -v needs a literal identifier, so each name is written out
  # explicitly instead. start_st is called with exactly these two names.
  case "$name" in
    server)
      ST_CFG_server="$home/config.xml"; ST_HOME_server="$home"; ST_PID_server="$pid"
      ST_GUI_server="$(python3 -c "import sys,xml.etree.ElementTree as ET;print(ET.parse(sys.argv[1]).getroot().findtext('gui/address'))" "$home/config.xml")"
      ;;
    pc)
      ST_CFG_pc="$home/config.xml"; ST_HOME_pc="$home"; ST_PID_pc="$pid"
      ST_GUI_pc="$(python3 -c "import sys,xml.etree.ElementTree as ET;print(ET.parse(sys.argv[1]).getroot().findtext('gui/address'))" "$home/config.xml")"
      ;;
    *) echo "  ❌ unknown instance name '$name'" >&2; return 1 ;;
  esac
  return 0
}

echo "▶ two real Syncthing instances"
start_st server "$SERVER_PORT" || fail "the server instance did not start"
SERVER_PID="$ST_PID_server"; SRV_CFG="$ST_CFG_server"; SRV_GUI="$ST_GUI_server"
pass "server ($SRV_GUI) and its config are in place"
start_st pc "$PC_PORT" || fail "the PC instance did not start"
PC_PID="$ST_PID_pc"; PC_CFG="$ST_CFG_pc"; PC_GUI="$ST_GUI_pc"
pass "PC ($PC_GUI) is running"

# The compose service name `syncthing:8384` is now redirected to the address Syncthing actually
# bound. Re-exported here, not earlier: the port is only known once the instance is up, and the
# stubs read these variables at run time, so the old value was never used.
export FAKE_ST_ADDR="$SRV_GUI"
export HERMES_ST_API="http://$SRV_GUI"

SRV_KEY="$ST_KEY"
[ -n "$SRV_KEY" ] || fail "no API key for the server"
sapi() { curl -fsS -X "$1" -H "X-API-Key: $SRV_KEY" -H 'Content-Type: application/json' \
           ${3:+-d "$3"} "http://$SRV_GUI/rest/$2"; }
sapi GET system/status >/dev/null || fail "the server Syncthing REST API is not answering"
# The kit mounts the server's config.xml read-only into the hermes container. Copied after the
# instance starts, because Syncthing rewrites the file on startup: a copy taken earlier carries a
# config that is no longer the one in force, and 00-preflight.sh would then check a stale file.
cp "$SRV_CFG" "$FAKE_STCONF/config.xml"
[ -s "$FAKE_STCONF/config.xml" ] || fail "the server config.xml was not created"
# The key the server is actually using has to be the one the scripts read: Syncthing rewrites
# config.xml on startup, and st_pair.py / syncthing_ready both authenticate with gui/apikey.
cp_key="$(python3 -c "import sys,xml.etree.ElementTree as ET;print(ET.parse(sys.argv[1]).getroot().findtext('gui/apikey') or '')" "$FAKE_STCONF/config.xml")"
# The scripts reach the server at FAKE_ST_ADDR; if that address is not the one Syncthing is
# actually serving, every "Syncthing이 응답하지 않습니다" is a harness lie, not a product fault.
curl -fsS -m 5 -H "X-API-Key: $ST_KEY" "http://$SRV_GUI/rest/system/status" >/dev/null \
  || fail "the test server is not answering at $SRV_GUI"
[ "$cp_key" = "$ST_KEY" ] || fail "the mounted config.xml does not carry the test API key"
pass "server config.xml is in place where the kit mounts it"

# Only the REST helpers are borrowed from lib.sh — the two functions below. The whole file is not
# sourced on purpose: lib.sh sets SKILL_DIR, VAULT_ROOT and WORK_DIR from $HOME as a side effect,
# and importing those here silently repointed the vault paths this test had already exported.
# Sourcing it wholesale is how the harness ended up checking a tree it was no longer pointing at.
json_field()  { python3 -c "
import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1],''))
except Exception: print('')" "$1"; }
json_has_key() { python3 -c "
import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(1)
if not isinstance(rows,list): sys.exit(1)
sys.exit(0 if any(str(r.get(sys.argv[1],''))==sys.argv[2] for r in rows) else 1)" "$1" "$2"; }
command -v json_field  >/dev/null || { echo "json_field missing from scripts/lib.sh" >&2; exit 1; }
command -v json_has_key >/dev/null || { echo "json_has_key missing from scripts/lib.sh" >&2; exit 1; }

# ── Syncthing REST helpers (from lib.sh) ─────────────────────────────────────
SRV_ID="$(sapi GET system/status | json_field myID)"
[ -n "$SRV_ID" ] || fail "could not read the server device id"

# The server's folders must point at real directories or nothing can sync. The kit
# provisions these paths; the test creates them so the round trip exercises Syncthing
# rather than a missing directory.
sapi POST config/folders "$(cat <<JSON
{"id":"hermes-work","label":"업무 볼트","path":"$FAKE_VAULTS/work","type":"sendreceive",
 "devices":[{"deviceID":"$SRV_ID"}],"rescanIntervalS":30,"fsWatcherEnabled":true}
JSON
)" >/dev/null || fail "could not create the server work folder"
sapi POST config/folders "$(cat <<JSON
{"id":"hermes-personal","label":"개인 볼트","path":"$FAKE_VAULTS/personal","type":"sendreceive",
 "devices":[{"deviceID":"$SRV_ID"}],"rescanIntervalS":30,"fsWatcherEnabled":true}
JSON
)" >/dev/null || fail "could not create the server personal folder"
pass "the server serves hermes-work and hermes-personal at the kit's paths"

# ── the student runs the skill, for real ──────────────────────────────────────
export SSH_ALIAS=hermes
export LOCAL_VAULT_ROOT="$WORK/HermesVaults"
export PORTABLE_ST_DIR="$WORK/portable"
REAL_HOME="$HOME"
export HOME="$WORK/pc-home"
# Put the PC config where local_st_config() actually looks on this OS. The Linux path
# ($HOME/.config/syncthing) is only one of three candidates; on macOS it is
# $HOME/Library/Application Support/Syncthing, so a Linux-only layout makes the script fall
# through and try to install its own Syncthing.
case "$(uname -s)" in
  Darwin) PC_CFG_DIR="$HOME/Library/Application Support/Syncthing" ;;
  MINGW*|MSYS*|CYGWIN*) PC_CFG_DIR="${LOCALAPPDATA:-$HOME/AppData/Local}/Syncthing" ;;
  *) PC_CFG_DIR="$HOME/.config/syncthing" ;;
esac
mkdir -p "$PC_CFG_DIR"
cp "$PC_CFG" "$PC_CFG_DIR/config.xml"    # local_st_config() finds it here

echo "▶ 00-preflight.sh"
# The output is echoed on failure rather than captured silently: a run that dies mid-step
# otherwise leaves the last line pointing at the step before, which is what made this test
# look like it hung for no reason.
rc=0; out="$(cd "$SKILL" && bash scripts/00-preflight.sh 2>&1)" || rc=$?
[ "$rc" = 0 ] || { echo "$out" >&2; fail "00-preflight.sh exited $rc"; }

rc=0; out="$(cd "$SKILL" && bash scripts/00-preflight.sh 2>&1)" || rc=$?
[ "$rc" = 0 ] || { echo "$out" >&2; fail "00-preflight.sh exited $rc"; }
pass "00-preflight.sh passed against the simulated VPS"

PC_KEY="$ST_KEY"
PC_ID="$(curl -fsS -H "X-API-Key: $PC_KEY" "http://$PC_GUI/rest/system/status" | json_field myID)"
[ -n "$PC_ID" ] || fail "could not read the PC's device id"

echo "▶ 01-pc-sync.sh"
rc=0; out="$(cd "$SKILL" && bash scripts/01-pc-sync.sh 2>&1)" || rc=$?
[ "$rc" = 0 ] || { echo "$out" >&2; fail "01-pc-sync.sh exited $rc"; }

# Assert on the Syncthing configuration, not on the script's wording. The script prints the
# Korean label ("업무 볼트"), not the folder id, so grepping the output for "hermes-work" tested
# the copy rather than the result. What matters is that the PC now holds both kit folders.
pc_folders="$(curl -fsS -H "X-API-Key: $PC_KEY" "http://$PC_GUI/rest/config/folders")"
printf '%s' "$pc_folders" | json_has_key id hermes-work \
  || { echo "$out"; fail "the PC has no hermes-work folder"; }
printf '%s' "$pc_folders" | json_has_key id hermes-personal \
  || { echo "$out"; fail "the PC has no hermes-personal folder"; }
pass "01-pc-sync.sh paired both kit vaults"

# The server side is the part that used to be wrong. Sharing can be configured and no file
# ever moves, which is exactly the failure the old single "wiki" folder had.
sapi GET config/folders | json_has_key id hermes-work || fail "the server has no hermes-work folder"
sapi GET config/folders | json_has_key id hermes-personal || fail "the server has no hermes-personal folder"
sapi GET config/devices | json_has_key deviceID "$PC_ID" || fail "the server does not know the PC device"
pass "server and PC know each other, using the kit's folder ids"

echo "▶ 02-verify.sh (a real file crosses the wire)"
rc=0; out="$(cd "$SKILL" && bash scripts/02-verify.sh 2>&1)" || rc=$?
[ "$rc" = 0 ] || { echo "$out" >&2; fail "02-verify.sh reported a failure"; }
echo "$out" | grep -q '동기화 확인 완료' || { echo "$out"; fail "02-verify.sh did not complete"; }
pass "a file written on the server arrived in the PC vault"

# Arriving is not enough. The content has to match and a deletion has to propagate;
# a one-way check would pass against a lossy sync.
echo "content and deletions"
echo "hermes-e2e-payload" > "$FAKE_VAULTS/work/roundtrip.txt"
for _ in $(seq 1 30); do
  [ -f "$LOCAL_VAULT_ROOT/work/roundtrip.txt" ] && break; sleep 1
done
[ -f "$LOCAL_VAULT_ROOT/work/roundtrip.txt" ] || fail "the round-trip file never arrived"
grep -q hermes-e2e-payload "$LOCAL_VAULT_ROOT/work/roundtrip.txt" || fail "the file arrived empty"
pass "content matches"
rm -f "$FAKE_VAULTS/work/roundtrip.txt"
for _ in $(seq 1 30); do
  [ -f "$LOCAL_VAULT_ROOT/work/roundtrip.txt" ] || break; sleep 1
done
[ -f "$LOCAL_VAULT_ROOT/work/roundtrip.txt" ] && fail "a deleted file came back on the PC"
pass "deletions propagate (sync is bidirectional, as the README says)"

export HOME="$REAL_HOME"
echo ""
echo "✅ e2e: passed (real Syncthing on both sides, real scripts, simulated VPS boundary)"

