"""OmniRoute mode: the student's own dashboard connections become the bot's models.

The student connects providers in the OmniRoute dashboard (subscriptions, free tiers, API keys);
the kit never sees those credentials. Given model IDs as the dashboard shows them ("prefix/model"),
the kit tool-tests each one, builds two short combos (chat, strong), and points the main model at
chat with the previous direct model as Hermes' fallback, and delegation, OMH and role profiles at
strong. If OmniRoute stops, Hermes falls back to the direct model instead of going silent.
"""
import json
import re
import uuid
from pathlib import Path

from components import _locked
from env_store import get_env, set_env
from omniroute_setup import (KEY_ENV, PROVIDER_NAME, BASE, STATE, Client, SetupError, _identifier, _items,
                             _named, _probe, _save)

MAX_MODELS = 5
MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:@-]{0,60}/[A-Za-z0-9][A-Za-z0-9._:/@-]{0,160}$')
# Browser-session scrapers break often and risk the provider's terms; never routed by the kit.
def _scraper(provider):
    return provider.endswith('-web') or provider == 'lmarena'


def parse_models(text):
    models = [m.strip() for m in (text or '').replace('\n', ',').split(',') if m.strip()]
    if not models or len(models) > MAX_MODELS or len(set(models)) != len(models):
        raise SetupError(f'모델을 1~{MAX_MODELS}개, 중복 없이 입력해 주세요')
    bad = [m for m in models if not MODEL_ID.fullmatch(m)]
    if bad:
        raise SetupError('대시보드에 표시된 "접두사/모델" 형식으로 입력해 주세요: ' + ', '.join(bad[:3]))
    return models


def _connections(client):
    """prefix -> active student connection (highest priority first), skipping kit-owned and scrapers."""
    found = {}
    for c in sorted(_items(client, '/api/providers', 'connections'), key=lambda c: c.get('priority') or 99):
        name, provider = str(c.get('name') or ''), str(c.get('provider') or '')
        if not c.get('isActive') or name.startswith('hermes-kit-') or _scraper(provider):
            continue
        prefix = (c.get('providerSpecificData') or {}).get('prefix') or provider
        found.setdefault(prefix, c)
    return found


def _steps(models, connections):
    steps, missing = [], []
    for m in models:
        prefix, model = m.split('/', 1)
        c = connections.get(prefix)
        if c is None:
            missing.append(m)
            continue
        steps.append({'provider': c['provider'], 'model': model, 'connectionId': _identifier(c.get('id')), 'id_': m})
    if missing:
        raise SetupError('대시보드에 연결되지 않았거나 사용할 수 없는 제공자입니다: ' + ', '.join(missing[:3]))
    return steps


def _replace_combo(client, name, steps):
    old = _named(_items(client, '/api/combos', 'combos'), name)
    if old:
        client.request('DELETE', '/api/combos/' + _identifier(old.get('id')))
    body = {'name': name, 'strategy': 'priority', 'description': 'hermes-kit OmniRoute mode',
            'models': [{k: v for k, v in s.items() if k != 'id_'} for s in steps]}
    created, _ = client.request('POST', '/api/combos', body)
    return _identifier((created.get('combo') or created).get('id'))


