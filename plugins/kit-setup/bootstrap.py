"""Retry optional components on every boot without reseeding student configuration."""
import json
import os
from pathlib import Path
import subprocess
from components import retry_components, _read_state

# The python the student must use to re-print the invite link: the system one may lack pyyaml.
HERMES_PY = "/opt/hermes/.venv/bin/python"

PUBLIC_SKILL='Wendy-Nam/hermes-skills-kr/youtube-summary'

def component_status(data_dir):
    root=Path(data_dir);rows=[]
    public=root/'skills/media/youtube-summary/SKILL.md'
    rows.append({'id':'youtube-summary','required':True,'status':'installed' if public.is_file() else 'failed',
                 'message':'영상 요약 스킬 설치 확인' if public.is_file() else '영상 요약 스킬이 없습니다. 설치 재시도를 눌러 주세요.'})
    try:
        state=_read_state(root)
        for kit in state.get('selected_kits',[]):
            path=root/'skills/kit'/kit/'SKILL.md'
            last=state.get('last_results',{}).get(kit,{})
            healthy=path.is_file() and last.get('status')!='failed'
            rows.append({'id':kit,'required':True,'status':'installed' if healthy else 'failed',
                         'message':f'{kit}: 설치됨' if healthy else f'{kit}: 설치 또는 업데이트를 재시도해 주세요'})
        last=state.get('last_results',{}).get('k-skill')
        if last:
            # Optional add-on: reported, never blocks setup completion.
            rows.append({'id':'k-skill','required':False,'status':last.get('status'),'message':last.get('message','')})
    except Exception:
        rows.append({'id':'components','required':True,'status':'failed','message':'설치 상태를 읽을 수 없습니다. 진단이 필요합니다.'})
    return rows

def retry_installation(data_dir, *, seed_dir=Path('/opt/kit/seed')):
    root=Path(data_dir);root.mkdir(parents=True,exist_ok=True)
    rows=retry_components(root,seed_dir=seed_dir)
    target=root/'skills/media/youtube-summary/SKILL.md'
    if not target.is_file():
        try:
            result=subprocess.run(['/opt/hermes/.venv/bin/hermes','skills','install',PUBLIC_SKILL,
                '--category','media','--yes','--force'],
                env={**os.environ,'HOME':str(root),'HERMES_HOME':str(root)},capture_output=True,timeout=90)
            # Never expose CLI output (may contain network/auth diagnostics).
        except Exception:pass
    rows.append({'id':'youtube-summary','status':'installed' if target.is_file() else 'failed',
                 'message':'영상 요약 스킬 설치 확인' if target.is_file() else '영상 요약 설치 실패. 네트워크 확인 후 설치 재시도를 눌러 주세요.'})
    return rows

def ensure_setup_enabled(data_dir):
    import config_store
    # Called during startup before the gateway starts; preserve other plugins.
    enabled=config_store.read(data_dir).get('plugins',{}).get('enabled',[])
    if not isinstance(enabled,list):raise ValueError('plugins.enabled must be a list')
    if 'kit-setup' not in enabled:
        config_store.write(data_dir,{'plugins.enabled':[*enabled,'kit-setup']},remember=False)

RTK_PLUGIN='rtk-rewrite'

def rtk_follows_route(data_dir):
    """OmniRoute compresses terminal results itself; with the main model routed through it, Hermes
    RTK would compress the same output twice. Direct providers keep Hermes RTK, the only compression
    they get. Runs after `rtk init` (which re-enables the plugin every boot) and on every apply."""
    from config_store import read, write
    root=Path(data_dir);config=read(root)
    model=config.get('model') or {}
    via_omniroute=isinstance(model,dict) and (model.get('provider') in ('omniroute','kit-omniroute') or ':20128' in str(model.get('base_url') or ''))
    enabled=list((config.get('plugins') or {}).get('enabled') or [])
    want=[p for p in enabled if p!=RTK_PLUGIN] if via_omniroute else \
        enabled+([RTK_PLUGIN] if (root/'plugins'/RTK_PLUGIN).is_dir() and RTK_PLUGIN not in enabled else [])
    if want!=enabled:write(root,{'plugins.enabled':want},remember=False)
    return RTK_PLUGIN in want

def boot(data_dir):
    root=Path(data_dir)
    ensure_setup_enabled(root)
    for row in retry_installation(root):print('[kit] '+row['message'])
    from omh_enhancements import upgrade_enhanced_omh
    upgraded=upgrade_enhanced_omh(root)
    if upgraded:print('[kit] OMH 보정 갱신: '+upgraded['status'])
    try:
        from roles import sync_roles
        sync_roles(root)
    except Exception as exc:print('[kit] 역할 프로필 동기화 실패: '+type(exc).__name__)
    # Invitation exists before Discord /setup becomes reachable. Token is never printed.
    # The link also goes to the data volume: a log the student can no longer scroll back to is
    # the one dead end in the install, and the bot cannot be asked for a link it never received.
    from owner import bot_token, configure_app, remember_invite
    token=bot_token(root)
    if token:
        url,error=configure_app(token)
        if url:
            print('[kit] 봇 초대: '+url)
            # The in-Discord route comes first: a student without SSH should never need the container.
            print('[kit] 초대 링크를 다시 보려면 Discord에서 /invite 를 실행하세요. SSH가 되면: '
                  +str(HERMES_PY)+' '+str(root/'plugins/kit-setup/owner.py'))
            if not remember_invite(root,url):print('[kit] 초대 링크 저장 실패 — 로그의 링크를 사용하세요')
        elif error:print('[kit] '+error)
    else:print('[kit] 봇 토큰이 없어 초대 링크를 만들지 않았습니다 — DISCORD_BOT_TOKEN 환경변수를 확인하세요')
    # Cron registration happens in /setup Apply after a home channel is chosen.
    # Registering earlier would produce an undeliverable maintenance failure notice.
    version=Path('/opt/kit/RELEASE_VERSION')
    if version.exists():(root/'.kit-release-version').write_text(version.read_text())

if __name__=='__main__':
    import sys
    home=Path(os.environ.get('HERMES_HOME','/opt/data'))
    if sys.argv[1:]==['rtk']:print('[kit] Hermes RTK: '+('켜짐' if rtk_follows_route(home) else 'OmniRoute가 압축하므로 꺼짐'))
    else:boot(home)
