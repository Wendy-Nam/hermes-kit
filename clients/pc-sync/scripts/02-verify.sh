#!/usr/bin/env bash
# 2단계: 실제 동기화가 되는지 끝까지 확인한다.
# hermes-kit의 pair_device()는 "공유 설정 저장"까지만 확인하고 파일 이동은 검증하지 않는다.
# 이 스크립트는 실제로 왕복 파일을 만들어 진짜 동기화 여부를 본다.
. "$(dirname "$0")/lib.sh"
discover
CFG="$(local_st_config || true)"
[ -n "$CFG" ] || { echo "❌ 로컬 Syncthing 설정(config.xml)을 찾지 못했습니다. 01-pc-sync.sh 를 먼저 실행하세요." >&2; exit 1; }
APIKEY="$(st_apikey "$CFG")"; GUI="$(st_gui_addr "$CFG")"
FAIL=0
st() { curl -fsS -H "X-API-Key: $APIKEY" "http://$GUI/rest/$1" 2>/dev/null; }

echo "▶ 1. 로컬 Syncthing"
st "system/status" >/dev/null && echo "  ✅ 실행 중 (http://$GUI)" || { echo "  ❌ 응답 없음"; exit 1; }
LOCAL_ID="$(st system/status | json_field myID)"

echo "▶ 2. 서버 볼트 2개 등록 여부"
# in_hermes, not a hand-built hssh string: the python program has quotes in it, and re-joining
# arguments with $* drops them, so the container received `python3 -c import ...` and the whole
# step exited non-zero with no message.
SERVER_ID="$(in_hermes python3 -c "
import xml.etree.ElementTree as ET,urllib.request,json
k=ET.parse('/opt/syncthing-config/config.xml').getroot().findtext('gui/apikey')
r=urllib.request.Request('http://syncthing:8384/rest/system/status',headers={'X-API-Key':k})
print(json.load(urllib.request.urlopen(r,timeout=10))['myID'])
" 2>/dev/null | tr -d '\r')"
[ -n "$SERVER_ID" ] && echo "  ✅ 서버 기기: ${SERVER_ID:0:7}…" || { echo "  ❌ 서버 Syncthing에 접근 못함"; FAIL=1; }
if [ -n "$SERVER_ID" ]; then
  st config/devices | json_has_key deviceID "$SERVER_ID" && echo "  ✅ 서버가 이 PC에 등록됨" || { echo "  ❌ 서버에 이 PC가 없음 — 01-pc-sync.sh 재실행"; FAIL=1; }
  for fid in hermes-work hermes-personal; do
    st config/folders | json_has_key id "$fid" && echo "  ✅ 로컬 폴더 $fid" || { echo "  ❌ 로컬 폴더 $fid 없음 — 01-pc-sync.sh 재실행"; FAIL=1; }
  done
fi

echo "▶ 3. 실제 파일 왕복 (서버 → PC)"
# 키트는 이걸 확인하지 않는다. 공유가 설정돼 있어도 경로·권한 문제로 파일이 안 움직일 수 있다.
STAMP="hermes-sync-check-$(date +%s)"
echo "  · 서버에 시험 파일 작성: $STAMP"
hssh "docker exec -u 10000 $CONTAINER sh -c 'mkdir -p /var/syncthing/vaults/work && echo $STAMP > /var/syncthing/vaults/work/$STAMP.txt'" >/dev/null 2>&1 \
  || hssh "docker exec -u 10000 $CONTAINER sh -c 'echo $STAMP > /opt/data/vaults/work/$STAMP.txt'" >/dev/null 2>&1 \
  || { echo "  ⚠️ 서버에 시험 파일을 쓰지 못했습니다 (볼트 경로 확인)"; FAIL=1; }
GOT=""
for i in $(seq 1 30); do
  sleep 4
  for d in "$WORK_DIR" "$VAULT_ROOT"; do
    [ -f "$d/$STAMP.txt" ] && { GOT="$d/$STAMP.txt"; break; }
  done
  [ -n "$GOT" ] && break
done
if [ -n "$GOT" ]; then
  echo "  ✅ 서버→PC 도착 (약 $((i*4))초): $GOT"
  grep -q "$STAMP" "$GOT" && echo "  ✅ 내용 일치" || { echo "  ⚠️ 내용은 비어 보입니다 — 아직 전송 중일 수 있음"; }
  rm -f "$GOT"
else
  echo "  ❌ 2분 안에 PC로 오지 않았습니다."
  echo "     Syncthing 화면(http://$GUI)에서 '업로드 대기'/'동기화되지 않음' 항목을 확인하세요."
  FAIL=1
fi
hssh "docker exec -u 10000 $CONTAINER sh -c 'rm -f /var/syncthing/vaults/work/$STAMP.txt /opt/data/vaults/work/$STAMP.txt'" >/dev/null 2>&1 || true

echo ""
if [ "$FAIL" = 0 ]; then echo "✅ 동기화 확인 완료."; else echo "❌ 확인되지 않은 항목이 있습니다 (위 ❌ 표시)."; exit 1; fi
