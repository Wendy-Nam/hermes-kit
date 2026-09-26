#!/opt/hermes/.venv/bin/python
"""Deep-merge a YAML overlay into a YAML file in place.

Dicts merge recursively; lists and scalars in the overlay replace the target's.
Used once on the first kit boot: Hermes' own cont-init seeds a full default
config.yaml before ours runs, so the kit only overlays the keys it changes.
Comments in the target are not preserved (PyYAML); the write is atomic and keeps the mode.

usage: merge_yaml.py <target.yaml> <overlay.yaml>
"""
import os
import sys
import tempfile
from pathlib import Path

import yaml


def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def merge_file(target: Path, overlay: Path) -> None:
    over = yaml.safe_load(overlay.read_text()) or {}
    if not isinstance(over, dict):
        raise ValueError(f"overlay must be a mapping: {overlay}")
    base = yaml.safe_load(target.read_text()) or {}
    merged = deep_merge(base, over)
    mode = os.stat(target).st_mode
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    os.chmod(tmp, mode)
    os.replace(tmp, target)


if __name__ == "__main__":
    merge_file(Path(sys.argv[1]), Path(sys.argv[2]))
