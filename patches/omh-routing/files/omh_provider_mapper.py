#!/usr/bin/env python3
"""Resolve OMH recommended model identities onto providers OmniRoute serves.

OMH recommends a model *identity* (kimi-k3, gpt-6-astra), not a provider. A
hand-written chain cannot track what the gateway actually serves, and pinning
one provider per identity let a single inactive connection remove the model.

Evidence source of truth is /api/combos, not /api/models. Combos are the routes
that actually execute and they carry long provider ids (codex, gh, cline). The
model catalog uses short aliases for the same providers (cx, gh, cl), so its
`available` flag cannot be joined to connection state by name. The catalog is
read only as a secondary hint.

Family policy. An identity matches its whole model family, so 'kimi-k3' also
admit 'kimi-k2.6': a family member is a usable degradation when the requested
version is unavailable. Ordering is explicit, never incidental:
    tier 0  exact version           kimi-k3
    tier 1  same family, other ver. kimi-k2.6
Ties inside a tier prefer an active connection, then provider name, so the
result is deterministic. A free suffix (':free') is the same model on a free
route, not a different model, and stays in the same tier.

Model identity is never silently substituted: every admitted reference is
reported with its tier so a caller can see whether a fallback would be a
version change. No inference calls are made.
"""
from __future__ import annotations

import json
import os
import re

