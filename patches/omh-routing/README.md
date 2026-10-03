# Hermes custom patches — OMH routing

Re-appliable after an OMH update. OMH ships its own copies of every file below
under `/opt/data/plugins/omh/`, so an update overwrites them. Re-run
`./apply.sh` afterwards to restore this behaviour.

## What each patch does and why

### 1. `omh_provider_mapper.py` -> `/opt/data/plugins/omh/omh_provider_mapper.py`
Resolves an OMH recommended model *identity* (`kimi-k3`, `gpt-6-astra`) onto
the providers OmniRoute actually serves, read from `/api/combos`. Never invents
an identity and never substitutes a different model: `gpt-6-astra` does not
match `gpt-6-sol`, and a version change is reported as a lower tier rather than
silently swapped.

Read-only. It computes; it does not write.

### 2. `route_readiness.py` -> `/opt/data/plugins/omh/route_readiness.py`
Bounded management snapshots with a 30s TTL and 0.8s timeout, so a slow or
absent OmniRoute cannot stall a delegation. Unknown or stale evidence stays
`unknown` and is never treated as proven unavailable.

### 3. `public_free_routing.py` -> `/opt/data/plugins/omh/public_free_routing.py`
Keeps public/free routing separate from private subscription routing.

### 4. `providers.json` (data, not code)
`/opt/data/.omh/routing/providers.json` is the entitlement document. OMH reads it
to decide which candidates this machine can actually serve, and it silently
mispredicts in two directions:

  - a provider listed in `excluded_providers` is demoted even when it works;
  - a provider missing from `providers` cannot be reasoned about at all.

`apply.sh` installs a minimal template that names only the gateway. **Add the
connections you actually hold.** An entry whose provider is idle costs nothing,
but an entry for a live connection you forgot to declare means OMH will not
prefer it.

### 5. Quota-aware availability (`route_readiness.py`)
A subscription account reports `isActive: true` while its rolling-window quota is
spent. OmniRoute drops such an account in a pre-dispatch filter and answers 429,
so readiness that trusts the active flag alone reports a dead route as healthy:
the first choice in a chain is returned, the turn is spent on it, and nothing
falls through to the next candidate. `_quota_exhausted()` reads the account
pool so a spent window counts as unavailable **at route time**, which is what
makes the chain move on before the request is spent rather than after.

Only a definite 100% reading counts. An absent, null or malformed window stays
`unknown`, because missing evidence must never be read as unavailability.

## Ordering

Routing effectiveness depends on entitlement ordering: a category whose first
choice has no live provider loses a turn before reaching a live fallback. See
`verify.py` for the current per-category live-provider report.

## Roll back

`/opt/data/.backups/` holds copies taken before each change. `apply.sh --dry-run`
prints the diff without writing.
