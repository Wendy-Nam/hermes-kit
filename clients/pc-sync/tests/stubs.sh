#!/usr/bin/env bash
# Test doubles for the VPS boundary.
#
# The scripts reach the server over SSH and then enter the hermes container. Neither
# exists on a laptop or a CI runner, so these two stubs stand in for them. Everything
# behind them is real: real files, a real Syncthing, real REST calls.
#
# Source this from tests/e2e.sh after exporting FAKE_DATA, FAKE_VAULTS and
# FAKE_STCONF, which are the directories that stand in for the container's
# /opt/data, /var/syncthing/vaults and /opt/syncthing-config.
set -euo pipefail

# fake ssh: the scripts only ever call `ssh <alias> <one command string>`.
# Drop the -o options and the alias, then run the command against the fake tree.
cat > "$STUB_BIN/ssh" <<'SH'
#!/usr/bin/env bash
# Drop the ssh options and the alias. The scripts call `ssh <alias> [redirects] <command...>`.
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
shift                                   # the SSH alias
# Real ssh consumes redirections locally and joins the rest into one remote command string, so
# `in_hermes "test -d /opt/x" 2>/dev/null` runs the test and hides stderr. Taking only "$1" dropped
# the command entirely on a call that passed the docker exec prefix and the program separately,
# which arrived as a bare `docker exec -u 10000 hermes`: valid, does nothing, exits non-zero.
# A redirection can sit anywhere on the line, not only first: `syncthing_ready` ends with
# `2>/dev/null`. Real ssh takes those as local redirections on the ssh process itself, so they
# are peeled off wherever they appear and applied to the command that runs here.
redir=()
args=()
for a in "$@"; do
  case "$a" in
    [0-9]'>'*) redir+=("$a") ;;
    '>'*) redir+=("$a") ;;
    *) args+=("$a") ;;
  esac
