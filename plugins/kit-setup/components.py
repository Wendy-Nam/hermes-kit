"""Versioned, retryable component installation, independent of the core image seed.

Only bundled or explicitly pinned packages are accepted. Package installation never
runs scripts or enables plugins; optional plugin activation is a separate reviewed step.
"""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

KITS = frozenset({'job', 'sales', 'mkt', 'pm', 'dev'})
STATE_NAME = '.kit-components.json'
VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')
TRUSTED_OPTIONAL_PACKAGES = {}  # id -> {path, manifest_sha256}; no implicit remote trust


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value):
    p = Path(value)
    if not value or p.is_absolute() or '..' in p.parts or str(p) != value:
        raise ValueError('unsafe package path')
    return p


def _manifest(source, expected_id):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('package directory unavailable')
    path = source / 'manifest.json'
    if path.is_symlink():
        raise ValueError('manifest link refused')
    doc = json.loads(path.read_text())
    if doc.get('schema_version') != 'kit-component/v1' or doc.get('id') != expected_id:
        raise ValueError('invalid package identity')
    if not VERSION.fullmatch(str(doc.get('version', ''))):
        raise ValueError('invalid package version')
    files = doc.get('files')
    if not isinstance(files, dict) or not files or len(files) > 1000:
        raise ValueError('empty or oversized manifest')
    actual = set()
    total = 0
    for p in source.rglob('*'):
        if p.is_symlink():
            raise ValueError('package links refused')
        if p.is_file() and p != path:
            actual.add(p.relative_to(source).as_posix())
            total += p.stat().st_size
    if total > 32 * 1024 * 1024 or actual != set(files):
        raise ValueError('package file inventory mismatch')
    for name, digest in files.items():
        p = source / _relative(name)
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest) or _digest(p) != digest:
            raise ValueError('package checksum mismatch')
    return doc


def _read_state(data):
    path = data / STATE_NAME
    if not path.exists():
        return {'schema_version': 'kit-components/v1', 'selected_kits': [], 'components': {}}
    doc = json.loads(path.read_text())
    if doc.get('schema_version') != 'kit-components/v1' or not isinstance(doc.get('components'), dict):
        raise ValueError('invalid component state; preserve it for recovery')
    return doc


def _save_state(data, state):
    fd, name = tempfile.mkstemp(prefix='.kit-state-', dir=data)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, data / STATE_NAME)
    finally:
        if os.path.exists(name): os.unlink(name)


@contextlib.contextmanager
def _locked(data):
    data.mkdir(parents=True, exist_ok=True)
    with (data / '.kit-components.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def _unchanged(target, receipt):
    if target.is_symlink() or not target.is_dir() or not receipt:
        return False
    files = receipt.get('files', {})
    actual = set()
    for p in target.rglob('*'):
        if p.is_symlink(): return False
        if p.is_file(): actual.add(p.relative_to(target).as_posix())
    return actual == set(files) and all(_digest(target / name) == digest for name, digest in files.items())


def _install(source, target, component_id, state):
    doc = _manifest(source, component_id)
    prior = state['components'].get(component_id, {})
    if target.exists() or target.is_symlink():
        if not _unchanged(target, prior):
            return {'id': component_id, 'status': 'preserved', 'message': '기존 파일에 사용자 변경이 있어 보존했습니다.'}
        old = tuple(int(x) for x in prior.get('version', '0.0.0').split('.'))
        new = tuple(int(x) for x in doc['version'].split('.'))
        if new < old:
            raise ValueError('package downgrade refused')
        if prior.get('version') == doc['version']:
            if prior.get('files') != doc['files']:
                raise ValueError('same version has different content')
            return {'id': component_id, 'status': 'installed', 'message': '현재 버전이 설치되어 있습니다.'}
    # Check every existing parent: never follow a user-created link outside the data tree.
    for parent in (target.parent, *target.parents):
        if parent.is_symlink(): raise ValueError('destination links refused')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.kit-stage-', dir=target.parent))
    backup = staging.with_name(staging.name + '-previous')
    published = False
    try:
        for name in doc['files']:
            dst = staging / name; dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(source) / name, dst)
        if target.exists(): os.replace(target, backup)
        try:
            os.replace(staging, target)
            published = True
        except BaseException:
            if backup.exists(): os.replace(backup, target)
            raise
        state['components'][component_id] = {'version': doc['version'], 'files': doc['files']}
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # A failed rollback may leave the only original in backup. Existence of
        # target alone is insufficient: another writer could have created it.
        if published:
            shutil.rmtree(backup, ignore_errors=True)
    return {'id': component_id, 'status': 'installed', 'message': f"{doc['version']} 설치 완료"}


