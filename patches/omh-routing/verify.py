#!/usr/bin/env python3
"""Scenario checks for OMH routing. Read-only; makes no model calls.

Answers one question per scenario: if Hermes asked OMH to route this category,
would the first model it tries actually have a live provider?
"""
from __future__ import annotations

import importlib
import sys

sys.path.insert(0, "/opt/data/plugins")
sys.path.insert(0, "/opt/data/plugins/omh")

import omh_provider_mapper as MAP  # noqa: E402

try:
    OMH = importlib.import_module("omh.hermes_delegation")
except ModuleNotFoundError:
    # OMH is optional and may not be installed yet. Importing at module scope used
    # to raise, so the caller saw a traceback instead of a report, and a missing
    # OMH looked like a broken gateway. Exit 2 is the "cannot read the gateway"
    # signal the caller already distinguishes.
    print("OMH is not installed; run the kit's OMH setup first.")
    raise SystemExit(2)


def main() -> int:
    resources = MAP.load_resources()
    if not resources.get("ok"):
        print("resources unavailable:", resources.get("reason"))
        return 2
    chains = OMH.effective_mixture_category_chains("/opt/data/.omh", "/opt/data")
    routes, _ = OMH.load_model_provider_routes("/opt/data/.omh")
    print("resources: ok  combos=%d  connections=%d"
          % (len(resources["combos"]), len(resources["connections"])))
    print()
    print("%-20s %-26s %-34s %s" % ("category", "alias", "address", "live providers"))
    print("-" * 100)
    dead_first = []
    for category in sorted(chains):
        for position, (alias, effort) in enumerate(chains[category]):
            mapped = MAP.resolve_identity(alias, resources)
            address = routes.get(alias)
            address_text = address[1] if address else "?"
            providers = ",".join(mapped["usable_providers"]) or "-none-"
            marker = ""
            if position == 0 and mapped["usable_count"] == 0:
                marker = "  <== FIRST CHOICE HAS NO LIVE PROVIDER"
                dead_first.append(category)
            print("%-20s %-26s %-34s %s%s"
                  % (category if position == 0 else "", alias, address_text, providers, marker))
    print()
    if dead_first:
        print("RESULT: %d categor(ies) lose a turn before reaching a live model: %s"
              % (len(dead_first), ", ".join(sorted(set(dead_first)))))
        return 1
    print("RESULT: every category's first choice has a live provider.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
