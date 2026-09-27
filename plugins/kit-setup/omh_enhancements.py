"""Optional public OMH per-task routing/calibration. No personal configuration.

Patch only the pinned, unmodified upstream plugin. The basic plugin is retained
byte-for-byte in a rollback receipt; neither enabling nor dispatch writes global
Hermes delegation defaults. Restart the gateway after enable/disable.
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

VERSION = 1
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$')
EFFORTS = frozenset({'low','medium','high','xhigh','max'})
PINNED_FILES = {
    'plugins/omh/tools/delegate_route_tool.py': '79e4fbb1f83113235bbd19d3507df3b99ef7cd6d9bf69174a4a65e44213b2b60',
    'plugins/omh/hooks/tool_hooks.py': 'a0382ed1cf9f78f0cf9202395c027cd29a01953a3b7983d2142747d764b60e3b',
}
SETTINGS = '.omh/routing/kit-enhanced.json'
RUNTIME = 'plugins/omh/kit_enhanced.py'
RECEIPT = '.kit-tools/omh-enhancements.json'
ROUTE_FILES = ('.omh/routing/model-providers.json', '.omh/routing/model-chains.json')

# This module is generated into the installed public plugin; no owner-specific
# prompts, endpoints, routes, credentials or personal skill data are embedded.
RUNTIME_SOURCE = r'''"""Opt-in immutable student routing and native OMH calibration."""
import hashlib, inspect, json, subprocess, threading, time
from copy import deepcopy
from pathlib import Path
from .host_observation import host_session_id
HOME = Path(__file__).resolve().parents[2]
SETTINGS = HOME / '.omh/routing/kit-enhanced.json'
_ISSUED = {}
_LOCK = threading.Lock()
_SCRIPT = """import hashlib,json,sys
from pathlib import Path
from omh.coding import unit_prompt_protocol as p
from omh.coding.model_routing import model_family
r=json.load(sys.stdin)
f='unknown' if r['kind']=='combo' else model_family(r['model'])
g=p.calibration_for_route({'selected_model':r['model'] if r['kind']=='model' else '', 'selected_reasoning_effort':r['reasoning_effort'], 'model_family':f})
print(json.dumps({'guidance':g,'family':f,'guidance_sha256':hashlib.sha256(g.encode()).hexdigest(),'source_sha256':hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()}))
"""

def settings():
    if not SETTINGS.exists(): return None
    try:
        d=json.loads(SETTINGS.read_text())
        return d if d.get('enabled') is True else None
    except (OSError,ValueError,TypeError,AttributeError):
        return {'enabled':True,'invalid':True}

def native_supported():
    try:
        from tools.delegate_tool import delegate_task, DELEGATE_TASK_SCHEMA
        return 'routing' in inspect.signature(delegate_task).parameters and 'routing' in DELEGATE_TASK_SCHEMA.get('parameters',{}).get('properties',{})
    except (ImportError,ValueError,TypeError): return False

def native_route(entry):
    return {k:entry[k] for k in ('model','provider','reasoning_effort')}

def calibrate(entry, config):
    result=subprocess.run([config['python'],'-c',_SCRIPT],input=json.dumps(entry),text=True,capture_output=True,timeout=5,check=False)
    if result.returncode or len(result.stdout)>65536: raise RuntimeError('calibration unavailable')
    d=json.loads(result.stdout)
    if not isinstance(d.get('guidance'),str) or hashlib.sha256(d['guidance'].encode()).hexdigest()!=d.get('guidance_sha256'): raise RuntimeError('invalid calibration')
    return d

def _key(route): return json.dumps(route,sort_keys=True,separators=(',',':'))

def route_handler(args, **kwargs):
    try:
        from . import runtime_paths
        error=runtime_paths.tool_home_error(args)
        if error: return json.dumps(error)
        config=settings()
        if not config: return json.dumps({'status':'disabled'})
        action=args.get('action','set'); categories=config['categories']; category=args.get('category','')
        if action=='status': return json.dumps({'status':'status','mode':'immutable_per_dispatch','categories':categories,'require_route':config['require_route']})
        if action=='clear':
            with _LOCK: _ISSUED.pop(host_session_id(kwargs),None)
            return json.dumps({'status':'cleared','message':'Only this session routing receipts were cleared; no model defaults changed.'})
        if not native_supported(): return json.dumps({'status':'error','error':'native_delegate_routing_unavailable'})
        if category not in categories: return json.dumps({'status':'error','error':'choose a configured category'})
        chain=categories[category]; index=0
        if action=='fallback':
            previous=args.get('previous_routing'); positions=[i for i,e in enumerate(chain) if native_route(e)==previous]
            if len(positions)!=1: return json.dumps({'status':'error','error':'exact previous_routing required'})
            index=positions[0]+1
            if index>=len(chain): return json.dumps({'status':'exhausted','category':category})
        elif action!='set': return json.dumps({'status':'error','error':'unsupported action'})
        if any(args.get(k) for k in ('model','provider','reasoning_effort')):
            return json.dumps({'status':'error','error':'enhanced mode uses configured category entries; edit the selected chain in setup'})
        entry=chain[index]; route=native_route(entry); calibration=calibrate(entry,config)
        sid=host_session_id(kwargs)
        if config['require_route'] and not sid: return json.dumps({'status':'error','error':'host session identity unavailable'})
        with _LOCK:
            now=time.monotonic()
            for stale in [s for s,v in _ISSUED.items() if now-v['at']>14400]: _ISSUED.pop(stale,None)
            if len(_ISSUED)>=256 and sid not in _ISSUED: _ISSUED.pop(min(_ISSUED,key=lambda s:_ISSUED[s]['at']))
            record=_ISSUED.setdefault(sid,{'at':now,'routes':{}});record['at']=now
            record['routes'][_key(route)]=dict(entry)
        return json.dumps({'status':'prepared','category':category,'routing':route,'delegate_args':{'routing':route},'calibration':calibration,'child_context_append':calibration['guidance'],'fallback_candidates':[native_route(e) for e in chain[index+1:]],'dispatch_instructions':'Pass delegate_args.routing unchanged to delegate_task. The hook injects calibration when applicable. This did not dispatch or change model defaults.'})
    except Exception as exc:
        return json.dumps({'status':'error','error':'enhanced route preparation failed','error_type':type(exc).__name__})

def guard(tool_name,args,**kwargs):
    if tool_name!='delegate_task' or not isinstance(args,dict) or args.get('action','spawn')!='spawn': return None
    try:
        config=settings()
        if not config: return None
        route=args.get('routing')
        if not route:
            return {'action':'block','message':'Call omh_delegate_route(action="set", category=...) first and pass delegate_args.routing unchanged. No user approval is needed.'} if config['require_route'] else None
        if not isinstance(route,dict) or set(route)!={'model','provider','reasoning_effort'}: raise ValueError('invalid route')
        candidates=[e for c in config['categories'].values() for e in c if native_route(e)==route]
        if not candidates: raise ValueError('route is not configured')
        if len({e['kind'] for e in candidates})!=1: raise ValueError('ambiguous model identity')
        sid=host_session_id(kwargs)
        with _LOCK:
            receipt=_ISSUED.get(sid)
            issued=receipt and time.monotonic()-receipt['at']<=14400 and _key(route) in receipt['routes']
        if config['require_route'] and not issued:
            return {'action':'block','message':'Prepare this route with omh_delegate_route in the current session before delegating.'}
        guidance=calibrate(candidates[0],config)['guidance']
        if not guidance.strip(): return None
        changed={}
        if isinstance(args.get('tasks'),list):
            tasks=deepcopy(args['tasks'])
            for task in tasks:
                if not isinstance(task,dict) or not isinstance(task.get('context',''),str): raise ValueError('invalid task context')
                if guidance not in task.get('context',''): task['context']=(task.get('context','')+'\n\n'+guidance).strip()
            if tasks!=args['tasks']: changed['tasks']=tasks
        else:
            context=args.get('context','')
            if not isinstance(context,str): raise ValueError('invalid context')
            if guidance not in context: changed['context']=(context+'\n\n'+guidance).strip()
        return {'action':'modify','args':changed} if changed else None
    except Exception as exc:
        return {'action':'block','message':'Enhanced OMH route/calibration unavailable; no child dispatched. ('+type(exc).__name__+')'}
'''

TOOL_APPEND = '''
# kit-enhanced-omh/v1: keep basic handler intact when optional mode is disabled.
_KIT_BASIC_ROUTE_HANDLER = omh_delegate_route_handler
from .. import kit_enhanced as _kit_enhanced
if _kit_enhanced.settings():
    OMH_DELEGATE_ROUTE_SCHEMA['description'] = 'Prepare an immutable per-task route and model calibration. Choose a configured category; pass delegate_args.routing unchanged to delegate_task. Does not change profile defaults.'
    OMH_DELEGATE_ROUTE_SCHEMA['parameters']['properties']['action']['description'] = 'set prepares a route; fallback takes exact previous_routing; status inspects; clear removes only session receipts.'
    OMH_DELEGATE_ROUTE_SCHEMA['parameters']['properties']['previous_routing'] = {'type':'object','description':'Exact routing returned by the preceding route preparation.'}
def omh_delegate_route_handler(args, **kwargs):
    if _kit_enhanced.settings():
        return _kit_enhanced.route_handler(args, **kwargs)
    return _KIT_BASIC_ROUTE_HANDLER(args, **kwargs)
'''
HOOK_APPEND = '''
# kit-enhanced-omh/v1: retain the upstream governance result and unrelated tools.
_KIT_BASIC_PRE_TOOL = pre_tool_call
from .. import kit_enhanced as _kit_enhanced
def pre_tool_call(**kwargs):
    original = _KIT_BASIC_PRE_TOOL(**kwargs)
    if original and original.get('action') == 'block': return original
    args = kwargs.get('tool_input') if 'tool_input' in kwargs else kwargs.get('args')
    if isinstance(args, dict):
        args = dict(args)
        if original and original.get('action') == 'modify': args.update(original.get('args', {}))
    directive = _kit_enhanced.guard(kwargs.get('tool_name'), args, session_id=kwargs.get('session_id'))
    if not directive: return original
    if directive.get('action') == 'block': return directive
    merged = dict(original or {})
    merged.update(directive)
    merged['args'] = {**(original or {}).get('args', {}), **directive.get('args', {})}
    return merged
'''


def validate_categories(category_routes):
    if not isinstance(category_routes,dict) or not category_routes or set(category_routes)-set(CATEGORIES):
        raise ValueError('explicit known task categories required')
    result={}; identity={}
    for category, chain in category_routes.items():
        if not isinstance(chain,list) or not 1<=len(chain)<=5: raise ValueError('one to five candidates required')
        result[category]=[];seen=set()
        for entry in chain:
            if not isinstance(entry,dict) or set(entry)!={'model','provider','reasoning_effort','kind'}: raise ValueError('explicit model/provider/effort/kind required')
            if any(not isinstance(entry[k],str) or not TOKEN.fullmatch(entry[k]) for k in ('model','provider')): raise ValueError('invalid route identifier')
            if entry['provider'] in ('auto','default') or entry['model'] in ('auto','default'): raise ValueError('explicit routing required')
            if entry['reasoning_effort'] not in EFFORTS or entry['kind'] not in ('model','combo'): raise ValueError('unsupported route metadata')
            key=(entry['provider'],entry['model'],entry['reasoning_effort'])
            if key in seen: raise ValueError('duplicate chain entry')
            if key in identity and identity[key]!=entry['kind']: raise ValueError('conflicting model identity')
            seen.add(key);identity[key]=entry['kind'];result[category].append(dict(entry))
    return result


def _sha(blob): return hashlib.sha256(blob).hexdigest()


def _safe(data, relative):
    target=data/relative
    for p in [target,*target.parents]:
        if p==data.parent: break
        if p.is_symlink(): raise ValueError('installation links refused')
    return target


def _write(path, blob):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.omh-enhance-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(blob)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def enable_enhanced_omh(data_dir, *, category_routes, require_route=True):
    """Enable opt-in public enhancements; preserve basic OMH and profile defaults."""
    try:
        routes=validate_categories(category_routes)
        if not isinstance(require_route,bool):raise ValueError('require_route must be boolean')
        data=Path(data_dir).resolve()
        with _locked(data),config_locked(data):
            receipt_path=_safe(data,RECEIPT)
            if receipt_path.exists():
                receipt=json.loads(receipt_path.read_text())
                if any(not _safe(data,k).is_file() or _sha(_safe(data,k).read_bytes())!=v for k,v in receipt['after'].items()):
                    return {'status':'conflict','message':'강화 모드 파일이 변경되어 보존했습니다. 덮어쓰지 않았습니다.'}
                settings=json.loads(_safe(data,SETTINGS).read_text())
                if settings['categories']==routes and settings['require_route']==require_route:
                    return {'status':'enabled','restart_required':True,'message':'이미 같은 강화 모드 설정입니다.'}
                return {'status':'conflict','message':'기존 강화 모드를 해제한 뒤 새 경로를 설정해 주세요.'}
            paths={k:_safe(data,k) for k in (*PINNED_FILES,RUNTIME,SETTINGS,*ROUTE_FILES)}
            before={k:p.read_bytes() if p.exists() else None for k,p in paths.items()}
            for name,digest in PINNED_FILES.items():
                if before[name] is None or _sha(before[name])!=digest: raise ValueError('pinned unmodified OMH 2.0.5 required')
            if before[RUNTIME] is not None or before[SETTINGS] is not None: raise ValueError('unmanaged enhancement exists')
            launcher=data/'.local/bin/omh'
            cli=launcher.resolve(strict=True)
            if not cli.is_relative_to(data):raise ValueError('external OMH interpreter refused')
            python=cli.parent/'python'
            if not python.is_file():raise ValueError('OMH interpreter unavailable')
            settings={'version':VERSION,'enabled':True,'require_route':require_route,'python':str(python),'categories':routes}
            updates={RUNTIME:RUNTIME_SOURCE.encode(),SETTINGS:(json.dumps(settings,indent=2)+'\n').encode()}
            provider_doc=json.loads(before[ROUTE_FILES[0]]) if before[ROUTE_FILES[0]] else {'schema_version':'model_provider_routes/v1','models':{}}
            chain_doc=json.loads(before[ROUTE_FILES[1]]) if before[ROUTE_FILES[1]] else {'schema_version':'mixture_chain_overrides/v1','categories':{}}
            for category,chain in routes.items():
                prepared=[]
                for index,entry in enumerate(chain):
                    alias=f'kit-enhanced-{category}-{index}'
                    if alias in provider_doc['models']:raise ValueError('owned alias already exists')
                    provider_doc['models'][alias]={'model':entry['model'],'provider':entry['provider']}
                    prepared.append({'model':alias,'reasoning_effort':entry['reasoning_effort']})
                chain_doc['categories'][category]=prepared
            for name,document in zip(ROUTE_FILES,(provider_doc,chain_doc)):
                updates[name]=(json.dumps(document,indent=2)+'\n').encode()
            for name,append in zip(PINNED_FILES,(TOOL_APPEND,HOOK_APPEND)):
                updates[name]=before[name]+append.encode()
            for name,blob in updates.items():
                if name.endswith('.py'):compile(blob,str(paths[name]),'exec')
            written=[]
            try:
                for name,blob in updates.items():_write(paths[name],blob);written.append(name)
                receipt={'version':VERSION,'before':{k:base64.b64encode(v).decode() if v is not None else None for k,v in before.items()},'after':{k:_sha(v) for k,v in updates.items()}}
                _write(receipt_path,(json.dumps(receipt,indent=2)+'\n').encode())
            except Exception:
                for name in reversed(written):
                    if before[name] is None:paths[name].unlink(missing_ok=True)
                    else:_write(paths[name],before[name])
                raise
            return {'status':'enabled','restart_required':True,'message':'작업별 모델 경로·보정 강화 모드를 설치했습니다. 재시작 후 적용됩니다.'}
    except Exception as exc:
        return {'status':'failed','message':'강화 모드 설치 실패; 기존 설정을 보존했습니다. ('+type(exc).__name__+')'}


def disable_enhanced_omh(data_dir):
    """Restore exact basic files only if no installed enhancement file was edited."""
    try:
        data=Path(data_dir).resolve()
        with _locked(data),config_locked(data):
            receipt_path=_safe(data,RECEIPT)
            if not receipt_path.exists():return {'status':'disabled','restart_required':False}
            receipt=json.loads(receipt_path.read_text())
            expected=set(PINNED_FILES)|{RUNTIME,SETTINGS}|set(ROUTE_FILES)
            if set(receipt['before'])!=expected or set(receipt['after'])!=expected:raise ValueError('invalid receipt')
            if any(not _safe(data,k).is_file() or _sha(_safe(data,k).read_bytes())!=v for k,v in receipt['after'].items()):
                return {'status':'conflict','message':'설치 이후 바뀐 파일을 보존했습니다. 자동 복원을 중단했습니다.'}
            current={k:_safe(data,k).read_bytes() for k in expected};written=[]
            try:
                for name,encoded in receipt['before'].items():
                    path=_safe(data,name)
                    if encoded is None:path.unlink()
                    else:_write(path,base64.b64decode(encoded,validate=True))
                    written.append(name)
                receipt_path.unlink()
            except Exception:
                for name in written:_write(_safe(data,name),current[name])
                raise
            return {'status':'disabled','restart_required':True,'message':'기본 OMH를 복원했습니다. 재시작 후 적용됩니다.'}
    except Exception as exc:return {'status':'failed','message':'강화 모드 복원 실패 ('+type(exc).__name__+')'}
