"""Explicit restore into a NEW directory; never overwrite a running Hermes home."""
import argparse
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from backup import INCLUDE, _excluded
MAX_TOTAL_BYTES = 2 * 1024 ** 3
MAX_FILES = 100_000


def restore(archive, target):
    archive, target = Path(archive).resolve(), Path(target).absolute()
    if target.exists() or target.is_symlink():
        return False, '복구 대상은 존재하지 않는 새 디렉터리여야 합니다'
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.kit-restore-', dir=target.parent))
        with tarfile.open(archive, 'r:gz') as tf:
            entries = tf.getmembers()
            if len(entries) > MAX_FILES or sum(m.size for m in entries) > MAX_TOTAL_BYTES:
                raise ValueError('archive limit')
            seen = set()
            for member in entries:
                path = PurePosixPath(member.name)
                # A kit backup has only regular files from allowlisted roots. Validate the
                # entire archive before writing any file, including duplicate path attacks.
                if (not member.isfile() or path.is_absolute() or '..' in path.parts
                        or '\\' in member.name or str(path) in seen or _excluded(str(path))
                        or not any(str(path) == p or str(path).startswith(p + '/') for p in INCLUDE)):
                    raise ValueError('unsafe archive member')
                seen.add(str(path))
            if not entries:
                raise ValueError('empty archive')
            for member in entries:
                dest = temporary / member.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tf.extractfile(member) as src, dest.open('xb') as out:
                    shutil.copyfileobj(src, out)
                dest.chmod(0o600)
                if member.name == 'cron/jobs.json':
                    document = json.loads(dest.read_text())
                    jobs = document.get('jobs', []) if isinstance(document, dict) else document
                    if not isinstance(jobs, list):
                        raise ValueError('invalid cron registry')
                    for job in jobs:
                        job['enabled'] = False
                    dest.write_text(json.dumps(document, ensure_ascii=False, indent=2))
        # Refuse a concurrently created target instead of replacing it.
        if target.exists() or target.is_symlink():
            raise FileExistsError('target appeared')
        os.rename(temporary, target)
        temporary = None
        return True, '복구 완료. 크론은 중지되어 있습니다. 키와 로그인은 /setup 및 모델 로그인으로 다시 연결하세요'
    except Exception as exc:
        return False, f'복구 실패 ({type(exc).__name__})'
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    ok, message = restore(args.archive, args.target)
    print(message)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
