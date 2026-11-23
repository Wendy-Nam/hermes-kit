"""Recommended OmniRoute available-resource combo presets & OMH routing/calibration wiring.

Inspects the user's connected OmniRoute dashboard providers (free pool + subscriptions),
filters the author's proven combo templates (hermes-chat, hermes-free, hermes-fast,
hermes-coding, hermes-ultrabrain, hermes-writing, hermes-visual-engineering, hermes-vision)
and OMH 12-category routing chains down to the models actually served by the user's
active connections, creates/updates the combos in OmniRoute, and wires OMH's per-category
routing + bias calibration (`enable_enhanced_omh` + `omh_routing.apply`).

Safe and non-destructive:
- Never modifies or deletes user provider connections.
- Only creates combos whose candidates match active connections on the user's OmniRoute.
- Preserves existing direct fallback providers so an OmniRoute outage never bricks chat.
"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from components import _locked
from env_store import get_env, set_env
from omniroute_mode import _chat_models, _connections, _replace_combo
from omniroute_setup import (
    BASE,
    KEY_ENV,
    PROVIDER_NAME,
    STATE,
    Client,
    SetupError,
    _identifier,
    _items,
    _probe,
    _save,
)

# Privacy classification (docs/omniroute-providers.md):
# - PRIVATE_PROVIDERS: subscriptions or zero-training APIs allowed in private/personal combos.
# - TRAINING_FREE_PROVIDERS: free/training-capable aggregators restricted strictly to public/free combos (`hermes-free`).
PRIVATE_PROVIDERS = frozenset({
    'claude', 'codex', 'agy', 'antigravity', 'cohere', 'mistral',
    'cloudflare-ai', 'scaleway', 'exaone', 'opencode-go', 'kiro',
    'openai', 'anthropic', 'upstage',
})
TRAINING_FREE_PROVIDERS = frozenset({
    'openrouter', 'kilocode', 'nvidia', 'cline', 'orcarouter', 'inception',
    'electronhub', 'kilo-anon', 'ovh-anon', 'clod', 'dreamprompting', 'septor',
    'unorouter', 'sail', 'xkiro', 'agnes',
})
PUBLIC_ONLY_COMBOS = frozenset({'hermes-free'})

# Curated candidate pools ordered by tier (head -> subscription -> zero-training API -> reserve).
PRESET_COMBO_SPECS = {
    'hermes-chat': {
        'description': '일상 대화 및 메인 에이전트 콤보 (Codex/Claude/Antigravity/EXAONE/OpenCode-Go)',
        'candidates': [
            'codex/gpt-6-luna',
            'codex/gpt-6.2-sol',
            'claude/claude-sonnet-5-5',
            'claude/claude-sonnet-5',
            'anthropic/claude-sonnet-4-6',
            'agy/claude-sonnet-4-6',
            'agy/gemini-3.8-flash-medium',
            'antigravity/claude-sonnet-4-6',
            'antigravity/gemini-3.8-flash-tiered',
            'exaone/k-exaone_v2.5',
            'upstage/solar-pro4',
            'opencode-go/deepseek/deepseek-v4.1-flash',
            'openai/gpt-4.1',
            'gemini/gemini-2.5-flash',
            'cloudflare-ai/@cf/openai/gpt-oss-120b',
        ],
    },
    'hermes-free': {
        'description': '공개·무료 가용 리소스 전용 콤보 (개인 데이터 미전송 공개 작업용)',
        'candidates': [
            'unorouter/kimi-k3:free',
            'sail/moonshotai/Kimi-K3',
            'sail/zai-org/GLM-5.3',
            'sail/zai-org/GLM-5.3-Flash',
            'cline/deepseek/deepseek-v4.1-flash',
            'cline/nvidia/nemotron-3-ultra-550b-a55b:free',
            'cline/nvidia/nemotron-3-super-120b-a12b:free',
            'cline/qwen/qwen3.8-27b:free',
            'cline/google/gemma-4-31b-it:free',
            'nvidia/nvidia/nemotron-3-ultra-550b-a55b',
            'openrouter/google/gemma-4-31b-it:free',
            'gemini/gemini-2.5-flash',
            'mistral/ministral-14b-latest',
            'mistral/ministral-8b-latest',
            'cloudflare-ai/@cf/openai/gpt-oss-120b',
            'xkiro/qwen/qwen3.8-max:free',
        ],
    },
    'hermes-fast': {
        'description': '초고속 경량 도구 호출 콤보 (quick / simple-work 위임용)',
        'candidates': [
            'exaone/k-exaone_v2.5',
            'mistral/ministral-8b-latest',
            'mistral/ministral-14b-latest',
            'codex/gpt-6-luna',
            'claude/claude-haiku-5-5',
            'claude/claude-haiku-4-5-20251001',
            'anthropic/claude-haiku-4-5-20251001',
            'agy/gemini-3.8-flash-medium',
            'gemini/gemini-2.5-flash',
            'openai/gpt-4.1-mini',
            'cloudflare-ai/@cf/openai/gpt-oss-120b',
        ],
    },
    'hermes-coding': {
        'description': '코딩·구현·디버깅 중심 콤보 (capable / deep-work / unspecified-high 위임용)',
        'candidates': [
            'codex/gpt-6.2-sol',
            'codex/gpt-6-sol',
            'claude/claude-opus-5-5',
            'claude/claude-opus-5',
            'claude/claude-sonnet-5-5',
            'claude/claude-sonnet-5',
            'anthropic/claude-sonnet-4-6',
            'kiro/claude-sonnet-4-5',
            'agy/gemini-3.1-pro-high',
            'agy/claude-sonnet-4-6',
            'opencode-go/deepseek/deepseek-v4.1-flash',
            'mistral/codestral-latest',
            'openai/gpt-4.1',
            'gemini/gemini-2.5-pro',
            'scaleway/qwen3-235b-a22b-instruct-2507',
        ],
    },
    'hermes-ultrabrain': {
        'description': '고난도 추론·아키텍처·심층 분석 콤보 (ultrabrain / architect / deep 위임용)',
        'candidates': [
            'codex/gpt-6.2-astra',
            'codex/gpt-6-astra',
            'codex/gpt-6.2-sol',
            'codex/gpt-6-sol',
            'claude/claude-fable-5-2',
            'claude/claude-opus-5-5',
            'claude/claude-opus-5',
            'anthropic/claude-opus-4-6',
            'agy/gemini-3.1-pro-high',
            'agy/claude-opus-4-6-thinking',
            'antigravity/gemini-3.1-pro-high',
            'antigravity/claude-opus-4-6-thinking',
            'gemini/gemini-2.5-pro',
            'scaleway/qwen3-235b-a22b-instruct-2507',
        ],
    },
    'hermes-writing': {
        'description': '한국어/다국어 문서 작성·요약·창작 콤보 (writing / artistry 위임용)',
        'candidates': [
            'exaone/k-exaone_v2.5',
            'upstage/solar-pro4',
            'agy/gemini-3.1-pro-high',
            'claude/claude-opus-5-5',
            'claude/claude-opus-5',
            'claude/claude-sonnet-5-5',
            'claude/claude-sonnet-5',
            'anthropic/claude-sonnet-4-6',
            'cohere/command-a-03-2025',
            'codex/gpt-6.2-sol',
            'codex/gpt-6-sol',
            'opencode-go/deepseek/deepseek-v4.1-flash',
            'gemini/gemini-2.5-pro',
            'cloudflare-ai/@cf/openai/gpt-oss-120b',
        ],
    },
    'hermes-visual-engineering': {
        'description': 'UI/UX·프론트엔드·시각 엔지니어링 콤보 (visual-engineering 위임용)',
        'candidates': [
            'claude/claude-fable-5-2',
            'claude/claude-opus-5-5',
            'claude/claude-opus-5',
            'anthropic/claude-sonnet-4-6',
            'agy/gemini-3.1-pro-high',
            'codex/gpt-6.2-sol',
            'codex/gpt-6-sol',
            'gemini/gemini-2.5-pro',
            'cloudflare-ai/@cf/openai/gpt-oss-120b',
        ],
    },
}

# Maps OMH's 12 task categories to ordered (combo_name, reasoning_effort) chains.
OMH_CATEGORY_COMBO_CHAINS = {
    'ultrabrain': [('hermes-ultrabrain', 'high'), ('hermes-coding', 'high'), ('hermes-free', 'high')],
    'deep': [('hermes-ultrabrain', 'high'), ('hermes-coding', 'high'), ('hermes-free', 'high')],
    'architect': [('hermes-ultrabrain', 'high'), ('hermes-coding', 'high'), ('hermes-free', 'high')],
    'deep-work': [('hermes-coding', 'high'), ('hermes-ultrabrain', 'high'), ('hermes-free', 'high')],
    'visual-engineering': [('hermes-visual-engineering', 'high'), ('hermes-coding', 'high'), ('hermes-free', 'high')],
    'artistry': [('hermes-writing', 'high'), ('hermes-ultrabrain', 'high'), ('hermes-free', 'high')],
    'writing': [('hermes-writing', 'medium'), ('hermes-chat', 'medium'), ('hermes-free', 'medium')],
    'capable': [('hermes-coding', 'medium'), ('hermes-chat', 'medium'), ('hermes-free', 'medium')],
    'unspecified-high': [('hermes-coding', 'medium'), ('hermes-ultrabrain', 'medium'), ('hermes-free', 'medium')],
    'quick': [('hermes-fast', 'low'), ('hermes-free', 'low'), ('hermes-chat', 'low')],
    'simple-work': [('hermes-fast', 'low'), ('hermes-free', 'low'), ('hermes-chat', 'low')],
    'unspecified-low': [('hermes-free', 'low'), ('hermes-fast', 'low'), ('hermes-chat', 'low')],
}


def discover_available_models(client, connections=None):
    """Return (connections_by_prefix, available_models_by_prefix).

    If a provider's `/models` endpoint is empty or uses dynamic pass-through (e.g. cline, upstage),
    its prefix is still recorded so curated candidates on that connection can be matched.
    """
    if connections is None:
        connections = _connections(client)
    catalog = {}
    for prefix, conn in connections.items():
        models = set()
        default_model = conn.get('defaultModel')
        if isinstance(default_model, str) and default_model.strip():
            models.add(default_model.strip())
        try:
            res, _ = client.request('GET', '/api/providers/' + _identifier(conn.get('id')) + '/models')
            for mid, _ in _chat_models(res.get('models') or []):
                models.add(mid)
        except Exception:
            pass
        catalog[prefix] = models
    return connections, catalog


def plan_presets(connections, catalog):
    """Build concrete combo step lists filtered to the user's active OmniRoute connections.

    Enforces privacy separation: training-capable free providers (`TRAINING_FREE_PROVIDERS`)
    are only placed in public/free combos (`PUBLIC_ONLY_COMBOS`), never in private combos.
    """
    planned = {}
    for combo_name, spec in PRESET_COMBO_SPECS.items():
        is_public = combo_name in PUBLIC_ONLY_COMBOS
        steps = []
        seen = set()
        for candidate in spec['candidates']:
            if '/' not in candidate or candidate in seen:
                continue
            prefix, model = candidate.split('/', 1)
            if not is_public and prefix in TRAINING_FREE_PROVIDERS:
                continue
            conn = connections.get(prefix)
            if conn is None:
                continue
            known = catalog.get(prefix) or set()
            # If the provider returned an explicit catalog, prefer models in it or well-known pass-through prefixes
            if known and model not in known and prefix not in ('cline', 'upstage', 'openrouter', 'nvidia', 'cloudflare-ai'):
                continue
            seen.add(candidate)
            steps.append({
                'provider': conn['provider'],
                'model': model,
                'connectionId': _identifier(conn.get('id')),
                'id_': candidate,
            })
        # Fallback: if no curated candidates matched, pick default/first chat models while respecting privacy boundary.
        if not steps:
            for prefix, conn in connections.items():
                if not is_public and prefix in TRAINING_FREE_PROVIDERS:
                    continue
                models = sorted(catalog.get(prefix) or [])
                pick = conn.get('defaultModel') or (models[0] if models else None)
                if pick:
                    cid = f'{prefix}/{pick}'
                    if cid not in seen:
                        seen.add(cid)
                        steps.append({
                            'provider': conn['provider'],
                            'model': pick,
                            'connectionId': _identifier(conn.get('id')),
                            'id_': cid,
                        })
                if len(steps) >= 5:
                    break
        if steps:
            planned[combo_name] = {
                'description': spec['description'],
                'steps': steps[:15],
            }
    return planned


def plan(data_dir, password):
    """Inspect active OmniRoute connections and return a dry-run preset plan without modifying anything."""
    try:
        if not isinstance(password, str) or not password.strip():
            raise SetupError('대시보드 비밀번호를 입력해 주세요')
        client = Client()
        client.request('POST', '/api/auth/login', {'password': password.strip()})
        connections, catalog = discover_available_models(client)
        if not connections:
            return {'status': 'failed', 'message': 'OmniRoute 대시보드에 활성화된 제공자 연결이 없습니다. 먼저 무료 풀이나 구독 계정을 연결해 주세요.'}
        planned = plan_presets(connections, catalog)
        if not planned:
            return {'status': 'failed', 'message': '연결된 제공자에서 사용할 수 있는 대화/도구 모델을 찾지 못했습니다.'}
        summary_rows = []
        for name, info in planned.items():
            preview = ', '.join(s['id_'] for s in info['steps'][:4])
            more = f" 외 {len(info['steps']) - 4}개" if len(info['steps']) > 4 else ''
            summary_rows.append(f"- `{name}` ({len(info['steps'])}개 후보): {preview}{more}")
        return {
            'status': 'ok',
            'connections': sorted(connections.keys()),
            'combos': {k: [s['id_'] for s in v['steps']] for k, v in planned.items()},
            'message': (
                f"활성 제공자 {len(connections)}개({', '.join(sorted(connections.keys()))}) 기준으로 "
                f"추천 콤보 {len(planned)}종 구성을 계산했습니다:\n" + '\n'.join(summary_rows)
            ),
        }
    except SetupError as exc:
        return {'status': 'failed', 'message': str(exc)}
    except Exception as exc:
        return {'status': 'failed', 'message': f'OmniRoute 프리셋 계획 실패 ({type(exc).__name__})'}


def apply_presets(data_dir, password, *, probe_heads=False, switch_main=False):
    """Create/update recommended OmniRoute combos and wire them into Hermes delegation + OMH 12-category routing."""
    data = Path(data_dir).resolve()
    try:
        if not isinstance(password, str) or not password.strip() or '\n' in password:
            raise SetupError('대시보드 비밀번호를 입력해 주세요')
        from config_store import read, write
        from env_store import drop_env
        with _locked(data):
            config = read(data)
            state = json.loads((data / STATE).read_text()) if (data / STATE).exists() else \
                {'schema_version': 'kit-omniroute/v1', 'installation': uuid.uuid4().hex}
            client = Client()
            client.request('POST', '/api/auth/login', {'password': password.strip()})
            connections, catalog = discover_available_models(client)
            if not connections:
                raise SetupError('OmniRoute 대시보드에 활성화된 제공자 연결이 없습니다')
            planned = plan_presets(connections, catalog)
            if not planned:
                raise SetupError('생성 가능한 추천 콤보 후보가 없습니다')
            cids = sorted({s['connectionId'] for info in planned.values() for s in info['steps']})
            vision_cid = (state.get('active') or {}).get('connection_id')
            allowed = sorted(set(cids) | ({vision_cid} if vision_cid else set()))
            prefix = 'hermes-kit-' + state['installation'][:12]
            key_name = prefix + '-preset-' + uuid.uuid4().hex[:8]
            created, _ = client.request('POST', '/api/keys', {'name': key_name, 'noLog': True, 'allowedConnections': allowed})
            inference = created.get('key')
            new_key_id = _identifier(created.get('id'))
            if not isinstance(inference, str) or not inference or '\n' in inference:
                try:
                    client.request('DELETE', '/api/keys/' + new_key_id)
                except SetupError:
                    pass
                raise SetupError('추론 키 생성 결과가 올바르지 않습니다')
            try:
                if probe_heads:
                    for combo_name, info in list(planned.items()):
                        kept = []
                        for step in info['steps']:
                            try:
                                _probe(client, step['id_'], inference, step['connectionId'])
                                kept.append(step)
                            except SetupError:
                                continue
                        if kept:
                            info['steps'] = kept
                created_combos = {}
                for combo_name, info in planned.items():
                    _replace_combo(client, combo_name, info['steps'])
                    created_combos[combo_name] = [s['id_'] for s in info['steps']]
            except Exception:
                try:
                    client.request('DELETE', '/api/keys/' + new_key_id)
                except SetupError:
                    pass
                raise
            default_aux_combo = (
                'hermes-coding' if 'hermes-coding' in created_combos
                else ('hermes-free' if 'hermes-free' in created_combos else next(iter(created_combos)))
            )
            default_chat_combo = (
                'hermes-chat' if 'hermes-chat' in created_combos else default_aux_combo
            )
            main = config.get('model') or {}
            fallback = config.get('fallback_providers') or []
            if main.get('provider') not in (None, '', 'auto', 'default', PROVIDER_NAME, 'omniroute') and main.get('default'):
                fallback = [{'provider': main['provider'], 'model': main['default']}]
            changes = {
                'providers.' + PROVIDER_NAME + '.api': BASE + '/v1',
                'providers.' + PROVIDER_NAME + '.key_env': KEY_ENV,
                'providers.' + PROVIDER_NAME + '.transport': 'openai_chat',
                'delegation.provider': PROVIDER_NAME,
                'delegation.model': default_aux_combo,
                'delegation.base_url': None,
                'delegation.api_key': None,
            }
            if switch_main and fallback:
                changes.update({
                    'model.provider': PROVIDER_NAME,
                    'model.default': default_chat_combo,
                    'model.base_url': None,
                    'model.api_mode': None,
                    'fallback_providers': fallback,
                })
            env_before = get_env(data / '.env')
            old_key = env_before.get(KEY_ENV)
            old_omni_key = env_before.get('OMNIROUTE_API_KEY')
            set_env(data / '.env', {KEY_ENV: inference, 'OMNIROUTE_API_KEY': inference})
            try:
                write(data, changes)
            except Exception:
                restore = {}
                drop = []
                if old_key:
                    restore[KEY_ENV] = old_key
                else:
                    drop.append(KEY_ENV)
                if old_omni_key:
                    restore['OMNIROUTE_API_KEY'] = old_omni_key
                else:
                    drop.append('OMNIROUTE_API_KEY')
                if restore:
                    set_env(data / '.env', restore)
                if drop:
                    drop_env(data / '.env', drop)
                try:
                    client.request('DELETE', '/api/keys/' + new_key_id)
                except SetupError:
                    pass
                raise
            state['presets'] = {
                'combos': created_combos,
                'aux_combo': default_aux_combo,
                'chat_combo': default_chat_combo,
                'key_id': new_key_id,
            }
            _save(data, state)
            for k in _items(client, '/api/keys', 'keys'):
                if str(k.get('name') or '').startswith(prefix + '-preset-') and k.get('id') != new_key_id:
                    try:
                        client.request('DELETE', '/api/keys/' + _identifier(k.get('id')))
                    except SetupError:
                        pass
        # Outside lock: wire OMH base route + 12-category chains + quota-aware routing patches
        from omh_enhancements import enable_enhanced_omh, sync_base_route
        from omh_routing import apply as apply_omh_routing
        sync_base_route(data, PROVIDER_NAME, default_aux_combo)
        omh_wired = False
        if (data / 'plugins/omh').is_dir():
            category_routes = {}
            for cat, raw_chain in OMH_CATEGORY_COMBO_CHAINS.items():
                chain_entries = []
                for cname, effort in raw_chain:
                    if cname in created_combos:
                        chain_entries.append({
                            'provider': PROVIDER_NAME,
                            'model': cname,
                            'reasoning_effort': effort,
                        })
                if chain_entries:
                    category_routes[cat] = chain_entries
            if category_routes:
                res = enable_enhanced_omh(data, category_routes=category_routes)
                omh_wired = res.get('status') == 'enabled'
            apply_omh_routing(data)
        omh_msg = ' OMH 12개 작업 카테고리별 라우팅 체인 및 편향 보정(calibration)까지 자동 연결했습니다.' if omh_wired else \
                  ' (OMH 설치 후 다시 실행하면 12개 카테고리 체인도 자동 연결됩니다.)'
        return {
            'status': 'ok',
            'combos': created_combos,
            'omh_wired': omh_wired,
            'message': (
                f"OmniRoute 추천 가용 리소스 콤보 {len(created_combos)}종({', '.join(created_combos.keys())}) 생성 완료!"
                f" 기본 위임 경로는 `{PROVIDER_NAME}/{default_aux_combo}`로 설정되었습니다.{omh_msg}"
                " 적용하기(재시작) 후 반영됩니다."
            ),
        }
    except SetupError as exc:
        return {'status': 'failed', 'message': str(exc) + ' · 기존 설정은 그대로입니다.'}
    except Exception as exc:
        return {'status': 'failed', 'message': f'OmniRoute 추천 프리셋 적용 실패 ({type(exc).__name__}). 기존 설정은 그대로입니다.'}
