#!/usr/bin/env python3
"""서버 Syncthing에 PC 기기 등록 + 키트 볼트 2개 공유. hermes 컨테이너 안(uid 10000)에서 실행.

hermes-kit은 Syncthing을 hermes 컨테이너가 아니라 별도 컨테이너로 돌린다.
따라서 이전 방식(/opt/data/.config/syncthing, 127.0.0.1:8384)은 동작하지 않는다.
키트가 syncthing_setup.py에서 쓰는 것과 같은 경로·주소를 사용한다:
  - 설정 파일: /opt/syncthing-config/config.xml  (hermes에 read-only로 마운트됨)
  - API 주소  : http://syncthing:8384            (같은 compose 네트워크의 syncthing 서비스)

사용: docker exec -u 10000 <hermes 컨테이너> python3 /opt/data/tmp/st_pair.py <PC_DEVICE_ID> [기기이름]
출력 마지막 줄: SERVER_ID=<서버 기기 ID>   (로컬 쪽 페어링에 사용)
"""
import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

# The defaults are the kit's own mount points. The environment overrides exist for the
# Linux CI test, which runs a real Syncthing outside the compose network: there the
# same script has to talk to a different address and a different config file. A test
# that has to rewrite the file to run is testing a rewritten file.
CONFIG = os.environ.get("HERMES_ST_CONFIG", "/opt/syncthing-config/config.xml")
API = os.environ.get("HERMES_ST_API", "http://syncthing:8384")
# hermes-kit이 만드는 볼트. id/경로는 kits의 syncthing_setup.FOLDERS와 반드시 같아야 한다.
FOLDERS = (
    ("hermes-work", "업무 볼트", os.environ.get("HERMES_ST_WORK", "/var/syncthing/vaults/work")),
    ("hermes-personal", "개인 볼트",
     os.environ.get("HERMES_ST_PERSONAL", "/var/syncthing/vaults/personal")),
)

if len(sys.argv) < 2:
    raise SystemExit("사용: st_pair.py <PC_DEVICE_ID> [기기이름]")
local_id = sys.argv[1].strip()
name = (sys.argv[2] if len(sys.argv) > 2 else "내 PC")[:80]


def req(method, path, body=None):
    r = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": apikey, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(r, timeout=15) as resp:
        d = resp.read()
        return json.loads(d) if d else None


try:
    apikey = ET.parse(CONFIG).getroot().findtext("gui/apikey")
except (OSError, ET.ParseError) as exc:
    raise SystemExit(
        f"서버 Syncthing 설정({CONFIG})을 읽을 수 없습니다: {exc}\n"
        "hermes-kit Compose에 syncthing 볼륨이 있는지 확인하세요.")
if not apikey:
    raise SystemExit("Syncthing GUI API 키가 비어 있습니다. 컨테이너 로그를 확인하세요.")

# Syncthing 컨테이너가 아직 기동 중일 수 있다 — 최대 30초 대기
my_id = None
for attempt in range(6):
    try:
        my_id = req("GET", "/rest/system/status")["myID"]
        break
    except Exception:
        if attempt == 5:
            raise SystemExit(
                "서버 Syncthing이 응답하지 않습니다 (http://syncthing:8384).\n"
                "Compose에서 syncthing 서비스가 실행 중인지 확인하세요.")
        time.sleep(5)

if local_id == my_id:
    raise SystemExit("서버 자신의 기기 ID입니다. PC의 Syncthing 기기 ID를 넣어 주세요.")

# ---- 기기 등록 ----
devices = req("GET", "/rest/config/devices")
device = next((d for d in devices if d.get("deviceID") == local_id), None)
if device is None:
    device = req("GET", "/rest/config/defaults/device")
    device.update(deviceID=local_id, name=name, introducer=False, autoAcceptFolders=False)
    req("POST", "/rest/config/devices", device)
    print(f"기기 등록: {name} ({local_id[:7]}…)")
else:
    print(f"기기 이미 등록됨: {name}")

# ---- 볼트 2개 공유 ----
folders = req("GET", "/rest/config/folders")
for fid, label, path in FOLDERS:
    folder = next((f for f in folders if f.get("id") == fid), None)
    if folder is None:
        req("POST", "/rest/config/folders", {
            "id": fid, "label": label, "path": path, "type": "sendreceive",
            "devices": [{"deviceID": my_id}, {"deviceID": local_id}],
            "rescanIntervalS": 60, "fsWatcherEnabled": True,
        })
        print(f"공유 생성: {label} ({fid})")
        continue
    if folder.get("path") != path:
        raise SystemExit(
            f"폴더 ID '{fid}'가 다른 경로({folder.get('path')})에 쓰이고 있습니다. "
            "기존 설정을 보존하고 중단했습니다.")
    if any(d.get("deviceID") == local_id for d in folder.get("devices", [])):
        print(f"공유 이미 설정됨: {label}")
        continue
    folder.setdefault("devices", []).append({"deviceID": local_id})
    req("PUT", "/rest/config/folders/" + fid, folder)
    print(f"공유에 기기 추가: {label}")

print("SERVER_ID=" + my_id)
