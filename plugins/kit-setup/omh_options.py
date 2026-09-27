"""Student-owned per-task OMH routes. No instructor defaults.

Each save covers one task type and merges with earlier saves. A chain is the main
model plus up to four fallbacks; OMH advances along it itself when a child fails.
"""
import json
from pathlib import Path
import subprocess

from model_setup import MODEL
from upstream_omh import CATEGORIES

LABELS = {'ultrabrain':'고난도 추론', 'deep':'깊은 분석', 'architect':'설계',
          'deep-work':'복잡한 실행', 'visual-engineering':'화면·디자인 구현', 'artistry':'창작',
          'writing':'글쓰기', 'capable':'일반 작업', 'unspecified-high':'분류되지 않은 복잡한 작업',
          'quick':'짧고 간단한 작업', 'simple-work':'간단한 실행', 'unspecified-low':'분류되지 않은 간단한 작업'}
EFFORTS = ('low','medium','high','xhigh','max')
RESET = ('-', 'reset', '기본')


def available_providers(data_dir):
    """Providers this student already connected: configured, in use, or keyed."""
    from config_store import read
    from env_store import get_env
    from model_setup import KEYS
    c=read(data_dir)
    names=set((c.get('providers') or {}).keys())
    for role in ('model','delegation'):
        item=c.get(role) or {}
        if isinstance(item,dict) and isinstance(item.get('provider'),str):names.add(item['provider'])
    env=get_env(Path(data_dir)/'.env') if (Path(data_dir)/'.env').exists() else {}
    names|={provider for provider,key in KEYS.items() if env.get(key)}
    return sorted(p for p in names if p not in ('auto','default','custom') and MODEL.fullmatch(p))


def parse_chain(provider, text, effort):
    """`model, fallback, other-provider=model` -> chain entries. Fallbacks keep the effort."""
    entries=[]
    for item in (part.strip() for part in text.split(',')):
        if not item:continue
        item_provider,_,item_model=item.rpartition('=')
        entries.append({'provider':item_provider.strip() or provider,'model':item_model.strip(),'reasoning_effort':effort})
    if not 1<=len(entries)<=5:raise ValueError('one to five models')
    return entries


def save_route(data_dir, category, provider, models, effort=''):
    """Probe every model in the chain with the student's own keys, then merge it in."""
    if category not in CATEGORIES:
        return {'status':'failed','message':'작업 종류를 목록에서 선택해 주세요.'}
    if not (Path(data_dir)/'plugins/omh').is_dir():
        return {'status':'failed','message':'먼저 OMH 기본 팩을 설치해 주세요.'}
    if models.strip().lower() in RESET:
        return reset_route(data_dir, category)
    from omh_enhancements import DEFAULT_EFFORTS, validate_chain
    effort=(effort or '').strip().lower() or DEFAULT_EFFORTS[category]
    try:
        if effort not in EFFORTS:raise ValueError('effort')
        chain=validate_chain(parse_chain(provider.strip(),models,effort))
    except ValueError:
        return {'status':'failed','message':'모델 ID(최대 5개, 쉼표 구분)와 추론 강도(low/medium/high/xhigh/max)를 확인해 주세요.'}
    connected=available_providers(data_dir)
    unknown=sorted({e['provider'] for e in chain}-set(connected))
    if unknown:
        return {'status':'failed','message':'연결하지 않은 제공자입니다: '+', '.join(unknown)+'. 사용 가능: '+', '.join(connected)}
    # Isolated, tool-free probes with this student's keys. Nothing is saved on failure.
    from model_setup import probe
    for entry in chain:
        ok,message=probe(data_dir,role='aux',candidate=(entry['provider'],entry['model']))
        if not ok:return {'status':'failed','message':f"{entry['provider']}/{entry['model']}: {message}"}
    from omh_enhancements import enable_enhanced_omh
    result=enable_enhanced_omh(data_dir,category_routes={category:chain})
    if result['status']=='enabled':
        route=' → '.join(f"{e['provider']}/{e['model']}" for e in chain)
        result=dict(result,message=f'{LABELS[category]}: {route} · {effort}. '+result['message'])
    return result


def reset_route(data_dir, category):
    from omh_enhancements import enable_enhanced_omh
    result=enable_enhanced_omh(data_dir,remove=(category,))
    if result['status']=='enabled':
        result=dict(result,message=f'{LABELS[category]}: 보조 모델 기본 경로로 되돌렸습니다. '+result['message'])
    return result


def recommendations(data_dir):
    """OMH 2.0.5's shipped chain per task type: what OMH itself would pick, for reference."""
    try:
        from omh_enhancements import _python
        script=('import json\nfrom omh.plugin_bundle.omh.hermes_delegation import HERMES_MIXTURE_CATEGORY_CHAINS as c\n'
                'print(json.dumps({k:[list(e) for e in v] for k,v in c.items()}))')
        result=subprocess.run([_python(Path(data_dir).resolve()),'-c',script],capture_output=True,text=True,timeout=30)
        return json.loads(result.stdout) if result.returncode==0 else {}
    except Exception:
        return {}


def summary(data_dir):
    from omh_enhancements import DEFAULT_EFFORTS, describe
    info=describe(data_dir)
    if not info.get('installed'):return 'OMH 기본 팩이 아직 설치되지 않았습니다.'
    base=info.get('base')
    lines=['OMH: 설치됨 · 모델 보정 '+('켜짐' if info.get('calibration') else '꺼짐'),
           '기본 경로(보조 모델): '+(f"{base['provider']}/{base['model']}" if base else '키트 밖에서 수정됨')]
    recommended=recommendations(data_dir)
    for category,label in LABELS.items():
        chain=info['categories'].get(category)
        if chain:
            route=' → '.join(f"{e['provider']}/{e['model']}" for e in chain)+' · '+chain[0]['reasoning_effort']
        else:
            route='기본 · '+DEFAULT_EFFORTS[category]
        tip=recommended.get(category) or []
        lines.append(f'- {label}: {route}'+(f" (OMH 추천: {tip[0][0]} {tip[0][1]})" if tip else ''))
    lines.append('보정 문구는 추론 강도 high 이상에서 붙습니다. 추천 모델은 참고용이며 본인 계정에서 쓸 수 있는 모델만 지정하세요.')
    if info.get('error'):lines.append('상태 파일을 읽지 못했습니다: '+info['error'])
    return '\n'.join(lines)
