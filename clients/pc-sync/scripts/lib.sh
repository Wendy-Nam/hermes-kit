#!/usr/bin/env bash
# 공용 헬퍼. 서버에서는 "-kit" 이미지로 띄운 컨테이너만 다룬다.
# 이전 버전은 /docker/hermes-agent-* (Hostinger 앱 카탈로그)를 찾았다 — 지금은 그 경로가 없다.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
[ -f "$SKILL_DIR/setup.env" ] && . "$SKILL_DIR/setup.env"

SSH_ALIAS="${SSH_ALIAS:-hermes}"
PORTABLE_ST_DIR="${PORTABLE_ST_DIR:-$HOME/.hermes-sync}"
# 키트는 볼트를 2개 만든다. 예전의 단일 wiki 폴더 구조는 더 이상 쓰지 않는다.
VAULT_ROOT="${LOCAL_VAULT_ROOT:-$HOME/HermesVaults}"
WORK_DIR="$VAULT_ROOT/work"
PERSONAL_DIR="$VAULT_ROOT/personal"

case "$(uname -s)" in
  Darwin) OS=mac ;;
  MINGW*|MSYS*|CYGWIN*) OS=win ;;
  *) OS=linux ;;
esac

# ssh 는 인자를 공백으로 이어 붙여 하나의 원격 명령 문자열을 만든다. 그래서 인자에 들어 있던
# 따옴표가 그대로 사라진다. 예를 들어
#   hssh "python3" "-c" "import sys"
# 는 서버에 python3 -c import sys 로 도착하고, 파이썬은 import 라는 파일을 찾으려다
# rc=2 로 죽는다. 호출한 곳에는 "서버 Syncthing 이 응답하지 않는다" 만 보이므로, 실제 원인은
# 한참 위에 있다. 이 문제를 CI 가 처음 잡아냈다.
#
# 셸에서 특별한 의미를 가지는 인자만 작은따옴표로 감싼 뒤 보낸다. 파이썬 코드의 줄바꿈과
# 내부 따옴표가 그대로 살아남고, 인용이 필요 없는 일반 단어(docker, test, -d)는 건드리지 않아
# 파이프라인을 쓰는 호출도 그대로 동작한다. printf %q 를 전체에 적용하면 첫 단어 docker 까지
# 이스케이프되어 명령을 못 찾으므로(rc=127) 쓰지 않는다.
# ssh 는 인자를 공백으로 이어 붙여 하나의 원격 명령 문자열을 만든다. 그래서 인자에 들어 있던
# 따옴표가 그대로 사라진다. 예를 들어
#   hssh "python3" "-c" "import sys"
# 는 서버에 python3 -c import sys 로 도착하고, 파이썬은 import 라는 파일을 찾으려다
# rc=2 로 죽는다. 호출한 곳에는 "서버 Syncthing 이 응답하지 않는다" 만 보이므로, 실제 원인은
# 한참 위에 있다. 이 문제를 CI 가 처음 잡아냈다.
#
# 인용은 프로그램 본문에만 건다. `test -d /opt/data/x` 같은 명령은 원래 여러 단어이고
# 원격 셸이 공백으로 나눠 실행해야 하므로, 통째로 작은따옴표로 감싸면 셸이 그 이름을 가진
# 프로그램을 찾다 rc=127 로 죽는다. -c 다음에 오는 인자만 프로그램으로 본다.
quote_arg() {
  local out="" rest="$1"
  # 작은따옴표로 감싸는 동안 안의 작은따옴표는 ' \ ' ' 로 빠져나와야 한다(닫기·백슬래시·
  # 따옴표·여닫기). 예전 코드는 여기를 ' \ ' ' 가 아니라 ' \ ' 로 닫아서 파이썬 코드가
  # \ '' 로 어글러져 SyntaxError 가 났고, 그 증상은 호출한 곳에서 "Syncthing 이 응답하지
  # 않는다" 였다. 한 겹 씌웠다가 두 겹 빠지는, 가장 찾기 어려운 종류의 인용 오류다.
  while [ -n "$rest" ]; do
    case "$rest" in
      *"'"*) out="$out${rest%%\'*}'\\''"; rest="${rest#*\'}" ;;
      *)     out="$out$rest"; rest="" ;;
    esac
  done
  printf "'%s'" "$out"
}

hssh() {
  local a in_program=0 quoted=()
  for a in "$@"; do
    case "$a" in
      -c) quoted+=("-c"); in_program=1 ;;
      # 파이프라인은 원격 셸이 파싱해야 하므로 인용하지 않는다.
      # A pipe marks a command line the remote shell has to parse, so it must not be quoted into
      # a single word — and a redirection and a pipe can arrive as two separate arguments, which
      # is what `in_hermes python3 -c "…" 2>/dev/null | tr -d "\r"` does. Neither may be quoted
      # after the program, or the remote shell gets one word and the pipeline never runs.
      # ";" and "&" are not listed: any string containing ";" already ends in one, and "&&"
      # contains "&", so extra patterns for them here would be dead.
      # "&&" contains "&" and "||" contains "|", so testing the single characters covers all of
      # them; listing the longer forms first is what shellcheck correctly calls dead code.
      *"|"*|*"&"*|*">"*|*"<"*) quoted+=("$a") ;;
      *)
        if [ "$in_program" = 1 ]; then quoted+=("$(quote_arg "$a")"); in_program=0
        else quoted+=("$a"); fi
        ;;
    esac
  done
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$SSH_ALIAS" "${quoted[*]}"
}
hscp() { scp -q -o BatchMode=yes -o ConnectTimeout=15 "$@"; }

