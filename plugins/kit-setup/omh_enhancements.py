"""Per-task OMH routes and native calibration for students. No personal configuration.

Routing stays upstream. OMH's own `omh_delegate_route` writes `delegation.*` for the
next dispatch from `.omh/routing/model-chains.json` + `model-providers.json`, and
handles fallback and baseline restore itself. The pinned Hermes 0.21.x host has no
`delegate_task(routing=...)`, so the kit never depends on one.

The kit owns exactly two things:
- the two routing documents, composed from the student's aux model (every task
  type, OMH's recommended effort per type) plus any per-task chains the student
  saved in /setup;
- one fail-open addition to the upstream `pre_tool_call` hook that appends OMH's
  native high-effort calibration for the route upstream prepared to the child
  context. It never blocks a dispatch and never writes Hermes config.

The upstream hook file is kept byte-for-byte in a receipt; disabling restores it and
rewrites the basic routing documents. Restart the gateway after enable/disable.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from components import _locked
from config_store import locked as config_locked
from upstream_omh import CATEGORIES

VERSION = 2
# Same grammar OMH accepts for delegation values: anything wider is refused upstream.
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$')
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
# OMH 2.0.5's shipped chain-head effort per task type, capped at `high`: a student's
# provider is not known to accept xhigh. Calibration applies from `high` upward.
DEFAULT_EFFORTS = {
    'ultrabrain': 'high', 'deep': 'high', 'architect': 'high', 'artistry': 'high',
    'visual-engineering': 'high', 'deep-work': 'high', 'writing': 'medium',
    'capable': 'medium', 'unspecified-high': 'medium', 'quick': 'low',
    'simple-work': 'low', 'unspecified-low': 'low',
}
BASE_ALIAS = 'student-selected'
HOOK_FILE = 'plugins/omh/hooks/tool_hooks.py'
PINNED_FILES = {HOOK_FILE: 'a0382ed1cf9f78f0cf9202395c027cd29a01953a3b7983d2142747d764b60e3b'}
ROUTE_TOOL = 'plugins/omh/tools/delegate_route_tool.py'  # patched only by v1 receipts
SETTINGS = '.omh/routing/kit-enhanced.json'
RUNTIME = 'plugins/omh/kit_enhanced.py'
RECEIPT = '.kit-tools/omh-enhancements.json'
ROUTE_FILES = ('.omh/routing/model-providers.json', '.omh/routing/model-chains.json')
PROVIDER_SCHEMA = 'model_provider_routes/v1'
CHAIN_SCHEMA = 'mixture_chain_overrides/v1'

# Generated into the installed public plugin; no owner-specific prompts, endpoints,
# routes, credentials or personal skill data are embedded.
RUNTIME_SOURCE = r'''"""Kit calibration over upstream OMH routing. Fail-open: never blocks a dispatch."""
import hashlib, json, subprocess, sys, threading
from copy import deepcopy
from pathlib import Path
HOME = Path(__file__).resolve().parents[2]
SETTINGS = HOME / '.omh/routing/kit-enhanced.json'
OMNIROUTE_STATE = HOME / '.kit-omniroute.json'
_CACHE = {}
_LOCK = threading.Lock()
_MODULES = []
# Added when OMH cannot name the serving model's family, e.g. a combo that may switch
# vendors between dispatches: invariants that hold whichever model answers.
FLOOR = ("Route floor (the serving model may change within this route): run one full verification pass "
         "before reporting; change files with targeted edits instead of rewriting whole files; never "
         "claim completion without execution evidence.")
_SCRIPT = """import hashlib,json,sys
from omh.coding import unit_prompt_protocol as p
from omh.coding.model_routing import model_family
r=json.load(sys.stdin)
f=model_family(r['model']) or 'unknown'
g=p.calibration_for_route({'selected_model':r['model'],'selected_reasoning_effort':r['reasoning_effort'],'model_family':f})
print(json.dumps({'guidance':g,'family':f,'guidance_sha256':hashlib.sha256(g.encode()).hexdigest()}))
"""

def settings():
    try:
        d=json.loads(SETTINGS.read_text())
    except (OSError,ValueError):
        return None
    return d if isinstance(d,dict) and d.get('enabled') is True else None

def current_route():
    from .delegation_routing import read_delegation_route
    return read_delegation_route(HOME)

def family_model(route):
    """The kit's own OmniRoute combo holds exactly one model: calibrate for that model."""
    model=str(route.get('model') or '')
    if route.get('provider')=='kit-omniroute':
        try:
            active=json.loads(OMNIROUTE_STATE.read_text()).get('active') or {}
            if active.get('name')==model and isinstance(active.get('model'),str): return active['model']
        except (OSError,ValueError,AttributeError):
            pass
    return model

