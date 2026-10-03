"""Quota-aware OMH routing patches, owned by the kit instead of a separate installer.

Three files under `patches/omh-routing/files` replace their OMH namesakes in
`plugins/omh`, and one data file lands in `.omh/routing`:

- `omh_provider_mapper.py` resolves an OMH recommended model *identity*
  (`kimi-k3`) onto the providers OmniRoute actually serves, read from
  `/api/combos`. It never substitutes a different model: a version change is
  reported as a lower tier rather than silently swapped.
- `route_readiness.py` takes bounded management snapshots (30s TTL, 0.8s
  timeout) and treats a spent rolling-window quota as unavailable **at route
  time**. A subscribe account reports `isActive: true` while its quota is
  gone, and OmniRoute drops it in a pre-dispatch filter and answers 429, so
  readiness that trusts the active flag alone spends the turn on a dead first
  choice and never falls through. Only a definite 100% reading counts as
  exhausted; absent, null or malformed stays `unknown`.
- `public_free_routing.py` keeps public/free routing separate from private
  subscription routing.
- `providers.json` is the entitlement document. A provider missing from
  `providers` cannot be reasoned about at all; one in `excluded_providers` is
  demoted even when it works.

Why this lives here rather than in a separate installer: OMH ships its own
copy of every patched file, so `omh update` silently restores upstream
behaviour. This module is re-run on every boot and after every OMH install, so
the patches are a property of the kit rather than a step the student can lose.

Nothing here writes student configuration beyond these four files, and the
student's own `providers.json` is never overwritten once they extend it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PATCH_DIR = Path('/opt/kit/patches/omh-routing')
SOURCE_DIR = PATCH_DIR / 'files'
PLUGIN_DIR = 'plugins/omh'
CODE_PATCHES = ('omh_provider_mapper.py', 'route_readiness.py', 'public_free_routing.py')
ENTITLEMENT = 'providers.json'
BACKUP_DIR = '.kit-omh-routing-backups'


def _root(data_dir):
    return Path(data_dir).resolve()


def omh_installed(data_dir):
    """OMH is present only once its plugin directory exists."""
    return (_root(data_dir) / PLUGIN_DIR).is_dir()


def _sources_present():
    return SOURCE_DIR.is_dir() and all((SOURCE_DIR / n).is_file() for n in CODE_PATCHES)


def _template():
    """The gateway-only entitlement document shipped with the kit, or None."""
    try:
        blob = json.loads((SOURCE_DIR / ENTITLEMENT).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return blob if isinstance(blob, dict) and isinstance(blob.get('providers'), dict) else None


def _atomic_write(path, blob):
    fd, temp = tempfile.mkstemp(prefix='.kit-omh-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(blob)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def _backup(path, data):
    """Keep the first original we ever replaced, so a rollback has something to read."""
    if not path.is_file():
        return
    root = data / BACKUP_DIR
    root.mkdir(parents=True, exist_ok=True)
    target = root / path.name
    if not target.exists():
        shutil.copy2(path, target)


def _is_students_own(current):
    """True when the student changed the template, so it must not be rewritten.

    Overwriting that would silently drop connections they added, which is the
    one thing this module must never do: the entitlement document is the
    student's record of what they actually hold.
    """
    template = _template()
    if template is None:
        return True
    # A file that is not there yet is the kit's to write, not the student's.
    # read_text on a missing path raises OSError, which would otherwise land in
    # the except below and read as "the student wrote something".
    if not current.is_file():
        return False
    try:
        document = json.loads(current.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return True
    if not isinstance(document, dict):
        return True
    for key, empty in (('providers', dict), ('subscription_clis', list), ('excluded_providers', list)):
        mine, theirs = document.get(key), template.get(key)
        if mine is None:
            continue
        if not isinstance(mine, empty):
            return True
        if mine != theirs:
            return True
    return False


def _entitlement_path(data):
    return data / '.omh/routing' / ENTITLEMENT


def status(data_dir):
    """Report each patch as applied, drifted or missing, without writing anything."""
    data = _root(data_dir)
    if not omh_installed(data):
        return {'status': 'absent', 'message': 'OMH가 설치되지 않았습니다.', 'files': {}}
    if not _sources_present():
        return {'status': 'unavailable', 'message': '키트에 라우팅 패치가 없습니다.', 'files': {}}
    rows, pending = {}, 0
    for name in CODE_PATCHES:
        target = data / PLUGIN_DIR / name
        if not target.is_file():
            rows[name] = 'missing'
        elif target.read_bytes() == (SOURCE_DIR / name).read_bytes():
            rows[name] = 'applied'
        else:
            rows[name] = 'drifted'
        pending += rows[name] != 'applied'
    entitlement = _entitlement_path(data)
    if not entitlement.is_file():
        rows[ENTITLEMENT] = 'missing'
    elif _is_students_own(entitlement):
        rows[ENTITLEMENT] = 'student'
    elif entitlement.read_bytes() == (SOURCE_DIR / ENTITLEMENT).read_bytes():
        rows[ENTITLEMENT] = 'applied'
    else:
        rows[ENTITLEMENT] = 'drifted'
    pending += rows[ENTITLEMENT] in ('missing', 'drifted')
    return {'status': 'pending' if pending else 'ok', 'files': rows, 'pending': pending}


def apply(data_dir):
    """Idempotently restore the kit's routing behaviour.

    Safe to call on every boot: a byte-identical file is left alone, and a
    student's own entitlement document is never rewritten.
    """
    data = _root(data_dir)
    if not omh_installed(data) or not _sources_present():
        return {'status': 'skipped', 'message': 'OMH 라우팅 패치를 적용하지 않았습니다.', 'changed': []}
    changed = []
    target_dir = data / PLUGIN_DIR
    for name in CODE_PATCHES:
        source, target = SOURCE_DIR / name, target_dir / name
        blob = source.read_bytes()
        if target.is_file() and target.read_bytes() == blob:
            continue
        _backup(target, data)
        _atomic_write(target, blob)
        # A stale bytecode cache would shadow the new source.
        for cached in target_dir.joinpath('__pycache__').glob(name[:-3] + '.cpython-*.pyc'):
            cached.unlink(missing_ok=True)
        changed.append(name)
    entitlement = _entitlement_path(data)
    template = SOURCE_DIR / ENTITLEMENT
    if not _is_students_own(entitlement):
        blob = template.read_bytes()
        if not entitlement.is_file() or entitlement.read_bytes() != blob:
            _backup(entitlement, data)
            entitlement.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(entitlement, blob)
            changed.append(ENTITLEMENT)
    return {'status': 'ok', 'changed': changed,
            'message': ('라우팅 패치를 적용했습니다: ' + ', '.join(changed)) if changed else '라우팅 패치가 이미 최신입니다.'}


def verify(data_dir):
    """Per-category readiness report. Reads the gateway, makes no model call.

    Delegates to the shipped scenario checker. A missing gateway is reported,
    never raised: this runs during boot. 0 = every first choice is live,
    1 = a category loses a turn before reaching a live model, 2 = the gateway
    could not be read. None of the three is a crash.
    """
    data = _root(data_dir)
    if not omh_installed(data):
        return {'status': 'absent', 'message': 'OMH가 설치되지 않았습니다.', 'detail': ''}
    checker = PATCH_DIR / 'verify.py'
    if not checker.is_file():
        return {'status': 'unavailable', 'message': '라우팅 검증 스크립트가 없습니다.', 'detail': ''}
    env = dict(os.environ, HOME=str(data), HERMES_HOME=str(data), OMH_HOME=str(data / '.omh'))
    try:
        done = subprocess.run([sys.executable, str(checker)], capture_output=True, text=True,
                              timeout=90, env=env, cwd=str(data))
    except (OSError, subprocess.SubprocessError):
        return {'status': 'error', 'message': '라우팅 검증에 실패했습니다.', 'detail': ''}
    outcome = {0: ('ok', '모든 작업의 1순위가 실제 연결을 가집니다.'),
               1: ('degraded', '연결 없는 경로가 1순위입니다. providers.json을 확인하세요.')}.get(
                   done.returncode, ('unavailable', '게이트웨이를 읽지 못했습니다.'))
    return {'status': outcome[0], 'message': outcome[1], 'detail': (done.stdout or '').strip()}


def rollback(data_dir):
    """Restore the files OMH shipped, from the backups taken on first replacement."""
    data = _root(data_dir)
    root = data / BACKUP_DIR
    if not root.is_dir():
        return {'status': 'skipped', 'message': '되돌릴 백업이 없습니다.', 'changed': []}
    changed = []
    for name in CODE_PATCHES + (ENTITLEMENT,):
        backup = root / name
        if not backup.is_file():
            continue
        target = data / PLUGIN_DIR / name if name in CODE_PATCHES else _entitlement_path(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, backup.read_bytes())
        changed.append(name)
    return {'status': 'ok', 'changed': changed,
            'message': ('원본을 복원했습니다: ' + ', '.join(changed)) if changed else '복원할 파일이 없습니다.'}