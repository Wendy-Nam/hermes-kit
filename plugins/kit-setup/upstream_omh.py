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
# OMH writes these values into delegation.*; its own grammar has no ':' or '@'.
TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$')


def validate_routing(routing):
    """The student's aux provider/model. Effort is chosen per task type, not here."""
    if not isinstance(routing, dict) or set(routing) - {'model', 'provider', 'reasoning_effort'}:
        raise ValueError('explicit student routing is required')
    for key in ('model', 'provider'):
        if not isinstance(routing.get(key), str) or not TOKEN.fullmatch(routing[key]):
            raise ValueError('invalid explicit routing')
    if routing['provider'] in ('auto', 'default', 'custom'):
        raise ValueError('provider must be explicit')
    return {'model': routing['model'], 'provider': routing['provider']}


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


# Bot-profile homes are independent HERMES_HOME trees the student owns. Upstream
# setup registers itself into every one of them, so their exact pre-install bytes
# are snapshotted (large files keep a digest) and restored afterwards: OMH lands
# in the primary home only, and no profile config, .env or skill is rewritten.
PROFILE_FILE_LIMIT = 8 * 1024 * 1024
PROFILE_SNAPSHOT_LIMIT = 128 * 1024 * 1024


def _snapshot_profiles(data):
    root = data / 'profiles'
    state = {'existed': root.exists(), 'files': {}, 'digests': {}, 'links': {}, 'dirs': set()}
    if not state['existed']:
        return state
    total = 0
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        kept = []
        for name in sorted(dirnames):
            path = base / name
            relative = str(path.relative_to(data))
            if path.is_symlink():
                state['links'][relative] = os.readlink(path)
            else:
                state['dirs'].add(relative)
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = base / name
            relative = str(path.relative_to(data))
            if path.is_symlink():
                state['links'][relative] = os.readlink(path)
                continue
            size = path.stat().st_size
            if size <= PROFILE_FILE_LIMIT and total + size <= PROFILE_SNAPSHOT_LIMIT:
                state['files'][relative] = path.read_bytes()
                total += size
            else:
                with path.open('rb') as handle:
                    state['digests'][relative] = hashlib.sha256(handle.read()).hexdigest()
    return state


