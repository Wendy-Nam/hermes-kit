"""Atomic, locked configuration edits shared by setup actions."""
import contextlib
import fcntl
import os
import tempfile
from pathlib import Path
import yaml

@contextlib.contextmanager
def locked(data_dir):
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.kit-config.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield

def read(data_dir):
    path = Path(data_dir)/'config.yaml'
    value = yaml.safe_load(path.read_text()) if path.exists() else {}
    if value is not None and not isinstance(value, dict):
        raise ValueError('설정 파일 형식이 잘못되었습니다')
    return value or {}

def write(data_dir, changes, *, remember=True):
    root = Path(data_dir)
    with locked(root):
        doc = read(root)
        if remember:
            from disconnect import snapshot
            from discord_ui import _flatten
            snapshot(root, changes, _flatten(doc))
        for dotted, value in changes.items():
            parts = dotted.split('.')
            if not all(parts): raise ValueError('invalid configuration key')
            node = doc
            for part in parts[:-1]:
                if part not in node: node[part] = {}
                if not isinstance(node[part], dict): raise ValueError('configuration shape mismatch')
                node = node[part]
            if value is None:
                node.pop(parts[-1], None)
            else:
                node[parts[-1]] = value
        target = root/'config.yaml'
        fd, name = tempfile.mkstemp(prefix='.config-', dir=root)
        try:
            with os.fdopen(fd,'w') as f:
                yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
                f.flush(); os.fsync(f.fileno())
            os.chmod(name,0o600)
            os.replace(name,target)
        finally:
            if os.path.exists(name): os.unlink(name)