def connect_mode(data_dir, password, chat_text, strong_text=''):
    """Return (ok, message). Nothing local changes unless every chosen model passed the tool test."""
    data = Path(data_dir).resolve()
    try:
        chat = parse_models(chat_text)
        strong = parse_models(strong_text) if (strong_text or '').strip() else list(chat)
        if not isinstance(password, str) or not password.strip() or '\n' in password:
            raise SetupError('대시보드 비밀번호를 입력해 주세요')
        from config_store import read
        with _locked(data):
            config = read(data)
            state = json.loads((data / STATE).read_text()) if (data / STATE).exists() else \
                {'schema_version': 'kit-omniroute/v1', 'installation': uuid.uuid4().hex}
            client = Client()
            client.request('POST', '/api/auth/login', {'password': password})
            connections = _connections(client)
            chat_steps, strong_steps = _steps(chat, connections), _steps(strong, connections)
            cids = sorted({s['connectionId'] for s in chat_steps + strong_steps})
            # A vision link made by the single-key setup keeps working under the new key.
            vision_cid = (state.get('active') or {}).get('connection_id')
            allowed = sorted(set(cids) | ({vision_cid} if vision_cid else set()))
            prefix = 'hermes-kit-' + state['installation'][:12]
            # A fresh key per attempt: the key the bot is using now is retired only after this one works.
            key_name = prefix + '-mode-' + uuid.uuid4().hex[:8]
            created, _ = client.request('POST', '/api/keys', {'name': key_name, 'noLog': True, 'allowedConnections': allowed})
            inference = created.get('key')
            if not isinstance(inference, str) or not inference or '\n' in inference:
                raise SetupError('추론 키 생성 결과가 올바르지 않습니다')
            failed = []
            for s in {s['id_']: s for s in chat_steps + strong_steps}.values():
                try:
                    _probe(client, s['id_'], inference, s['connectionId'])
                except SetupError:
                    failed.append(s['id_'])
            chat_steps = [s for s in chat_steps if s['id_'] not in failed]
            strong_steps = [s for s in strong_steps if s['id_'] not in failed]
            if not chat_steps or not strong_steps:
                raise SetupError('도구 호출 시험을 통과한 모델이 없습니다: ' + ', '.join(failed[:5]))
            chat_combo, strong_combo = prefix + '-chat', prefix + '-strong'
            _replace_combo(client, chat_combo, chat_steps)
            _replace_combo(client, strong_combo, strong_steps)
            new_key_id = _identifier(created.get('id'))
            main = config.get('model') or {}
            fallback = config.get('fallback_providers') or []
            if main.get('provider') not in (None, '', 'auto', 'default', PROVIDER_NAME) and main.get('default'):
                fallback = [{'provider': main['provider'], 'model': main['default']}]
            changes = {'providers.' + PROVIDER_NAME + '.api': BASE + '/v1',
                       'providers.' + PROVIDER_NAME + '.key_env': KEY_ENV,
                       'providers.' + PROVIDER_NAME + '.transport': 'openai_chat',
                       'delegation.provider': PROVIDER_NAME, 'delegation.model': strong_combo,
                       'delegation.base_url': None, 'delegation.api_key': None}
            if fallback:
                # Without a working direct model to fall back to, the chat stays direct: an OmniRoute
                # outage must never leave the bot unable to answer.
                changes.update({'model.provider': PROVIDER_NAME, 'model.default': chat_combo,
                                'model.base_url': None, 'model.api_mode': None, 'fallback_providers': fallback})
            from config_store import write
            from env_store import drop_env
            old_key = get_env(data / '.env').get(KEY_ENV)
            set_env(data / '.env', {KEY_ENV: inference})
            try:
                write(data, changes)
            except Exception:
                # The config still points at the old combos: give it back the key they work with.
                if old_key:
                    set_env(data / '.env', {KEY_ENV: old_key})
                else:
                    drop_env(data / '.env', [KEY_ENV])
                raise
            previous = state.get('mode') or {}
            delegation = config.get('delegation') or {}
            state['mode'] = {'chat': [s['id_'] for s in chat_steps], 'strong': [s['id_'] for s in strong_steps],
                             'main_switched': bool(fallback), 'key_id': new_key_id,
                             # What leave_mode restores: the aux route from before the mode was first turned on.
                             'previous_delegation': previous.get('previous_delegation', {
                                 k: delegation.get(k) for k in ('provider', 'model') if delegation.get(k)})}
            _save(data, state)
            for k in _items(client, '/api/keys', 'keys'):
                if str(k.get('name') or '').startswith(prefix + '-mode') and k.get('id') != new_key_id:
                    try:
                        client.request('DELETE', '/api/keys/' + _identifier(k.get('id')))
                    except SetupError:
                        pass
        from omh_enhancements import sync_base_route
        sync_base_route(data, PROVIDER_NAME, strong_combo)
        note = f" 시험 실패로 뺀 모델: {', '.join(failed)}." if failed else ''
        where = ('대화는 OmniRoute(' + ', '.join(state['mode']['chat']) + '), OmniRoute가 멈추면 '
                 + fallback[0]['model'] + '로 직접 연결합니다.') if fallback else \
                '대화 모델은 직접 연결을 유지합니다(되돌아갈 직접 연결 모델이 없어서).'
        return True, ('OmniRoute 모드 준비 완료. ' + where + ' 위임·역할 프로필은 ' + ', '.join(state['mode']['strong'])
                      + '.' + note + ' 적용하기(재시작) 후 반영됩니다.')
    except SetupError as exc:
        return False, str(exc) + ' · 기존 설정은 그대로입니다.'
    except Exception as exc:
        return False, f'OmniRoute 모드 설정 실패 ({type(exc).__name__}). 기존 설정은 그대로입니다.'


def leave_mode(data_dir):
    """Chat back on the direct fallback model; delegation back on the main model."""
    from config_store import read, write
    data = Path(data_dir).resolve()
    config = read(data)
    main = config.get('model') or {}
    fallback = config.get('fallback_providers') or []
    if main.get('provider') != PROVIDER_NAME:
        return False, 'OmniRoute 모드가 켜져 있지 않습니다.'
    if not fallback:
        return False, '되돌아갈 직접 연결 모델 기록이 없습니다. 두뇌 선택에서 대화 모델을 지정해 주세요.'
    first = fallback[0]
    state_path = data / STATE
    before = (json.loads(state_path.read_text()).get('mode') or {}).get('previous_delegation') or {} \
        if state_path.exists() else {}
    write(data, {'model.provider': first['provider'], 'model.default': first['model'], 'fallback_providers': None,
                 'delegation.provider': before.get('provider'), 'delegation.model': before.get('model')})
    from model_setup import delegation_route
    route, _ = delegation_route(read(data))
    from omh_enhancements import sync_base_route
    sync_base_route(data, route['provider'], route['model'])
    return True, f"대화를 {first['model']} 직접 연결로 되돌렸습니다. 적용하기(재시작) 후 반영됩니다."
