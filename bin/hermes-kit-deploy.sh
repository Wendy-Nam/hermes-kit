#!/usr/bin/env bash
# hermes-kit-deploy.sh — All-in-one local & remote SSH setup, migration, and verification CLI
#
# Supports:
#   1. Local execution directly on a VPS:
#        ./bin/hermes-kit-deploy.sh install [--with-omniroute] [--build-local]
#        ./bin/hermes-kit-deploy.sh migrate [--with-omniroute] [--build-local] [--apply-presets]
#        ./bin/hermes-kit-deploy.sh verify
#        ./bin/hermes-kit-deploy.sh preset [plan|apply]
#   2. Remote execution over SSH (zero manual file copying required):
#        ./bin/hermes-kit-deploy.sh --ssh user@host [-p 22] [-i ~/.ssh/id_ed25519] install --with-omniroute
#        ./bin/hermes-kit-deploy.sh --ssh user@host migrate --with-omniroute --apply-presets
#
# Deterministic & Non-Destructive Guarantees:
#   - Never deletes or overwrites an existing container's user data, `.env`, `auth.json`, vaults, or sessions.
#   - Before any migration/update, snapshots `/opt/data` config, `.omh`, and plugins into a timestamped backup.
#   - Syncs `/opt/data/plugins/kit-setup` from the latest kit image so running or existing volumes get the
#     latest `omh_routing.py`, `omniroute_presets.py`, and OMH v5.0.0 upgrader.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${REPO_ROOT}/versions.env" ]]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/versions.env"
fi

HERMES_VERSION="${HERMES_VERSION:-0.23.3}"
KIT_VERSION="${KIT_VERSION:-19}"
RELEASE_TAG="${HERMES_VERSION}-k${KIT_VERSION}"
DEFAULT_HERMES_IMAGE="ghcr.io/wendy-nam/hermes-kit:${RELEASE_TAG}"
DEFAULT_OMNIROUTE_IMAGE="ghcr.io/diegosouzapw/omniroute:3.8.54"

SSH_TARGET=""
SSH_PORT="22"
SSH_IDENTITY=""
REMOTE_DIR="/opt/hermes-kit"
WITH_OMNIROUTE=0
BUILD_LOCAL=0
APPLY_PRESETS=0
CONTAINER_NAME=""
OMNIROUTE_VOLUME="${KIT_OMNIROUTE_VOLUME:-}"
ACTION=""

usage() {
  cat <<'EOF'
Usage:
  bin/hermes-kit-deploy.sh [SSH_OPTIONS] <COMMAND> [OPTIONS]

Commands:
  install       Fresh setup of Hermes v0.23.3-k19 + Syncthing (+ optional OmniRoute v3.8.54-web)
  migrate       Non-destructive upgrade/migration of an existing Hermes / OMH / OmniRoute server
  verify        Verify Hermes core, voice quick-call adapter, OMH v5.0.0 routing, and OmniRoute status
  preset        Plan or apply recommended OmniRoute available-resource combos & OMH 12-category chains
  job-hunt      Install or update Wendy-Nam/hermes-job-hunt-for-korean inside the Hermes container (native)

SSH Options (optional — omit to run locally on the current machine):
  --ssh <user@host>        Run deployment on a remote VPS over SSH
  -p, --port <port>        SSH port (default: 22)
  -i, --identity <file>    SSH private key path
  --remote-dir <path>      Target directory on remote server (default: /opt/hermes-kit)

Options:
  --with-omniroute         Include OmniRoute (v3.8.54-web + RTK envelope + UI overlay)
  --build-local            Build Docker images locally from the repository instead of pulling GHCR tags
  --apply-presets          Automatically apply recommended OmniRoute combos + OMH 12-category routing
  --container <name>       Target an existing Hermes container by name (auto-detected if omitted)
  --omniroute-volume <v>   Attach this existing Docker volume as OmniRoute /app/data (env: KIT_OMNIROUTE_VOLUME).
                           Required when more than one OmniRoute data volume exists (e.g. after a VPS move).
  -h, --help               Show this help message
EOF
}

EXTRA_ARGS=()

