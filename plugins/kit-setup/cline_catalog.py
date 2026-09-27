"""On-demand public Cline price inspection. Never registers accounts or changes routes."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import time
import urllib.request

CATALOG_URL = "https://api.cline.bot/api/v1/ai/cline/models"
DEFAULT_MAX_AGE = 900
MAX_AGE_LIMIT = 3600
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class CatalogError(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CatalogError("Catalog redirect refused")


def price_status(row):
    """zero_advertised means all published fields zero, not a billing guarantee."""
    prices = row.get("pricing") if isinstance(row, dict) else None
    if not isinstance(prices, dict) or not {"prompt", "completion"} <= prices.keys():
        return "unknown"
    try:
        values = []
        for value in prices.values():
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                return "unknown"
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                return "unknown"
            values.append(number)
        return "positive" if any(values) else "zero_advertised"
    except (InvalidOperation, ValueError, TypeError):
        return "unknown"


def cache_price_status(row):
    """Absent cache-read or cache-write prices remain explicitly unknown."""
    prices = row.get("pricing") if isinstance(row, dict) else None
    if not isinstance(prices, dict):
        return "unknown"
    if not {"input_cache_read", "input_cache_write"} <= prices.keys():
        return "unknown"
    cache = {key: value for key, value in prices.items() if "cache" in key.lower()}
    return price_status({"pricing": {"prompt": 0, "completion": 0, **cache}})


def make_snapshot(payload, checked_at):
    """Validate already-read public data without network or filesystem effects."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str)
        or not row["id"].strip() for row in rows
    ):
        raise CatalogError("Invalid public model catalog")
    if isinstance(checked_at, bool) or not isinstance(checked_at, (int, float)) or not math.isfinite(checked_at):
        raise CatalogError("Invalid price check time")
    # Copy only public model/price metadata needed here, not arbitrary response fields.
    return {"source": CATALOG_URL, "checked_at": checked_at,
            "models": [{"id": row["id"], "pricing": copy.deepcopy(row.get("pricing"))}
                       for row in rows]}


def fetch_catalog():
    """One bounded unauthenticated GET, only when explicitly called."""
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        request = urllib.request.Request(CATALOG_URL, headers={"Accept": "application/json"})
        with opener.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CatalogError("Catalog too large")
        return make_snapshot(json.loads(raw), time.time())
    except Exception:
        # Do not reflect HTTP response bodies, credentials, or transport exception text.
        raise CatalogError("Public Cline pricing could not be verified; no route changes proposed") from None


def inspect_catalog(snapshot, *, now=None, max_age=DEFAULT_MAX_AGE):
    """Return per-ID pricing evidence; reject stale/future/invalid snapshots."""
    now = time.time() if now is None else now
    if (isinstance(max_age, bool) or not isinstance(max_age, (int, float))
            or not math.isfinite(max_age) or not 0 < max_age <= MAX_AGE_LIMIT):
        raise CatalogError("Price maximum age must be between 0 and 3600 seconds")
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
        raise CatalogError("Invalid current time")
    if not isinstance(snapshot, dict) or snapshot.get("source") != CATALOG_URL:
        raise CatalogError("Unknown catalog source")
    valid = make_snapshot({"data": snapshot.get("models")}, snapshot.get("checked_at"))
    if not 0 <= now - valid["checked_at"] <= max_age:
        raise CatalogError("Price evidence expired or has a future timestamp; refresh explicitly")
    grouped = {}
    for row in valid["models"]:
        grouped.setdefault(row["id"], []).append(row)
    result = {}
    for mid, rows in grouped.items():
        statuses = [price_status(row) for row in rows]
        status = ("positive" if "positive" in statuses else
                  "unknown" if "unknown" in statuses else "zero_advertised")
        cache = [cache_price_status(row) for row in rows]
        result[mid] = {"status": status,
                       "cache_price_status": ("positive" if "positive" in cache else
                                              "unknown" if "unknown" in cache else "zero_advertised"),
                       "pricing": [row["pricing"] for row in rows],
                       "checked_at": valid["checked_at"]}
    return result


def _cline_model_id(entry):
    """Resolve routed strings and native IDs with explicit provider metadata.

    Provider names and model namespaces are different: Cline can itself expose
    an ID such as openrouter/free. Never infer a routing provider from a native
    namespace. Contradictory explicit routing metadata is rejected.
    """
    mid = entry if isinstance(entry, str) else entry.get("model") if isinstance(entry, dict) else None
    if not isinstance(mid, str) or not mid.strip() or mid != mid.strip():
        raise CatalogError("Invalid model entry")
    providers = set()
    if isinstance(entry, dict):
        for field in ("provider", "providerId"):
            value = entry.get(field)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise CatalogError("Invalid provider metadata")
            providers.add(value.strip().lower())
    if len(providers) > 1:
        raise CatalogError("Conflicting provider metadata")
    provider = next(iter(providers), None)
    routed_cline = mid.split("/", 1)[0].lower() == "cline" and "/" in mid
    if routed_cline:
        if provider not in (None, "cline"):
            raise CatalogError("Cline model prefix conflicts with provider metadata")
        native = mid.split("/", 1)[1]
        if not native:
            raise CatalogError("Invalid Cline model ID")
        return native
    return mid if provider == "cline" else None


def propose_removals(models, snapshot, *, now=None, max_age=DEFAULT_MAX_AGE):
    """Pure proposal: preserve input and flag positive/unknown Cline entries only.

    Retained zero-advertised entries still require account entitlement and a tool
    round-trip test. Caller must obtain authorization and fresh route state before
    applying any proposal. A stale catalog raises, rather than removing everything.
    """
    evidence = inspect_catalog(snapshot, now=now, max_age=max_age)
    keep, remove = [], []
    for entry in models:
        native = _cline_model_id(entry)
        row = evidence.get(native) if native is not None else None
        if native is not None and (row is None or row["status"] != "zero_advertised"):
            remove.append({"entry": copy.deepcopy(entry), "reason": row["status"] if row else "unknown"})
        else:
            keep.append(copy.deepcopy(entry))
    return {"retained": keep, "proposed_removals": remove, "checked_at": snapshot["checked_at"],
            "applied": False}


def main():
    parser = argparse.ArgumentParser(description="Explicitly fetch public Cline zero-price candidates; no account or route changes")
    parser.add_argument("--list", action="store_true", help="Fetch current public pricing once")
    args = parser.parse_args()
    if not args.list:
        parser.print_help()
        return 0
    try:
        snapshot = fetch_catalog()
        evidence = inspect_catalog(snapshot)
        print(json.dumps({"source": CATALOG_URL,
                          "pricing_checked_at": datetime.fromtimestamp(snapshot["checked_at"], timezone.utc).isoformat(),
                          "notice": "Zero advertised prices only; missing cache prices are unknown. Account access, modality and tool calls are untested.",
                          "candidates": [{"id": mid, **row} for mid, row in evidence.items()
                                         if row["status"] == "zero_advertised"]}, ensure_ascii=False, indent=2))
        return 0
    except CatalogError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
