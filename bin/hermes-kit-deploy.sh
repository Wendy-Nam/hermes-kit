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
#     latest `voice_adapter.py`, `omh_routing.py`, `omniroute_presets.py`, and OMH v5.0.0 upgrader.
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
DEFAULT_OMNIROUTE_IMAGE="ghcr.io/wendy-nam/hermes-kit:omniroute-rtk-json-3"

SSH_TARGET=""
SSH_PORT="22"
SSH_IDENTITY=""
REMOTE_DIR="/opt/hermes-kit"
WITH_OMNIROUTE=0
BUILD_LOCAL=0
APPLY_PRESETS=0
CONTAINER_NAME=""
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

SSH Options (optional — omit to run locally on the current machine):
  --ssh <user@host>        Run deployment on a remote VPS over SSH
  -p, --port <port>        SSH port (default: 22)
  -i, --identity <file>    SSH private key path
  --remote-dir <path>      Target directory on remote server (default: /opt/hermes-kit)

Options:
  --with-omniroute         Include OmniRoute (v3.8.54-web + RTK envelope + CommandCode/UI overlay)
  --build-local            Build Docker images locally from the repository instead of pulling GHCR tags
  --apply-presets          Automatically apply recommended OmniRoute combos + OMH 12-category routing
  --container <name>       Target an existing Hermes container by name (auto-detected if omitted)
  -h, --help               Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh)
      SSH_TARGET="$2"
      shift 2
      ;;
    -p|--port)
      SSH_PORT="$2"
      shift 2
      ;;
    -i|--identity)
      SSH_IDENTITY="$2"
      shift 2
      ;;
    --remote-dir)
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
      CONTAINER_NAME="$2"
      shift 2
      ;;
    install|migrate|update|verify|doctor|preset)
      ACTION="$1"
      shift
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  usage >&2
  exit 2
fi

EXTRA_ARGS=("$@")

# ── Remote SSH Dispatch ───────────────────────────────────────────────────────────────────────
if [[ -n "${SSH_TARGET}" ]]; then
  SSH_OPTS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new)
  if [[ -n "${SSH_IDENTITY}" ]]; then
    SSH_OPTS+=(-i "${SSH_IDENTITY}")
  fi
  echo "[deploy] Syncing hermes-kit (${RELEASE_TAG}) to ${SSH_TARGET}:${REMOTE_DIR} ..."
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "mkdir -p '${REMOTE_DIR}'"
  tar -C "${REPO_ROOT}" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    -czf - . | ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "tar -xzf - -C '${REMOTE_DIR}'"

  FORWARD_FLAGS=()
  [[ "${WITH_OMNIROUTE}" -eq 1 ]] && FORWARD_FLAGS+=(--with-omniroute)
  [[ "${BUILD_LOCAL}" -eq 1 ]] && FORWARD_FLAGS+=(--build-local)
  [[ "${APPLY_PRESETS}" -eq 1 ]] && FORWARD_FLAGS+=(--apply-presets)
  [[ -n "${CONTAINER_NAME}" ]] && FORWARD_FLAGS+=(--container "${CONTAINER_NAME}")

  REMOTE_ENV=()
  [[ -n "${DISCORD_BOT_TOKEN:-}" ]] && REMOTE_ENV+=("DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}")
  [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]] && REMOTE_ENV+=("KIT_OMNIROUTE_PASSWORD=${KIT_OMNIROUTE_PASSWORD}")

  echo "[deploy] Executing '${ACTION}' on ${SSH_TARGET} ..."
  exec ssh -t "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "cd '${REMOTE_DIR}' && env ${REMOTE_ENV[*]:-} bash ./bin/hermes-kit-deploy.sh ${FORWARD_FLAGS[*]:-} ${ACTION} ${EXTRA_ARGS[*]:-}"
fi

# ── Local Execution Helpers ───────────────────────────────────────────────────────────────────
log() { printf '\033[1;34m[hermes-kit]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[hermes-kit][warn]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[hermes-kit][error]\033[0m %s\n' "$*" >&2; exit 1; }

detect_hermes_container() {
  if [[ -n "${CONTAINER_NAME}" ]]; then
    echo "${CONTAINER_NAME}"
    return
  fi
  local found
  found="$(docker ps --format '{{.Names}}\t{{.Image}}' | awk '$1 ~ /hermes/ || $2 ~ /hermes/ {print $1; exit}')"
  echo "${found}"
}