def install_component(source, data_dir, component_id):
    """Install a skill component from a previously trusted source. No executable installers."""
    if component_id not in KITS:
        return {'id': component_id, 'status': 'unavailable', 'message': '제공되지 않는 직무 팩입니다.'}
    data = Path(data_dir).resolve()
    with _locked(data):
        state = _read_state(data)
        result = _install(Path(source), data / 'skills' / 'kit' / component_id, component_id, state)
        _save_state(data, state)
        return result


def retry_components(data_dir, *, selected_kits=None, seed_dir=Path('/opt/kit/seed'),
                     private_token='', private_repo='Wendy-Nam/hermes-kit-packs', private_ref=None):
    data = Path(data_dir).resolve(); results = []
    with _locked(data):
        state = _read_state(data)
        if selected_kits is not None:
            selected = sorted(set(selected_kits))
            if any(k not in KITS for k in selected): raise ValueError('unknown job kit')
            state['selected_kits'] = selected
        _save_state(data, state)  # selection survives an interrupted/failed install
        for kit in state.get('selected_kits', []):
            try:
                result = _install(Path(seed_dir) / 'kits' / kit, data / 'skills' / 'kit' / kit, kit, state)
            except Exception as exc:
                result = {'id': kit, 'status': 'failed', 'message': f'설치 실패 ({type(exc).__name__}); 재시도할 수 있습니다.'}
            results.append(result)
            state.setdefault('last_results', {})[kit] = result
            _save_state(data, state)
        if (Path(seed_dir) / 'kskill').is_dir():  # absent in images before k7
            results.append(_install_kskills(data, state, Path(seed_dir) / 'kskill'))
            _save_state(data, state)
    if private_token:
        from fetch_packs import fetch
        ok, message = fetch(private_repo, private_ref or '', private_token, data)
        results.append({'id': 'private-packs', 'status': 'installed' if ok else 'unavailable', 'message': message})
    return results


def kskill_names(selected_kits):
    """Vendored k-skill skills for everyone plus the selected job kits, with dependencies."""
    spec = json.loads(Path(__file__).with_name('kskills.json').read_text())
    names = list(spec['common'])
    for kit in selected_kits:
        names += spec['kits'].get(kit, [])
    for name in list(names):
        names += spec['requires'].get(name, [])
    return list(dict.fromkeys(names))


def _install_kskills(data, state, source):
    """One summary row: each skill is its own verified component under skills/k-skill."""
    names = kskill_names(state.get('selected_kits', []))
    failed = []
    for name in names:
        try:
            result = _install(source / name, data / 'skills' / 'k-skill' / name, name, state)
        except Exception:
            result = {'status': 'failed'}
        if result['status'] == 'failed':
            failed.append(name)
    if failed:
        result = {'id': 'k-skill', 'status': 'failed',
                  'message': '한국형 스킬 일부 설치 실패: ' + ', '.join(failed) + '. 설치 재시도를 눌러 주세요.'}
    else:
        result = {'id': 'k-skill', 'status': 'installed', 'message': f'한국형 스킬 {len(names)}개 설치 확인'}
    state.setdefault('last_results', {})['k-skill'] = result
    return result


def install_optional(package_id, data_dir, *, trusted_registry=None):
    """Explicit trust contract for optional OMH bundles; no bundle ships by default.

    A registry entry pins the package manifest digest, whose inventory pins every
    file. Plugins are staged only; enable/configure and health checks remain explicit.
    """
    registry = TRUSTED_OPTIONAL_PACKAGES if trusted_registry is None else trusted_registry
    entry = registry.get(package_id)
    if package_id != 'omh' or not entry:
        return {'id': package_id, 'status': 'unavailable', 'message': '검증된 설치 패키지가 아직 제공되지 않습니다.'}
    data = Path(data_dir).resolve()
    try:
        source = Path(entry['path'])
        if _digest(source / 'manifest.json') != entry['manifest_sha256']:
            raise ValueError('untrusted manifest')
        doc = _manifest(source, package_id)
        if 'plugin.yaml' not in doc['files'] or '__init__.py' not in doc['files']:
            raise ValueError('plugin entrypoints missing')
        with _locked(data):
            state = _read_state(data)
            result = _install(source, data / 'plugins' / package_id, package_id, state)
            _save_state(data, state)
            result['message'] += ' · 활성화 및 호환성 검증은 별도 필요합니다.'
            return result
    except Exception as exc:
        return {'id': package_id, 'status': 'failed', 'message': f'패키지 검증 실패 ({type(exc).__name__})'}
