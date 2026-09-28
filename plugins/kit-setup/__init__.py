"""hermes-kit /setup — Discord-only key entry, verification and application.

A non-developer should never paste a key into a chat window: it would land in the session log and
the model's context. This plugin takes keys through a Discord modal, checks them against the
provider, and only then writes them to .env. No LLM is involved in any of it.
"""
import logging
import os
import sys

# The loader imports this folder as the package hermes_plugins.kit_setup, but every module here
# uses flat sibling imports (from discord_ui import build), as bootstrap.py does when run as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

log = logging.getLogger(__name__)


def register(ctx):
    """Entry point. Everything Discord-specific lives in discord_ui, which imports discord."""
    from discord_ui import build

    ctx.register_platform_handler("discord", build)