need_arg() {
  if [[ "$2" -lt 2 ]]; then
    echo "[error] Option '$1' requires an argument." >&2
    usage >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh)
      need_arg "$1" "$#"
      SSH_TARGET="$2"
      shift 2
      ;;
    -p|--port)
      need_arg "$1" "$#"
      SSH_PORT="$2"
      shift 2
      ;;
    -i|--identity)
      need_arg "$1" "$#"
      SSH_IDENTITY="$2"
      shift 2
      ;;
    --remote-dir)
      need_arg "$1" "$#"
      REMOTE_DIR="$2"
      shift 2
      ;;
    --with-omniroute)
      WITH_OMNIROUTE=1
      shift
      ;;
    --build-local)
      BUILD_LOCAL=1
      shift
      ;;
    --apply-presets)
      APPLY_PRESETS=1
      shift
      ;;
    --container)
      need_arg "$1" "$#"
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --omniroute-volume)
      need_arg "$1" "$#"
      OMNIROUTE_VOLUME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    -*)
      echo "[error] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
    install|migrate|update|verify|doctor|preset|job-hunt)
      if [[ -z "${ACTION}" ]]; then
        ACTION="$1"
      else
        EXTRA_ARGS+=("$1")
      fi
      shift
      ;;
    *)
      if [[ -z "${ACTION}" ]]; then
        echo "[error] Unknown command: $1" >&2
        usage >&2
        exit 2
      fi
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  usage >&2
  exit 2
fi

# ── Remote SSH Dispatch ───────────────────────────────────────────────────────────────────────
if [[ -n "${SSH_TARGET}" ]]; then
  SSH_OPTS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new)
  if [[ -n "${SSH_IDENTITY}" ]]; then
    SSH_OPTS+=(-i "${SSH_IDENTITY}")
  fi
  REMOTE_DIR_Q="$(printf '%q' "${REMOTE_DIR}")"
  echo "[deploy] Syncing hermes-kit (${RELEASE_TAG}) to ${SSH_TARGET}:${REMOTE_DIR} ..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p ${REMOTE_DIR_Q}"
  tar -C "${REPO_ROOT}" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    -czf - . | ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "tar -xzf - -C ${REMOTE_DIR_Q}"

  REMOTE_CMD=(bash ./bin/hermes-kit-deploy.sh)
  [[ "${WITH_OMNIROUTE}" -eq 1 ]] && REMOTE_CMD+=(--with-omniroute)
  [[ "${BUILD_LOCAL}" -eq 1 ]] && REMOTE_CMD+=(--build-local)
  [[ "${APPLY_PRESETS}" -eq 1 ]] && REMOTE_CMD+=(--apply-presets)
  [[ -n "${CONTAINER_NAME}" ]] && REMOTE_CMD+=(--container "${CONTAINER_NAME}")
  [[ -n "${OMNIROUTE_VOLUME}" ]] && REMOTE_CMD+=(--omniroute-volume "${OMNIROUTE_VOLUME}")
  REMOTE_CMD+=("${ACTION}")
  if [[ "${#EXTRA_ARGS[@]}" -gt 0 ]]; then
    REMOTE_CMD+=("${EXTRA_ARGS[@]}")
  fi

  REMOTE_CMD_Q=""
  for arg in "${REMOTE_CMD[@]}"; do
    REMOTE_CMD_Q+=" $(printf '%q' "${arg}")"
  done

  # Transfer secrets via a mode-0600 temp file over stdin rather than remote command-line args
  # (avoids shell injection on special characters and keeps secrets out of remote `ps`).
  REMOTE_ENV_PAYLOAD=""
  if [[ -n "${DISCORD_BOT_TOKEN:-}" ]]; then
    REMOTE_ENV_PAYLOAD+="export DISCORD_BOT_TOKEN=$(printf '%q' "${DISCORD_BOT_TOKEN}")"$'\n'
  fi
  if [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]]; then
    REMOTE_ENV_PAYLOAD+="export KIT_OMNIROUTE_PASSWORD=$(printf '%q' "${KIT_OMNIROUTE_PASSWORD}")"$'\n'
  fi

  echo "[deploy] Executing '${ACTION}' on ${SSH_TARGET} ..."
  if [[ -n "${REMOTE_ENV_PAYLOAD}" ]]; then
    REMOTE_ENV_FILE="$(printf '%s' "${REMOTE_ENV_PAYLOAD}" | ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
      'umask 077 && f="$(mktemp /tmp/hermes-kit-env.XXXXXX)" && cat > "$f" && printf "%s" "$f"')"
    REMOTE_ENV_FILE_Q="$(printf '%q' "${REMOTE_ENV_FILE}")"
    SSH_TTY_ARGS=()
    [[ -t 0 ]] && SSH_TTY_ARGS+=(-t)
    exec ssh "${SSH_TTY_ARGS[@]}" "${SSH_OPTS[@]}" "${SSH_TARGET}" \
      "trap 'rm -f ${REMOTE_ENV_FILE_Q}' EXIT; . ${REMOTE_ENV_FILE_Q}; rm -f ${REMOTE_ENV_FILE_Q}; cd ${REMOTE_DIR_Q} &&${REMOTE_CMD_Q}"
  else
    SSH_TTY_ARGS=()
    [[ -t 0 ]] && SSH_TTY_ARGS+=(-t)
    exec ssh "${SSH_TTY_ARGS[@]}" "${SSH_OPTS[@]}" "${SSH_TARGET}" \
      "cd ${REMOTE_DIR_Q} &&${REMOTE_CMD_Q}"
  fi
