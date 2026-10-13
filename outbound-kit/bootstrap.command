#!/bin/bash
# Native macOS bootstrap for machines without a suitable host Python.
set -euo pipefail
umask 077

TAG="v0.21.7"
COMMIT="71d34bad1045610252eda02ee79549436896e784"
INSTALLER_SHA256="034845e34289813ff5fb7fd3e071ec69f6b14aee8ba297a477b31dda6374cb86"
INSTALLER_URL="https://raw.githubusercontent.com/NousResearch/hermes-agent/$COMMIT/scripts/install.sh"

die() { printf 'Hermes Outbound bootstrap: %s\n' "$*" >&2; exit 1; }
command -v uname >/dev/null 2>&1 || die "uname이 필요합니다."
[ "$(uname -s)" = "Darwin" ] || die "bootstrap.command는 macOS 전용입니다. Windows에서는 bootstrap.ps1을 사용하세요."

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || die "키트 경로를 확인할 수 없습니다."
START="$SCRIPT_DIR/start.py"
CONFIG="$SCRIPT_DIR/setup.json"
[ -f "$START" ] || die "start.py가 없습니다. 키트 ZIP을 다시 받아 압축을 완전히 푸세요."
[ -f "$CONFIG" ] || die "setup.json이 없습니다. 키트 설정을 먼저 생성해 같은 폴더에 두세요."

USER_HOME=${HOME:?HOME이 없어 기본 설치 경로를 정할 수 없습니다.}
HERMES_HOME="$USER_HOME/.hermes-outbound"
INSTALL_DIR="$HERMES_HOME/hermes-agent"
TOOLS_DIR="$HERMES_HOME/tools"
MARKER="$INSTALL_DIR/.hermes-bootstrap-complete"
FACTS="$TOOLS_DIR/facts.json"

MODE=app
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
  printf '사용 화면을 선택하세요: app(기본, Hermes Desktop) / terminal: ' >/dev/tty
  IFS= read -r answer </dev/tty || answer=""
  case "${answer:-app}" in
    app|APP|App|"") MODE=app ;;
    terminal|TERMINAL|Terminal) MODE=terminal ;;
    *) die "app 또는 terminal만 입력하세요." ;;
  esac
fi

resolve_managed_python() {
  [ -f "$FACTS" ] && [ ! -L "$FACTS" ] || return 1
  entry=$(tr -d '\r\n' <"$FACTS" | sed -n 's/.*"python"[[:space:]]*:[[:space:]]*{[^}]*"entry"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  case "$entry" in
    ""|/*|*..*|*[!A-Za-z0-9._/-]*) return 1 ;;
  esac
  candidate="$TOOLS_DIR/$entry/bin/python3"
  [ -f "$candidate" ] && [ -x "$candidate" ] || return 1
  parent=$(CDPATH= cd -- "$(dirname -- "$candidate")" && pwd -P) || return 1
  resolved="$parent/$(basename -- "$candidate")"
  case "$resolved" in "$TOOLS_DIR"/*) printf '%s\n' "$resolved" ;; *) return 1 ;; esac
}

marker_matches() {
  [ -f "$MARKER" ] && [ ! -L "$MARKER" ] || return 1
  grep -Eq '"pinnedCommit"[[:space:]]*:[[:space:]]*"'"$COMMIT"'"' "$MARKER"
}

desktop_present() {
  for app in "$INSTALL_DIR"/apps/desktop/release/mac*/Hermes.app/Contents/MacOS/Hermes; do
    [ -f "$app" ] && [ -x "$app" ] && return 0
  done
  return 1
}

PYTHON=""
if [ -e "$INSTALL_DIR" ]; then
  [ -d "$INSTALL_DIR/.git" ] || die "기존 $INSTALL_DIR 은 공식 scoped checkout으로 확인되지 않아 보존했습니다. 새 home을 검토하세요."
  marker_matches || die "기존 scoped checkout의 pinned commit 증거가 다릅니다. 자동 reset하지 않았습니다. 수동 검토하세요."
  PYTHON=$(resolve_managed_python) || die "기존 scoped checkout의 PM facts/runtime이 불완전합니다. 자동 재설치하지 않았습니다."
  [ "$MODE" != app ] || desktop_present || die "기존 scoped 설치에 Hermes Desktop 산출물이 없습니다. terminal을 선택하면 기존 runtime을 재사용합니다. 자동 reset/build하지 않았습니다."
  printf '검증된 기존 Hermes runtime을 재사용합니다: %s\n' "$INSTALL_DIR"
else
  command -v curl >/dev/null 2>&1 || die "curl이 필요합니다. macOS Command Line Tools/네트워크 정책을 확인하세요."
  command -v shasum >/dev/null 2>&1 || die "shasum이 필요합니다. macOS 기본 도구 상태를 확인하세요."
  command -v bash >/dev/null 2>&1 || die "bash를 찾을 수 없습니다."
  if command -v hermes >/dev/null 2>&1; then
    printf '기존 전역 Hermes는 사용하거나 덮어쓰지 않습니다: %s\n' "$(command -v hermes)"
  fi
  temporary=$(mktemp -d "${TMPDIR:-/tmp}/hermes-outbound-bootstrap.XXXXXXXX") || die "임시 폴더를 만들 수 없습니다."
  cleanup() {
    case "$temporary" in "${TMPDIR:-/tmp}"/hermes-outbound-bootstrap.*) rm -rf -- "$temporary" ;; esac
  }
  trap cleanup EXIT INT TERM
  artifact="$temporary/hermes-install-$TAG.sh"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    "$INSTALLER_URL" --output "$artifact" || die "공식 고정 installer 다운로드에 실패했습니다."
  actual=$(shasum -a 256 "$artifact" | awk '{print $1}')
  [ "$actual" = "$INSTALLER_SHA256" ] || die "installer SHA-256이 검토값과 다릅니다. 실행하지 않았습니다."
  args=("$artifact" --branch main --commit "$COMMIT" --hermes-home "$HERMES_HOME" \
        --dir "$INSTALL_DIR" --non-interactive --skip-browser --skip-computer-use)
  [ "$MODE" = app ] && args+=(--include-desktop)
  mkdir -p -- "$HERMES_HOME"
  # Upstream writes ~/.local and shell lines. Override HOME for this child so all
  # such writes remain in the dedicated Hermes home, never the user's shared home.
  HOME="$HERMES_HOME" HERMES_HOME="$HERMES_HOME" HERMES_RUNTIME_DIR="$TOOLS_DIR" \
    bash "${args[@]}" || die "공식 Hermes installer가 실패했습니다. 위 오류를 확인하세요."
  marker_matches || die "설치 완료 marker의 pinned commit을 확인하지 못했습니다."
  PYTHON=$(resolve_managed_python) || die "설치된 PM facts에서 managed Python을 확인하지 못했습니다."
  [ "$MODE" != app ] || desktop_present || die "installer는 성공했지만 Hermes Desktop 산출물을 확인하지 못했습니다."
fi

export HERMES_HOME HERMES_RUNTIME_DIR="$TOOLS_DIR"
exec "$PYTHON" -P "$START" --config "$CONFIG"