done
[ ${#args[@]} -gt 0 ] || { echo "stub ssh: no command given" >&2; exit 1; }
set -- "${args[@]}"
# The command arrives already joined into a single string, exactly as real ssh would build it:
#   hssh "docker ps ... | head -1"
# quotes nothing per word, because there is one word. Re-quoting it as a whole makes it a single
# quoted token, and bash then looks for a program literally named
# `docker ps --format "{{.Names}}|{{.Image}}"` and exits 127.
#
# in_hermes, on the other hand, passes the docker exec prefix and the program as separate
# arguments, so the arguments are joined with spaces here. That is what the caller wrote and is
# what the container has to receive.
sub() { printf '%s' "${1//$2/$3}"; }
# How the arguments are joined is the whole ballgame here, and getting it wrong is invisible:
#
#   "$*"         strips the quotes, so `python3 -c "print(1)"` becomes `python3 -c print(1)` and
#                python3 tries to run a file called print(1) — a SyntaxError, reported by the
#                caller as "Syncthing이 응답하지 않습니다".
#   printf %q    escapes the first word too, so `docker` no longer resolves and everything exits
#                127 with "command not found".
#
# Real ssh builds one remote command line and the *remote shell* parses it. An argument that
# already contains shell syntax — a pipeline, a redirection, quoted python code, newlines — is
# forwarded verbatim; an argument that is a plain word is forwarded verbatim too. So the rule
# is: join with spaces, and quote only the argument if it is a plain word containing a space,
# which is the one case that would otherwise split.
# hssh quotes the program text before sending it, so the string arriving here still carries the
# quoting. A remote shell would remove it once; this stub has to do the same, and it does by
# evaluating the command line below rather than reading it as a plain string. Unquoting here as
# well would strip the quotes twice and hand python3 an unterminated string literal, which is a
# SyntaxError reported as "Syncthing이 응답하지 않습니다".
cmd="${args[*]}"
# The one place container paths are rewritten. The docker stub is reached through this one and
# must not map them again: a second rewrite appended $FAKE_DATA to an already-rewritten path, so
# every check looked at $FAKE_DATA/opt/data/... — a directory that never existed — and preflight
# failed on the harness rather than on the product.
cmd="$(sub "$cmd" /opt/data "$FAKE_DATA")"
cmd="$(sub "$cmd" /var/syncthing/vaults "$FAKE_VAULTS")"
cmd="$(sub "$cmd" /opt/syncthing-config "$FAKE_STCONF")"
cmd="${cmd//syncthing:8384/$FAKE_ST_ADDR}"
# Traced to a file, never to stderr: the callers redirect stderr (syncthing_ready ends with
# 2>/dev/null), so a stderr trace vanishes exactly when it is needed most.
[ -n "${STUB_DEBUG_LOG:-}" ] && printf '%s\n' "$cmd" >> "$STUB_DEBUG_LOG"

# The redirections are applied by THIS shell, not handed to bash -c. Passing them as arguments
# makes the first one the script bash runs, so `bash -c "$cmd" 2>/dev/null` tried to execute
# "2>/dev/null" as a program. eval keeps the command in the same shell, where 2>/dev/null means
# what the caller wrote.
# The redirections are applied here, on this process, because that is what real ssh does: they
# belong to the ssh invocation, not to the remote command. Folding them into the remote string
# pushed them one level down, where `docker exec … 2>/dev/null` was read as a command line ending
# in a redirection — the docker stub then had nothing left to run.
# eval is what broke `python3 -c "…multi-line code…"`. eval re-parses the string, so the code
# after -c is split on whitespace and newlines: python3 received the first line as its program
# and the rest as file names, exited 2, and syncthing_ready reported "응답하지 않습니다". The
# trace showed an empty argv, because the program string was never one argument to begin with.
#
# The command is therefore NOT re-parsed here. The arguments the caller passed are already the
# argument vector of the remote command, so they are handed to the stub process as an array and
# the shell inside docker (or the stub) decides what to do with them. A redirection among them
# still has to be consumed by this shell, which is what real ssh does with it.
# How the remote command is run. Both obvious answers are wrong, in opposite directions:
#
#   eval "$cmd"  re-parses the joined string, so `python3 -c "…multi-line code…"` loses its
#                quoting: python3 gets the first line as its program and the rest as file names.
#                The trace showed an empty argv, because the program was never one argument.
#   "$@"         keeps every argument intact, but discover() passes a whole `docker ps | grep |
#                head` pipeline as ONE argument, so the pipe would be read as a program name and
#                the command would exit 127.
#
# The difference between the two callers is whether the command line contains shell syntax, so
# that is what the stub tests for. A command line goes to a shell; a plain argument vector is
# executed as one. This mirrors what the remote side does, which is why the same scripts work
# against a real server.
# ssh hands the remote side ONE command line and a shell parses it, so the line is evaluated
# here too. Two things make that work now:
#
#   - a pipeline (`docker ps | grep | head`) is one argument, and the shell parses it. Quoting
#     it in lib.sh would make the shell hunt for a program named after the whole pipeline.
#   - a program passed to `python3 -c` is quoted in lib.sh, so the quotes arrive as literal
#     characters and this shell removes them exactly once, handing python3 one argument.
#
# The redirections were peeled off above and are re-applied by this shell, as real ssh does with
# the ones written on the ssh command line.
# The command line is evaluated, which is what the remote shell does, and it is also what makes
# the quoting hssh applied come out right: eval removes exactly one layer, so the single quotes
# around the program survive as string delimiters and the backslash-escaped quotes inside the
# program are restored to plain quotes. Reading the string without a shell would leave both
# layers in place and python3 would choke on a literal backslash in its source.
#
# The redirections were peeled off above and are re-applied by this shell, as real ssh does with
# the ones written on the ssh command line.
if [ ${#redir[@]} -gt 0 ]; then
  eval "$cmd ${redir[*]}"
else
  eval "$cmd"
fi
SH

# fake scp: copy into the fake data dir instead of over ssh.
# The destination is `hermes:/opt/data/tmp/` — an alias-prefixed remote path. Copying to a file
# literally named "hermes:" failed, and with `set -e` in the caller that killed the whole step,
# so st_pair.py never ran and the pair appeared to succeed while configuring nothing.
cat > "$STUB_BIN/scp" <<'SH'
#!/usr/bin/env bash
dest=""; src=""; paths=()
while [ $# -gt 0 ]; do
  case "$1" in
    # "-o BatchMode=yes" is two arguments, not one. Treating it as a single flag left
    # "BatchMode=yes" to be picked up as the source path, and the copy failed on a file that
    # does not exist — with the real scp the option always carries a value.
    -o) shift 2 ;;
    -*) shift ;;
    *) paths+=("$1"); shift ;;
  esac
done
src="${paths[0]:-}"; dest="${paths[1]:-}"
[ -n "$src" ] && [ -n "$dest" ] || { echo "stub scp: expected <src> <dest>" >&2; exit 1; }
# Strip the ssh alias prefix and map the container path the ssh stub also maps.
dest="${dest#*:}"
dest="${dest//\/opt\/data/$FAKE_DATA}"
dest="${dest//\/opt\/syncthing-config/$FAKE_STCONF}"
mkdir -p "$(dirname "$dest")" && cp "$src" "$dest"
SH

# fake docker: `docker ps` lists the kit container, `docker exec` runs it here.
#
# The container boundary is the only thing simulated here. Container paths were already rewritten
# by the ssh stub and must not be touched again: $FAKE_DATA itself contains "/opt/data", so a
# second substitution produced a path that cannot exist and every check failed on the harness
# rather than on the scripts.
#
# The command after the container name is run through a shell, the way a remote `docker exec`
# runs it, because the scripts pass compound commands: a pipeline, a redirection, or
# `python3 -c` with newlines and quotes in the program. Running the words with exec instead
# breaks in two ways that are both silent: a shell builtin (`test -d /x`) has no executable to
# exec, and the program of `python3 -c "…"` is a single argument that would be re-split.
cat > "$STUB_BIN/docker" <<'SH'
#!/usr/bin/env bash
[ "${1:-}" = ps ] && { echo "hermes|ghcr.io/wendy-nam/hermes-kit:test"; exit 0; }
[ "${1:-}" = logs ] && exit 0
if [ "${1:-}" != exec ]; then exit 0; fi

shift
# `if`, not `cond && shift`: the scripts run under `set -e`, where a false condition in the
# last command of a branch exits the whole stub, so every `docker exec` without -u died here.
if [ "${1:-}" = -u ]; then shift 2; fi
if [ $# -eq 0 ]; then echo "stub docker: exec with no command" >&2; exit 1; fi
shift                                        # the container name

# Trace the resolved command to a file. The callers redirect stderr — syncthing_ready() ends
# with 2>/dev/null — so a traceback there would be invisible exactly when it is needed.
if [ -n "${STUB_DEBUG_LOG:-}" ]; then
  printf '%s\n' "$*" >> "${STUB_DEBUG_LOG}.docker"
fi

# One shell, the arguments quoted so the shell rebuilds the same boundaries the caller had.
#
# This is the part that matters most and is easy to get subtly wrong. Joining with a plain
# space turns `python3 -c "…k=ET.parse('/p')…"` into a script whose inner single quotes the shell
# consumes, so python3 receives a program with the quotes stripped and dies on a syntax error —
# and the caller, which only checks the exit status, reports "Syncthing이 응답하지 않습니다".
#
# printf %q per argument re-quotes every one of them, which is what a remote shell needs: the
# argument boundaries and the quotes inside them both survive. It must be applied to each
# argument separately, never to the joined string.
parts=()
for a in "$@"; do parts+=("$(printf '%q' "$a")"); done
exec bash -c "${parts[*]}"
SH

# Syncthing and Obsidian are installed by 01-pc-sync.sh when missing. In CI they are
# irrelevant to what is being tested, so the installers are stubbed and everything
# after them — pairing, REST calls, folder creation — runs for real.
cat > "$STUB_BIN/brew" <<'SH'
#!/usr/bin/env bash
echo "stub brew: $*" >&2; exit 0
SH

# st_pair.py reaches the server Syncthing at http://syncthing:8384, a compose network
# name that does not resolve off the VPS. Both stubs rewrite it to the real test
# instance, so st_pair.py itself runs unmodified against a real REST API.
: "${FAKE_ST_ADDR:=127.0.0.1:8391}"

chmod +x "$STUB_BIN"/ssh "$STUB_BIN"/scp "$STUB_BIN"/docker "$STUB_BIN"/brew