def _in_process(config):
    """OMH's pure-Python package, imported once from its own venv when the interpreter
    matches; the subprocess below is the fallback, so a mismatch only costs latency."""
    with _LOCK:
        if not _MODULES:
            _MODULES.append(None)
            try:
                site = Path(config['python']).parent.parent / 'lib' / f'python{sys.version_info[0]}.{sys.version_info[1]}' / 'site-packages'
                if (site / 'omh').is_dir():
                    if str(site) not in sys.path: sys.path.append(str(site))
                    from omh.coding import unit_prompt_protocol as p
                    from omh.coding.model_routing import model_family
                    _MODULES[0] = (p, model_family)
            except Exception:
                _MODULES[0] = None
        return _MODULES[0]

def calibrate(model, effort, config):
    key=(model,effort)
    with _LOCK:
        if key in _CACHE: return _CACHE[key]
    modules=_in_process(config)
    if modules:
        p, model_family = modules
        family = model_family(model) or 'unknown'
        guidance = p.calibration_for_route({'selected_model':model,'selected_reasoning_effort':effort,'model_family':family})
        d = {'guidance':guidance,'family':family}
        with _LOCK:
            if len(_CACHE)>=64: _CACHE.clear()
            _CACHE[key]=d
        return d
    result=subprocess.run([config['python'],'-c',_SCRIPT],input=json.dumps({'model':model,'reasoning_effort':effort}),
                          text=True,capture_output=True,timeout=10,check=False)
    if result.returncode or len(result.stdout)>65536: raise RuntimeError('calibration unavailable')
    d=json.loads(result.stdout)
    if not isinstance(d.get('guidance'),str) or hashlib.sha256(d['guidance'].encode()).hexdigest()!=d.get('guidance_sha256'):
        raise RuntimeError('invalid calibration')
    with _LOCK:
        if len(_CACHE)>=64: _CACHE.clear()
        _CACHE[key]=d
    return d

def guidance_for(route, config):
    if not isinstance(route,dict) or not route.get('model'): return ''
    d = calibrate(family_model(route), str(route.get('reasoning_effort') or ''), config)
    parts = [d['guidance'].strip()] + ([FLOOR] if d.get('family') in (None, '', 'unknown') else [])
    return '\n\n'.join(part for part in parts if part)

def guard(tool_name, args, **kwargs):
    """Append calibration for the route upstream prepared. Any failure dispatches unchanged."""
    if tool_name!='delegate_task' or not isinstance(args,dict) or (args.get('action') or 'spawn')!='spawn': return None
    try:
        config=settings()
        if not config: return None
        guidance=guidance_for(current_route(),config).strip()
        if not guidance: return None
        changed={}
        if isinstance(args.get('tasks'),list):
            tasks=deepcopy(args['tasks'])
            for task in tasks:
                if isinstance(task,dict) and isinstance(task.get('context',''),str) and guidance not in task.get('context',''):
                    task['context']=(task.get('context','')+'\n\n'+guidance).strip()
            if tasks!=args['tasks']: changed['tasks']=tasks
        else:
            context=args.get('context','')
            if isinstance(context,str) and guidance not in context: changed['context']=(context+'\n\n'+guidance).strip()
        return {'action':'modify','args':changed} if changed else None
    except Exception:
        return None
'''

HOOK_APPEND = '''
# kit-enhanced-omh/v2: upstream governance first; the kit only appends calibration context.
_KIT_BASIC_PRE_TOOL = pre_tool_call
from .. import kit_enhanced as _kit_enhanced
def pre_tool_call(**kwargs):
    original = _KIT_BASIC_PRE_TOOL(**kwargs)
    if original and original.get('action') != 'modify': return original
    try:
        args = kwargs.get('tool_input') if 'tool_input' in kwargs else kwargs.get('args')
        if isinstance(args, dict):
            args = dict(args)
            if original: args.update(original.get('args') or {})
        directive = _kit_enhanced.guard(kwargs.get('tool_name'), args)
    except Exception:
        return original
    if not directive: return original
    return {'action': 'modify', 'args': {**((original or {}).get('args') or {}), **directive['args']}}