build_local_images() {
  log "Building hermes-kit:${RELEASE_TAG} locally from Dockerfile ..."
  docker build \
    --build-arg "HERMES_BASE_IMAGE=${HERMES_BASE_IMAGE}" \
    --build-arg "HERMES_VERSION=${HERMES_VERSION}" \
    --build-arg "RTK_VERSION=${RTK_VERSION}" \
    --build-arg "KIT_VERSION=${KIT_VERSION}" \
    -t "hermes-kit:${RELEASE_TAG}" \
    "${REPO_ROOT}"
  export KIT_HERMES_IMAGE="hermes-kit:${RELEASE_TAG}"

  if [[ "${WITH_OMNIROUTE}" -eq 1 ]]; then
    log "Building OmniRoute v3.8.54-web RTK adapter & CommandCode/UI overlay locally ..."
    docker build -t "hermes-kit:omniroute-adapter" "${REPO_ROOT}/advanced/omniroute-rtk-envelope"
    docker build \
      --build-arg "KIT_OMNIROUTE_IMAGE=hermes-kit:omniroute-adapter" \
      -t "hermes-kit:omniroute-cc-ui" \
      "${REPO_ROOT}/advanced/omniroute-patches"
    export KIT_OMNIROUTE_IMAGE="hermes-kit:omniroute-cc-ui"
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
    cp -rf /opt/kit/plugins/kit-setup/. /opt/data/plugins/kit-setup/
    chown -R 10000:10000 /opt/data/plugins/kit-setup 2>/dev/null || true
  "
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
    if [[ -z "${KIT_OMNIROUTE_PASSWORD:-}" ]]; then
      warn "--apply-presets requested, but KIT_OMNIROUTE_PASSWORD is not set in environment. Skipping preset apply."
    else
      log "Applying recommended OmniRoute resource combos + OMH 12-category routing chains ..."
      docker exec -e "KIT_OMNIROUTE_PASSWORD=${KIT_OMNIROUTE_PASSWORD}" "${cid}" \
        /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset apply
    fi
  fi
}

run_verification() {
  local cid
  cid="$(detect_hermes_container)"
  [[ -n "${cid}" ]] || die "No running Hermes container found."
  log "Verifying Hermes container '${cid}' ..."
  docker exec "${cid}" /opt/hermes/.venv/bin/python -c '
import sys
from pathlib import Path
sys.path.insert(0, "/opt/data/plugins/kit-setup")
import voice_adapter
v = voice_adapter.install_all()
print("[verify] Voice quick-call & auto-follow adapter:", v)
import omh_routing
r = omh_routing.status("/opt/data")
print("[verify] OMH quota-aware routing patches:", r["status"], r.get("files", {}))
import components
st = components._read_state(Path("/opt/data"))
print("[verify] Installed component keys:", sorted(st.get("components", {}).keys()))
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
    log "Starting Hermes (${KIT_HERMES_IMAGE:-${DEFAULT_HERMES_IMAGE}}) + Syncthing stack ..."
    docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d
    if [[ "${WITH_OMNIROUTE}" -eq 1 ]]; then
      [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]] || grep -q '^KIT_OMNIROUTE_PASSWORD=' "${REPO_ROOT}/.env" 2>/dev/null \
        || die "KIT_OMNIROUTE_PASSWORD is required when --with-omniroute is set."
      log "Starting OmniRoute (${KIT_OMNIROUTE_IMAGE:-${DEFAULT_OMNIROUTE_IMAGE}}) stack ..."
      docker compose -f "${REPO_ROOT}/advanced/docker-compose.omniroute.yml" up -d
    fi
    cid="$(detect_hermes_container)"
    if [[ -n "${cid}" ]] && [[ "${APPLY_PRESETS}" -eq 1 ]] && [[ -n "${KIT_OMNIROUTE_PASSWORD:-}" ]]; then
      sleep 3
      docker exec -e "KIT_OMNIROUTE_PASSWORD=${KIT_OMNIROUTE_PASSWORD}" "${cid}" \
        /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset apply
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
        docker compose -f "${REPO_ROOT}/advanced/docker-compose.omniroute.yml" up -d
      fi
      run_verification
    else
      log "No running Hermes container detected; running compose update in ${REPO_ROOT} ..."
      docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d
      [[ "${WITH_OMNIROUTE}" -eq 1 ]] && docker compose -f "${REPO_ROOT}/advanced/docker-compose.omniroute.yml" up -d
      cid="$(detect_hermes_container)"
      [[ -n "${cid}" ]] && run_container_migration "${cid}"
      run_verification
    fi
    ;;

  preset)
    cid="$(detect_hermes_container)"
    [[ -n "${cid}" ]] || die "No running Hermes container found."
    sub="${EXTRA_ARGS[0]:-plan}"
    pw="${EXTRA_ARGS[1]:-${KIT_OMNIROUTE_PASSWORD:-}}"
    [[ -n "${pw}" ]] || die "Pass OmniRoute dashboard password as argument or KIT_OMNIROUTE_PASSWORD env var."
    docker exec -e "KIT_OMNIROUTE_PASSWORD=${pw}" "${cid}" \
      /opt/hermes/.venv/bin/python /opt/data/plugins/kit-setup/bootstrap.py omniroute-preset "${sub}"
    ;;

  verify|doctor)
    run_verification
    ;;
esac
