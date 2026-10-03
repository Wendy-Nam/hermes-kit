"""Operator-owned free category overrides, merged only after public-session proof."""
from __future__ import annotations
import json
import re
from pathlib import Path

SCHEMA = 'public_free_routing/v1'
_TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$')
_EFFORTS = {'low','medium','high','xhigh','max','ultra','minimal'}
_MAX_BYTES = 65536
_SHARED_OMH_HOME = Path('/opt/data/.omh')


def parse_public_free_document(document, known_categories):
    if not isinstance(document, dict) or document.get('schema_version') != SCHEMA:
        raise ValueError('invalid_public_free_schema')
    if set(document) - {'schema_version','categories','routes'}:
        raise ValueError('unknown_public_free_fields')
    categories, routes = document.get('categories'), document.get('routes')
    if not isinstance(categories, dict) or not isinstance(routes, dict) or len(routes) > 32:
        raise ValueError('invalid_public_free_routes')
    parsed_routes = {}
    for alias, route in routes.items():
        if not isinstance(alias,str) or not _TOKEN.fullmatch(alias) or not isinstance(route,dict) or set(route) != {'provider','model'}:
            raise ValueError('invalid_public_free_route')
        model = route.get('model')
        if route.get('provider') != 'omniroute' or not isinstance(model,str) or not _TOKEN.fullmatch(model) or not model.startswith('public-model-'):
            raise ValueError('public_free_route_requires_guarded_combo')
        parsed_routes[alias] = ('omniroute', model)
    parsed_chains = {}
    for category, entries in categories.items():
        if category not in known_categories or not isinstance(entries,list) or not 1 <= len(entries) <= 8:
            raise ValueError('invalid_public_free_category')
        chain = []
        for entry in entries:
            if not isinstance(entry,dict) or set(entry) != {'model','reasoning_effort'}:
                raise ValueError('invalid_public_free_chain_entry')
            alias, effort = entry.get('model'), entry.get('reasoning_effort')
            if not isinstance(alias,str) or alias not in parsed_routes or effort not in _EFFORTS:
                raise ValueError('unmapped_public_free_alias')
            if any(a == alias for a,_ in chain):
                raise ValueError('duplicate_public_free_alias')
            chain.append((alias,effort))
        parsed_chains[category] = tuple(chain)
    return parsed_chains, parsed_routes


def apply_public_free_overrides(chains, routes, omh_home, is_public):
    if not is_public:
        return chains, routes, {'status':'not_public'}
    path = Path(omh_home) / 'routing' / 'free-category-chains.json'
    # Public profile homes can inherit the one operator-owned shared policy.
    # An explicit profile file (including invalid/symlink files) wins or fails closed.
    if not path.exists() and not path.is_symlink():
        path = _SHARED_OMH_HOME / 'routing' / 'free-category-chains.json'
    try:
        if path.is_symlink():
            raise ValueError('public_free_symlink_refused')
        with path.open('rb') as stream:
            data = stream.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            raise ValueError('public_free_document_too_large')
        overrides, extra_routes = parse_public_free_document(json.loads(data), chains)
    except FileNotFoundError:
        return chains, routes, {'status':'not_configured'}
    except Exception as exc:
        return chains, routes, {'status':'invalid','error_type':type(exc).__name__}
    # Never rewrite an existing identity mapping, even within public mode.
    if any(alias in routes and routes[alias] != route for alias,route in extra_routes.items()):
        return chains, routes, {'status':'invalid','error_type':'AliasConflict'}
    return {**chains,**overrides}, {**routes,**extra_routes}, {
        'status':'applied','categories':sorted(overrides),'source_path':str(path),
        'evidence_boundary':'Operator free-route policy; actual entitlement, price and task quality require their own evidence.'}
