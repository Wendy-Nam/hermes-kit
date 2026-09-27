"""Pair a PC using Syncthing's granular REST API; never rewrite config.xml."""
import copy
import json
import re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

FOLDERS = (("hermes-work", "업무 볼트", "/var/syncthing/vaults/work"),
           ("hermes-personal", "개인 볼트", "/var/syncthing/vaults/personal"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect refused")


def _request(api_url, key, method, endpoint, payload=None):
    req = urllib.request.Request(api_url + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"X-API-Key": key, "Content-Type": "application/json"}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(req, timeout=15) as response:
        body = response.read(2 * 1024 * 1024)
        return json.loads(body) if body else None


def pair_device(device_id: str, name="내 PC", *,
                config_path=Path("/opt/syncthing-config/config.xml"),
                api_url="http://syncthing:8384") -> tuple[bool, str]:
    """Success means sharing configured, not that the PC accepted or synced it."""
    if not isinstance(device_id, str) or not re.fullmatch(r"[A-Za-z0-9 -]{52,80}", device_id):
        return False, "PC의 Syncthing 장치 ID를 전체 복사해 주세요."
    if api_url not in ("http://syncthing:8384", "http://127.0.0.1:8384", "http://localhost:8384"):
        return False, "동기화 API 주소는 키트 내부 주소만 허용합니다."
    changed = False
    try:
        raw = Path(config_path).read_bytes()
        if len(raw) > 2 * 1024 * 1024 or b"<!DOCTYPE" in raw.upper():
            raise ValueError("invalid configuration")
        key = ET.fromstring(raw).findtext("gui/apikey")
        if not key:
            raise ValueError("missing API key")
        def call(method, endpoint, payload=None):
            return _request(api_url, key, method, endpoint, payload)
        validated = call("GET", "/rest/svc/deviceid?id=" + urllib.parse.quote(device_id))
        peer = validated.get("id")
        if not peer:
            return False, "장치 ID 검증에 실패했습니다. PC의 ID를 다시 복사해 주세요."
        server = call("GET", "/rest/system/status")["myID"]
        if peer == server:
            return False, "서버 자신의 ID입니다. 연결할 PC의 장치 ID를 입력해 주세요."
        devices = call("GET", "/rest/config/devices")
        folders = call("GET", "/rest/config/folders")
        # Check every collision before writing anything. Never repurpose a folder.
        for fid, _, path in FOLDERS:
            for folder in folders:
                if folder.get("id") == fid and folder.get("path") != path:
                    return False, "같은 폴더 ID가 다른 경로에 사용 중입니다. 기존 설정을 보존하고 중단했습니다."
                if folder.get("path") == path and folder.get("id") != fid:
                    return False, "볼트가 다른 폴더 ID로 이미 공유 중입니다. 기존 설정을 확인해 주세요."
        device = next((copy.deepcopy(d) for d in devices if d.get("deviceID") == peer), None)
        if device is None:
            device = call("GET", "/rest/config/defaults/device")
            device.update(deviceID=peer, name=str(name)[:80], introducer=False, autoAcceptFolders=False)
            changed = True
            call("POST", "/rest/config/devices", device)
        for fid, label, path in FOLDERS:
            folder = next((copy.deepcopy(f) for f in folders if f.get("id") == fid), None)
            if folder is None:
                folder = call("GET", "/rest/config/defaults/folder")
                folder.update(id=fid, label=label, path=path, type="sendreceive",
                              devices=[{"deviceID": server}], paused=False)
            if any(d.get("deviceID") == peer for d in folder.get("devices", [])):
                continue
            folder.setdefault("devices", []).append({"deviceID": peer})
            changed = True
            call("POST", "/rest/config/folders", folder)
        return True, (f"서버 공유 설정을 저장했습니다. 서버 장치 ID: {server}\n"
                      "PC에서 서버와 업무·개인 폴더 공유를 수락해 주세요. 실제 파일 동기화는 아직 확인하지 않았습니다.")
    except Exception:
        suffix = " 일부 설정은 이미 저장됐을 수 있습니다. 같은 ID로 다시 시도할 수 있습니다." if changed else ""
        return False, "동기화 설정을 완료하지 못했습니다. Syncthing 실행 상태와 설정 볼륨을 확인해 주세요." + suffix
