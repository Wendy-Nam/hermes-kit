# Test-only: send Command Code traffic to the local fake endpoint. Loaded via PYTHONPATH.
FAKE = 'http://127.0.0.1:8099/v1'
try:
    import hermes_cli.runtime_provider as rp
    _orig = rp.resolve_runtime_provider
    def resolve_runtime_provider(*a, **kw):
        if 'commandcode' in str(kw.get('explicit_base_url') or ''):
            kw['explicit_base_url'] = FAKE
        return _orig(*a, **kw)
    rp.resolve_runtime_provider = resolve_runtime_provider
except Exception:
    pass
