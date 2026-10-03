#!/usr/bin/env bash
# 1단계: PC에 Syncthing·Obsidian를 준비하고, 키트 볼트 2개(work·personal)를 양방향 페어링한다.
#
# 이 스크립트는 서버 설정을 건드리지 않는다. 서버 쪽 설정은 hermes-kit의 /setup 이 전부 담당한다.
# 예전 버전은 이 단계에서 "wiki" 폴더 1개를 만들었으나, 키트는 볼트를 2개 만든다.
. "$(dirname "$0")/lib.sh"
discover

echo "▶ 볼트 위치: $VAULT_ROOT"
mkdir -p "$WORK_DIR" "$PERSONAL_DIR"
# 옵시디언이 시상시에 갱신하는 파일은 동기화에서 제외 (충돌·노이즈 방지)
for v in "$WORK_DIR" "$PERSONAL_DIR"; do
  [ -f "$v/.stignore" ] || printf '(?d).obsidian/workspace*\n(?d).trash/\n(?d).DS_Store\n(?d)Thumbs.db\n' > "$v/.stignore"
done

# ---------- 1) 로컬 Syncthing 확보 ----------
gh_latest_tag() {
  curl -fsSL "https://api.github.com/repos/$1/releases/latest" \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1
}
install_syncthing_portable() {
  echo "▶ Syncthing 설치 중 ($PORTABLE_ST_DIR)..."
  mkdir -p "$PORTABLE_ST_DIR/bin" "$PORTABLE_ST_DIR/home"
  local TAG PKG EXT ARCH TMP
  TAG="$(gh_latest_tag syncthing/syncthing)"
  [ -n "$TAG" ] || { echo "❌ syncthing 버전 조회 실패 (네트워크 확인)"; exit 1; }
  case "$OS" in
    mac) case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac
         PKG="syncthing-macos-$ARCH-$TAG"; EXT=zip ;;
    win) PKG="syncthing-windows-amd64-$TAG"; EXT=zip ;;
    *)   case "$(uname -m)" in aarch64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac
         PKG="syncthing-linux-$ARCH-$TAG"; EXT=tar.gz ;;
  esac
  TMP="$(mktemp -d)"
  curl -fsSL -o "$TMP/st.$EXT" "https://github.com/syncthing/syncthing/releases/download/$TAG/$PKG.$EXT"
  tar -xf "$TMP/st.$EXT" -C "$TMP"
  if [ "$OS" = win ]; then cp "$TMP/$PKG/syncthing.exe" "$PORTABLE_ST_DIR/bin/"
  else cp "$TMP/$PKG/syncthing" "$PORTABLE_ST_DIR/bin/"; chmod +x "$PORTABLE_ST_DIR/bin/syncthing"; fi
  rm -rf "$TMP"
  echo "✅ syncthing $TAG 설치"
}
register_autostart() {
  case "$OS" in
    mac)
      local PLIST="$HOME/Library/LaunchAgents/net.hermes.syncthing.plist"
      [ -f "$PLIST" ] && return 0
      mkdir -p "$HOME/Library/LaunchAgents"
      cat > "$PLIST" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>net.hermes.syncthing</string>
  <key>ProgramArguments</key><array>
    <string>$PORTABLE_ST_DIR/bin/syncthing</string><string>--no-browser</string>
    <string>--home=$PORTABLE_ST_DIR/home</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
XML
      launchctl load "$PLIST" 2>/dev/null || true
      echo "✅ 로그인 시 자동 시작 등록 (launchd)"
      ;;
    win)
      local STARTUP="${APPDATA:-$HOME/AppData/Roaming}/Microsoft/Windows/Start Menu/Programs/Startup"
      local VBS="$STARTUP/hermes-syncthing.vbs"
      [ -f "$VBS" ] && return 0
      mkdir -p "$STARTUP"
      printf 'CreateObject("WScript.Shell").Run """%s""" --no-browser --home="""%s""", 0\r\n' \
        "$(cygpath -w "$(portable_bin)")" "$(cygpath -w "$PORTABLE_ST_DIR/home")" > "$VBS"
      echo "✅ 로그인 시 자동 시작 등록 (시작 프로그램)"
      ;;
  esac
}