fi

# ── Local Execution Helpers ───────────────────────────────────────────────────────────────────
log() { printf '\033[1;34m[hermes-kit]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[hermes-kit][warn]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[hermes-kit][error]\033[0m %s\n' "$*" >&2; exit 1; }

# A real Hermes runtime ships the gateway venv; sidecars (OmniRoute, Syncthing) never do.
is_hermes_runtime() {
  docker exec "$1" test -x /opt/hermes/.venv/bin/python >/dev/null 2>&1
}

# Prints the single running Hermes container, or nothing. Dies if the choice is ambiguous.
# Name/image substring matching alone is unsafe: `hermes-kit:omniroute-*` images and the
# `hermes-kit-syncthing-*` compose containers also contain "hermes".
detect_hermes_container() {
  if [[ -n "${CONTAINER_NAME}" ]]; then
    [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null)" == "true" ]] \
      || die "--container '${CONTAINER_NAME}' is not a running container."
    is_hermes_runtime "${CONTAINER_NAME}" \
      || die "--container '${CONTAINER_NAME}' is not a Hermes runtime (no /opt/hermes/.venv)."
    echo "${CONTAINER_NAME}"
    return
  fi
  local name image service
  local labelled=() matched=()
  while IFS=$'\t' read -r name image service; do
    [[ -n "${name}" ]] || continue
    case "${name} ${image} ${service}" in
      *omniroute*|*syncthing*|*swap-init*) continue ;;
    esac
    if [[ "${service}" == "hermes" ]]; then
      is_hermes_runtime "${name}" && labelled+=("${name}")
    elif [[ "${name}" == *hermes* || "${image}" == *hermes* ]]; then
      is_hermes_runtime "${name}" && matched+=("${name}")
    fi
  done < <(docker ps --format '{{.Names}}\t{{.Image}}\t{{.Label "com.docker.compose.service"}}')
  local candidates=("${labelled[@]}")
  [[ "${#candidates[@]}" -gt 0 ]] || candidates=("${matched[@]}")
  if [[ "${#candidates[@]}" -gt 1 ]]; then
    die "Multiple Hermes containers are running (${candidates[*]}). Pick one with --container <name>."
  fi
  echo "${candidates[0]:-}"
}

# Prints the OmniRoute data volume to attach, or nothing (compose then creates its default volume).
# Never guesses between several candidates: after a VPS move an empty auto-created volume and the
# migrated one can both exist, and picking the wrong one silently hides all OmniRoute state.
resolve_omniroute_volume() {
  if [[ -n "${OMNIROUTE_VOLUME}" ]]; then
    docker volume inspect "${OMNIROUTE_VOLUME}" >/dev/null 2>&1 \
      || die "OmniRoute volume '${OMNIROUTE_VOLUME}' does not exist (refusing to create an empty one)."
    echo "${OMNIROUTE_VOLUME}"
    return
  fi
  local vols
  vols="$(docker volume ls --format '{{.Name}}' | grep -i 'omniroute' | sort -u || true)"
  local count
  count="$(printf '%s' "${vols}" | grep -c . || true)"
  if [[ "${count}" -gt 1 ]]; then
    die "Multiple OmniRoute data volumes exist: $(echo ${vols}). Pick the one holding storage.sqlite with --omniroute-volume <name>."
  fi
  printf '%s' "${vols}"
}

