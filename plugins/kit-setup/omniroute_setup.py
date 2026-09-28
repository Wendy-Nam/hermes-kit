"""Opt-in API-key-only OmniRoute setup, scoped to one student connection.

Management password is used only in memory. Remote objects have per-installation
names. Only after a two-turn tool test succeeds do local delegation settings change.
"""
from __future__ import annotations
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request
import uuid

from components import _locked
from env_store import get_env, set_env

BASE = 'http://omniroute:20128'
PROVIDERS = {'gemini', 'openai', 'anthropic'}
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$')
STATE = '.kit-omniroute.json'
KEY_ENV = 'KIT_OMNIROUTE_API_KEY'
PROVIDER_NAME = 'kit-omniroute'


class SetupError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect())

    def request(self, method, path, body=None, key=None):
        headers = {'Content-Type': 'application/json'}
        if key: headers['Authorization'] = 'Bearer ' + key
        request = urllib.request.Request(BASE + path, method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=getattr(self, 'timeout', 100)) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024: raise SetupError('응답 크기 제한을 넘었습니다')
                return json.loads(raw or b'{}'), dict(response.headers)
        except urllib.error.HTTPError as exc:
            # Never include response bodies: upstream errors can echo credentials.
            raise SetupError(f'OmniRoute 요청 실패 (HTTP {exc.code})') from None
        except (OSError, ValueError):
            raise SetupError('OmniRoute 연결 또는 응답 확인에 실패했습니다') from None


