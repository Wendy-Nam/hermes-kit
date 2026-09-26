"""Phase 0 spike — throwaway.

S2: can a plugin add a Discord app command that opens a Modal, via
    ctx.register_platform_handler("discord", factory(bot, adapter))?
S3: can the plugin approve the guild owner through gateway.pairing.PairingStore?

Finding (run 1): the gateway snapshots the *global* command tree for its safe sync a few ms
before plugin factories run, so globally-added commands miss the sync. The gateway only manages
global commands, so this plugin registers guild-scoped commands and syncs each guild itself
(guild commands apply instantly and never collide with the gateway's global reconcile).

Submitted values are never logged or echoed — only their length.
"""
import asyncio
import logging

log = logging.getLogger(__name__)


def register(ctx):
    ctx.register_platform_handler("discord", _build)


def _approved_ids(store):
    return {str(u.get("user_id") if isinstance(u, dict) else u) for u in store.list_approved("discord")}


def _build(bot, adapter):
    import discord
    from discord import app_commands

    class Probe(discord.ui.Modal, title="kit spike"):
        value = discord.ui.TextInput(label="아무 값 (테스트)", required=True)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.send_message(f"S2 ok: len={len(self.value.value)}", ephemeral=True)

    async def kitping(interaction: discord.Interaction):
        await interaction.response.send_modal(Probe())

    async def kitowner(interaction: discord.Interaction):
        g = interaction.guild
        if g is None or interaction.user.id != g.owner_id:
            await interaction.response.send_message("S3: 서버 소유자가 아님 → 거절", ephemeral=True)
            return
        from gateway.pairing import PairingStore

        store, uid = PairingStore(), str(interaction.user.id)
        already = uid in _approved_ids(store)
        approved_now = None
        if not already:
            code = store.generate_code("discord", uid, interaction.user.name)
            approved_now = bool(code and store.approve_code("discord", code))
        in_list = uid in _approved_ids(store)
        await interaction.response.send_message(
            f"S3: already={already} approved_now={approved_now} in_list={in_list}", ephemeral=True
        )

    commands = [
        app_commands.Command(name="kitping", description="hermes-kit spike: modal", callback=kitping),
        app_commands.Command(name="kitowner", description="hermes-kit spike: owner auto-approve", callback=kitowner),
    ]

    async def sync_guild(guild):
        for cmd in commands:
            bot.tree.add_command(cmd, guild=guild, override=True)
        synced = await bot.tree.sync(guild=guild)
        log.info("kitspike: guild %s synced %d command(s)", guild.id, len(synced))

    async def sync_all():
        await bot.wait_until_ready()
        for guild in bot.guilds:
            try:
                await sync_guild(guild)
            except Exception:
                log.exception("kitspike: guild sync failed")

    async def on_guild_join(guild):
        await sync_guild(guild)

    bot.add_listener(on_guild_join, "on_guild_join")
    asyncio.get_event_loop().create_task(sync_all())
    log.info("kitspike: guild-scoped sync scheduled")