CFG="$(local_st_config || true)"
PORTABLE=0
if [ -z "$CFG" ]; then
  install_syncthing_portable
  "$(portable_bin)" generate --no-default-folder --home="$PORTABLE_ST_DIR/home" >/dev/null 2>&1
  CFG="$PORTABLE_ST_DIR/home/config.xml"; PORTABLE=1; register_autostart
else
  echo "· 기존 Syncthing 설치 발견: $CFG"
  case "$CFG" in "$PORTABLE_ST_DIR"*) PORTABLE=1 ;; esac
fi
APIKEY="$(st_apikey "$CFG")"; GUI="$(st_gui_addr "$CFG")"

if ! curl -fsS -H "X-API-Key: $APIKEY" "http://$GUI/rest/system/status" >/dev/null 2>&1; then
  if [ "$PORTABLE" = 1 ]; then
    nohup "$(portable_bin)" --no-browser --home="$PORTABLE_ST_DIR/home" >/dev/null 2>&1 &
  elif [ "$OS" = mac ]; then open -a Syncthing 2>/dev/null || true; fi
  sleep 6
fi
curl -fsS -H "X-API-Key: $APIKEY" "http://$GUI/rest/system/status" >/dev/null 2>&1 \
  || { echo "❌ 로컬 Syncthing이 실행되지 않습니다. 앱을 직접 실행한 뒤 재실행하세요." >&2; exit 3; }
echo "✅ 로컬 Syncthing 실행 중 (http://$GUI)"
LOCAL_ID="$(curl -fsS -H "X-API-Key: $APIKEY" "http://$GUI/rest/system/status" | json_field myID)"
[ -n "$LOCAL_ID" ] || { echo "❌ 로컬 기기 ID를 읽지 못함"; exit 1; }
echo "· 로컬 기기 ID: ${LOCAL_ID:0:7}…"

# ---------- 2) 서버측 등록 (볼트 2개) ----------
hssh "mkdir -p /opt/data/tmp" >/dev/null
hscp "$SKILL_DIR/scripts/remote/st_pair.py" "$SSH_ALIAS:/opt/data/tmp/" >/dev/null
PAIR_OUT="$(hssh "docker exec -u 10000 $CONTAINER python3 /opt/data/tmp/st_pair.py $LOCAL_ID 내-PC" 2>&1)" || {
  echo "$PAIR_OUT" >&2; echo "❌ 서버 등록 실패 (위 메시지 확인)" >&2; exit 1; }
echo "$PAIR_OUT" | grep -v '^SERVER_ID=' | sed 's/^/  /'
SERVER_ID="$(echo "$PAIR_OUT" | sed -n 's/^SERVER_ID=//p')"
[ -n "$SERVER_ID" ] || { echo "❌ 서버 기기 ID를 받지 못했습니다." >&2; exit 1; }

# ---------- 3) 로컬측 등록 + 볼트 2개 연결 ----------
api() { curl -fsS -X "$1" -H "X-API-Key: $APIKEY" -H "Content-Type: application/json" ${3:+-d "$3"} "http://$GUI/$2"; }
if ! api GET rest/config/devices | json_has_key deviceID "$SERVER_ID"; then
  api POST rest/config/devices "{\"deviceID\":\"$SERVER_ID\",\"name\":\"hermes-vps\"}" >/dev/null
  echo "✅ 서버 기기 등록(로컬)"
else
  echo "· 서버 기기 이미 등록됨(로컬)"
