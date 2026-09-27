"""Undo what /setup did: forget the keys, put the settings back.

Reverting a setting requires knowing what it was before, so every pack records a snapshot of
the config keys it touches the first time it is applied. Without that, "연결 해제" could only
delete keys and leave `stt.provider: groq` behind — the box would look configured with no
credentials to run on.

Deleting a key is destructive, so this only ever runs from an explicit button press, and it
writes the new .env atomically like every other write.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

SNAPSHOT = ".kit-config-snapshot.json"      # in HERMES_HOME, next to .env


def _load(data_dir: Path) -> dict:
    try:
        value = json.loads((Path(data_dir) / SNAPSHOT).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("복원 기록 형식이 잘못되었습니다")
    return value


def _save(data_dir: Path, snap: dict) -> None:
    """Persist the recovery baseline atomically; failure must abort configuration edits.

    Callers performing configuration changes hold config_store.locked throughout the
    snapshot/read/write transaction. This helper does not nest that same lock.
    """
    root = Path(data_dir)
    fd, temporary = tempfile.mkstemp(prefix='.kit-snapshot-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(snap, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, root / SNAPSHOT)
    finally:
        Path(temporary).unlink(missing_ok=True)


def snapshot(data_dir: Path, config: dict, current: dict) -> None:
    """Record the pre-apply value of each key, once. Later applies do not overwrite it."""
    if not config:
        return
    snap = _load(data_dir)
    for k in config:
        if k in snap:
            continue        # the first apply is the baseline; a second apply must not clobber it
        snap[k] = current.get(k)      # None means "was not set"
    _save(data_dir, snap)


def remove_keys(env_file: Path, names) -> list[str]:
    """Remove the given keys from .env. env_store owns .env writes, including the permissions."""
    from env_store import drop_env

    return drop_env(Path(env_file), names)


def plan(data_dir: Path, env_file: Path, packs) -> tuple[list[str], list[str]]:
    """What a disconnect would do, without doing it — so the confirmation can be honest."""
    from env_store import get_env

    env = get_env(env_file) if Path(env_file).exists() else {}
    keys = [k.env for p in packs for k in p.keys if env.get(k.env)]
    settings = list(_load(data_dir))
    return keys, settings


def revert_config(data_dir: Path, apply_fn) -> list[str]:
    """Put the snapshotted settings back. `apply_fn(key, value)` is injected so this module
    never shells out on its own, and stays testable without a Hermes install."""
    snap = _load(data_dir)
    done = []
    for k, was in snap.items():
        try:
            apply_fn(k, was)
            done.append(k)
        except Exception as e:
            log.warning("could not revert %s: %s", k, e)
    return done


def forget(data_dir: Path) -> None:
    """Drop the snapshot once the settings are back, so a later disconnect is a no-op."""
    (Path(data_dir) / SNAPSHOT).unlink(missing_ok=True)
