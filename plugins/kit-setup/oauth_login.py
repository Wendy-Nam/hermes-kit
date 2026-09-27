"""Bounded Discord relay for Hermes' own device login; only URL and user code leave it."""
import asyncio
import json
import os
import re
from pathlib import Path
from model_setup import PYTHON

_ACTIVE=set()
async def login_codex(data_dir, notify):
    root=str(Path(data_dir).resolve())
    if root in _ACTIVE: return False, '이미 로그인 대기 중입니다. 먼저 열린 링크에서 완료해 주세요.'
    _ACTIVE.add(root);proc=None
    try:
        proc=await asyncio.create_subprocess_exec(PYTHON,str(Path(__file__).with_name('model_worker.py')),'login',
            env={**os.environ,'HERMES_HOME':root,'HERMES_DATA':root},
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        async with asyncio.timeout(600):
            success=False
            async for raw in proc.stdout:
                if len(raw)>4096: raise ValueError('oversized event')
                try: event=json.loads(raw)
                except (ValueError,UnicodeError): continue
                if event.get('kit_event')=='device':
                    if event.get('url')!='https://auth.openai.com/codex/device' or not re.fullmatch(r'[A-Za-z0-9 -]{1,32}',event.get('code','')):
                        raise ValueError('invalid auth event')
                    await notify(f"[ChatGPT 로그인]({event['url']})을 열고 코드 **{event['code']}**를 입력해 주세요. 이 요청을 직접 시작한 경우에만 승인하세요.")
                elif event.get('kit_event')=='login' and event.get('ok') is True: success=True
            rc=await proc.wait()
            return (True,'ChatGPT 로그인을 저장했습니다. 두뇌 연결에서 모델을 선택해 주세요.') if success and rc==0 else (False,'로그인을 완료하지 못했습니다. 잠시 후 다시 시도하거나 다른 제공자를 선택해 주세요.')
    except TimeoutError:
        return False,'로그인 대기 시간이 끝났습니다. 다시 시작해 주세요.'
    except Exception:
        return False,'로그인 연결을 시작하지 못했습니다. /doctor로 확인해 주세요.'
    finally:
        if proc and proc.returncode is None:
            proc.terminate()
            try: await asyncio.wait_for(proc.wait(),5)
            except TimeoutError: proc.kill();await proc.wait()
        _ACTIVE.discard(root)