'''


def validate_chain(chain):
    if not isinstance(chain, list) or not 1 <= len(chain) <= 5:
        raise ValueError('one to five candidates required')
    result, seen = [], set()
    for entry in chain:
        if not isinstance(entry, dict) or set(entry) != {'model', 'provider', 'reasoning_effort'}:
            raise ValueError('explicit model/provider/effort required')
        if any(not isinstance(entry[k], str) or not TOKEN.fullmatch(entry[k]) for k in ('model', 'provider')):
            raise ValueError('invalid route identifier')
        if entry['provider'] in ('auto', 'default', 'custom') or entry['model'] in ('auto', 'default'):
            raise ValueError('explicit routing required')
        if entry['reasoning_effort'] not in EFFORTS:
            raise ValueError('unsupported effort')
        identity = (entry['provider'], entry['model'])
        if identity in seen:
            raise ValueError('duplicate chain entry')
        seen.add(identity)
        result.append(dict(entry))
    return result


def validate_categories(category_routes):
    if not isinstance(category_routes, dict) or set(category_routes) - set(CATEGORIES):
        raise ValueError('explicit known task categories required')
    return {category: validate_chain(chain) for category, chain in category_routes.items()}


def validate_base(base):
    if base is None:
        return None
    if not isinstance(base, dict) or set(base) != {'model', 'provider'}:
        raise ValueError('invalid base route')
    validate_chain([{**base, 'reasoning_effort': 'medium'}])
    return dict(base)


def compose(base, categories):
    """Both routing documents. One alias per provider/model: OMH maps a live route back
    to its chain position by alias, and two aliases for one identity make fallback ambiguous."""
    aliases, models = {}, {}
    def alias(provider, model):
        identity = (provider, model)
        if identity not in aliases:
            name = BASE_ALIAS if base and identity == (base['provider'], base['model']) else \
                'kit-' + hashlib.sha256(f'{provider}\n{model}'.encode()).hexdigest()[:12]
            aliases[identity] = name
            models[name] = {'model': model, 'provider': provider}
        return aliases[identity]
    chains = {}
    for category in CATEGORIES:
        chain = categories.get(category)
        if chain is None and base:
            chain = [{**base, 'reasoning_effort': DEFAULT_EFFORTS[category]}]
        if chain:
            chains[category] = [{'model': alias(e['provider'], e['model']), 'reasoning_effort': e['reasoning_effort']}
                                for e in chain]
    providers = {'schema_version': PROVIDER_SCHEMA, 'models': dict(sorted(models.items()))}
    return providers, {'schema_version': CHAIN_SCHEMA, 'categories': chains}


def _encode(document):
    return (json.dumps(document, indent=2) + '\n').encode()


def _base_from_documents(provider_blob, chain_blob):
    """Recognize exactly what the kit's basic install wrote (any version); else None."""
    try:
        providers, chains = json.loads(provider_blob), json.loads(chain_blob)
        models = providers.get('models')
        if providers.get('schema_version') != PROVIDER_SCHEMA or set(models) != {BASE_ALIAS}:
            return None
        base = validate_base(models[BASE_ALIAS])
        categories = chains.get('categories')
        if chains.get('schema_version') != CHAIN_SCHEMA or set(categories) != set(CATEGORIES):
            return None
        for chain in categories.values():
            if len(chain) != 1 or chain[0].get('model') != BASE_ALIAS or chain[0].get('reasoning_effort') not in EFFORTS:
                return None
        return base
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


def _sha(blob): return hashlib.sha256(blob).hexdigest()


def _safe(data, relative):
    target = data / relative
    for p in [target, *target.parents]:
        if p == data.parent: break
        if p.is_symlink(): raise ValueError('installation links refused')
    return target


def _write(path, blob):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.omh-enhance-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f: f.write(blob)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def _apply(data, updates, rollback):
    """Write every update or none. `rollback` maps path -> previous bytes (None = absent)."""
    written = []
    try:
        for name, blob in updates.items():
            if blob is not None and name.endswith('.py'): compile(blob, name, 'exec')
        for name, blob in updates.items():
            path = _safe(data, name)
            if blob is None: path.unlink(missing_ok=True)
            else: _write(path, blob)
            written.append(name)
    except Exception:
        for name in reversed(written):
            previous = rollback.get(name)
            if previous is None: _safe(data, name).unlink(missing_ok=True)
            else: _write(_safe(data, name), previous)
        raise


def _read(data, name):
    path = _safe(data, name)
    return path.read_bytes() if path.exists() else None


def _python(data):
    cli = (data / '.local/bin/omh').resolve(strict=True)
    if not cli.is_relative_to(data): raise ValueError('external OMH interpreter refused')
    python = cli.parent / 'python'
    if not python.is_file(): raise ValueError('OMH interpreter unavailable')
    return str(python)


def _load_receipt(data):
    path = _safe(data, RECEIPT)
    if not path.exists(): return None
    receipt = json.loads(path.read_text())
    if any(not _safe(data, k).is_file() or _sha(_safe(data, k).read_bytes()) != v for k, v in receipt['after'].items()):
        raise FileExistsError('edited after install')
    return receipt


def enable_locked(data, *, updates=None, remove=(), base=False):
    """Caller holds the component and config locks. `base=False` keeps the stored aux route.

    First enable needs the pinned, unmodified upstream hook and routing documents the
    kit wrote itself; later calls merge task chains into the stored settings.
    """
    updates = validate_categories(updates or {})
    if set(remove) - set(CATEGORIES): raise ValueError('unknown task category')
    receipt = _load_receipt(data)
    if receipt and receipt.get('version') != VERSION:
        _disable_locked(data, receipt)  # v1 relied on host routing Hermes 0.21 never had
        receipt = None
    if receipt:
        settings = json.loads(_read(data, SETTINGS))
        stored_base, categories = settings.get('base'), settings['categories']
        hook_before = receipt['before'][HOOK_FILE]
    else:
        hook = _read(data, HOOK_FILE)
        if hook is None or _sha(hook) != PINNED_FILES[HOOK_FILE]:
            raise ValueError('pinned unmodified OMH 2.0.5 required')
        if _read(data, RUNTIME) is not None or _read(data, SETTINGS) is not None:
            raise ValueError('unmanaged enhancement exists')
        provider_blob, chain_blob = (_read(data, name) for name in ROUTE_FILES)
        stored_base = None
        if provider_blob is not None or chain_blob is not None:
            stored_base = _base_from_documents(provider_blob or b'', chain_blob or b'')
            if stored_base is None: raise FileExistsError('routing documents were customized')
        categories = {}
        hook_before = base64.b64encode(hook).decode()
    if base is not False: stored_base = validate_base(base)
    categories = {k: v for k, v in {**categories, **updates}.items() if k not in remove}
    if stored_base is None and set(categories) != set(CATEGORIES):
        # Uncovered task types would fall back to OMH's shipped chains, which name
        # models this student's accounts are not known to serve.
        raise ValueError('aux route required')
    settings = {'version': VERSION, 'enabled': True, 'python': _python(data),
                'base': stored_base, 'categories': dict(sorted(categories.items()))}
    providers, chains = compose(stored_base, categories)
    blobs = {SETTINGS: _encode(settings), ROUTE_FILES[0]: _encode(providers), ROUTE_FILES[1]: _encode(chains),
             RUNTIME: RUNTIME_SOURCE.encode()}
    if not receipt: blobs[HOOK_FILE] = base64.b64decode(hook_before) + HOOK_APPEND.encode()
    rollback = {name: _read(data, name) for name in blobs}
    after = {**(receipt or {}).get('after', {}), **{k: _sha(v) for k, v in blobs.items()}}
    new_receipt = {'version': VERSION, 'before': {HOOK_FILE: hook_before}, 'after': after}
    _apply(data, {**blobs, RECEIPT: _encode(new_receipt)}, {**rollback, RECEIPT: _read(data, RECEIPT)})
    return settings


def enable_enhanced_omh(data_dir, *, category_routes=None, remove=()):
    """Save per-task chains (merged with earlier ones) and turn calibration on."""
    try:
        data = Path(data_dir).resolve()
        with _locked(data), config_locked(data):
            enable_locked(data, updates=category_routes, remove=remove)
        return {'status': 'enabled', 'restart_required': True,
                'message': '작업별 모델 경로와 보정을 저장했습니다. 적용하기(재시작) 후 반영됩니다.'}
    except FileExistsError:
        return {'status': 'conflict', 'message': 'OMH 경로 파일이 키트 밖에서 수정되어 보존했습니다. 덮어쓰지 않았습니다.'}
    except Exception as exc:
        return {'status': 'failed', 'message': '강화 모드 설정 실패; 기존 설정을 보존했습니다. (' + type(exc).__name__ + ')'}


def sync_base_route(data_dir, provider, model):
    """Follow a changed aux model. Only kit-written routing documents are rewritten."""
    try:
        data = Path(data_dir).resolve()
        base = validate_base({'provider': provider, 'model': model})
        with _locked(data), config_locked(data):
            if not (data / 'plugins/omh').is_dir(): return {'status': 'absent'}
            if _safe(data, RECEIPT).exists():
                enable_locked(data, base=base)
            else:
                provider_blob, chain_blob = (_read(data, name) for name in ROUTE_FILES)
                if _base_from_documents(provider_blob or b'', chain_blob or b'') is None:
                    return {'status': 'preserved'}
                providers, chains = compose(base, {})
                blobs = {ROUTE_FILES[0]: _encode(providers), ROUTE_FILES[1]: _encode(chains)}
                _apply(data, blobs, {ROUTE_FILES[0]: provider_blob, ROUTE_FILES[1]: chain_blob})
        return {'status': 'synced'}
    except FileExistsError:
        return {'status': 'preserved'}
    except Exception as exc:
        return {'status': 'failed', 'error': type(exc).__name__}


def _disable_locked(data, receipt):
    allowed = {HOOK_FILE, ROUTE_TOOL}
    if not set(receipt['before']) <= allowed | {RUNTIME, SETTINGS, *ROUTE_FILES}:
        raise ValueError('invalid receipt')
    base = None
    try:
        base = validate_base(json.loads(_read(data, SETTINGS)).get('base'))
    except (TypeError, ValueError, AttributeError):
        pass
    blobs, rollback = {}, {}
    for name in receipt['after']:
        rollback[name] = _read(data, name)
        encoded = receipt['before'].get(name)
        blobs[name] = base64.b64decode(encoded, validate=True) if encoded else None
    if base:
        providers, chains = compose(base, {})
        blobs[ROUTE_FILES[0]], blobs[ROUTE_FILES[1]] = _encode(providers), _encode(chains)
    blobs[RECEIPT] = None
    rollback[RECEIPT] = _read(data, RECEIPT)
    _apply(data, blobs, rollback)


def disable_enhanced_omh(data_dir):
    """Restore the exact upstream hook and the basic aux-model routes."""
    try:
        data = Path(data_dir).resolve()
        with _locked(data), config_locked(data):
            if not _safe(data, RECEIPT).exists(): return {'status': 'disabled', 'restart_required': False,
                'message': '이미 기본 OMH 상태입니다.'}
            _disable_locked(data, _load_receipt(data))
        return {'status': 'disabled', 'restart_required': True,
                'message': '작업별 경로와 보정을 끄고 기본 OMH로 복원했습니다. 적용하기(재시작) 후 반영됩니다.'}
    except FileExistsError:
        return {'status': 'conflict', 'message': '설치 이후 바뀐 파일을 보존했습니다. 자동 복원을 중단했습니다.'}
    except Exception as exc:
        return {'status': 'failed', 'message': '강화 모드 복원 실패 (' + type(exc).__name__ + ')'}


def describe(data_dir):
    """Plain status for /setup and /doctor: mode, base route and per-task chains."""
    data = Path(data_dir).resolve()
    if not (data / 'plugins/omh').is_dir():
        return {'installed': False}
    info = {'installed': True, 'calibration': False, 'base': None, 'categories': {}}
    try:
        if _safe(data, RECEIPT).exists():
            settings = json.loads(_read(data, SETTINGS))
            info.update(calibration=bool(settings.get('enabled')), base=settings.get('base'),
                        categories=settings.get('categories') or {})
        else:
            info['base'] = _base_from_documents(_read(data, ROUTE_FILES[0]) or b'', _read(data, ROUTE_FILES[1]) or b'')
    except Exception as exc:
        info['error'] = type(exc).__name__
    return info
