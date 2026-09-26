"""hermes-kit /setup — Discord-only key entry, verification and application.

A non-developer should never paste a key into a chat window: it would land in the session log and
the model's context. This plugin takes keys through a Discord modal, checks them against the
provider, and only then writes them to .env. No LLM is involved in any of it.
"""
import logging

log = logging.getLogger(__name__)


def register(ctx):
    """Entry point. Everything Discord-specific lives in discord_ui, which imports discord."""
    from discord_ui import build

    ctx.register_platform_handler("discord", build)
