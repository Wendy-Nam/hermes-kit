"""Discord widgets for /setup. Imported only inside the gateway process, where discord.py exists.

Splitting the SDK-bound widgets from discord_ui.py keeps the setup logic importable (and testable)
in an environment without the Discord library, such as CI or a plain unit-test run.
"""
import asyncio
import logging

import discord

from discord_ui import (ENV_FILE, PENDING, TICK, CROSS, _apply, _env, _verify, restart_gateway)

log = logging.getLogger(__name__)

class DoctorView(discord.ui.View):
    """The /doctor result plus a button that renders the instructor-copy in a code block."""

    def __init__(self, findings, timeout=900):
        super().__init__(timeout=timeout)
        self.findings = findings
        self.add_item(ShareButton())


class ShareButton(discord.ui.Button):
    def __init__(self):
        super().__init__(style=discord.ButtonStyle.secondary, label="강사에게 보내기용 복사본",
                         custom_id="kit:doctor:share")

    async def callback(self, interaction):
        import doctor
        # Discord refuses to put very long text in a component callback, so the copy is sent
        # as a followup rather than edited into the original message.
        await interaction.response.send_message(
            "아래를 그대로 강사에게 보내 주세요 (키·채널ID·이메일은 가려집니다):\n"
            f"```\n{doctor.copy_for_instructor(self.view.findings)[:1800]}\n```",
            ephemeral=True)


class PackModal(discord.ui.Modal):
    """One pack's keys. Must be the interaction's first response — Discord allows nothing else."""

    def __init__(self, pack, home):
        super().__init__(title=pack.title[:45])
        self.pack, self.home = pack, home
        for spec in pack.keys:
            self._add(spec)

    def _add(self, spec):
        ti = discord.ui.TextInput(label=spec.label[:45], required=not spec.optional,
                                  style=discord.TextStyle.short)
        ti.placeholder = spec.hint[:100] if spec.hint else None
        setattr(self, f"k_{spec.env}", ti)
        self.add_item(ti)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        entries = [(s, str(getattr(self, f"k_{s.env}")).strip()) for s in self.pack.keys
                   if str(getattr(self, f"k_{s.env}")).strip()]
        if not entries:
            await interaction.followup.send("입력된 키가 없습니다.", ephemeral=True)
            return
        results = await _verify(entries)
        failed = [r for r in results if not r[1]]
        if failed:
            # Nothing is written. A half-configured pack is the state nobody can debug later.
            bad = {name for name, _, _ in failed}
            body = ("확인에 실패한 키 — **아무것도 저장되지 않았습니다.**\n"
                    + "\n".join(f"{CROSS} {name}: {msg}" for name, _, msg in failed))
            for spec, _ in entries:
                if spec.env in bad and spec.url:
                    body += f"\n발급: {spec.url}"
            await interaction.followup.send(body[:1900], ephemeral=True)
            return
        try:
            lines = _apply(entries, self.pack.config)
        except Exception as e:
            log.exception("pack apply failed")
            await interaction.followup.send(f"저장에 실패했습니다: {type(e).__name__}", ephemeral=True)
            return
        detail = "\n".join(f"· {msg}" for _, ok, msg in results if ok)
        await interaction.followup.send("\n".join(lines) + "\n" + detail, ephemeral=True)
        self.home.refresh()


class PackButton(discord.ui.Button):
    def __init__(self, pack, home):
        env = _env()
        done = all(env.get(k.env) for k in pack.keys)
        super().__init__(style=discord.ButtonStyle.success if done else discord.ButtonStyle.secondary,
                         label=pack.title[:80], custom_id=f"kit:pack:{pack.id}")
        self.pack, self.home = pack, home

    async def callback(self, interaction):
        # The modal has to be the *first* response, so nothing may precede this call.
        await interaction.response.send_modal(PackModal(self.pack, self.home))


class ApplyButton(discord.ui.Button):
    def __init__(self, home):
        super().__init__(style=discord.ButtonStyle.primary, label="적용하기 (재시작)",
                         custom_id="kit:apply")
        self.home = home

    async def callback(self, interaction):
        from env_store import set_env
        from packs import load_packs, missing_keys
        import validators as v

        waiting = missing_keys(load_packs(v.VALIDATORS), _env())
        if waiting:
            await interaction.response.send_message(
                "아직 필요한 키가 없습니다: " + ", ".join(k.label for k in waiting), ephemeral=True)
            return
        channel_id = str(self.home.channel_id or "")
        set_env(ENV_FILE, {"DISCORD_HOME_CHANNEL": channel_id})
        PENDING.write_text(channel_id, encoding="utf-8")
        await interaction.response.send_message("재시작합니다. 10초 뒤 준비 완료를 알려드릴게요.",
                                                ephemeral=True)
        await asyncio.sleep(1)
        restart_gateway()


class HomeView(discord.ui.View):
    def __init__(self, packs, channel_id=None, timeout=900):
        super().__init__(timeout=timeout)
        self.channel_id = channel_id
        row = 0
        for p in packs:
            if row == 4:
                self.add_item(ApplyButton(self))
                row = 0
            self.add_item(PackButton(p, self))
            row += 1
        if len(self.children) <= 4:
            self.add_item(ApplyButton(self))

    def refresh(self):
        """Update button states in place after a pack saves, without needing a new interaction."""
        env = _env()
        for child in self.children:
            if isinstance(child, PackButton):
                done = all(env.get(k.env) for k in child.pack.keys)
                child.style = discord.ButtonStyle.success if done else discord.ButtonStyle.secondary

