"""Explicit model selection and isolated, tool-free inference checks."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROVIDERS = {'openai-codex': 'ChatGPT 구독', 'gemini': 'Gemini API',
             'opencode-go': 'OpenCode Go', 'commandcode': 'Command Code'}
KEYS = {'gemini': 'GEMINI_API_KEY', 'opencode-go': 'OPENCODE_GO_API_KEY',
        'commandcode': 'COMMANDCODE_API_KEY'}
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}$')
PYTHON = '/opt/hermes/.venv/bin/python'

def delegation_route(config):
    """Where delegated work runs: the aux model when one is set, otherwise the main model
    (Hermes children inherit the parent). Returns (route or None, aux_is_set)."""
    aux = config.get('delegation') or {}
    if isinstance(aux, dict) and aux.get('provider') and aux.get('model'):
        return {'provider': aux['provider'], 'model': aux['model']}, True
    main = config.get('model') or {}
    if isinstance(main, dict) and main.get('provider') and main.get('default'):
        return {'provider': main['provider'], 'model': main['default']}, False
    return None, False

def select_model(data_dir, provider, model, role="main"):
    if role not in ("main", "aux") or provider not in PROVIDERS or not MODEL.fullmatch(model.strip()):
        return False, '지원하는 제공자와 정확한 모델 ID를 입력해 주세요.'
    from env_store import get_env
    from config_store import write
    env = get_env(Path(data_dir)/'.env')
    if provider in KEYS and not env.get(KEYS[provider]):
        return False, '먼저 해당 제공자의 키를 입력해 주세요.'
    ok,msg=probe(data_dir,role=role,candidate=(provider,model.strip()))
    if not ok:return False,msg
    changes = {'model.provider': provider, 'model.default': model.strip(),
               'model.base_url': None, 'model.api_mode': None}
    if role == 'aux':
        changes = {'delegation.provider': provider, 'delegation.model': model.strip()}
    if provider == 'commandcode':
        changes.update({'providers.commandcode.api': 'https://api.commandcode.ai/provider/v1',
                        'providers.commandcode.key_env': 'COMMANDCODE_API_KEY', 'providers.commandcode.transport':'openai_chat'})
    write(data_dir, changes)
    # OMH routes every unassigned task type to the delegation route; keep that in step.
    from config_store import read
    route, _ = delegation_route(read(data_dir))
    if route:
        from omh_enhancements import sync_base_route
        sync_base_route(data_dir, route['provider'], route['model'])
    return True, '모델을 선택했습니다. 실제 연결 확인 후 적용해 주세요.'

def probe(data_dir, *, timeout=90, role="main", candidate=None):
    """No private prompt or local tools are sent; worker sees fresh persisted keys."""
    root = Path(data_dir)
    from config_store import read
    model = read(root).get('model' if role == 'main' else 'delegation') or {}
    model = {**model, 'default': model.get('default') or model.get('model')} if isinstance(model, dict) else {}
    if candidate:model = {'provider':candidate[0], 'default':candidate[1]}
    if not isinstance(model, dict) or not model.get('provider') or not model.get('default'):
        return False, '두뇌 연결에서 제공자와 모델을 먼저 선택해 주세요.'
    env = {**os.environ, 'HERMES_HOME': str(root), 'HERMES_DATA': str(root)}
    if candidate:env.update(KIT_PROBE_PROVIDER=candidate[0],KIT_PROBE_MODEL=candidate[1])
    try:
        p = subprocess.run([PYTHON if Path(PYTHON).exists() else sys.executable,
                            str(Path(__file__).with_name('model_worker.py')), 'probe' if role == 'main' else 'probe-aux'],
                           env=env, capture_output=True, text=True, timeout=timeout)
        rows = [json.loads(line) for line in p.stdout.splitlines() if line.startswith('{"kit_event":')]
        result = next((r for r in reversed(rows) if r.get('kit_event')=='probe'), {})
        if p.returncode == 0 and result.get('ok') is True:
            return True, '선택한 모델의 실제 응답을 확인했습니다.'
        return False, '모델 응답 확인에 실패했습니다. 로그인·모델 ID·사용 한도를 확인해 주세요.'
    except subprocess.TimeoutExpired:
        return False, '모델 응답이 지연됐습니다. 잠시 후 다시 확인해 주세요.'
    except Exception:
        return False, '연결 확인을 실행하지 못했습니다. /doctor에서 설치 상태를 확인해 주세요.'