# 키트 컨테이너 탐색. 컨테이너 이름에 hermes가 들어가고 kit 이미지를 쓰는 것만 Pick한다.
discover() {
  CONTAINER="$(hssh 'docker ps --format "{{.Names}}|{{.Image}}" | grep -i hermes | grep -iv omniroute | head -1' | cut -d'|' -f1)"
  if [ -z "$CONTAINER" ]; then
    cat >&2 <<'EOF'
❌ 실행 중인 Hermes 키트 컨테이너를 찾지 못했습니다.

먼저 hermes-kit을 배포해야 합니다.
  1) Hostinger Docker Manager에 docker-compose.yml을 붙여넣으세요.
  2) 환경변수 DISCORD_BOT_TOKEN에 봇 토큰을 넣으세요.
  3) 배포가 끝나면 컨테이너 로그의 [kit] 봇 초대: 링크로 서버에 초대하세요.
  4) Discord에서 /setup 을 실행해 설정 순서를 끝내세요.
자세한 내용은 hermes-kit 저장소의 README와 docs/instructor-install-guide.md를 보세요.
EOF
    exit 1
  fi
  DATA_DIR="/opt/data"
}

# 서버에서 실행: hermes 컨테이너 안(uid 10000)으로 명령을 넘긴다.
# root로 실행하면 파일 소유권이 오염되므로 10000 고정.
#
# "$*" 로 인자를 이어 붙이면 따옴표가 사라진다. 예를 들어
#   in_hermes "python3 -c \"import sys\""
# 는 컨테이너에 `python3 -c import sys` 로 도착해 파싱 오류(rc=2)가 되고, 호출한 곳에서는
# 그 rc를 "Syncthing이 응답하지 않는다" 같은 전혀 다른 증상으로 본다.
# 인자를 그대로 넘기면 ssh 가 하나의 원격 명령 문자열로 조립하므로 따옴표가 보존된다.
in_hermes() { hssh "docker exec -u 10000 $CONTAINER" "$@"; }

# Syncthing은 hermes 컨테이너가 아니라 별도 컨테이너다.
# Syncthing v1.27 이상은 /rest/system/status 에도 API 키를 요구하고, 키 없이 호출하면 403 이라
# 컨테이너가 멀쩡한데도 "응답하지 않는다"로 보고된다. 키는 마운트된 config.xml 에서 읽는다.
syncthing_ready() { in_hermes python3 -c "
import urllib.request,sys
try:
    import xml.etree.ElementTree as ET
    k=ET.parse('/opt/syncthing-config/config.xml').getroot().findtext('gui/apikey')
    r=urllib.request.Request('http://syncthing:8384/rest/system/status',headers={'X-API-Key':k or ''})
    urllib.request.urlopen(r,timeout=5)
except Exception: sys.exit(1)
" 2>/dev/null; }

portable_bin() { if [ "$OS" = win ]; then echo "$PORTABLE_ST_DIR/bin/syncthing.exe"; else echo "$PORTABLE_ST_DIR/bin/syncthing"; fi; }

# ---- 로컬 Syncthing 헬퍼 (기존 설치를 우선 재사용) ----
local_st_config() {
  local candidates=() c
  case "$OS" in
    mac) candidates=("$HOME/Library/Application Support/Syncthing/config.xml") ;;
    win) candidates=("${LOCALAPPDATA:-$HOME/AppData/Local}/Syncthing/config.xml") ;;
    *)   candidates=("$HOME/.local/state/syncthing/config.xml" "$HOME/.config/syncthing/config.xml") ;;
  esac
  candidates+=("$PORTABLE_ST_DIR/home/config.xml")
  for c in "${candidates[@]}"; do
    if [ -f "$c" ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}
st_apikey()   { sed -n 's/.*<apikey>\(.*\)<\/apikey>.*/\1/p' "$1" | head -1; }
st_gui_addr() {
  # XML 파서로 읽는다. sed + head -1 은 config.xml 의 첫 <address> 를 고르는데, 그건
  # globalAnnounceEnabled 나 listen 주소일 수 있어 GUI 주소가 아닌 포트를 돌려준다.
  python3 -c "
import sys, xml.etree.ElementTree as ET
try: print(ET.parse(sys.argv[1]).getroot().findtext('gui/address') or '')
except Exception: print('')" "$1" 2>/dev/null
}

# ---- Syncthing REST 응답 파싱 ----
# Syncthing 은 버전마다 JSON 공백이 달라 "myID":"X" 와 "myID": "X" 가 모두 나온다.
# grep/sed 로 특정 필드를 찾으면 조용히 아무것도 못 찾은 채 "정상"처럼 지나가므로,
# 필드 추출과 존재 확인은 전부 JSON 파서로 한다. 파싱 실패는 비정상(비영)으로 알린다.
json_field() { python3 -c "
import json,sys
try: print(json.load(sys.stdin).get(sys.argv[1],''))
except Exception: print('')" "$1"; }

json_has_key() { python3 -c "
import json,sys
try: rows=json.load(sys.stdin)
except Exception: sys.exit(1)
if not isinstance(rows,list): sys.exit(1)
sys.exit(0 if any(str(r.get(sys.argv[1],''))==sys.argv[2] for r in rows) else 1)" "$1" "$2"; }
