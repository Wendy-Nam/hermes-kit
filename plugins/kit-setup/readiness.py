"""Setup completion is a measured result, not the presence of a key."""
from pathlib import Path
import json
import time

def check(data_dir, *, run_probe=True):
    from env_store import get_env
    from packs import load_packs, missing_keys
    from model_setup import probe
    from bootstrap import component_status
    root=Path(data_dir)
    problems=[k.label+' 입력이 필요합니다' for k in missing_keys(load_packs(),get_env(root/'.env'))]
    # Only selected/base installed components are required, not unavailable add-ons.
    for row in component_status(root):
        if row.get('required') and row.get('status') not in ('installed','preserved'):
            problems.append(row.get('message') or f"{row['id']} 설치가 끝나지 않았습니다")
    if problems:return False,problems
    if run_probe:
        ok,msg=probe(root)
        if not ok:return False,[msg]
        from config_store import read
        from model_setup import delegation_route
        if delegation_route(read(root))[1]:  # optional: without it the main model delegates
            ok,msg=probe(root,role="aux")
            if not ok:return False,["보조 모델: "+msg]
    return True,['기본 키·선택 구성요소·모델 응답 확인 완료']

def wizard_status(data_dir):
    """Which of the four /setup steps are done, read from state rather than remembered clicks."""
    from env_store import get_env
    from config_store import read
    from components import _read_state
    root=Path(data_dir)
    model=read(root).get('model') or {}
    try:kits=_read_state(root).get('selected_kits') or []
    except Exception:kits=[]
    return {'model':isinstance(model,dict) and bool(model.get('provider') and model.get('default')),
            'gemini':bool(get_env(root/'.env').get('GEMINI_API_KEY')),
            'kits':bool(kits),
            'recommended':(root/'plugins/omh').is_dir() and (root/'profiles/research').is_dir()}