def _atomic(path, blob, mode=0o600):
    fd, temp = tempfile.mkstemp(prefix='.kit-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(blob); f.flush(); os.fsync(f.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _save(data, state):
    _atomic(data / STATE, json.dumps(state, sort_keys=True, indent=2).encode())


def _items(client, path, key):
    result, _ = client.request('GET', path)
    values = result.get(key) if isinstance(result, dict) else result
    if not isinstance(values, list): raise SetupError('OmniRoute 목록 형식이 지원되지 않습니다')
    if isinstance(result, dict) and result.get('total', len(values)) > len(values):
        # Avoid a partial listing accidentally creating duplicate objects.
        raise SetupError('OmniRoute 목록이 일부만 반환됐습니다. 대시보드에서 연결을 확인해 주세요')
    return values


def _named(items, name):
    matches = [x for x in items if x.get('name') == name]
    if len(matches) > 1: raise SetupError('키트 연결 이름이 중복되었습니다. 대시보드에서 확인해 주세요')
    return matches[0] if matches else None


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise SetupError('OmniRoute 객체 ID가 올바르지 않습니다')
    return value


def _probe(client, combo, key, connection_id):
    tool = {'type':'function', 'function':{'name':'kit_echo', 'description':'Return the supplied value.',
        'parameters':{'type':'object','properties':{'value':{'type':'string'}},'required':['value'], 'additionalProperties':False}}}
    messages = [{'role':'user','content':'Call kit_echo with value KIT_READY. After the tool result reply exactly KIT_READY.'}]
    first, headers = client.request('POST','/v1/chat/completions',{
        'model':combo,'messages':messages,'tools':[tool],
        'tool_choice':{'type':'function','function':{'name':'kit_echo'}},'max_tokens':512,'stream':False},key)
    try:
        message = first['choices'][0]['message']; calls = message.get('tool_calls') or []
        if len(calls) != 1: raise ValueError()
        call = calls[0]
        args = json.loads(call['function']['arguments'])
        if call['function']['name'] != 'kit_echo' or args != {'value':'KIT_READY'}: raise ValueError()
        if not isinstance(call['id'], str) or not call['id']: raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise SetupError('모델의 실제 도구 호출 시험이 통과하지 못했습니다') from None
    for k,v in headers.items():
        allowed = {connection_id} if isinstance(connection_id, str) else set(connection_id)
        if k.lower() == 'x-omniroute-selected-connection-id' and v not in allowed:
            raise SetupError('요청한 연결과 실제 실행 연결이 다릅니다')
    messages += [message, {'role':'tool','tool_call_id':call['id'],'content':'KIT_READY'}]
    second, _ = client.request('POST','/v1/chat/completions',{
        'model':combo,'messages':messages,'tools':[tool],'tool_choice':'none','max_tokens':512,'stream':False},key)
    try:
        message = second['choices'][0]['message']
        if message.get('tool_calls') or message.get('content','').strip() != 'KIT_READY': raise ValueError()
    except (KeyError,IndexError,TypeError,ValueError):
        raise SetupError('도구 결과를 읽고 답하는 두 번째 시험이 통과하지 못했습니다') from None


def _apply_local(data, config, inference_key, combo):
    from config_store import locked, read
    with locked(data):
        # Network probes can take minutes: preserve edits made while they were running.
        return _apply_local_locked(data, read(data), inference_key, combo)


def _apply_local_locked(data, config, inference_key, combo):
    import yaml
    path = data / 'config.yaml'; env_path = data / '.env'
    old_config = path.read_bytes()
    old_env = env_path.read_bytes() if env_path.exists() else None
    original = json.loads(json.dumps(config))
    vision = config.get('auxiliary', {}).get('vision', {})
    if vision.get('provider') == PROVIDER_NAME and vision.get('model') != combo:
        raise SetupError('현재 이미지 연결을 보존했습니다. 이미지 연결을 해제한 뒤 모델을 변경해 주세요')
    providers = config.setdefault('providers', {})
    existing = providers.get(PROVIDER_NAME)
    desired = {'api':BASE + '/v1', 'key_env':KEY_ENV, 'transport':'openai_chat'}
    if existing and any(existing.get(k) != v for k,v in desired.items()):
        raise SetupError('같은 이름의 기존 사용자 제공자 설정을 보존했습니다')
    providers[PROVIDER_NAME] = {**(existing or {}), **desired}
    delegation = config.setdefault('delegation', {})
    delegation.update({'provider':PROVIDER_NAME,'model':combo})
    # Let Hermes resolve this named provider's key_env, never inherit the parent's key.
    delegation.pop('base_url', None)
    delegation.pop('api_key', None)
    from disconnect import snapshot
    def flatten(doc, prefix=''):
        result={}
        for name,value in doc.items():
            key=(prefix+'.' if prefix else '')+name
            if isinstance(value,dict): result.update(flatten(value,key))
            else: result[key]=value
        return result
    snapshot(data, {**{'providers.'+PROVIDER_NAME+'.'+k:v for k,v in desired.items()},
        'delegation.provider':PROVIDER_NAME,'delegation.model':combo,'delegation.base_url':None,'delegation.api_key':None}, flatten(original))
    try:
        set_env(env_path, {KEY_ENV:inference_key})
        _atomic(path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode())
    except Exception:
        _atomic(path, old_config)
        if old_env is None: env_path.unlink(missing_ok=True)
        else: _atomic(env_path, old_env)
        raise


def configure(data_dir, password, provider, api_key, model):
    """Return (ok, message). Only delegation is switched; main model remains direct."""
    if provider not in PROVIDERS or not isinstance(model,str) or not MODEL.fullmatch(model):
        return False, 'Gemini/OpenAI/Anthropic와 명시적인 모델 ID가 필요합니다.'
    for value in (password, api_key):
        if not isinstance(value,str) or not value.strip() or len(value)>10000 or '\n' in value or '\r' in value:
            return False, '관리 비밀번호와 API 키를 올바르게 입력해 주세요.'
    if model.startswith(provider + '/'): model=model[len(provider)+1:]
    if not model: return False, '모델 ID가 필요합니다.'
    data = Path(data_dir).resolve()
    try:
        import yaml
        with _locked(data):
            if any((data / p).is_symlink() for p in ('config.yaml','.env',STATE)):
                raise SetupError('설정 파일 링크를 허용하지 않습니다')
            config = yaml.safe_load((data / 'config.yaml').read_text())
            if not isinstance(config,dict): raise SetupError('기본 모델 설정을 먼저 완료해 주세요')
            state = json.loads((data / STATE).read_text()) if (data / STATE).exists() else {'schema_version':'kit-omniroute/v1','installation':uuid.uuid4().hex}
            if state.get('schema_version') != 'kit-omniroute/v1' or not re.fullmatch('[a-f0-9]{32}', state.get('installation','')):
                raise SetupError('OmniRoute 설치 기록을 확인해 주세요')
            client = Client()
            client.request('POST','/api/auth/login',{'password':password})
            _save(data,state)  # no secrets: journal survives failed network calls
            fingerprint = hashlib.sha256((provider+'\0'+model+'\0'+api_key).encode()).hexdigest()[:16]
            name = 'hermes-kit-' + state['installation'][:12] + '-' + fingerprint
            connection = _named(_items(client,'/api/providers','connections'), name)
            if not connection:
                created,_ = client.request('POST','/api/providers',{'provider':provider,'apiKey':api_key,
                    'name':name,'defaultModel':model,'priority':1})
                connection=created.get('connection',{})
            if connection.get('provider') != provider: raise SetupError('기존 연결의 제공자가 다릅니다')
            cid = _identifier(connection.get('id'))
            client.request('PUT','/api/providers/'+cid,{'isActive':True})
            combo = _named(_items(client,'/api/combos','combos'),name)
            combo_body={'name':name,'strategy':'priority','models':[{'provider':provider,'model':model,'connectionId':cid}],
                        'description':'hermes-kit student connection; no model fallback'}
            if combo:
                steps = combo.get('models')
                if isinstance(steps, str): steps=json.loads(steps)
                if not isinstance(steps,list) or len(steps)!=1 or not isinstance(steps[0],dict):
                    raise SetupError('기존 키트 콤보가 변경되어 보존했습니다')
                step=steps[0]
                if step.get('provider',step.get('providerId')) != provider or step.get('model') not in (model,provider+'/'+model) or step.get('connectionId') != cid:
                    raise SetupError('기존 키트 콤보가 변경되어 보존했습니다')
                combo_id = _identifier(combo.get('id'))
            else:
                created,_=client.request('POST','/api/combos',combo_body)
                combo_id = _identifier((created.get('combo') or created).get('id'))
            key_record = _named(_items(client,'/api/keys','keys'),name)
            inference = get_env(data / '.env').get(KEY_ENV)
            active = state.get('active',{})
            if key_record and active.get('key_id') == key_record.get('id') and inference:
                if key_record.get('allowedConnections') != [cid]:
                    raise SetupError('추론 키의 허용 연결이 변경되어 보존했습니다')
                key_id = _identifier(key_record['id'])
            else:
                if key_record:
                    # An abandoned incomplete setup owns this name, not the active configuration.
                    client.request('DELETE','/api/keys/'+_identifier(key_record.get('id')))
                created,_=client.request('POST','/api/keys',{'name':name,'noLog':True,'allowedConnections':[cid]})
                inference = created.get('key'); key_id = _identifier(created.get('id'))
                if not isinstance(inference,str) or not inference or '\n' in inference: raise SetupError('추론 키 생성 결과가 올바르지 않습니다')
            _probe(client,name,inference,cid)
            _apply_local(data,config,inference,name)
            previous = state.get('active',{})
            state['active']={'name':name,'connection_id':cid,'combo_id':combo_id,'key_id':key_id,
                             'provider':provider,'model':model,'tool_probe':'two-turn-passed'}
            _save(data,state)
            # Retire only resources whose exact IDs were recorded by our previous success.
            for kind,field in (('keys','key_id'),('combos','combo_id'),('providers','connection_id')):
                old=previous.get(field)
                if old and old != state['active'][field]:
                    try:client.request('DELETE','/api/'+kind+'/'+_identifier(old))
                    except SetupError:pass  # preserved for operator cleanup; never change non-kit records
        # Outside the component lock: the OMH sync takes it itself.
        from omh_enhancements import sync_base_route
        sync_base_route(data, PROVIDER_NAME, name)
        return True, 'OmniRoute 도구 시험 2단계 통과. 보조 작업만 연결했습니다. 재시작 후 적용됩니다.'
    except SetupError as exc:
        return False, str(exc) + ' · 메인 모델 설정은 유지됩니다.'
    except Exception as exc:
        return False, f'OmniRoute 설정 실패 ({type(exc).__name__}). 메인 모델 설정은 유지됩니다.'


def _vision_sample():
    """A small random color grid generated locally without imaging dependencies."""
    import base64
    import secrets
    import struct
    import zlib
    colors = {'RED': (255, 0, 0), 'GREEN': (0, 180, 0), 'BLUE': (0, 0, 255),
              'YELLOW': (255, 255, 0)}
    expected = [secrets.choice(list(colors)) for _ in range(6)]
    pixels = b''.join(b'\x00' + b''.join(bytes((255, 255, 255) if x % 48 < 2 or y % 48 < 2 else colors[expected[(y // 48) * 3 + x // 48]])
        for x in range(144)) for y in range(96))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 144, 96, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(png).decode(), expected


def _probe_vision(client, combo, key, connection_id):
    url, expected = _vision_sample()
    response, headers = client.request('POST', '/v1/chat/completions', {
        'model': combo, 'stream': False, 'max_tokens': 128,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Read this 2-row, 3-column color grid. Return only a JSON array of six uppercase color names in row-major order, using RED, GREEN, BLUE, YELLOW.'},
            {'type': 'image_url', 'image_url': {'url': url, 'detail': 'high'}}]}]}, key)
    try:
        message = response['choices'][0]['message']
        if message.get('tool_calls') or json.loads(message['content'].strip()) != expected:
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise SetupError('합성 이미지 읽기 시험이 통과하지 못했습니다. 기존 이미지 설정을 유지합니다') from None
    for name, value in headers.items():
        if name.lower() == 'x-omniroute-selected-connection-id' and value != connection_id:
            raise SetupError('이미지 시험이 선택한 연결과 다른 연결에서 실행되었습니다')


def _explicit_vision(selection):
    # Stock auto/empty defaults (including timeout tuning) are not a model choice.
    return bool(selection) and (selection.get('provider') not in (None, '', 'auto')
        or any(selection.get(k) for k in ('model', 'base_url', 'api_key', 'key_env', 'fallback_chain')))


def connect_vision(data_dir, password, *, disable_shared_bridge=False):
    """Explicitly test/attach the current student combo; never guess vision support.

    Disabling OmniRoute's bridge affects every client of that router and therefore
    requires a separate explicit UI choice. Failed setup restores its prior value.
    """
    if not isinstance(password, str) or not password.strip() or len(password) > 10000 or '\n' in password or '\r' in password:
        return False, '관리 비밀번호를 올바르게 입력해 주세요.'
    data = Path(data_dir).resolve()
    client = None
    changed_bridge = False
    original_bridge = None
    try:
        from config_store import locked, read
        import yaml
        with _locked(data):
            if any((data / p).is_symlink() for p in ('config.yaml', '.env', STATE)):
                raise SetupError('설정 파일 링크를 허용하지 않습니다')
            state = json.loads((data / STATE).read_text())
            active = state.get('active', {})
            if active.get('tool_probe') != 'two-turn-passed':
                raise SetupError('먼저 OmniRoute 보조 모델의 도구 시험을 완료해 주세요')
            name, cid = active['name'], _identifier(active['connection_id'])
            inference = get_env(data / '.env').get(KEY_ENV)
            if not inference: raise SetupError('현재 OmniRoute 추론 키가 없습니다')
            with locked(data):
                before = read(data)
                prior_vision = before.get('auxiliary', {}).get('vision', {})
                if _explicit_vision(prior_vision) and (prior_vision.get('provider') != PROVIDER_NAME or prior_vision.get('model') != name):
                    raise SetupError('기존 이미지 모델 선택을 보존했습니다. 먼저 해당 이미지 연결을 해제해 주세요')
            client = Client()
            client.timeout = 25
            client.request('POST', '/api/auth/login', {'password': password})
            combo = _named(_items(client, '/api/combos', 'combos'), name)
            steps = combo.get('models') if combo else None
            if isinstance(steps, str): steps = json.loads(steps)
            if not isinstance(steps, list) or len(steps) != 1 or steps[0].get('connectionId') != cid or steps[0].get('model') not in (active['model'], active['provider'] + '/' + active['model']) or steps[0].get('provider', steps[0].get('providerId')) != active['provider']:
                raise SetupError('기존 키트 콤보가 변경되어 보존했습니다')
            settings, _ = client.request('GET', '/api/settings')
            settings = settings.get('settings', settings)
            original_bridge = settings.get('modalityBridgeVisionEnabled', settings.get('visionBridgeEnabled', True))
            if not isinstance(original_bridge, bool): raise SetupError('이미지 브리지 설정을 확인할 수 없습니다')
            if original_bridge:
                if disable_shared_bridge is not True:
                    raise SetupError('이미지 브리지를 끄면 이 OmniRoute를 공유하는 모든 연결에 적용됩니다. 명시적으로 선택한 뒤 다시 시험해 주세요')
                changed_bridge = True  # Also restore after an ambiguous transport failure.
                client.request('PATCH', '/api/settings', {'modalityBridgeVisionEnabled': False})
                verified, _ = client.request('GET', '/api/settings')
                if verified.get('settings', verified).get('modalityBridgeVisionEnabled') is not False:
                    raise SetupError('이미지 브리지 변경을 확인하지 못했습니다')
            _probe(client, name, inference, cid)
            _probe_vision(client, name, inference, cid)
            desired = {'provider': PROVIDER_NAME, 'model': name, 'base_url': BASE + '/v1',
                       'key_env': KEY_ENV, 'timeout': 30, 'configured_routes_only': True, 'fallback_chain': []}
            with locked(data):
                config = read(data)
                if config.get('auxiliary', {}).get('vision', {}) != prior_vision:
                    raise SetupError('시험 중 이미지 설정이 바뀌어 기존 선택을 보존했습니다')
                provider = config.get('providers', {}).get(PROVIDER_NAME, {})
                if provider.get('key_env') != KEY_ENV or provider.get('api') != BASE + '/v1' or get_env(data / '.env').get(KEY_ENV) != inference:
                    raise SetupError('시험 중 연결 설정이 바뀌었습니다. 다시 시험해 주세요')
                from disconnect import snapshot
                updates = {'auxiliary.vision.' + k: v for k, v in desired.items()}
                updates['auxiliary.vision.api_key'] = None
                previous = {'auxiliary.vision.' + k: prior_vision.get(k) for k in (*desired, 'api_key')}
                snapshot(data, updates, previous)
                vision = config.setdefault('auxiliary', {}).setdefault('vision', {})
                vision.update(desired)
                vision.pop('api_key', None)
                _atomic(data / 'config.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode())
            return True, '도구 2단계와 합성 이미지 시험을 통과했습니다. 이미지 모델만 연결했습니다. 한글 OCR 정확도는 별도 확인이 필요합니다. 재시작 후 적용됩니다.'
    except Exception as exc:
        restored = True
        if changed_bridge and client:
            try: client.request('PATCH', '/api/settings', {'modalityBridgeVisionEnabled': original_bridge})
            except Exception: restored = False
        message = str(exc) if isinstance(exc, SetupError) else f'이미지 연결 실패 ({type(exc).__name__})'
        if not restored: message += ' · 공유 이미지 브리지 복원도 실패했습니다. OmniRoute 설정을 확인해 주세요'
        return False, message


def disconnect_vision(data_dir):
    """Restore only this kit's current vision selection; keep shared router and keys."""
    data = Path(data_dir).resolve()
    try:
        from config_store import locked, read
        from disconnect import _load, SNAPSHOT
        import yaml
        with _locked(data):
            if any((data / p).is_symlink() for p in ('config.yaml', STATE, SNAPSHOT)):
                raise SetupError('설정 파일 링크를 허용하지 않습니다')
            with locked(data):
                config = read(data)
                vision = config.get('auxiliary', {}).get('vision', {})
                state = json.loads((data / STATE).read_text()) if (data / STATE).exists() else {}
                active = state.get('active', {})
                if vision.get('provider') != PROVIDER_NAME or not active.get('name') or vision.get('model') != active['name'] or vision.get('key_env') != KEY_ENV:
                    raise SetupError('키트의 현재 이미지 연결이 아니므로 기존 설정을 보존했습니다')
                saved = _load(data)
                prefix = 'auxiliary.vision.'
                restore = {key[len(prefix):]: value for key, value in saved.items() if key.startswith(prefix)}
                if not {'provider', 'model'}.issubset(restore):
                    raise SetupError('이미지 설정 복원 기록이 없어 기존 연결을 보존했습니다')
                for dotted, value in restore.items():
                    parts = dotted.split('.')
                    if not all(parts): raise SetupError('이미지 복원 기록이 올바르지 않습니다')
                    node = vision
                    for part in parts[:-1]:
                        node = node.setdefault(part, {})
                        if not isinstance(node, dict): raise SetupError('이미지 복원 설정 형식이 올바르지 않습니다')
                    if value is None: node.pop(parts[-1], None)
                    else: node[parts[-1]] = value
                # We already hold config_store.locked: its public write() would
                # reacquire the same flock. Do the atomic write here without a
                # new snapshot, equivalent to remember=False in that transaction.
                _atomic(data / 'config.yaml', yaml.safe_dump(config, allow_unicode=True, sort_keys=False).encode())
        return True, '이미지 연결만 해제했습니다. 보조 모델을 다시 선택할 수 있습니다. 공유 브리지와 키는 유지하며, 재시작 후 적용됩니다.'
    except Exception as exc:
        return False, str(exc) if isinstance(exc, SetupError) else f'이미지 연결 해제 실패 ({type(exc).__name__}). 기존 설정을 보존했습니다.'
