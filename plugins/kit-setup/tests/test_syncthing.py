import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import syncthing_setup as sync

PEER = "A" * 56
SERVER = "B" * 56

class SyncthingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Path(self.tmp.name)/"config.xml"
        self.config.write_text("<configuration><gui><apikey>secret</apikey></gui></configuration>")
        self.devices = [{"deviceID":SERVER,"name":"server"}]
        self.folders = [{"id":"existing","path":"/unrelated","devices":[]}]
        self.posts = []
    def tearDown(self): self.tmp.cleanup()
    def api(self, url, key, method, endpoint, payload):
        self.assertEqual(key,"secret")
        if method == "POST":
            self.posts.append((endpoint,copy.deepcopy(payload)))
            rows = self.devices if endpoint.endswith("devices") else self.folders
            field = "deviceID" if endpoint.endswith("devices") else "id"
            rows[:] = [r for r in rows if r[field]!=payload[field]]+[copy.deepcopy(payload)]
            return None
        if endpoint.startswith("/rest/svc/deviceid"): return {"id":PEER}
        return copy.deepcopy({"/rest/system/status":{"myID":SERVER},
            "/rest/config/devices":self.devices,"/rest/config/folders":self.folders,
            "/rest/config/defaults/device":{"addresses":["dynamic"]},
            "/rest/config/defaults/folder":{"rescanIntervalS":3600,"devices":[]}}[endpoint])
    def pair(self): return sync.pair_device(PEER,config_path=self.config)
    def test_pair_preserves_existing_and_idempotent(self):
        before=self.config.read_bytes()
        with patch.object(sync,"_request",side_effect=self.api):
            ok,msg=self.pair(); self.assertTrue(ok);self.assertIn(SERVER,msg)
            self.assertEqual(len(self.posts),3)
            self.assertTrue(self.pair()[0]);self.assertEqual(len(self.posts),3)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.folders[0]["path"],"/unrelated")
        self.assertEqual({f["path"] for f in self.folders[1:]}, {f[2] for f in sync.FOLDERS})
    def test_existing_folder_options_and_devices_preserved(self):
        self.folders.append({"id":"hermes-work","path":sync.FOLDERS[0][2],
            "devices":[{"deviceID":SERVER},{"deviceID":"old-peer"}],"versioning":{"type":"simple"},"paused":True})
        with patch.object(sync,"_request",side_effect=self.api):self.assertTrue(self.pair()[0])
        folder=next(f for f in self.folders if f["id"]=="hermes-work")
        self.assertTrue(folder["paused"]);self.assertEqual(folder["versioning"],{"type":"simple"})
        self.assertEqual(len(folder["devices"]),3)
    def test_path_collision_no_mutation(self):
        self.folders.append({"id":"hermes-personal","path":"/secrets"})
        with patch.object(sync,"_request",side_effect=self.api):self.assertFalse(self.pair()[0])
        self.assertFalse(self.posts)
    def test_invalid_id_api_and_secret_errors(self):
        with patch.object(sync,"_request",return_value={"error":"invalid"}):self.assertFalse(self.pair()[0])
        with patch.object(sync,"_request",side_effect=RuntimeError("secret")):
            ok,msg=self.pair();self.assertFalse(ok);self.assertNotIn("secret",msg)
    def test_partial_failure_reported(self):
        def fail(*args):
            if args[3]=="/rest/config/defaults/folder":raise OSError("secret")
            return self.api(*args)
        with patch.object(sync,"_request",side_effect=fail):
            ok,msg=self.pair();self.assertFalse(ok);self.assertIn("일부 설정",msg)

if __name__=="__main__":unittest.main()