# Compose project of an existing OmniRoute container, so `up` recreates it in place instead of
# starting a duplicate that fights over 127.0.0.1:20128.
existing_omniroute_project() {
  local name image service project
  while IFS=$'\t' read -r name image service project; do
    [[ -n "${name}" ]] || continue
    if [[ "${service}" == "omniroute" || "${image}" == *omniroute* ]]; then
      [[ -n "${project}" ]] \
        || die "OmniRoute container '${name}' is not managed by docker compose. Stop it first (docker stop ${name}); its data volume is kept."
      echo "${project}"
      return
    fi
  done < <(docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Label "com.docker.compose.service"}}\t{{.Label "com.docker.compose.project"}}')
}

build_local_images() {
  log "Building ${DEFAULT_HERMES_IMAGE} locally from Dockerfile ..."
  docker build \
    --build-arg "HERMES_BASE_IMAGE=${HERMES_BASE_IMAGE}" \
    --build-arg "HERMES_VERSION=${HERMES_VERSION}" \
    --build-arg "RTK_VERSION=${RTK_VERSION}" \
    --build-arg "KIT_VERSION=${KIT_VERSION}" \
    -t "${DEFAULT_HERMES_IMAGE}" \
    -t "hermes-kit:${RELEASE_TAG}" \
    "${REPO_ROOT}"

  if [[ "${WITH_OMNIROUTE}" -eq 1 ]]; then
    log "Building OmniRoute v3.8.54-web RTK adapter & UI overlay locally ..."
    docker build -t "hermes-kit:omniroute-adapter" "${REPO_ROOT}/advanced/omniroute-rtk-envelope"
    docker build \
      --build-arg "KIT_OMNIROUTE_IMAGE=hermes-kit:omniroute-adapter" \
      -t "hermes-kit:omniroute-ui-patch" \
      "${REPO_ROOT}/advanced/omniroute-patches"
    export KIT_OMNIROUTE_IMAGE="hermes-kit:omniroute-ui-patch"
  fi
}

