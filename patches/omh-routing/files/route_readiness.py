"""Bounded management snapshots; configured connections are not model capability proof.

Only a fresh, completely known all-inactive route is rejected. Missing, stale,
unsupported or malformed observations remain explicit unknowns. No inference calls.
"""
from __future__ import annotations
import json
import os
import threading
import time
from urllib.request import Request, urlopen

_BASE = 'http://omniroute:20128'
_TTL = 30.0
_TIMEOUT = 0.8
_MAX_BYTES = 2_000_000
_CACHE = None
_CACHE_AT = 0.0
_LOCK = threading.Lock()
_BOUNDARY = 'Connection configuration only; quota, model entitlement, tool behavior and task success are not verified.'


def sanitize_snapshot(combos, providers):
    if not isinstance(combos, dict) or not isinstance(providers, dict):
        raise ValueError('invalid_management_shape')
    cs, ps = combos.get('combos'), providers.get('connections')
    if not isinstance(cs, list) or not isinstance(ps, list):
        raise ValueError('invalid_management_lists')
    result = {'combos': {}, 'connections': [], 'fresh': True, 'observed_at': time.time()}
    for c in cs:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str):
            raise ValueError('invalid_combo')
        models = c.get('models')
        if not isinstance(models, list):
            raise ValueError('invalid_combo_models')
        result['combos'][c['name']] = [
            {k: v for k, v in m.items() if k in {'kind','model','provider','providerId','connectionId','combo','comboId'} and isinstance(v, str)}
            if isinstance(m, dict) else {} for m in models]
    for p in ps:
        if not isinstance(p, dict) or not isinstance(p.get('provider'), str):
            raise ValueError('invalid_connection')
        data = p.get('providerSpecificData') or {}
        prefix = data.get('prefix') if isinstance(data, dict) else None
        result['connections'].append({'id': str(p.get('id') or ''),
            'provider': p['provider'], 'prefix': prefix if isinstance(prefix, str) else '',
            'active': p.get('isActive') if isinstance(p.get('isActive'), bool) else None,
            'test_status': str(p.get('testStatus') or ''),
            'quota_exhausted': _quota_exhausted(p)})
    return result


def _quota_exhausted(connection):
    """True when a subscription account sits at its rolling-window cap.

    A Codex-style login reports isActive=true while its session quota is spent.
    OmniRoute drops such an account in a pre-dispatch filter and answers 429, so
    treating the active flag alone as proof of availability made the first choice
    in a chain look healthy and cost the turn instead of falling through to the
    next candidate.

    Only a definite 100% reading counts. An absent, null or malformed window
    stays False, because unknown evidence must never be read as unavailability.
    """
    pool = connection.get('codexAccountPool')
    if not isinstance(pool, dict):
        return False
    aggregate = pool.get('aggregate')
    if isinstance(aggregate, dict):
        status = aggregate.get('status')
        if isinstance(status, str) and status not in ('', 'available'):
            return True
    children = pool.get('children')
    if not isinstance(children, list):
        return False
    for child in children:
        if not isinstance(child, dict) or child.get('unavailable') is True:
            continue
        quota = child.get('quota')
        windows = quota.get('windows') if isinstance(quota, dict) else None
        if not isinstance(windows, dict):
            continue
        for window in windows.values():
            if not isinstance(window, dict):
                continue
            value = window.get('usedPercentage')
            if value is None:
                continue
            try:
                if float(value) >= 100.0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _read_json(path, token):
    req = Request(_BASE + path, headers={'Authorization': 'Bearer ' + token})
    with urlopen(req, timeout=_TIMEOUT) as response:
        data = response.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError('management_response_too_large')
    return json.loads(data)


def readiness_snapshot():
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if _CACHE is not None and now - _CACHE_AT < _TTL:
        return _CACHE
    if not _LOCK.acquire(blocking=False):
        return {'fresh': False, 'reason': 'refresh_in_progress'}
    try:
        now = time.monotonic()
        if _CACHE is not None and now - _CACHE_AT < _TTL:
            return _CACHE
        token = os.environ.get('OMNIROUTE_API_KEY', '')
        if not token:
            result = {'fresh': False, 'reason': 'management_credentials_unavailable'}
        else:
            try:
                result = sanitize_snapshot(_read_json('/api/combos', token), _read_json('/api/providers', token))
            except Exception as exc:
                # Never expose a response, URL, token or exception text.
                result = {'fresh': False, 'reason': 'management_unavailable', 'error_type': type(exc).__name__}
        _CACHE, _CACHE_AT = result, time.monotonic()
        return result
    finally:
        _LOCK.release()


def route_eligibility(provider, model, snapshot):
    """Pure predicate. Refuse only known all-inactive members in a fresh snapshot."""
    result = {'state': 'unknown', 'evidence_boundary': _BOUNDARY}
    if provider != 'omniroute':
        return {**result, 'reason': 'outside_omniroute'}
    if not snapshot or not snapshot.get('fresh'):
        return {**result, 'reason': (snapshot or {}).get('reason', 'snapshot_unavailable')}
    result['observed_at'] = snapshot.get('observed_at')
    combos = snapshot.get('combos', {})
    connections = snapshot.get('connections', [])
    if model not in combos:
        return {**result, 'reason': 'combo_not_observed'}
    members = combos[model]
    if not members:
        return {**result, 'reason': 'empty_combo'}
    states = []
    for member in members:
        if member.get('kind') not in (None, '', 'model'):
            states.append('unknown')
            continue
        cid = member.get('connectionId')
        name = member.get('providerId') or member.get('provider') or str(member.get('model') or '').split('/', 1)[0]
        if not cid and not name:
            states.append('unknown')
            continue
        matched = [c for c in connections if (c.get('id') == cid if cid else name in {c.get('provider'),c.get('prefix')})]
        if not matched:
            states.append('unknown')
            continue
        # A live connection whose subscription window is spent cannot serve the
        # request: OmniRoute filters it before dispatch and answers 429. Count
        # it as unavailable so the chain falls through to its next candidate at
        # route time instead of spending the turn on it.
        serving = [c for c in matched if c.get('active') is True and not c.get('quota_exhausted')]
        blocked = [c for c in matched if c.get('quota_exhausted')]
        if serving:
            states.append('configured_active')
        elif blocked:
            states.append('quota_exhausted')
        elif all(c.get('active') is False for c in matched):
            states.append('unavailable')
        else:
            states.append('unknown')
    if 'configured_active' in states:
        return {**result, 'state': 'configured_active', 'reason': 'at_least_one_active_connection'}
    if states and all(s in {'unavailable', 'quota_exhausted'} for s in states):
        reason = ('all_observed_connections_quota_exhausted'
                  if 'quota_exhausted' in states else 'all_observed_connections_inactive')
        return {**result, 'state': 'unavailable', 'reason': reason}
    return {**result, 'reason': 'member_connection_unresolved'}
