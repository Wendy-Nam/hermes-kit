"""Minimal OpenAI-compatible chat endpoint for install tests: always answers "OK", no tools."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS = '/tmp/fake-openai-calls.jsonl'


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self._json(200, {'object': 'list', 'data': [{'id': 'fake-model', 'object': 'model'}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        with open(CALLS, 'a') as f:
            f.write(json.dumps({'path': self.path, 'model': req.get('model'), 'tools': len(req.get('tools') or [])}) + '\n')
        msg = {'role': 'assistant', 'content': 'OK'}
        # The kit's two-turn tool probe: call the forced tool, then answer with its result.
        choice = req.get('tool_choice')
        last = (req.get('messages') or [{}])[-1]
        if 'broken' in str(req.get('model')):
            pass  # a model that ignores tools: fails the kit's tool test
        elif isinstance(choice, dict) and choice.get('type') == 'function':
            name = choice['function']['name']
            msg = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_1', 'type': 'function',
                   'function': {'name': name, 'arguments': json.dumps({'value': 'KIT_READY'})}}]}
        elif last.get('role') == 'tool':
            msg = {'role': 'assistant', 'content': str(last.get('content') or '')}
        if req.get('stream'):
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            for delta, fin in (({'role': 'assistant', 'content': 'OK'}, None), ({}, 'stop')):
                chunk = {'id': 'x', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': req.get('model'),
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': fin}]}
                self.wfile.write(b'data: ' + json.dumps(chunk).encode() + b'\n\n')
            self.wfile.write(b'data: [DONE]\n\n'); return
        self._json(200, {'id': 'x', 'object': 'chat.completion', 'created': int(time.time()), 'model': req.get('model'),
                         'choices': [{'index': 0, 'message': msg, 'finish_reason': 'stop'}],
                         'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})


import os
ThreadingHTTPServer((os.environ.get('FAKE_HOST', '127.0.0.1'), 8099), H).serve_forever()
