"""Opt-in upstream OMH bootstrap. Never copies the author's personal plugin patches.

Pinned source was installed and setup-smoked in an isolated home. Live Hermes tool
execution remains a separate acceptance check after restart. No main model change.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

from components import _locked, _read_state, _save_state

OMH_COMMIT = 'b84f096e59d50fc933ed4b43fd36675e8cff593a'
OMH_VERSION = '2.0.5'
OMH_SHA256 = '3a27c03301cc7f4dcb96a1476bd5a38bef57117148ba7f7e7aba4f15fffe608a'
OMH_URL = 'https://codeload.github.com/rlaope/oh-my-hermes/tar.gz/' + OMH_COMMIT
CATEGORIES = ('quick', 'deep', 'architect', 'artistry', 'ultrabrain', 'writing',
              'visual-engineering', 'capable', 'simple-work', 'deep-work',
              'unspecified-low', 'unspecified-high')
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$')


def validate_routing(routing):
    if not isinstance(routing, dict) or set(routing) - {'model', 'provider', 'reasoning_effort'}:
        raise ValueError('explicit student routing is required')
    for key in ('model', 'provider'):
        if not isinstance(routing.get(key), str) or not TOKEN.fullmatch(routing[key]):
            raise ValueError('invalid explicit routing')
    if routing['provider'] in ('auto', 'default'):
        raise ValueError('provider must be explicit')
    effort = routing.get('reasoning_effort', 'medium')
    if effort not in ('low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('unsupported effort')
    return dict(routing, reasoning_effort=effort)


def _source(blob, destination):
    if len(blob) > 64 * 1024 * 1024 or hashlib.sha256(blob).hexdigest() != OMH_SHA256:
        raise ValueError('upstream archive checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tf:
        members = tf.getmembers()
        if len(members) > 6000 or sum(m.size for m in members) > 128 * 1024 * 1024:
            raise ValueError('upstream archive limit')
        for m in members:
            if m.issym() or m.islnk() or m.name.startswith('/') or '..' in Path(m.name).parts:
                raise ValueError('unsafe upstream archive')
        tf.extractall(destination, members=members, filter='data')
    return destination / ('oh-my-hermes-' + OMH_COMMIT)


def _run(argv, env):
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=240)
    if result.returncode:
        # Provider config or subprocess output never flows into the user-facing error.
        raise RuntimeError('upstream command failed')
    return result.stdout


def install_upstream_omh(data_dir, *, routing, host_version):
    """Install upstream core + explicit same-model student chain, without personal defaults.

    Refuses existing OMH rather than overwriting it. Host version is supplied from
    the pinned kit image, not inferred from a user's credentials or model response.
    """
    try:
        route = validate_routing(routing)
        if not re.fullmatch(r'0\.21\.[0-9]+', host_version) or int(host_version.split('.')[-1]) < 1:
            raise ValueError('supported Hermes version is >=0.21.1,<0.22.0')
    except Exception as exc:
        return {'id':'omh','status':'failed','message':f'설치 조건 확인 실패 ({type(exc).__name__})'}
    data = Path(data_dir).resolve()
    from config_store import locked as config_locked
    # Keep the same order as OmniRoute: component lock, then shared config lock.
    # Upstream setup and its rollback both rewrite config.yaml; neither may race
    # a student changing a model or service in another setup interaction.
    with _locked(data), config_locked(data):
        state = _read_state(data)
        if (data / 'plugins/omh').exists() or (data / '.omh').exists():
            return {'id':'omh','status':'preserved','message':'기존 OMH를 보존했습니다. 새로 설치하거나 덮어쓰지 않았습니다.'}
        config = data / 'config.yaml'
        if not config.is_file() or config.is_symlink():
            return {'id':'omh','status':'failed','message':'먼저 기본 모델 설정을 완료해 주세요.'}
        if any(p.is_symlink() for p in (data / 'plugins', data / '.kit-tools')):
            return {'id':'omh','status':'failed','message':'설치 경로 링크를 허용하지 않습니다.'}
        launcher = data / '.local/bin/omh'
        if launcher.exists() or launcher.is_symlink():
            return {'id':'omh','status':'preserved','message':'기존 OMH 명령을 보존했습니다. 별도 업그레이드가 필요합니다.'}
        if any(p.is_symlink() for p in (data / '.local', data / '.local/bin')):
            return {'id':'omh','status':'failed','message':'명령 설치 경로 링크를 허용하지 않습니다.'}
        before = config.read_bytes()
        tools_dir = data / '.kit-tools'; tools_dir.mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='omh-2.0.5-', dir=tools_dir))
        env = dict(os.environ, HOME=str(data), HERMES_HOME=str(data), OMH_HOME=str(data / '.omh'))
        try:
            with urllib.request.urlopen(OMH_URL, timeout=60) as response:
                blob = response.read(64 * 1024 * 1024 + 1)
            source = _source(blob, work)
            venv = work / 'venv'
            _run([sys.executable, '-m', 'venv', str(venv)], env)
            _run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--disable-pip-version-check',
                  '--no-deps', str(source)], env)
            cli = str(venv / 'bin/omh')
            payload = json.loads(_run([cli, '--hermes-home', str(data), '--omh-home', str(data / '.omh'),
                'setup', '--core', '--yes', '--no-interactive', '--no-omh-tui', '--no-menubar',
                '--memory-mode', 'off', '--default-executor', 'hermes', '--json'], env))
            if not payload.get('ok') or not payload.get('plugin_distribution', {}).get('import_smoke'):
                raise RuntimeError('upstream setup verification failed')
            routing_dir = data / '.omh/routing'; routing_dir.mkdir(exist_ok=True)
            alias = 'student-selected'
            (routing_dir / 'model-providers.json').write_text(json.dumps({'schema_version':'model_provider_routes/v1',
                'models':{alias:{'model':route['model'], 'provider':route['provider']}}},indent=2)+'\n')
            (routing_dir / 'model-chains.json').write_text(json.dumps({'schema_version':'mixture_chain_overrides/v1',
                'categories':{c:[{'model':alias,'reasoning_effort':route['reasoning_effort']}] for c in CATEGORIES}},indent=2)+'\n')
            launcher.parent.mkdir(parents=True, exist_ok=True)
            launcher.symlink_to(cli)
            receipt = {'version':OMH_VERSION,'source_commit':OMH_COMMIT,'archive_sha256':OMH_SHA256,
                       'cli':cli,'routing':route,'mode':'upstream-core','live_dispatch_verified':False}
            state['components']['omh-upstream'] = receipt
            result = {'id':'omh','status':'installed','message':'OMH 기본 팩 설치 완료. 재시작 후 실제 도구 실행 검증이 필요합니다.'}
            state.setdefault('last_results', {})['omh-upstream'] = result
            _save_state(data,state)
            return result
        except Exception as exc:
            # Restore activation config; keep failed artifacts in a recovery directory.
            if launcher.is_symlink() and str(launcher.readlink()).startswith(str(work)):
                launcher.unlink()
            restored = work / 'config.restore'; restored.write_bytes(before); os.replace(restored, config)
            for name, label in (('.omh','omh-state'), ('plugins/omh','omh-plugin')):
                path = data / name
                if path.exists(): shutil.move(str(path), str(work / ('failed-' + label)))
            return {'id':'omh','status':'failed','message':f'OMH 설치 실패 ({type(exc).__name__}). 기존 설정을 복원했습니다.'}
