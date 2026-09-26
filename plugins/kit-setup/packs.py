"""Pack and job-kit definitions, validated on load.

A student never sees this file directly, so a typo here surfaces as "that option
is broken" three weeks into a course. Everything is checked at import time
instead: an unknown validator, a duplicate env name, or a kit pointing at a
missing pack fails the plugin load loudly rather than silently at /setup time.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
MAX_KEYS_PER_PACK = 5   # Discord modal limit; a pack above this cannot be entered at all


@dataclass(frozen=True)
class KeySpec:
    env: str
    label: str
    hint: str
    validator: str
    url: str
    optional: bool = False


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    keys: tuple[KeySpec, ...]
    config: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)
    required: bool = False
    required_one_of: str | None = None
    features: tuple[str, ...] = ()


@dataclass(frozen=True)
class Kit:
    id: str
    title: str
    features: tuple[str, ...]
    skills_dir: str | None
    installer: str | None = None
    consent: bool = False


def _fail(msg):
    raise ValueError(f"packs.json: {msg}")


def _key(k):
    if not _ENV_NAME.match(k.get("env", "")):
        _fail(f"env name must be UPPER_SNAKE: {k!r}")
    return KeySpec(env=k["env"], label=k["label"], hint=k.get("hint", ""),
                   validator=k["validator"], url=k.get("url", ""),
                   optional=bool(k.get("optional")))


def _load(name):
    data = json.loads((HERE / name).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        _fail(f"{name} must be a non-empty list")
    return data


def load_packs(validators: dict | None = None) -> list[Pack]:
    raw = _load("packs.json")
    seen_ids, seen_env = set(), {}
    packs = []
    for p in raw:
        pid = p.get("id", "")
        if not pid or pid in seen_ids:
            _fail(f"duplicate or empty pack id: {pid!r}")
        seen_ids.add(pid)
        keys = tuple(_key(k) for k in p.get("keys", []))
        if len(keys) > MAX_KEYS_PER_PACK:
            _fail(f"pack {pid} has {len(keys)} keys (max {MAX_KEYS_PER_PACK}) — it would not fit a modal")
        if validators is not None:
            for k in keys:
                if k.validator not in validators:
                    _fail(f"pack {pid} references unknown validator {k.validator!r}")
        # Two packs writing the same env var would make "which one did I pick?" unanswerable,
        # and required_one_of is exactly how a user asks for one of two.
        if not p.get("required_one_of"):
            for k in keys:
                if k.env in seen_env and seen_env[k.env] != pid:
                    _fail(f"{k.env} is claimed by both {seen_env[k.env]!r} and {pid!r}")
                seen_env[k.env] = pid
        packs.append(Pack(id=pid, title=p.get("title", pid), keys=keys,
                          config=p.get("config") or {}, env=p.get("env") or {},
                          required=bool(p.get("required")),
                          required_one_of=p.get("required_one_of"),
                          features=tuple(p.get("features") or [])))
    return packs


def load_kits() -> list[Kit]:
    packs = {p.id for p in load_packs()}
    kits = []
    for k in _load("kits.json"):
        missing = [f for f in k.get("features", []) if f not in packs]
        if missing:
            _fail(f"kit {k.get('id')!r} references missing packs: {missing}")
        kits.append(Kit(id=k["id"], title=k.get("title", k["id"]), features=tuple(k.get("features") or []),
                        skills_dir=k.get("skills_dir"), installer=k.get("installer"),
                        consent=bool(k.get("consent"))))
    return kits


def packs_for_kits(kit_ids, packs, kits=None) -> list[Pack]:
    """The feature packs a set of kits needs, plus the always-required base pack, in a stable order.

    Stable order matters: the modal the student fills in must not reshuffle between runs.
    """
    catalog = {k.id: k for k in (kits if kits is not None else load_kits())}
    wanted = {"base"}
    for kid in kit_ids:
        kit = catalog.get(kid)
        if kit is None:
            raise ValueError(f"unknown kit: {kid}")
        wanted.update(kit.features)
    return [p for p in packs if p.id in wanted]


def missing_keys(packs, env: dict) -> list[KeySpec]:
    """Keys of required packs that have no value yet. Empty means the student can restart the bot."""
    return [k for p in packs if p.required for k in p.keys
            if not k.optional and not env.get(k.env)]
