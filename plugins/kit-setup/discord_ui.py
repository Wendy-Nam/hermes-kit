"""The /setup flow, end to end, inside Discord.

Two rules shape everything here:

1. A key is never echoed, logged, or put in a message. Modals are the only input path, and the
   values go straight from the modal into a validator and then into .env.
2. Nothing is saved unless every key in the pack verified. A half-configured pack is worse than
   an unconfigured one, because the student will not know which half is the broken half.

Commands are registered per guild on purpose. The gateway snapshots the *global* command tree for
its safe sync a few ms before plugin factories run, so a globally-added command silently misses
the sync (spike S2). Guild commands apply immediately and never collide with that reconcile.
"""
import asyncio
import logging
import os
import signal
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# discord is a Hermes dependency, present in the gateway process, but not in the test runner or
# during image build. Importing it here (not at module top) keeps this file importable anywhere.
try:
    import discord
    from discord import app_commands
except ImportError:      # pragma: no cover - only hit outside the gateway
    discord = None
    app_commands = None


HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("HERMES_HOME") or os.environ.get("HERMES_DATA") or "/opt/data")
ENV_FILE = DATA / ".env"
PENDING = DATA / ".kit-pending-greeting"   # consumed on the next boot to greet in the home channel
HERMES = "/opt/hermes/.venv/bin/hermes"

TICK, CROSS = "✅", "❌"



def _env():
    from env_store import get_env
    return get_env(ENV_FILE)


def _write(values: dict, config: dict) -> None:
    """Persist keys, then config. Either both happen or the student is told nothing was saved."""
    from env_store import set_env

    set_env(ENV_FILE, values)
    for k, v in config.items():
        if "${" in str(v):       # a value that refers back to an env var keeps that reference
            continue
        subprocess.run([HERMES, "config", "set", k, str(v), "--force"],
                       capture_output=True, text=True, timeout=60, check=False)


async def _verify(entries) -> list[tuple[str, bool, str]]:
    """Validate a pack's keys concurrently — a pack is a few seconds, not a few minutes.

    `entries` is [(KeySpec, value)]; values are passed straight to the validator and are never
    stored anywhere but the validator call and (on success) .env.
    """
    import validators as v

    async def one(spec, value):
        return spec.env, await asyncio.to_thread(v.VALIDATORS[spec.validator], value)

    results = await asyncio.gather(*(one(s, val) for s, val in entries), return_exceptions=True)
    out = []
    for r in results:
        if isinstance(r, Exception):
            out.append(("?", False, f"검증 중 오류: {type(r).__name__}"))
        else:
            env_name, (ok, msg) = r
            out.append((env_name, ok, msg))
    return out


def _apply(entries, config) -> list[str]:
    """Write a verified pack. Returns human-readable status lines (never the values)."""
    lines = []
    _write({spec.env: val for spec, val in entries}, config)
    for spec, _ in entries:
        lines.append(f"{TICK} {spec.label} 저장")
    for k in config:
        lines.append(f"{TICK} 설정 적용: {k}")
    return lines


def restart_gateway() -> bool:
    """TERM the gateway and let s6 restart it (~5s, measured in spike S4).

    Only used after an explicit button press, never during a modal submit.
    """
    try:
        out = subprocess.run(["pgrep", "-f", "hermes gateway run"],
                             capture_output=True, text=True, timeout=10).stdout.split()
        for pid in out:
            os.kill(int(pid), signal.SIGTERM)
        return bool(out)
    except Exception:
        log.exception("gateway restart failed")
        return False




async def setup_command(interaction, packs_list, kits_list, bot):
    """`/setup` — owner-only, approves the owner, then walks the student through the packs."""
    import owner as owner_mod
    from packs import missing_keys
    from views import HomeView
    import validators as v

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("서버에서만 실행할 수 있습니다.", ephemeral=True)
        return
    if interaction.user.id != guild.owner_id and not owner_mod.is_approved(interaction.user.id):
        await interaction.response.send_message(
            "이 서버의 소유자만 실행할 수 있습니다.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    registered = owner_mod.ensure_owner(interaction.user.id, interaction.user.name)
    note = "주인으로 등록했어요." if registered else "이미 주인으로 등록되어 있어요."

    token = _env().get("DISCORD_BOT_TOKEN", "")
    invite = None
    if token:
        invite, err = owner_mod.configure_app(token)
        if err:
            log.warning("discord app configuration failed: %s", err)


    waiting = missing_keys(packs_list, _env())
    head = [note, ""]
    if invite:
        head.append(f"1️⃣ 아래 링크로 이 서버에 봇을 초대해 주세요 (권한은 자동으로 계산됩니다):\n{invite}\n")
    else:
        head.append("1️⃣ 봇 토큰(DISCORD_BOT_TOKEN)이 없어 초대 링크를 만들지 못했습니다. "
                    "compose의 DISCORD_BOT_TOKEN을 확인해 주세요.\n")
    head.append("2️⃣ 아래 버튼으로 키를 입력해 주세요. 입력 즉시 확인하고, **전부 통과해야** 저장됩니다."
                if waiting else
                "2️⃣ 필요한 키가 모두 있습니다. 그대로 적용해도 됩니다.")

    view = HomeView(packs_list, channel_id=interaction.channel_id)
    await interaction.followup.send("\n".join(head), view=view, ephemeral=True)


def build(bot, adapter):
    """Factory passed to ctx.register_platform_handler("discord", build).

    Guild-scoped registration with our own sync — see the module docstring for why (spike S2).
    """
    import discord as dc
    from discord import app_commands
    from views import HomeView   # imported here, not at module level: it needs discord.py

    import validators as v
    from packs import load_kits, load_packs

    try:
        packs_list, kits_list = load_packs(v.VALIDATORS), load_kits()
    except Exception:
        log.exception("kit-setup: pack definitions are invalid — /setup is disabled")
        return

    async def setup(interaction: dc.Interaction):
        await setup_command(interaction, packs_list, kits_list, bot)

    commands = [app_commands.Command(name="setup",
                                     description="키 입력 · 검증 · 적용 (서버 소유자 전용)",
                                     callback=setup)]

    async def sync_guild(guild):
        for cmd in commands:
            bot.tree.add_command(cmd, guild=guild, override=True)
        synced = await bot.tree.sync(guild=guild)
        log.info("kit-setup: guild %s synced %d command(s)", guild.id, len(synced))

    async def sync_all():
        await bot.wait_until_ready()
        for guild in bot.guilds:
            try:
                await sync_guild(guild)
            except Exception:
                log.exception("kit-setup: guild sync failed")

    async def on_guild_join(guild):
        await sync_guild(guild)

    async def greet_after_restart():
        """Say 'ready' in the home channel once the bot comes back from an apply-restart."""
        if not PENDING.exists():
            return
        channel_id = PENDING.read_text(encoding="utf-8").strip()
        PENDING.unlink(missing_ok=True)
        await bot.wait_until_ready()
        channel = bot.get_channel(int(channel_id)) if channel_id.isdigit() else None
        if channel is None:
            log.info("kit-setup: home channel %s not available after restart", channel_id)
            return
        await channel.send("준비 끝! 이제 질문을 해 보세요. 다시 설정하려면 `/setup`을 실행하세요.")

    bot.add_listener(on_guild_join, "on_guild_join")
    asyncio.get_event_loop().create_task(sync_all())
    asyncio.get_event_loop().create_task(greet_after_restart())
    log.info("kit-setup: guild-scoped /setup registered")

