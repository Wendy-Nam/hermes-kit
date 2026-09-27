import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import composio_setup as c

KEY="ck_testconsumerkey"
class Response(io.BytesIO):
    def __init__(self,payload,kind="application/json",session=None,status=200):
        super().__init__(payload if isinstance(payload,bytes) else json.dumps(payload).encode())
        self.headers={"Content-Type":kind};self.status=status
        if session:self.headers["Mcp-Session-Id"]=session

class ComposioTests(unittest.TestCase):
    def test_handshake_headers_and_no_tool_execution(self):
        calls=[]
        class Opener:
            def open(self,req,timeout):
                calls.append(req)
                p=json.loads(req.data)
                if p["method"]=="initialize":return Response({"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}},session="test-session")
                if p["method"]=="notifications/initialized":return Response(b"",status=202)
                result={"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"COMPOSIO_SEARCH_TOOLS"},{"name":"COMPOSIO_MANAGE_CONNECTIONS"}]}}
                return Response(b"event: message\n"+b"data: "+json.dumps(result).encode()+b"\n\n",kind="text/event-stream")
        with patch.object(c.urllib.request,"build_opener",return_value=Opener()):
            ok,msg=c.validate_consumer_key(KEY)
        self.assertTrue(ok);self.assertIn("별도로",msg)
        self.assertEqual(len(calls),3)
        self.assertTrue(all(r.full_url==c.URL for r in calls))
        self.assertEqual(calls[0].get_header("X-consumer-api-key"),KEY)
        self.assertEqual(calls[2].get_header("Mcp-session-id"),"test-session")
        self.assertEqual([json.loads(r.data)["method"] for r in calls],["initialize","notifications/initialized","tools/list"])
    def test_wrong_key_type_no_network(self):
        with patch.object(c,"_post") as post:
            self.assertFalse(c.validate_consumer_key("ak_something")[0]);post.assert_not_called()
    def test_error_and_no_secret_leak(self):
        for error in (RuntimeError(KEY),urllib.error.HTTPError(c.URL,401,KEY,{},None)):
            with patch.object(c,"_post",side_effect=error):
                ok,msg=c.validate_consumer_key(KEY);self.assertFalse(ok);self.assertNotIn(KEY,msg)
    def test_rpc_error_wrong_id_and_missing_tools_rejected(self):
        for response in ({"jsonrpc":"2.0","id":1,"error":{"message":KEY}},
                         {"jsonrpc":"2.0","id":999,"result":{}}):
            with patch.object(c,"_post",return_value=(response,None)):
                self.assertFalse(c.validate_consumer_key(KEY)[0])
        good={"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}}
        missing={"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"other"}]}}
        with patch.object(c,"_post",side_effect=[(good,None),(None,None),(missing,None)]):
            self.assertFalse(c.validate_consumer_key(KEY)[0])
    def test_redirect_refused(self):
        with self.assertRaises(ValueError):c._NoRedirect().redirect_request(None,None,None,None,None,None)

if __name__=="__main__":unittest.main()