fi
native() { if [ "$OS" = win ] && command -v cygpath >/dev/null 2>&1; then cygpath -w "$1" | sed 's/\\/\\\\/g'; else printf '%s' "$1"; fi; }
link_folder() {
  local fid="$1" label="$2" dir="$3"
  if api GET rest/config/folders | json_has_key id "$fid"; then
    echo "· 로컬에 '$fid' 폴더가 이미 있음 — Syncthing 화면에서 공유 중인지 확인하세요."
    return 0
  fi
  api POST rest/config/folders "{\"id\":\"$fid\",\"label\":\"$label\",\"path\":\"$(native "$dir")\",\"type\":\"sendreceive\",\"devices\":[{\"deviceID\":\"$SERVER_ID\"},{\"deviceID\":\"$LOCAL_ID\"}],\"rescanIntervalS\":60,\"fsWatcherEnabled\":true}" >/dev/null
  echo "✅ $label 연결(로컬): $dir"
}
link_folder "hermes-work"     "업무 볼트" "$WORK_DIR"
link_folder "hermes-personal" "개인 볼트" "$PERSONAL_DIR"

# ---------- 4) Obsidian 설치 (없으면) ----------
obsidian_installed() {
  case "$OS" in
    mac) [ -d "/Applications/Obsidian.app" ] || [ -d "$HOME/Applications/Obsidian.app" ] ;;
    win) [ -f "${LOCALAPPDATA:-$HOME/AppData/Local}/Obsidian/Obsidian.exe" ] \
      || [ -f "${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/Obsidian/Obsidian.exe" ] ;;
    *) command -v obsidian >/dev/null 2>&1 ;;
  esac
}
if ! obsidian_installed; then
  echo "▶ Obsidian 설치 중..."
  case "$OS" in
    mac)
      if command -v brew >/dev/null 2>&1; then brew install --cask obsidian
      else
        URL="$(curl -fsSL https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest \
          | sed -n 's/.*"browser_download_url": *"\([^"]*universal\.dmg\)".*/\1/p' | head -1)"
        [ -n "$URL" ] || URL="$(curl -fsSL https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest \
          | sed -n 's/.*"browser_download_url": *"\([^"]*\.dmg\)".*/\1/p' | head -1)"
        TMP="$(mktemp -d)"; curl -fsSL -o "$TMP/obsidian.dmg" "$URL"
        MNT="$(hdiutil attach -nobrowse "$TMP/obsidian.dmg" | sed -n 's/.*\(\/Volumes\/.*\)/\1/p' | head -1)"
        cp -R "$MNT/Obsidian.app" /Applications/; hdiutil detach "$MNT" >/dev/null; rm -rf "$TMP"
      fi
      echo "✅ Obsidian 설치" ;;
    win)
      if command -v winget.exe >/dev/null 2>&1 || command -v winget >/dev/null 2>&1; then
        winget install -e --id Obsidian.Obsidian --accept-source-agreements --accept-package-agreements
        echo "✅ Obsidian 설치"
      else
        URL="$(curl -fsSL https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest \
          | sed -n 's/.*"browser_download_url": *"\([^"]*\.exe\)".*/\1/p' | grep -vi arm | head -1)"
        TMP="$(mktemp -d)"; curl -fsSL -o "$TMP/ObsidianSetup.exe" "$URL"
        cmd //c start "" "$(cygpath -w "$TMP/ObsidianSetup.exe")" || true
        echo "· 설치 창이 뜨면 완료해 주세요."
      fi ;;
    *) echo "· Linux는 https://obsidian.md/download 에서 수동 설치" ;;
  esac
else
  echo "· Obsidian 이미 설치됨"
fi

# ---------- 5) 볼트 열기 ----------
case "$OS" in
  mac) open "obsidian://open?path=$VAULT_ROOT" 2>/dev/null || true ;;
  win) cmd //c start "" "obsidian://open?path=$(cygpath -w "$VAULT_ROOT")" 2>/dev/null || true ;;
esac
echo ""
echo "🎉 PC 셋업 완료. 첫 동기화에 1~2분 걸릴 수 있습니다."
echo "   Obsidian에서 열리려면: 'Open folder as vault' → $WORK_DIR 또는 $PERSONAL_DIR"
echo ""
echo "다음: bash scripts/02-verify.sh"