def _remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _restore_profiles(data, state):
    """Delete every profile path upstream created and rewrite the changed bytes."""
    root = data / 'profiles'
    recorded = set(state['files']) | set(state['digests']) | set(state['links']) | state['dirs']
    if root.is_dir() and not root.is_symlink():
        for current, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
            base = Path(current)
            for name in filenames:
                path = base / name
                if str(path.relative_to(data)) not in recorded:
                    path.unlink(missing_ok=True)
            for name in dirnames:
                path = base / name
                if str(path.relative_to(data)) not in recorded:
                    _remove(path)
            relative = str(base.relative_to(data))
            if base != root and relative not in state['dirs']:
                _remove(base)
    if not state['existed']:
        if root.is_dir() and not root.is_symlink() and not any(root.iterdir()):
            root.rmdir()
        return
    root.mkdir(parents=True, exist_ok=True)
    for relative in sorted(state['dirs']):
        (data / relative).mkdir(parents=True, exist_ok=True)
    for relative, blob in state['files'].items():
        path = data / relative
        if path.is_file() and not path.is_symlink() and path.read_bytes() == blob:
            continue
        if path.exists() or path.is_symlink():
            _remove(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    for relative, target in state['links'].items():
        path = data / relative
        if path.is_symlink() and os.readlink(path) == target:
            continue
        if path.exists() or path.is_symlink():
            _remove(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    for relative, digest in state['digests'].items():
        path = data / relative
        # Over the byte cap: never rewritten in practice, but a silent loss here
        # would be unrecoverable, so refuse instead of guessing.
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('profile file changed during install')


def _restored_routes(data):
    """Task chains from a backup restore: `.omh` holding only routing documents.

    Returns the saved per-task chains ({} when none), or None when `.omh` is absent
    or holds anything else, which is a real OMH home and is never replaced.
    """
    home = data / '.omh'
    if not home.is_dir() or home.is_symlink() or {p.name for p in home.iterdir()} != {'routing'}:
        return None
    try:
        from omh_enhancements import validate_categories
        settings = json.loads((home / 'routing/kit-enhanced.json').read_text())
        return validate_categories(settings.get('categories') or {})
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


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
        restored = _restored_routes(data)
        if (data / 'plugins/omh').exists() or ((data / '.omh').exists() and restored is None):
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
        if restored is not None:
            # Only routing documents from a backup: keep them aside, reapply the task chains.
            shutil.move(str(data / '.omh'), str(work / 'restored-omh'))
        try:
            snapshot = _snapshot_profiles(data)
        except Exception as exc:
            return {'id':'omh','status':'failed','message':f'프로필 보존 준비 실패 ({type(exc).__name__})'}
        # Upstream setup syncs its registration into every bot-profile home under
        # profiles/. Those homes belong to the student, so they are snapshotted and
        # restored byte-for-byte; caches are redirected so HOME stays clean too.
        env = dict(os.environ, HOME=str(data), HERMES_HOME=str(data), OMH_HOME=str(data / '.omh'),
                   PIP_CACHE_DIR=str(work / 'pip-cache'), XDG_CACHE_HOME=str(work / 'cache'))
        result = {'id':'omh','status':'failed','message':'OMH 설치 실패. 기존 설정을 복원했습니다.'}
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
            # Every task type routes to the student's aux model at OMH's recommended
            # effort for that type; per-task chains are added later in /setup.
            from omh_enhancements import compose, enable_locked
            routing_dir = data / '.omh/routing'; routing_dir.mkdir(exist_ok=True)
            providers, chains = compose(route, {})
            (routing_dir / 'model-providers.json').write_text(json.dumps(providers, indent=2)+'\n')
            (routing_dir / 'model-chains.json').write_text(json.dumps(chains, indent=2)+'\n')
            launcher.parent.mkdir(parents=True, exist_ok=True)
            launcher.symlink_to(cli)
            receipt = {'version':OMH_VERSION,'source_commit':OMH_COMMIT,'archive_sha256':OMH_SHA256,
                       'cli':cli,'routing':route,'mode':'upstream-core','live_dispatch_verified':False}
            state['components']['omh-upstream'] = receipt
            message = 'OMH 기본 팩 설치 완료. 작업 종류별 권장 추론 강도와 모델 보정이 켜졌습니다.'
            try:
                try:
                    enable_locked(data, updates=restored or {})
                except ValueError:
                    enable_locked(data)  # a restored chain no longer validates: start clean
            except Exception as exc:
                # The upstream pack works without calibration; say so instead of failing it.
                message = f'OMH 기본 팩 설치 완료. 모델 보정은 켜지 못했습니다 ({type(exc).__name__}).'
            result = {'id':'omh','status':'installed','message':message+' 적용하기(재시작) 후 실제 위임으로 확인해 주세요.'}
            state.setdefault('last_results', {})['omh-upstream'] = result
            _save_state(data,state)
        except Exception as exc:
            # Restore activation config; keep failed artifacts in a recovery directory.
            if launcher.is_symlink() and str(launcher.readlink()).startswith(str(work)):
                launcher.unlink()
            # The calibration receipt describes files that are moved aside below.
            (data / '.kit-tools/omh-enhancements.json').unlink(missing_ok=True)
            restored = work / 'config.restore'; restored.write_bytes(before); os.replace(restored, config)
            for name, label in (('.omh','omh-state'), ('plugins/omh','omh-plugin')):
                path = data / name
                if path.exists(): shutil.move(str(path), str(work / ('failed-' + label)))
            if (work / 'restored-omh').is_dir():
                shutil.move(str(work / 'restored-omh'), str(data / '.omh'))
            result ={'id':'omh','status':'failed','message':f'OMH 설치 실패 ({type(exc).__name__}). 기존 설정을 복원했습니다.'}
        finally:
            # Every student profile home must come back exactly as it was, whether
            # the install succeeded, failed, or only partly wrote.
            try:
                _restore_profiles(data, snapshot)
            except Exception as exc:
                result = {'id':'omh','status':'failed',
                          'message':f'프로필 복원 실패 ({type(exc).__name__}). 관리자에게 문의해 주세요.'}
        return result
