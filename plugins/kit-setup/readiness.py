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
