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


def _read_config() -> dict:
    """The current config, flattened to "a.b.c" -> value.

    Read straight from config.yaml rather than shelling out per key: this runs on every pack
    apply, and one `hermes config get` per setting is a round trip nobody needs.
    """
    import yaml

    try:
        doc = yaml.safe_load((DATA / "config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    except Exception:
        return {}          # a malformed config must not block a pack apply
    return _flatten(doc) if isinstance(doc, dict) else {}


def _flatten(doc, prefix=()):
    out = {}
    for k, v in doc.items():
        key = prefix + (str(k),)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[".".join(key)] = v
    return out


def _write(values: dict, config: dict) -> list[str]:
    """Persist keys, then config. Returns a line per config key, naming any that failed.

    Keys first, then config: if this raises, the key is saved and the student is told the save
    failed — the reverse order would leave a key-less config pointing at a key that is not there.
    """
    from env_store import set_env

    set_env(ENV_FILE, values)
    from config_store import write
    try:
        write(ENV_FILE.parent, config)
        return [f"{TICK} 설정 적용: {k}" for k in config]
    except Exception:
        return [f"{CROSS} 설정 적용 실패: {k} — 키는 저장됐지만 설정은 반영되지 않았습니다" for k in config]


async def _verify(entries) -> list[tuple[str, bool, str]]:
    """Validate a pack's keys concurrently — a pack is a few seconds, not a few minutes.

    `entries` is [(KeySpec, value)]; values are passed straight to the validator and are never
    stored anywhere but the validator call and (on success) .env.
    """
    import validators as v

    async def one(spec, value):
        return spec.env, await asyncio.to_thread(v.VALIDATORS[spec.validator], value)

    proxy_names = {"WEBSHARE_PROXY_USERNAME", "WEBSHARE_PROXY_PASSWORD"}
    proxy_entries = {s.env: val for s, val in entries if s.env in proxy_names}
    if proxy_entries:
        ok, msg = await asyncio.to_thread(v.webshare_credentials,
            proxy_entries.get("WEBSHARE_PROXY_USERNAME", ""), proxy_entries.get("WEBSHARE_PROXY_PASSWORD", ""))
        return [(name, ok, msg) for name in sorted(proxy_names)]
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
    lines = [f"{TICK} {spec.label} 저장" for spec, _ in entries]
    lines += _write({spec.env: val for spec, val in entries}, config)
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

    # The bot is already in this server (the command came through it), so no invite step here.
    # Intents and install params are set at boot by bootstrap.configure_app. A student who cannot
    # find the boot log line is told about /invite rather than left hunting through container logs.
    from views import WizardView, wizard_text
    view = WizardView(packs_list, channel_id=interaction.channel_id, owner_id=interaction.user.id)
    head = [note, "", wizard_text(view.status),
            "", "로그에서 `[kit] 봇 초대:` 링크를 못 찾았거나 다른 서버에 다시 초대하려면 `/invite` 를 사용하세요."]
    await interaction.followup.send("\n".join(head), view=view, ephemeral=True)


async def invite_command(interaction, data_dir: Path):
    """`/invite` — reprint the invite link when the boot log line is gone.

    Registered on the same terms as /setup: the person who owns the server is the person who
    may add the bot, and the link is the only way into a fresh server. The message is ephemeral
    so a link never sits in a channel a student shares by screenshot.
    """
    import owner as owner_mod

    # Same terms as /setup, checked the same way. A `guild is not None and …` guard would skip
    # the check entirely in a DM, and this command PATCHes the Discord application.
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("서버에서만 실행할 수 있습니다.", ephemeral=True)
    if interaction.user.id != guild.owner_id and not owner_mod.is_approved(interaction.user.id):
        return await interaction.response.send_message(
            "이 서버의 소유자만 실행할 수 있습니다.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    url, note = await asyncio.to_thread(owner_mod.invite_link, data_dir)
    if not url:
        body = "\n".join(p for p in (note, "링크를 만들지 못했습니다. 위 안내대로 직접 만들어 주세요.") if p)
    else:
        # The URL goes first and is never truncated. A link cut in half is worse than no link:
        # it looks clickable and lands on a 404, so the student blames the kit.
        room = 1900 - len(url) - 2
        parts = [url] + ([note[:room]] if room > 0 and note else [])
        body = "\n\n".join(parts)
    await interaction.followup.send(body[:1900], ephemeral=True)


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

    import doctor as doctor_mod

    async def doctor(interaction: dc.Interaction):
        await doctor_mod.doctor_command(interaction, DATA, ENV_FILE)

    async def invite(interaction: dc.Interaction):
        await invite_command(interaction, DATA)

    commands = [
        app_commands.Command(name="setup", description="키 입력 · 검증 · 적용 (서버 소유자 전용)",
                             callback=setup),
        app_commands.Command(name="doctor", description="무엇이 안 되는지 스스로 진단 (키는 가려짐)",
                             callback=doctor),
        app_commands.Command(name="invite", description="봇 초대 링크 다시 보기 (로그를 못 찾았을 때)",
                             callback=invite),
    ]

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
        await channel.send("설정을 적용하고 다시 연결했습니다. 질문을 해 보세요. 상태 확인은 `/doctor`, 변경은 `/setup`입니다.")

    bot.add_listener(on_guild_join, "on_guild_join")
    asyncio.get_event_loop().create_task(sync_all())
    asyncio.get_event_loop().create_task(greet_after_restart())
    log.info("kit-setup: guild-scoped /setup registered")

