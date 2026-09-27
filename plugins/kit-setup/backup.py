"""Consistent, bounded note/config backups without credentials or previous archives."""
import fcntl
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import time
from urllib.parse import parse_qsl, urlsplit
from pathlib import Path

# .omh/routing: per-task OMH chains; reapplied when OMH is reinstalled after a restore.
INCLUDE = ("memories", "config.yaml", "SOUL.md", "cron/jobs.json", "profiles", "vaults", ".omh/routing")
EXCLUDE_NAMES = {"auth.json", "auth_tokens.json", "sessions", "cookies.json",
                 "credentials.json", "auth", "executors", "_backup"}
KEEP = 4
_SECRET_KEY = re.compile(r"(?:api[_-]?key|token|secret|password|authorization|cookie|credential)", re.I)


def _excluded(rel):
    return any(p in EXCLUDE_NAMES or p.startswith('.env') or p.endswith('.env')
               or any(p.startswith(n + '.') for n in EXCLUDE_NAMES)
               for p in Path(rel).parts)


def _scrub(value):
    if isinstance(value, dict):
        return {k: (v if isinstance(v, str) and re.fullmatch(r'\$\{[A-Z][A-Z0-9_]*\}', v)
                    else '[REENTER VIA SETUP]') if _SECRET_KEY.search(str(k)) else _scrub(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and '://' in value:
        # MCP/proxy credentials are sometimes embedded in otherwise innocuous
        # "url" fields. Do not publish those URLs into the synced backup vault.
        try:
            url = urlsplit(value)
            fields = parse_qsl(url.query, keep_blank_values=True) + parse_qsl(url.fragment, keep_blank_values=True)
            if url.username is not None or url.password is not None or any(
                (_SECRET_KEY.search(k) or k.lower() in ('key', 'auth', 'access_key'))
                and not re.fullmatch(r'\$\{[A-Z][A-Z0-9_]*\}', v)
                for k, v in fields
            ):
                return '[REENTER VIA SETUP]'
        except ValueError:
            # A malformed URL is not evidence that it is safe to copy.
            return '[REENTER VIA SETUP]'
    return value


def archive_bytes(path):
    """Strip inline credential fields from configs; never silently copy unparsed YAML."""
    raw = path.read_bytes()
    if path.name == 'config.yaml':
        import yaml
        return yaml.safe_dump(_scrub(yaml.safe_load(raw)), allow_unicode=True).encode()
    if path.name == 'jobs.json':
        return json.dumps(_scrub(json.loads(raw)), ensure_ascii=False, indent=2).encode()
    return raw


def _build(data_dir, dest):
    out = dest / f"{time.strftime('%Y-%m-%d')}.tar.gz"
    if out.exists():
        return False, f"오늘 백업이 이미 있습니다: {out.name}"
    fd, temporary = tempfile.mkstemp(prefix='.kit-backup-', suffix='.tmp', dir=dest)
    os.close(fd)
    tmp = Path(temporary)
    members = 0
    try:
        with tarfile.open(tmp, 'w:gz') as tf:
            for name in INCLUDE:
                src = data_dir / name
                paths = [src] if src.is_file() else sorted(src.rglob('*'))
                for path in paths:
                    rel = path.relative_to(data_dir)
                    # rglob does not descend symlink dirs; reject symlink files and parents too.
                    if not path.is_file() or any(p.is_symlink() for p in [path, *path.parents]):
                        continue
                    if dest == path or dest in path.parents or _excluded(rel):
                        continue
                    blob = archive_bytes(path)
                    info = tarfile.TarInfo(str(rel))
                    info.size, info.mode, info.mtime = len(blob), 0o600, int(path.stat().st_mtime)
                    tf.addfile(info, io.BytesIO(blob))
                    members += 1
        if not members:
            return False, '백업할 파일이 없습니다'
        with tmp.open('rb') as stream:
            os.fsync(stream.fileno())
        # Validate readability before publishing or pruning any previous backup.
        with tarfile.open(tmp) as tf:
            for item in tf:
                with tf.extractfile(item) as stream:
                    while stream.read(1024 * 1024):
                        pass
        os.replace(tmp, out)
        for old in sorted(dest.glob('????-??-??.tar.gz'), reverse=True)[KEEP:]:
            old.unlink()
        return True, f'백업 완료: {out.name} ({members}개 파일, {out.stat().st_size // 1024}KB)'
    finally:
        tmp.unlink(missing_ok=True)


def build(data_dir: Path, dest: Path):
    data_dir, dest = Path(data_dir).resolve(), Path(dest).resolve()
    if not data_dir.is_dir():
        return False, '데이터 디렉터리가 없습니다'
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with (dest / '.backup.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _build(data_dir, dest)
    except Exception as exc:
        return False, f'백업 실패: {type(exc).__name__}'


def install_cron(data_dir: Path):
    from maintenance import install_job
    return install_job(data_dir, 'kit-backup', 'hermes-kit 주간 백업',
                       '0 4 * * 1', Path(__file__))


def main():
    home = Path(os.environ.get('HERMES_HOME') or '/opt/data')
    ok, message = build(home, home / 'vaults/personal/_backup')
    print(message, file=sys.stderr)
    return 0 if ok or message.startswith('오늘 백업이 이미 있습니다:') else 1


if __name__ == '__main__':
    raise SystemExit(main())