_BASE = 'http://omniroute:20128'
_TIMEOUT = 8.0
_TRUSTED_TEST = {'active', 'ok', 'success'}
# Effort and provider-side qualifiers that are not a different model.
def _norm(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


def _tokens(value: str) -> list[str]:
    """Split on separators that are not part of a version token.

    A plain character split turns 'K2.6' into ('k','2','6') and loses the fact
    that it is one version token. Split only on '-', '_', '/' and spaces, and
    keep dots inside a token.
    """
    text = str(value or '').lower()
    return [t for t in re.split(r'[-_/\s]+', text) if t]


# OMH's shipped chains use editorial aliases that are not model names.
# 'deepseek-flash' stands for 'deepseek-v4.1-flash'; without this the alias
# resolves to nothing and the category looks provider-less.
_ALIASES = {
    'deepseek-flash': 'deepseek-v4.1-flash',
}


def resolve_alias(identity: str) -> str:
    """Map an editorial alias to the model identity it stands for."""
    key = str(identity or '').strip().lower()
    return _ALIASES.get(key, str(identity or ''))


def _strip_free(reference: str) -> str:
    return str(reference or '').split(':', 1)[0]



def _name_of(reference: str) -> str:
    """The model-name portion of a reference.

    A reference may be 'provider/model', 'provider/org/model' or
    'provider/org/vendor/model'. Take the trailing segment that starts with an
    alphabetic family token, scanning from the right.
    """
    text = _strip_free(reference)
    if '/' not in text:
        return text
    parts = text.split('/')
    for index in range(len(parts) - 1, 0, -1):
        head = parts[index].split('-')[0].split('.')[0]
        if head and head[0].isalpha():
            return '/'.join(parts[index:])
    return parts[-1]


def _signature(name: str) -> tuple[str, tuple[str, ...]]:
    """Split a model name into (family, discriminating tokens).

    'glm-5.3-flash'  -> ('glm',  ('5', '3', 'flash'))
    'kimi-k3'        -> ('kimi', ('k', '3'))
    'gpt-6-astra'    -> ('gpt', ('6', 'astra'))
    'gpt-6-sol'      -> ('gpt', ('6', 'sol'))

    The family is the leading alphabetic token. Every remaining token is part of
    the model identity, so 'gpt-6-astra' and 'gpt-6-sol' stay distinct while
    'kimi-k3' and 'kimi-k3-high' share a signature once an effort tier is
    dropped. Comparing the full token tuple, not just the numbers, is what keeps
    two same-numbered variants from being confused.
    """
    tokens = _tokens(name)
    if not tokens or not tokens[0] or not tokens[0][0].isalpha():
        return '', ()
    return tokens[0], tuple(tokens[1:])


_EFFORT_TOKENS = {'high', 'xhigh', 'medium', 'low', 'max', 'ultra',
                  'thinking', 'reasoning', 'spark', 'fast'}


def _drop_effort(tokens: tuple[str, ...]) -> tuple[str, ...]:
    while tokens and tokens[-1] in _EFFORT_TOKENS:
        tokens = tokens[:-1]
    return tokens


# 'k3' and 'k2.6' are both a single letter-prefixed version token.
_LETTER_VERSION = re.compile(r'^([a-z]+)(\d+(?:\.\d+)*)$')


def _numbers(tokens: tuple[str, ...]) -> tuple[int, ...]:
    """Numeric parts of each token.

    'k3' and '3' both denote 3, so a letter-prefixed version still compares:
    kimi-k3, kimi-k4 and Kimi-K2.6 carry 3, 4 and (2, 6) respectively.
    """
    out: list[int] = []
    for token in tokens:
        digits = re.findall(r'\d+', token)
        if digits:
            out.append(int(digits[0]))
    return tuple(out)


def _version_key(tokens: tuple[str, ...]) -> tuple[int, ...] | None:
    """Version as a comparable tuple, normalising letter-prefixed versions.

    'kimi-k3' and 'kimi-k2.6' both belong to the same lineage even though the
    bare numbers (3) and (2, 6) differ in shape, so a token like 'k3' is read as
    the single version 3 rather than as a different major.
    """
    if not tokens:
        return None
    letter = _LETTER_VERSION.match(tokens[0])
    if letter:
        return _numbers((letter.group(2),))
    return _numbers(tokens)


def classify(identity: str, reference: str) -> int | None:
    """0 = same model, 1 = same family, other version, None = different model.

    'kimi-k3' accepts 'kimi-k3-high' (tier 0, same model) and 'kimi-k2.6'
    (tier 1, a deliberate degradation when the requested version is gone). It
    rejects 'glm-5.3-flash', 'gpt-6-sol' and 'gpt-6-luna': those are different
    models, and silently substituting one would misapply model calibration.
    """
    identity = resolve_alias(identity)
    ident_family, ident_tokens = _signature(_name_of(identity) or str(identity or ''))
    if not ident_family:
        return None
    ref_family, ref_tokens = _signature(_name_of(reference))
    if ref_family != ident_family or not ref_tokens:
        return None

    ident_core = _drop_effort(ident_tokens)
    ref_core = _drop_effort(ref_tokens)

    # Numbers must line up: a different major/minor version is a family member.
    ident_numbers, ref_numbers = _numbers(ident_core), _numbers(ref_core)
    if ident_numbers != ref_numbers:
        # A family fallback is a degradation within one lineage, never across
        # unrelated ones: gpt-6 must not fall back to gpt-4 or gpt-oss. Compare
        # the dotted version rather than the leading integer so that
        # claude-opus-4.6 and 4.7 stay in family while kimi-k3 and k2.6 do too.
        ident_key = _version_key(ident_core)
        ref_key = _version_key(ref_core)
        if not ident_key or not ref_key:
            return None
        # 'kimi-k3' and 'kimi-k2.6' are the K line, so a letter-prefixed version
        # keeps its major comparable: compare the trailing minor only.
        ident_letter = _LETTER_VERSION.match(ident_core[0]) if ident_core else None
        ref_letter = _LETTER_VERSION.match(ref_core[0]) if ref_core else None
        if ident_letter and ref_letter:
            # Same lettered line ('k3', 'k2.6'): compare the numeric part only.
            ident_key = ident_key
            ref_key = ref_key
        ident_major, ident_minor = ident_key[0], (ident_key[1] if len(ident_key) > 1 else 0)
        ref_major, ref_minor = ref_key[0], (ref_key[1] if len(ref_key) > 1 else 0)
        # Both sides are letter-prefixed versions of one line ('k3', 'k2.6'):
        # the letter is the line marker, so any numeric step stays in family.
        if ident_letter and ref_letter:
            return 1
        if ref_major != ident_major:
            return None
        # Same major: a different minor is a family sibling (4.6 -> 4.7, k3 -> k2.6).
        if ident_minor and ref_minor and abs(ident_minor - ref_minor) > 1:
            return None
        return 1
    # Same numbers: any remaining word ('astra', 'flash') must also match, so
    # gpt-6-astra never matches gpt-6-sol.
    ident_words = tuple(t for t in ident_core if not t.isdigit())
    ref_words = tuple(t for t in ref_core if not t.isdigit())
    if ident_words and ref_words and ident_words != ref_words:
        return None
    return 0


def _quota_exhausted(connection: dict) -> bool:
    """True when a subscription account is at its session/5h cap.

    Codex and friends report a per-account pool where `usage` is the percentage
    of the rolling window already consumed. OmniRoute drops such accounts in a
    pre-dispatch filter and answers 503, so a live connection with an exhausted
    quota is not a usable route.
    """
    pool = connection.get('codexAccountPool')
    if not isinstance(pool, dict):
        return False
    aggregate = pool.get('aggregate')
    if isinstance(aggregate, dict) and aggregate.get('status') not in (None, 'available'):
        return True
    for child in pool.get('children') or []:
        if not isinstance(child, dict) or child.get('unavailable'):
            continue
        quota = child.get('quota') or {}
        windows = quota.get('windows') or {}
        for window in windows.values():
            if isinstance(window, dict) and window.get('usedPercentage') is not None:
                try:
                    if float(window['usedPercentage']) >= 100.0:
                        return True
                except (TypeError, ValueError):
                    continue
    return False


def _get_json(path: str, token: str) -> dict:
    import urllib.request
    request = urllib.request.Request(_BASE + path, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read())


def load_resources(token: str | None = None) -> dict:
    """Combos (authoritative), connections and catalog hints. Never raises."""
    key = token if token is not None else os.environ.get('OMNIROUTE_API_KEY', '')
    if not key:
        return {'ok': False, 'reason': 'management_credentials_unavailable'}
    try:
        combos = _get_json('/api/combos', key).get('combos')
    except Exception as exc:
        return {'ok': False, 'reason': 'combos_unavailable', 'error_type': type(exc).__name__}
    if not isinstance(combos, list):
        return {'ok': False, 'reason': 'invalid_combos_shape'}
    connections: dict[str, dict] = {}
    reason = ''
    try:
        for connection in _get_json('/api/providers', key).get('connections') or []:
            if not isinstance(connection, dict):
                continue
            name = str(connection.get('provider') or '')
            if not name:
                continue
            active = connection.get('isActive') is True
            test = str(connection.get('testStatus') or '')
            exhausted = _quota_exhausted(connection)
            # isActive stays true while a subscription sits at its session cap;
            # OmniRoute filters such an account before dispatch, so an active
            # flag alone would wrongly report the route as usable.
            usable = active and not exhausted
            current = connections.get(name)
            if current is None or (current['usable'] is False and usable):
                connections[name] = {'active': active, 'usable': usable,
                                     'quota_exhausted': exhausted,
                                     'test_status': test,
                                     'trusted_test': test in _TRUSTED_TEST}
    except Exception as exc:
        reason = 'connections_unavailable:' + type(exc).__name__
    catalog: set[str] = set()
    try:
        for model in _get_json('/api/models', key).get('models') or []:
            if isinstance(model, dict) and model.get('available'):
                catalog.add(str(model.get('fullModel') or ''))
    except Exception:
        pass
    return {'ok': True, 'reason': reason, 'combos': combos,
            'connections': connections, 'catalog_available': catalog}


def resolve_identity(identity: str, resources: dict) -> dict:
    """Map one identity to every provider a live combo routes its family to."""
    if not resources.get('ok'):
        return {'identity': identity, 'resolved': False, 'providers': [],
                'usable_providers': [], 'usable_count': 0, 'free_references': [],
                'combos': {}, 'reason': resources.get('reason', 'resources_unavailable')}
    connections = resources.get('connections') or {}

    # provider -> tier -> reference
    found: dict[str, dict[int, list[str]]] = {}
    combos: dict[str, list[str]] = {}
    for combo in resources.get('combos') or []:
        if not isinstance(combo, dict):
            continue
        combo_name = str(combo.get('name') or '')
        for member in combo.get('models') or []:
            if not isinstance(member, dict):
                continue
            reference = str(member.get('model') or '')
            tier = classify(identity, reference)
            if tier is None:
                continue
            provider = str(member.get('providerId') or
                           (reference.split('/', 1)[0] if '/' in reference else ''))
            if not provider:
                continue
            tiers = found.setdefault(provider, {})
            if reference not in tiers.setdefault(tier, []):
                tiers[tier].append(reference)
            if combo_name and provider not in combos.setdefault(combo_name, []):
                combos[combo_name].append(provider)

    providers: list[dict] = []
    for provider, tiers in found.items():
        connection = connections.get(provider) or {}
        providers.append({
            'provider': provider,
            'active': bool(connection.get('active')),
            'usable': bool(connection.get('usable')),
            'quota_exhausted': bool(connection.get('quota_exhausted')),
            'connection_test': connection.get('test_status', 'unobserved'),
            'exact': sorted(tiers.get(0, [])),
            'family_only': sorted(tiers.get(1, [])),
            'references': sorted(tiers.get(0, [])) + sorted(tiers.get(1, [])),
        })
    # Deterministic: active first, then exact-version before family-only.
    providers.sort(key=lambda p: (not p.get('usable'),
                                  0 if p['exact'] else 1,
                                  p['provider']))

    usable = [p for p in providers if p.get('usable')]
    exact_usable = [p['provider'] for p in usable if p['exact']]
    free = [ref for p in providers for ref in p['references'] if ref.endswith(':free')]
    return {
        'identity': identity,
        'resolved': bool(providers),
        'providers': providers,
        'usable_providers': [p['provider'] for p in usable],
        'usable_count': len(usable),
        'exact_usable_providers': exact_usable,
        'inactive_providers': [p['provider'] for p in providers if not p['active']],
        'free_references': free,
        'combos': {name: sorted(v) for name, v in sorted(combos.items())},
        'ordering': 'active first, then exact version before other family versions',
        'reason': '' if providers else 'identity_not_served_by_any_combo',
    }


def map_recommendations(recommendations: dict, resources: dict) -> dict:
    """recommendations: {category: [{'model':..,'reasoning_effort':..}]}."""
    result = {'schema_version': 'omh_provider_mapping/v4',
              'resources_ok': bool(resources.get('ok')),
              'resources_reason': resources.get('reason', ''),
              'categories': {}}
    for category, rows in (recommendations or {}).items():
        entries = []
        for row in rows or []:
            identity = row.get('model') if isinstance(row, dict) else row
            if not identity:
                continue
            mapped = resolve_identity(identity, resources)
            if isinstance(row, dict):
                mapped['reasoning_effort'] = row.get('reasoning_effort')
            entries.append(mapped)
        result['categories'][category] = entries
    return result
