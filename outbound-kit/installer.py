#!/usr/bin/env python3
"""Guided installation, prescribed first run, and contextual recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

import kit
import paths
from support import SupportError, explain_error

STEPS = ('preflight', 'engine', 'pack', 'sample', 'model', 'model-test', 'omh',
         'channels', 'services', 'routing', 'workflow', 'vault', 'gateway',
         'doctor', 'operations', 'desktop')
SETUP_STEPS = ('preflight', 'engine', 'pack', 'model', 'model-test', 'omh',
               'channels', 'services', 'routing', 'workflow', 'doctor',
               'gateway', 'operations', 'desktop')
INTERACTIVE = {'model', 'channels', 'services', 'routing'}
LABELS = dict(preflight='환경 확인', engine='Hermes 준비', pack='업무 스킬 설치',
              sample='샘플 실행', model='모델 계정 연결', **{'model-test':'모델 응답 확인'},
              omh='OMH 설치', channels='메신저 연결', services='추가 서비스 적용',
              routing='선택 모델 라우터', workflow='첫 시나리오 실행',
              vault='결과물 볼트 확인', gateway='메신저 실행', doctor='설치 진단',
              operations='예약 실행', desktop='데스크톱 앱 열기')
RECEIPT_STATES = {'passed', 'configured', 'needs_user', 'deferred', 'blocked', 'failed',
                  'skipped', 'executed_unverified'}
ROOT = Path(__file__).resolve().parent


def tool_fingerprint():
    digest = hashlib.sha256()
    for name in ('installer.py', 'kit.py', 'paths.py', 'workflow.py', 'support.py',
                 'engine_bootstrap.py', 'omh_setup.py', 'omniroute_setup.py',
                 'services.py', 'runtime_connect.py', 'operations.py', 'vault_sync.py',
                 'docs_support.py'):
        path = ROOT / name
        digest.update(name.encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def config_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def user_path(value, default):
    path = Path(value).expanduser() if value else Path(default)
    if not path.is_absolute():
        path = Path.home() / path
    path = path.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SupportError('PATH_LINK', 'preflight', '이 경로는 다른 위치를 가리키는 링크예요.',
                           ['본인 폴더 안의 실제 디렉터리를 선택하세요.'])
    return path


def plan(data, home, output, vault=None):
    remote = data.get('install_location', 'local') == 'remote'
    selected = [step for step in SETUP_STEPS if not skip_reason(data, step)]
    return {
        'schema_version': 2, 'target': data['target'], 'location': 'remote' if remote else 'local',
        'home': str(home), 'output': str(output), 'vault': str(vault or Path(home)/'vault'),
        'scenario': data.get('scenario', 'job_signal'),
        'source_mode': data.get('source_mode', 'sample'),
        'draft_mode': data.get('draft_mode', 'template'),
        'server': {k:data.get(k) for k in ('server_host','server_port','server_user','ssh_key_path')} if remote else None,
        'steps': ([{'id': k, 'status':'pending', 'tool':'server_access.py'}
                   for k in ['plan'] + (['keygen'] if data.get('ssh_key_action') == 'generate' else []) +
                   ['trust','probe','deploy','setup']] if remote else []) +
                 [{'id': step, 'label':LABELS[step], 'status':'pending',
                   'private_terminal':step in INTERACTIVE,
                   'execution_location':'server' if remote else 'this device'} for step in selected],
        'selected': {k:data.get(k,[]) for k in ('workflows','services')},
        'optional_components': {
            'omh':{'requested':data.get('omh_enabled',False),'helper':'omh_setup.py'},
            'omniroute':{'requested':data.get('omniroute_enabled',False),'helper':'omniroute_setup.py',
                        'next':'설치 후 제공자 로그인과 모델 확인을 진행하세요.'}},
        'first_result':'선택한 자료의 회사별 근거, 제품 조건을 반영한 초안과 검토 노트',
        'model_or_channel_test': '실제 응답을 확인하는 단계는 계정 연결 후 실행합니다.',
        'automatic_send':False,
    }


def skip_reason(data, step, offline=False, no_launch=False):
    if offline and step not in {'preflight','pack','sample','workflow','vault'}:
        return '샘플 모드에서는 이 연결을 나중에 진행합니다.'
    if step in {'model','model-test'} and data.get('model_auth') == 'later':
        return '모델 연결은 나중에 진행하기로 선택했습니다.'
    if step == 'omh' and not data.get('omh_enabled',False):
        return 'OMH를 선택하지 않았습니다.'
    if step == 'channels' and not kit.channels(data):
        return '로컬 대화로 진행합니다.'
    if step == 'services' and not data.get('services'):
        return '추가 서비스를 선택하지 않았습니다.'
    if step == 'routing' and not data.get('omniroute_enabled'):
        return '직접 모델 연결을 사용합니다.'
    if step == 'operations' and not data.get('schedule_enabled'):
        return '예약 실행은 선택하지 않았습니다.'
    if step == 'gateway' and (not kit.channels(data) or not data.get('gateway_enabled',True)):
        return '메신저 자동 실행은 선택하지 않았습니다.'
    if step == 'desktop' and (data.get('target') != 'desktop' or data.get('desktop_mode','terminal') != 'app' or no_launch):
        return '앱을 자동으로 열지 않습니다.'
    return None


def preflight(data, home):
    if sys.version_info < (3,11):
        raise SupportError('PYTHON_VERSION','preflight','전체 키트에는 Python 3.11 이상이 필요해요.',
                           ['설치 스킬의 Python 준비 단계를 먼저 진행하세요.'],'install')
    runtime = paths.resolve_hermes(home, required=False)
    print(json.dumps({'status':'runtime_found' if runtime else 'engine_required',
                      'python_3_11_plus':True,'platform':platform.system(),'home':str(home),
                      'runtime':str(runtime) if runtime else None,
                      'next_action':'업무 스킬을 설치합니다.' if runtime else '다음 단계에서 Hermes를 설치합니다.'},
                     ensure_ascii=False))
    return 0


def write_receipt(folder, config, step, status, code, execution_context=None,
                  evidence=None, next_actions=None):
    folder = user_path(folder, folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (step+'.json')
    if target.is_symlink():
        raise SupportError('STATE_LINK', step, '상태 파일 경로를 사용할 수 없어요.', ['다른 상태 폴더를 선택하세요.'])
    body = {'schema_version':2,'config_sha256':config_digest(config),'tool_sha256':tool_fingerprint(),
            'step':step,'status':status,'exit_code':code,'live_verified':False,
            'execution_context':execution_context or {},'evidence':evidence or {},
            'next_actions':next_actions or []}
    fd, staged = tempfile.mkstemp(prefix='.state-',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(body,stream,ensure_ascii=False,indent=2); stream.write('\n')
        os.replace(staged,target)
    finally:
        if os.path.exists(staged): os.unlink(staged)


def status_rows(folder, data, context):
    folder = user_path(folder, folder)
    rows = []
    for step in STEPS:
        path = folder / (step+'.json')
        state = {'step':step,'label':LABELS[step],'status':'not_run'}
        if path.is_symlink():
            state['status'] = 'invalid_receipt'
        elif path.exists():
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                valid = (isinstance(saved,dict) and saved.get('schema_version')==2 and saved.get('step')==step
                         and bool(re.fullmatch(r'[a-f0-9]{64}',saved.get('config_sha256','')))
                         and isinstance(saved.get('execution_context'),dict)
                         and saved.get('status') in RECEIPT_STATES and type(saved.get('exit_code')) is int
                         and saved.get('live_verified') is False and isinstance(saved.get('evidence',{}),dict))
                if not valid:
                    state['status']='invalid_receipt'
                else:
                    state.update({k:saved[k] for k in ('status','exit_code','execution_context','evidence','next_actions','config_sha256')})
                    if saved['config_sha256'] != config_digest(data): state['status']='stale_config'
                    elif saved.get('tool_sha256') != tool_fingerprint(): state['status']='stale_tools'
                    elif saved['execution_context'] != context: state['status']='stale_context'
            except (ValueError,TypeError,KeyError):
                state['status']='invalid_receipt'
        rows.append(state)
    return rows


def child(script, arguments, capture=False, timeout=600):
    helper = ROOT / script
    if not helper.is_file():
        raise SupportError('MISSING_HELPER',script,'이 단계의 실행 파일이 키트에 없어요.',
                           ['전체 키트를 다시 받아 같은 설정으로 재개하세요.'])
    proc = subprocess.run([sys.executable,str(helper),*map(str,arguments)],
                          check=False, capture_output=capture, text=True,
                          timeout=timeout)
    if proc.returncode:
        raise SupportError('COMPONENT_FAILED',script.replace('.py',''),
                           '이 연결을 완료하지 못했어요.',
                           ['설정과 인터넷 연결을 확인하세요.','같은 단계를 재개하면 완료한 파일은 보존합니다.'])
    if capture:
        try:
            result = json.loads(proc.stdout)
            if not isinstance(result, dict):
                raise ValueError('object required')
            if result.get('status') in {'failed','blocked','error','not_installed'}:
                raise SupportError('COMPONENT_FAILED', script.replace('.py',''),
                                   '이 단계에 필요한 설정을 확인해야 해요.',
                                   ['설치 스킬에게 해당 단계부터 점검해 달라고 요청하세요.'])
            return result
        except SupportError:
            raise
        except (ValueError,TypeError):
            raise SupportError('INVALID_RESULT',script,'실행 결과 형식을 확인하지 못했어요.',
                               ['진단을 실행하고 설치 스킬에 이 단계를 알려주세요.']) from None
    return {}


def _private(step):
    if not sys.stdin.isatty():
        raise SupportError('INPUT_PRIVATE_TERMINAL',step,
                           '로그인과 비밀값 입력은 본인의 터미널에서 이어가 주세요.',
                           [f'installer.py run --step {step} 명령을 같은 설정과 경로로 직접 실행하세요.',
                            '키나 비밀번호를 AI 채팅에 붙여넣지 않아도 됩니다.'])


def run_step(data, config_path, step, home, output, vault=None):
    if data.get('install_location') == 'remote':
        raise SupportError('REMOTE_CONTEXT',step,'서버 설정은 서버 안에서 적용해야 해요.',
                           ['installer.py setup으로 서버 배포와 접속 안내부터 진행하세요.'],'install')
    home = paths.normalize_home(home)
    config_path = Path(config_path).absolute()
    vault = user_path(vault or data.get('vault_path'),home/'vault')
    if step == 'preflight':
        return preflight(data,home)
    if step == 'engine':
        import engine_bootstrap as bootstrap
        runtime = paths.resolve_hermes(home,required=False)
        mode = data.get('desktop_mode','terminal') if data['target']=='desktop' else 'terminal'
        if runtime:
            if mode=='app' and not paths.resolve_desktop_app(home,required=False):
                raise SupportError('DESKTOP_MISSING','engine','Hermes는 있지만 데스크톱 앱 파일이 없어요.',
                                   ['기존 엔진을 보존한 채 공식 desktop 빌드 단계를 진행하세요.'],'desktop')
            return 0
        target = bootstrap.target_platform()
        installed = paths.install_dir(home)
        artifact = bootstrap.download(target,str(home/'installers'))
        bootstrap.install_engine(target,artifact['path'],home,installed,mode)
        return 0
    if step == 'pack':
        kit.install(data,home); return 0
    if step == 'sample':
        kit.sample(data,output); return 0
    if step == 'model':
        if data.get('model_auth')=='later':
            raise SupportError('INPUT_MODEL_LATER',step,'모델 연결을 나중에 진행하기로 선택했어요.',
                               ['첫 샘플은 템플릿 모드로 실행할 수 있습니다.'],'model')
        if data.get('model_auth') == 'existing':
            print('기존 모델 설정을 보존하고 다음 단계에서 실제 응답을 확인합니다.')
            return 0
        _private(step)
        return kit.hermes(home,['model'])
    if step == 'model-test':
        executable = paths.resolve_hermes(home)
        env = dict(os.environ,HERMES_HOME=str(home))
        proc = subprocess.run([str(executable),'chat','--query','연결 확인을 위해 OK라는 한 단어로 답해주세요.',
                               '--oneshot','--quiet','--format','text'],env=env,
                              capture_output=True,text=True,timeout=120)
        if proc.returncode or not proc.stdout.strip():
            raise SupportError('MODEL_RESPONSE_FAILED',step,'모델에서 답변을 받지 못했어요.',
                               ['모델 로그인과 사용 한도를 확인하고 다시 테스트하세요.'],'model',
                               exit_code=proc.returncode if proc.returncode > 0 else 1)
        print('모델에서 실제 답변을 받았습니다.')
        return 0
    if step=='channels':
        if kit.channels(data): _private(step)
        kit.connect(data,home); return 0
    if step=='services':
        if not data.get('services'): return 0
        import services
        rows=services.service_status(data,home)
        if any(not row['credential_present'] for row in rows): _private(step)
        services.connect_services(data,home)
        from runtime_connect import apply_services
        applied=apply_services(data,home)
        print(json.dumps(applied,ensure_ascii=False))
        return 0
    if step=='omh':
        if not data.get('omh_enabled'): return 0
        child('omh_setup.py',['install','--config',config_path,'--home',home],capture=True)
        return 0
    if step=='routing':
        if not data.get('omniroute_enabled'): return 0
        _private(step)
        child('omniroute_setup.py',['install','--config',config_path,'--home',home],timeout=900)
        if data.get('routing_bindings_path'):
            child('omniroute_setup.py',['apply','--config',config_path,'--home',home,
                                      '--bindings',data['routing_bindings_path']],capture=True)
        else:
            print('OmniRoute 설치 후 대시보드에서 모델 계정을 연결하세요. 설치 스킬이 모델 확인과 연결을 이어서 안내합니다.')
        return 0
    if step=='workflow':
        if data.get('vault_mode')=='existing' and not data.get('vault_existing_approved'):
            raise SupportError('INPUT_VAULT_APPROVAL',step,'기존 볼트에 파일을 추가하기 전에 확인이 필요해요.',
                               ['추가할 폴더를 확인하거나 새 결과물 폴더를 선택하세요.'])
        args=['run','--config',config_path,'--home',home,'--output',output,'--vault',vault,
              '--source-mode',data.get('source_mode','sample'),
              '--draft-mode',data.get('draft_mode','template')]
        if data.get('scenario'): args.extend(['--scenario',data['scenario']])
        if data.get('drafts_path'): args.extend(['--drafts-file',data['drafts_path']])
        result=child('workflow.py',args,capture=True)
        if not isinstance(result.get('runs'),list) or not result['runs']:
            raise SupportError('NO_WORKFLOW_RESULT',step,'시나리오 실행 결과가 비어 있어요.',
                               ['시나리오와 입력 자료를 확인하세요.'])
        print('선택한 시나리오의 결과를 만들었습니다. 결과 폴더: '+str(vault))
        return 0
    if step=='vault':
        if data.get('vault_mode','none')=='none': return 0
        child('vault_flow.py',['status','--vault',vault],capture=True)
        return 0
    if step=='gateway':
        if not kit.channels(data): return 0
        _private(step)
        print('메신저 실행을 연결합니다. 각 봇에서 본인 메시지에 답하는지도 확인해주세요.')
        return kit.hermes(home,['gateway','install','--if-missing'])
    if step=='doctor':
        return kit.hermes(home,['doctor'])
    if step=='operations':
        if not data.get('schedule_enabled'): return 0
        common=['--config',config_path,'--home',home,'--output',output,'--vault',vault]
        child('operations.py',['run-once',*common],capture=True,timeout=900)
        child('operations.py',['install',*common,'--apply'],capture=True)
        return 0
    if step=='desktop':
        command=paths.desktop_command(home)
        subprocess.Popen(command,env=dict(os.environ,HERMES_HOME=str(home)),
                         cwd=str(paths.install_dir(home)),stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        print('Hermes 데스크톱 앱을 열었습니다.')
        return 0
    raise SupportError('UNKNOWN_STEP',step,'지원하는 설치 단계를 선택해주세요.', ['installer.py --help를 확인하세요.'])


def _context(home,output,vault):
    return dict(home=str(home),output=str(output),vault=str(vault))


def main(argv=None):
    parser=argparse.ArgumentParser(description='질문한 설정으로 설치하고 첫 시나리오까지 안내합니다.')
    parser.add_argument('action',choices=('plan','setup','resume','run','status','diagnose','start'))
    parser.add_argument('--config',default=str(ROOT/'setup.json'))
    parser.add_argument('--step',choices=STEPS)
    parser.add_argument('--home'); parser.add_argument('--output'); parser.add_argument('--vault')
    parser.add_argument('--state-dir')
    parser.add_argument('--offline',action='store_true',help='연결 없이 샘플 시나리오부터 실행')
    parser.add_argument('--no-launch',action='store_true',help='설치 후 앱을 자동으로 열지 않음')
    args=parser.parse_args(argv)
    phase=args.step or args.action
    try:
        config=Path(args.config).expanduser().absolute()
        if not config.is_file():
            raise SupportError('INPUT_CONFIG',phase,'아직 설치 질문의 답을 저장하지 않았어요.',
                               ['설치 스킬에게 질문부터 진행해 달라고 요청하세요.',
                                'prepare.py 또는 wizard.html로 설정을 만들 수 있습니다.'])
        data=kit.load(config)
        home=paths.normalize_home(args.home or data.get('install_home') or None)
        output=user_path(args.output or data.get('output_path'),home/'output')
        vault=user_path(args.vault or data.get('vault_path'),home/'vault')
        state=user_path(args.state_dir,home/'installer-state')
        context=_context(home,output,vault)
        if args.action=='plan':
            print(json.dumps(plan(data,home,output,vault),ensure_ascii=False,indent=2)); return 0
        if args.action in {'status','diagnose'}:
            print(json.dumps(status_rows(state,data,context),ensure_ascii=False,indent=2)); return 0
        if args.action in {'setup','resume'} and data.get('install_location')=='remote':
            import server_access
            result=server_access.setup_remote(data,config,execute=sys.stdin.isatty())
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return 2 if result.get('status')=='needs_user_terminal' else 0
        if args.offline:
            data={**data,'source_mode':'sample','draft_mode':'template'}
        selected=([args.step] if args.action=='run' else
                  ['desktop'] if args.action=='start' and data.get('desktop_mode')=='app' else
                  ['gateway'] if args.action=='start' else list(SETUP_STEPS))
        if args.action=='run' and not args.step:
            parser.error('run에는 --step을 지정해주세요.')
        results=[]
        previous = {row['step']:row for row in status_rows(state,data,context)} if args.action=='resume' else {}
        for step in selected:
            phase=step
            saved=previous.get(step,{})
            if saved.get('status') in {'passed','configured'} and saved.get('exit_code') == 0:
                results.append({'step':step,'status':'reused','message':'같은 설정으로 완료한 단계입니다.'})
                print(LABELS[step]+'의 완료 기록을 확인했습니다.')
                continue
            skipped=skip_reason(data,step,args.offline,args.no_launch)
            if skipped:
                write_receipt(state,data,step,'skipped',0,context,next_actions=[skipped])
                results.append({'step':step,'status':'skipped','message':skipped})
                continue
            print(LABELS[step]+'을 진행합니다.')
            try:
                code=run_step(data,config,step,home,output,vault)
                if code:
                    raise SupportError('STEP_EXIT',step,LABELS[step]+'을 마치지 못했어요.',
                                       ['해당 단계의 계정과 설정을 확인하고 재개하세요.'],exit_code=code)
            except (ValueError,OSError,subprocess.SubprocessError,SupportError) as exc:
                error=explain_error(exc,step)
                write_receipt(state,data,step,error.as_dict()['status'],1,context,
                              next_actions=error.next_actions)
                print(json.dumps(error.as_dict(),ensure_ascii=False),file=sys.stderr)
                return 2 if error.code.startswith('INPUT_') else error.exit_code
            status='configured' if step in {'model','omh','channels','services','routing','gateway','desktop'} else 'passed'
            evidence={'phase_executed':True}
            if step=='omh': evidence.update(static_smoke_only=True, host_loaded=False, live_delegation=False)
            if step=='desktop': evidence.update(launch_requested=True, user_visible=False)
            if step=='routing': evidence.update(container_install_requested=True, model_routing_verified=False)
            if step=='services': evidence.update(runtime_apply_requested=True, functional_verified=False)
            write_receipt(state,data,step,status,0,context,evidence=evidence)
            results.append({'step':step,'status':status})
        print(json.dumps({'status':'sample_ready' if args.offline else 'setup_steps_completed',
                          'home':str(home),'output':str(output),'vault':str(vault),
                          'results':results,'automatic_send':False,
                          'next_action':'결과 폴더에서 근거와 초안을 검토하세요.'},
                         ensure_ascii=False,indent=2))
        return 0
    except KeyboardInterrupt:
        print('여기서 멈췄어요. 같은 설정으로 resume을 실행하면 이어갈 수 있습니다.',file=sys.stderr)
        return 130
    except (ValueError,OSError,subprocess.SubprocessError,SupportError) as exc:
        error=explain_error(exc,phase)
        print(json.dumps(error.as_dict(),ensure_ascii=False),file=sys.stderr)
        return 2 if error.code.startswith('INPUT_') else error.exit_code


if __name__=='__main__':
    raise SystemExit(main())