sync_kit_into_container() {
  local cid="$1"
  log "Syncing latest /opt/kit and /opt/data/plugins/kit-setup into container '${cid}' ..."
  docker exec -u 0 "${cid}" mkdir -p /opt/kit /opt/data/plugins/kit-setup
  for sub in bin patches plugins seed versions.env; do
    if [[ -e "${REPO_ROOT}/${sub}" ]]; then
      docker cp "${REPO_ROOT}/${sub}" "${cid}:/opt/kit/"
    fi
  done
  docker exec -u 0 "${cid}" sh -c "
    echo '${KIT_VERSION}' > /opt/kit/VERSION
    echo '${RELEASE_TAG}' > /opt/kit/RELEASE_VERSION
    SITE=\$(/opt/hermes/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')
    if [ ! -f \"\$SITE/yaml.py\" ] && [ ! -d \"\$SITE/yaml\" ]; then
      printf 'from hermes_yaml import safe_load, safe_dump, YAMLError\nload = safe_load\ndump = safe_dump\n' > \"\$SITE/yaml.py\"
    fi
    rm -rf /opt/data/plugins/kit-setup/__pycache__
    cp -rf /opt/kit/plugins/kit-setup/. /opt/data/plugins/kit-setup/
    rm -rf /opt/data/plugins/kit-setup/__pycache__
    chown -R 10000:10000 /opt/data/plugins/kit-setup 2>/dev/null || true
  "
}

resolve_omniroute_password() {
  if [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]]; then
    printf '%s' "${KIT_OMNIROUTE_PASSWORD}"
    return 0
  fi
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    local line
    line="$(grep -m1 '^KIT_OMNIROUTE_PASSWORD=' "${REPO_ROOT}/.env" 2>/dev/null || true)"
    if [[ -n "${line}" ]]; then
      printf '%s' "${line#KIT_OMNIROUTE_PASSWORD=}"
      return 0
    fi
  fi
  return 1
}

compose_omniroute_up() {
  local args=(-f "${REPO_ROOT}/advanced/docker-compose.omniroute.yml")
  local vol project
  vol="$(resolve_omniroute_volume)"
  project="$(existing_omniroute_project)"
  if [[ -n "${vol}" ]]; then
    local override="${REPO_ROOT}/advanced/.omniroute-volume.override.yml"
    printf 'volumes:\n  omniroute-data:\n    external: true\n    name: "%s"\n' "${vol}" > "${override}"
    args+=(-f "${override}")
    log "OmniRoute will use existing data volume '${vol}'."
  elif [[ "${ACTION}" == "migrate" || "${ACTION}" == "update" ]]; then
    warn "No existing OmniRoute data volume found; compose will create a new empty one."
  fi
  [[ -n "${project}" ]] && args+=(-p "${project}")
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    args+=(--env-file "${REPO_ROOT}/.env")
  fi
  if [[ "${BUILD_LOCAL}" -eq 1 ]]; then
    docker compose "${args[@]}" up -d --pull never
  else
    docker compose "${args[@]}" up -d
  fi
}

run_container_migration() {
  local cid="$1"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  log "Creating atomic pre-migration backup inside '${cid}:/opt/data/.kit-tools/migration-backup-${ts}' ..."
  docker exec "${cid}" sh -c "
    set -e
    BK=/opt/data/.kit-tools/migration-backup-${ts}
    mkdir -p \"\$BK\"
    for item in config.yaml .env .kit-components.json .kit-omniroute.json .omh plugins/kit-setup; do
      if [ -e \"/opt/data/\$item\" ]; then
        mkdir -p \"\$BK/\$(dirname \"\$item\")\"
        cp -a \"/opt/data/\$item\" \"\$BK/\$item\"
      fi
    done
  "
  sync_kit_into_container "${cid}"

  log "Running kit bootstrap (recommended skills, k-skill, voice adapter, OMH routing patches) ..."
  docker exec "${cid}" /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py

  log "Checking OMH installation for v5.0.0 upgrade ..."
  docker exec "${cid}" sh -c '
    if [ -d /opt/data/plugins/omh ] || [ -d /opt/data/.omh ]; then
      /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omh-upgrade
    else
      echo "[kit] OMH not yet installed; install via Discord /setup or bootstrap.py"
    fi
  '

  if [[ "${APPLY_PRESETS}" -eq 1 ]]; then
    local pw=""
    pw="$(resolve_omniroute_password || true)"
    if [[ -z "${pw}" ]]; then
      warn "--apply-presets requested, but KIT_OMNIROUTE_PASSWORD is not set in environment or .env. Skipping preset apply."
    else
      log "Applying recommended OmniRoute resource combos + OMH 12-category routing chains ..."
      docker exec -e "KIT_OMNIROUTE_PASSWORD=${pw}" "${cid}" \
        /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset apply
    fi
  fi
}

run_verification() {
  local cid
  cid="$(detect_hermes_container)"
  [[ -n "${cid}" ]] || die "No running Hermes container found."
  log "Verifying Hermes container '${cid}' (read-only) ..."
  docker exec "${cid}" /opt/hermes/.venv/bin/python -c '
import sys
from pathlib import Path
sys.path.insert(0, "/opt/data/plugins/kit-setup")
tts_ok = False
slash_ok = False
try:
    import tools.tts_tool as tts_mod
    tts_ok = "none" in getattr(tts_mod, "VALID_PROVIDERS", ())
except Exception:
    pass
try:
    import gateway.run_slash as slash_mod
    slash_ok = hasattr(getattr(slash_mod, "GatewaySlashCommandsMixin", None), "_handle_call_command")
except Exception:
    pass
print("[verify] Voice patches (build-time):", {"tts": tts_ok, "call_slash": slash_ok})
import omh_routing
r = omh_routing.status("/opt/data")
print("[verify] OMH quota-aware routing patches:", r["status"], r.get("files", {}))
import components
st = components._read_state(Path("/opt/data"))
print("[verify] Installed component keys:", sorted(st.get("components", {}).keys()))
db = Path("/opt/data/state.db")
if db.is_file():
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        qc = con.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        con.close()
    print("[verify] state.db quick_check:", qc)
    if qc != "ok":
        sys.exit(1)
if r["status"] in ("drifted", "degraded", "error"):
    sys.exit(1)
'
  log "Verification complete."
}

case "${ACTION}" in
  install)
    command -v docker >/dev/null 2>&1 || die "Docker is required. Install Docker and Docker Compose v2 first."
    if [[ "${BUILD_LOCAL}" -eq 1 ]]; then
      build_local_images
    fi
    if [[ ! -f "${REPO_ROOT}/.env" ]] && [[ -n "${DISCORD_BOT_TOKEN:-}" ]]; then
      umask 077
      printf 'DISCORD_BOT_TOKEN=%s\n' "${DISCORD_BOT_TOKEN}" > "${REPO_ROOT}/.env"
      [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]] && printf 'KIT_OMNIROUTE_PASSWORD=%s\n' "${KIT_OMNIROUTE_PASSWORD}" >> "${REPO_ROOT}/.env"
    fi
    log "Starting Hermes (${DEFAULT_HERMES_IMAGE}) + Syncthing stack ..."
    docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d
    if [[ "${WITH_OMNIROUTE}" -eq 1 ]]; then
      pw="$(resolve_omniroute_password || true)"
      [[ -n "${pw}" ]] || die "KIT_OMNIROUTE_PASSWORD is required when --with-omniroute is set."
      log "Starting OmniRoute (${KIT_OMNIROUTE_IMAGE:-${DEFAULT_OMNIROUTE_IMAGE}}) stack ..."
      compose_omniroute_up
    fi
    cid="$(detect_hermes_container)"
    if [[ -n "${cid}" ]] && [[ "${APPLY_PRESETS}" -eq 1 ]]; then
      pw="$(resolve_omniroute_password || true)"
      if [[ -n "${pw}" ]]; then
        sleep 3
        docker exec -e "KIT_OMNIROUTE_PASSWORD=${pw}" "${cid}" \
          /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset apply
      else
        warn "--apply-presets requested, but KIT_OMNIROUTE_PASSWORD is not set in environment or .env. Skipping preset apply."
      fi
    fi
    run_verification
    ;;

  migrate|update)
    command -v docker >/dev/null 2>&1 || die "Docker is required."
    if [[ "${BUILD_LOCAL}" -eq 1 ]]; then
      build_local_images
    fi
    cid="$(detect_hermes_container)"
    if [[ -n "${cid}" ]]; then
      log "Found existing Hermes container '${cid}'. Performing non-destructive in-place migration ..."
      run_container_migration "${cid}"
      if [[ "${WITH_OMNIROUTE}" -eq 1 ]]; then
        log "Updating OmniRoute container stack ..."
        compose_omniroute_up
      fi
      run_verification
    else
      log "No running Hermes container detected; running compose update in ${REPO_ROOT} ..."
      docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d
      [[ "${WITH_OMNIROUTE}" -eq 1 ]] && compose_omniroute_up
      cid="$(detect_hermes_container)"
      [[ -n "${cid}" ]] && run_container_migration "${cid}"
      run_verification
    fi
    ;;

  preset)
    cid="$(detect_hermes_container)"
    [[ -n "${cid}" ]] || die "No running Hermes container found."
    sub="${EXTRA_ARGS[0]:-plan}"
    pw="${EXTRA_ARGS[1]:-$(resolve_omniroute_password || true)}"
    [[ -n "${pw}" ]] || die "Pass OmniRoute dashboard password as argument or KIT_OMNIROUTE_PASSWORD env var."
    docker exec -e "KIT_OMNIROUTE_PASSWORD=${pw}" "${cid}" \
      /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset "${sub}"
    ;;

  job-hunt)
    cid="$(detect_hermes_container)"
    [[ -n "${cid}" ]] || die "No running Hermes container found."
    log "Installing/updating Wendy-Nam/hermes-job-hunt-for-korean inside '${cid}' (native) ..."
    docker exec "${cid}" sh -eu -c '
      tmp="$(mktemp -d /tmp/job-hunt.XXXXXX)"
      trap '\''rm -rf "$tmp"'\'' EXIT
      git clone --depth 1 https://github.com/Wendy-Nam/hermes-job-hunt-for-korean.git "$tmp"
      /opt/hermes/.venv/bin/python "$tmp/native/install.py" \
        --home /opt/data \
        --job-root /opt/data/vaults/personal/job-hunting \
        --mail-backend none \
        "$@"
    ' _ "${EXTRA_ARGS[@]}"
    log "job-hunt native install/update complete."
    ;;

  verify|doctor)
    run_verification
    ;;
esac
