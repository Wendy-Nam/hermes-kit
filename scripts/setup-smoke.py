"""In-image integration: real Hermes client, fake HTTP model, no credentials or delivery."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

HERE=Path('/opt/kit/plugins/kit-setup')
sys.path.insert(0,str(HERE))
from env_store import set_env
from config_store import write
from model_setup import probe

requests=[]
class Model(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(body)
        assert not body.get('tools'), 'model probe must not expose tools'
        text=json.dumps(body,ensure_ascii=False)
        assert 'PRIVATE_PERSONA_SENTINEL' not in text, 'private persona escaped isolation'
        assert 'PRIVATE_MEMORY_SENTINEL' not in text, 'private memory escaped isolation'
        reply='작은 아이디어 하나를 메모해 보는 건 어때요?' if '관심 주제' in text else 'OK'
        self.send_response(200)
        if body.get('stream'):
            self.send_header('Content-Type','text/event-stream');self.end_headers()
            for delta,finish in [({'role':'assistant','content':reply},None),({},'stop')]:
                chunk={'id':'smoke','object':'chat.completion.chunk','created':1,'model':'kit-fake','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'id':'smoke','object':'chat.completion','created':1,'model':'kit-fake','choices':[{'index':0,'message':{'role':'assistant','content':reply},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}).encode())

with tempfile.TemporaryDirectory(prefix='kit-smoke-') as temporary:
    home=Path(temporary)
    server=ThreadingHTTPServer(('127.0.0.1',0),Model)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        set_env(home/'.env',{'KIT_TEST_KEY':'fixture-only'})
        write(home,{'model.provider':'kit-test','model.default':'kit-fake',
                    'providers.kit-test.api':f'http://127.0.0.1:{server.server_port}/v1',
                    'providers.kit-test.key_env':'KIT_TEST_KEY',
                    'delegation.provider':'kit-test','delegation.model':'kit-fake'},remember=False)
        (home/'SOUL.md').write_text('PRIVATE_PERSONA_SENTINEL')
        (home/'memories').mkdir();(home/'memories/MEMORY.md').write_text('PRIVATE_MEMORY_SENTINEL')
        for role in ('main','aux'):
            ok,msg=probe(home,role=role)
            assert ok,(role,msg)
        proactive={'enabled':True,'topic':'작은 글쓰기 아이디어','provider':'kit-test','model':'kit-fake'}
        (home/'.kit-proactive.json').write_text(json.dumps(proactive))
        result=subprocess.run([sys.executable,str(HERE/'proactive.py')],env={**os.environ,'HERMES_HOME':str(home)},capture_output=True,text=True,timeout=100)
        assert result.returncode==0 and '아이디어' in result.stdout,(result.returncode,result.stderr)
        proactive['enabled']=False;(home/'.kit-proactive.json').write_text(json.dumps(proactive))
        count=len(requests)
        result=subprocess.run([sys.executable,str(HERE/'proactive.py')],env={**os.environ,'HERMES_HOME':str(home)},capture_output=True,text=True,timeout=15)
        assert result.returncode==0 and not result.stdout and len(requests)==count
        assert len(requests)>=3
        print('PASS: main/aux inference, text-only proactive generation, off switch, no private context, no tools, no external delivery')
    finally:
        server.shutdown();server.server_close()
