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
            lines = await asyncio.to_thread(_apply, entries, self.pack.config)
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        await apply_and_restart(interaction, self.home.channel_id)


async def apply_and_restart(interaction, channel_id):
    """Check, install maintenance, sync role profiles, restart. The interaction is already deferred."""
    from env_store import set_env
    from readiness import check
    from maintenance import install_all
    from roles import sync_roles
    ok, messages = await asyncio.to_thread(check, ENV_FILE.parent)
    if not ok:
        await interaction.followup.send("아직 적용할 수 없습니다:\n" + "\n".join(messages), ephemeral=True)
        return
    results = await asyncio.to_thread(install_all, ENV_FILE.parent)
    failed = [msg for _, msg in results if '실패' in msg]
    if failed:
        await interaction.followup.send("유지보수 설정을 완료하지 못했습니다:\n" + "\n".join(failed), ephemeral=True)
        return
    try:
        from bootstrap import rtk_follows_route
        await asyncio.to_thread(sync_roles, ENV_FILE.parent)
        await asyncio.to_thread(rtk_follows_route, ENV_FILE.parent)
    except Exception:
        log.exception("role/rtk sync failed")  # previous state stays; boot retries
    channel_id = str(channel_id or "")
    set_env(ENV_FILE, {"DISCORD_HOME_CHANNEL": channel_id})
    PENDING.write_text(channel_id, encoding="utf-8")
    await interaction.followup.send("연결 확인이 끝났습니다. 재시작 후 적용 결과를 알려드릴게요.",
                                    ephemeral=True)
    await asyncio.sleep(1)
    if not restart_gateway():
        # No stale marker left behind: otherwise the next unrelated restart greets
        # the channel for a setup that never completed.
        PENDING.unlink(missing_ok=True)
        await interaction.followup.send(
            "재시작하지 못했습니다. Hostinger에서 컨테이너를 다시 시작해 주세요.", ephemeral=True)


class OwnedView(discord.ui.View):
    def __init__(self, owner_id, **kwargs):
        super().__init__(**kwargs)
        self.owner_id = owner_id
    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message('이 설정 화면을 연 사용자만 변경할 수 있습니다.', ephemeral=True)
        return False

class PackSelect(discord.ui.Select):
    def __init__(self, packs, home):
        self.packs={p.id:p for p in packs};self.home=home
        super().__init__(placeholder='서비스 키 입력 · 변경',row=0,
            options=[discord.SelectOption(label=p.title[:100],value=p.id) for p in packs])
    async def callback(self,interaction):
        await interaction.response.send_modal(PackModal(self.packs[self.values[0]],self.home))

class KitSelect(discord.ui.Select):
    def __init__(self):
        from packs import load_kits
        from components import KITS
        super().__init__(placeholder='설치할 직무 스킬 선택',min_values=1,max_values=len(KITS),row=1,
            options=[discord.SelectOption(label=k.title,value=k.id) for k in load_kits() if k.id in KITS])
    async def callback(self,interaction):
        from components import retry_components
        await interaction.response.defer(ephemeral=True,thinking=True)
        result=await asyncio.to_thread(retry_components,ENV_FILE.parent,selected_kits=list(self.values))
        await interaction.followup.send('\n'.join(f"{r['id']}: {r['message']}" for r in result)[:1900],ephemeral=True)

class ModelModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='대화 모델 선택')
        self.provider=discord.ui.TextInput(label='제공자',placeholder='openai-codex / gemini / opencode-go / commandcode',max_length=40)
        self.model=discord.ui.TextInput(label='계정에서 사용할 모델 ID',placeholder='제공자 대시보드에 표시된 모델 ID',max_length=200)
        self.role=discord.ui.TextInput(label='용도: main(대화) / aux(선택: 위임 전용)',default='main',max_length=4)
        self.add_item(self.provider);self.add_item(self.model);self.add_item(self.role)
    async def on_submit(self,interaction):
        from model_setup import select_model,probe
        await interaction.response.defer(ephemeral=True,thinking=True)
        ok,msg=await asyncio.to_thread(select_model,ENV_FILE.parent,str(self.provider).strip(),str(self.model).strip(),str(self.role).strip())
        await interaction.followup.send(msg+(' 적용하기를 눌러 반영하세요.' if ok else ''),ephemeral=True)

class TextActionModal(discord.ui.Modal):
    def __init__(self,action,title,label,placeholder='',max_length=200):
        super().__init__(title=title);self.action=action
        self.value=discord.ui.TextInput(label=label,placeholder=placeholder,max_length=max_length)
        self.add_item(self.value)
    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True,thinking=True)
        value=str(self.value).strip()
        if self.action=='sync':
            from syncthing_setup import pair_device
            ok,msg=await asyncio.to_thread(pair_device,value)
        elif self.action=='import':
            from pathlib import Path
            from importer import import_export
            if Path(value).name!=value or not value.lower().endswith('.zip'):
                ok,msg=False,'Inbox/import에 넣은 ZIP 파일명만 입력해 주세요.'
            else:ok,msg=await asyncio.to_thread(import_export,ENV_FILE.parent/'vaults/personal/Inbox/import'/value,ENV_FILE.parent)
        else:ok,msg=False,'지원하지 않는 작업입니다.'
        await interaction.followup.send(msg[:1900],ephemeral=True)

class ProactiveModal(discord.ui.Modal):
    def __init__(self,channel_id):
        super().__init__(title='일반 선톡 켜기 · 하루 한 번')
        self.channel_id=channel_id
        self.when=discord.ui.TextInput(label='보낼 시각 (한국 시간, HH:MM)',default='09:00',max_length=5)
        self.topic=discord.ui.TextInput(label='주제 · 관심사',placeholder='짧은 글쓰기 아이디어, 오늘 생각해 볼 질문 등',max_length=200)
        self.add_item(self.when);self.add_item(self.topic)
    async def on_submit(self,interaction):
        from proactive import enable
        await interaction.response.defer(ephemeral=True,thinking=True)
        ok,msg=await asyncio.to_thread(enable,ENV_FILE.parent,str(self.channel_id),str(self.when),str(self.topic))
        await interaction.followup.send(msg,ephemeral=True)

class OmniModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='OmniRoute 연결 · 보조 모델')
        self.password=discord.ui.TextInput(label='OmniRoute 대시보드 비밀번호',max_length=200)
        self.provider=discord.ui.TextInput(label='제공자: gemini / openai / anthropic',max_length=32)
        self.key=discord.ui.TextInput(label='해당 제공자의 API 키',max_length=512)
        self.model=discord.ui.TextInput(label='사용할 정확한 모델 ID',max_length=200)
        for item in (self.password,self.provider,self.key,self.model):self.add_item(item)
    async def on_submit(self,interaction):
        from omniroute_setup import configure
        await interaction.response.defer(ephemeral=True,thinking=True)
        ok,msg=await asyncio.to_thread(configure,ENV_FILE.parent,str(self.password),str(self.provider).strip(),str(self.key).strip(),str(self.model).strip())
        await interaction.followup.send(msg[:1900],ephemeral=True)

class OmniVisionModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='현재 OmniRoute 모델로 이미지 읽기')
        self.mode=discord.ui.TextInput(label='connect 연결 / disconnect 해제',default='connect',max_length=10)
        self.password=discord.ui.TextInput(label='OmniRoute 비밀번호 (연결할 때 필요)',max_length=200,required=False)
        self.bridge=discord.ui.TextInput(label='공유 Vision Bridge 끄기 허용: yes / no',default='no',max_length=3,
            placeholder='yes는 이 OmniRoute를 쓰는 다른 앱에도 영향')
        self.add_item(self.mode);self.add_item(self.password);self.add_item(self.bridge)
    async def on_submit(self,interaction):
        from omniroute_setup import connect_vision, disconnect_vision
        mode=str(self.mode).strip().lower()
        if mode not in ("connect","disconnect"):
            return await interaction.response.send_message("connect 또는 disconnect를 입력해 주세요.",ephemeral=True)
        if mode == "disconnect":
            await interaction.response.defer(ephemeral=True,thinking=True)
            ok,msg=await asyncio.to_thread(disconnect_vision,ENV_FILE.parent)
            return await interaction.followup.send(msg[:1900],ephemeral=True)
        if not str(self.password):
            return await interaction.response.send_message("연결하려면 대시보드 비밀번호가 필요합니다.",ephemeral=True)
        consent=str(self.bridge).strip().lower()
        if consent not in ('yes','no'):
            return await interaction.response.send_message('yes 또는 no를 입력해 주세요.',ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        ok,msg=await asyncio.to_thread(connect_vision,ENV_FILE.parent,str(self.password),disable_shared_bridge=consent=='yes')
        await interaction.followup.send(msg[:1900],ephemeral=True)

class ConfirmDisconnect(OwnedView):
    def __init__(self,owner_id):
        super().__init__(owner_id,timeout=180)
    @discord.ui.button(label='확인: 서비스 키 삭제·설정 복원',style=discord.ButtonStyle.danger)
    async def confirm(self,interaction,button):
        import disconnect
        from config_store import write
        from packs import load_packs
        from model_setup import KEYS
        await interaction.response.defer(ephemeral=True,thinking=True)
        def execute():
            # Restore config first. If restoration fails retain keys and recovery snapshot.
            snap=disconnect._load(ENV_FILE.parent)
            write(ENV_FILE.parent,snap,remember=False)
            names={k.env for p in load_packs() for k in p.keys}|{'KIT_OMNIROUTE_API_KEY'}
            removed=disconnect.remove_keys(ENV_FILE,names)
            disconnect.forget(ENV_FILE.parent)
            return len(removed)
        try:
            count=await asyncio.to_thread(execute)
            await interaction.followup.send(f'서비스 키 {count}개를 지우고 설정을 복원했습니다. ChatGPT OAuth 로그인과 외부 계정 연결은 해당 서비스에서 별도로 해제하세요. 적용을 위해 컨테이너를 재시작하세요.',ephemeral=True)
        except Exception:
            await interaction.followup.send('연결 해제에 실패했습니다. 복원 기록을 보존했습니다. /doctor를 확인해 주세요.',ephemeral=True)
        self.stop()

class ActionButton(discord.ui.Button):
    def __init__(self,action,label,row,home):
        super().__init__(label=label,custom_id='kit:action:'+action,row=row)
        self.action=action;self.home=home
    async def callback(self,interaction):
        a=self.action
        if a=='omh':
            return await interaction.response.send_message(
                'OMH 기본 팩을 설치하면 모든 작업 종류가 보조 모델(지정하지 않았으면 대화 모델)로 위임되고, OMH 권장 추론 강도와 모델별 보정이 켜집니다. '
                '작업을 고르면 그 작업만 다른 모델과 대체 모델(최대 5개)로 바꿀 수 있습니다. 저장은 작업별로 누적됩니다. '
                '본인이 연결한 제공자만 쓰며, 모델마다 짧은 테스트 요청을 한 번씩 보냅니다. '
                '설정 뒤 적용하기로 재시작하세요. 기본 대화 모델은 바꾸지 않습니다.',
                view=OmhOptionsView(interaction.user.id,self.home),ephemeral=True)
        if a=='extras':
            from crawl4ai_setup import status
            installed=status(ENV_FILE.parent).get('installed')
            return await interaction.response.send_message(
                'JS 페이지 추출기: 스크립트로 내용을 그리는 페이지를 로컬 브라우저로 읽는 보조 도구입니다. '
                '디스크 약 1GB를 쓰고, 기본 웹 읽기가 빈 결과를 줄 때만 사용합니다. 현재: '+('설치됨' if installed else '미설치'),
                view=ExtrasView(interaction.user.id,self.home),ephemeral=True)
        if a=='model':return await interaction.response.send_modal(ModelModal())
        if a=='sync':
            # The modal alone asks for a device id with no idea what it is; the steps come first.
            from onboarding import sync_guide
            return await interaction.response.send_message(sync_guide(),view=NotesView(interaction.user.id),ephemeral=True)
        if a=='import':return await interaction.response.send_modal(TextActionModal(a,'대화 ZIP 가져오기','personal/Inbox/import의 ZIP 파일명',max_length=180))
        if a=='proactive':return await interaction.response.send_modal(ProactiveModal(self.home.channel_id))
        if a=='omni':
            from omniroute_mode import tunnel_maybe_open
            warn='\n⚠️ 전에 연 대시보드 링크가 닫히지 않았을 수 있습니다. **대시보드 링크 닫기**를 눌러 주세요.' if tunnel_maybe_open(ENV_FILE.parent) else ''
            return await interaction.response.send_message(
                '**OmniRoute 쓰는 순서**\n'
                '1. **대시보드 열기 (15분)** → 받은 링크에서 비밀번호로 로그인하고, 쓰고 싶은 계정(구독·무료·API 키)을 연결합니다.\n'
                '2. **모델 고르기** → 연결한 계정의 모델이 목록으로 나옵니다. 대화용·강한 작업용을 고르면, 하나씩 도구 호출 시험을 한 뒤 통과한 것만 씁니다.\n'
                '3. 고급 설정의 **적용하기**로 재시작합니다. OmniRoute가 멈추면 지금의 직접 연결 모델로 자동 전환됩니다.\n'
                '목록에 없는 모델은 **ID 직접 입력**, 키 하나로 보조 모델만 연결하려면 **API 키 하나로 연결**.'+warn,
                view=OmniChoiceView(interaction.user.id),ephemeral=True)
        if a=='vision':return await interaction.response.send_modal(OmniVisionModal())
        if a=='disconnect':
            import disconnect
            from packs import load_packs
            try:keys,settings=disconnect.plan(ENV_FILE.parent,ENV_FILE,load_packs())
            except Exception:return await interaction.response.send_message('복원 기록을 읽을 수 없습니다. /doctor로 확인해 주세요. 키와 설정은 변경하지 않았습니다.',ephemeral=True)
            return await interaction.response.send_message(f'서비스 키 {len(keys)}개와 설정 {len(settings)}개를 해제/복원합니다. 노트와 봇 토큰은 유지합니다. OAuth·외부 앱 계정은 별도 해제가 필요합니다.',view=ConfirmDisconnect(interaction.user.id),ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            if a=='login':
                from oauth_login import login_codex
                async def notify(text):await interaction.followup.send(text,ephemeral=True)
                ok,msg=await login_codex(ENV_FILE.parent,notify)
            elif a=='check':
                from readiness import check
                ok,rows=await asyncio.to_thread(check,ENV_FILE.parent);msg='\n'.join(rows)
            elif a=='retry':
                from bootstrap import retry_installation
                rows=await asyncio.to_thread(retry_installation,ENV_FILE.parent)
                msg='\n'.join(r['message'] for r in rows)
            elif a=='backup':
                import backup
                ok,msg=await asyncio.to_thread(backup.build,ENV_FILE.parent,ENV_FILE.parent/'vaults/personal/_backup')
            elif a=='stop':
                from proactive import disable
                ok,msg=await asyncio.to_thread(disable,ENV_FILE.parent)
            elif a=='jsextract':
                from crawl4ai_setup import install
                ok,msg=await asyncio.to_thread(install,ENV_FILE.parent)
            elif a=='jsextract-remove':
                from crawl4ai_setup import uninstall
                ok,msg=await asyncio.to_thread(uninstall,ENV_FILE.parent)
            elif a=='omh-basic':
                from upstream_omh import install_upstream_omh
                from pathlib import Path
                from config_store import read
                from model_setup import delegation_route
                route,_=delegation_route(read(ENV_FILE.parent))
                if not route:
                    msg='두뇌 선택에서 대화 모델을 먼저 설정하세요. OMH는 그 경로(보조 모델이 있으면 보조 모델)만 사용하도록 설치합니다.'
                else:
                    row=await asyncio.to_thread(install_upstream_omh,ENV_FILE.parent,routing=route,host_version=Path('/opt/kit/RELEASE_VERSION').read_text().strip().split('-k')[0])
                    msg=row['message']
            else:msg='지원하지 않는 작업입니다.'
        except Exception as exc:
            msg=f'작업을 완료하지 못했습니다 ({type(exc).__name__}). 기존 설정을 확인하고 다시 시도해 주세요.'
        await interaction.followup.send(msg[:1900] or '완료했습니다.',ephemeral=True)

class HomeView(OwnedView):
    def __init__(self,packs,channel_id=None,owner_id=None,timeout=900):
        super().__init__(owner_id,timeout=timeout)
        self.channel_id=channel_id
        self.add_item(PackSelect(packs,self));self.add_item(KitSelect())
        rows=[('model','두뇌 선택',2),('login','ChatGPT 로그인',2),('check','연결 확인',2),('retry','설치 재시도',2),('sync','PC 동기화',2),
              ('import','대화 가져오기',3),('backup','지금 백업',3),('disconnect','연결 해제',3),('proactive','일반 선톡 켜기',3),('stop','선톡 끄기',3),
              ('omh','OMH 설정',4),('omni','OmniRoute 연결',4),('vision','이미지 연결',4),('extras','추가 기능',4)]
        for action,label,row in rows:self.add_item(ActionButton(action,label,row,self))
        apply=ApplyButton(self);apply.row=4;self.add_item(apply)
    def refresh(self):
        pass # Every action reports its measured outcome; reopening refreshes persisted state.

class OmhRouteModal(discord.ui.Modal):
    def __init__(self, category):
        from omh_options import LABELS, available_providers
        from omh_enhancements import DEFAULT_EFFORTS
        super().__init__(title=('OMH: '+LABELS[category])[:45])
        self.category=category
        providers=available_providers(ENV_FILE.parent)
        self.provider=discord.ui.TextInput(label='연결한 제공자',placeholder=', '.join(providers)[:100],max_length=100)
        self.model=discord.ui.TextInput(label='모델 ID (대체 모델은 쉼표로, 최대 5개)',max_length=400,
            placeholder='예: gemini-3-pro, gemini-3-flash · 다른 제공자는 제공자=모델 · 되돌리기는 -')
        self.effort=discord.ui.TextInput(label='추론 강도 (비우면 권장값 '+DEFAULT_EFFORTS[category]+')',required=False,max_length=6,
            placeholder='low / medium / high / xhigh / max · medium 이상에서 보정 적용')
        for field in (self.provider,self.model,self.effort):self.add_item(field)
    async def on_submit(self,interaction):
        from omh_options import save_route
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            result=await asyncio.to_thread(save_route,ENV_FILE.parent,self.category,
                str(self.provider).strip(),str(self.model).strip(),str(self.effort).strip())
            message=result['message']
        except Exception as exc:message=f'설정을 저장하지 못했습니다 ({type(exc).__name__}).'
        await interaction.followup.send(message[:1800],ephemeral=True)

class OmhCategorySelect(discord.ui.Select):
    def __init__(self):
        from omh_options import LABELS
        super().__init__(placeholder='모델을 지정할 작업 선택',custom_id='kit:omh:category',
            options=[discord.SelectOption(label=label,value=category) for category,label in LABELS.items()])
    async def callback(self,interaction):
        await interaction.response.send_modal(OmhRouteModal(self.values[0]))

class OmhStatusButton(discord.ui.Button):
    def __init__(self):super().__init__(label='현재 경로·추천 보기',custom_id='kit:omh:status')
    async def callback(self,interaction):
        from omh_options import summary
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:message=await asyncio.to_thread(summary,ENV_FILE.parent)
        except Exception as exc:message=f'상태를 읽지 못했습니다 ({type(exc).__name__}).'
        await interaction.followup.send(message[:1900],ephemeral=True)

class OmhDisableButton(discord.ui.Button):
    def __init__(self):super().__init__(label='작업별 경로·보정 끄기',custom_id='kit:omh:disable')
    async def callback(self,interaction):
        from omh_enhancements import disable_enhanced_omh
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:result=await asyncio.to_thread(disable_enhanced_omh,ENV_FILE.parent)
        except Exception as exc:result={'message':f'해제하지 못했습니다 ({type(exc).__name__}). 기존 설정을 확인해 주세요.'}
        await interaction.followup.send(result['message'][:1800],ephemeral=True)

class OmhEnableButton(discord.ui.Button):
    def __init__(self):super().__init__(label='보정 다시 켜기',custom_id='kit:omh:enable')
    async def callback(self,interaction):
        from omh_enhancements import enable_enhanced_omh
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:result=await asyncio.to_thread(enable_enhanced_omh,ENV_FILE.parent)
        except Exception as exc:result={'message':f'켜지 못했습니다 ({type(exc).__name__}).'}
        await interaction.followup.send(result['message'][:1800],ephemeral=True)

class ExtrasView(OwnedView):
    def __init__(self,owner_id,home):
        super().__init__(owner_id,timeout=900)
        self.add_item(ActionButton('jsextract','JS 페이지 추출기 설치',0,home))
        self.add_item(ActionButton('jsextract-remove','JS 추출기 제거',0,home))

class OmhOptionsView(OwnedView):
    def __init__(self,owner_id,home):
        super().__init__(owner_id,timeout=900)
        self.add_item(OmhCategorySelect())
        self.add_item(ActionButton('omh-basic','기본 팩 설치',1,home))
        self.add_item(OmhStatusButton())
        self.add_item(OmhEnableButton())
        self.add_item(OmhDisableButton())


# ── First-run wizard ───────────────────────────────────────────────────────────────────────────
# Four numbered steps in the order they must happen; everything else lives behind 고급 설정.

ADVANCED_GUIDE = (
    "**고급 설정** — 처음 설치라면 1~4를 먼저 끝내고 여기로 오세요. 아래는 전부 선택이며, "
    "지금 안 눌러도 기본 대화·위임·영상 요약은 동작합니다.\n"
    "· **서비스 키 입력 · 변경** — 보조 모델·음성·프록시·수집·Composio 키. 입력 즉시 검증되며 "
    "실패한 키는 저장되지 않습니다.\n"
    "· **두뇌 선택 / ChatGPT 로그인** — 대화 모델과 위임용 보조 모델을 바꾸거나 다시 로그인합니다.\n"
    "· **연결 확인** — 저장된 키와 모델로 실제 요청을 보내 봅니다.\n"
    "· **설치 재시도** — 스킬 설치가 네트워크 문제로 실패했을 때 이어서 합니다.\n"
    "· **PC 동기화 / 대화 가져오기** — PC 옵시디언과 노트를 맞추고, 대화 ZIP를 가져옵니다.\n"
    "· **지금 백업** — 수동 백업. 적용 시 주간 백업·업데이트 확인이 등록됩니다.\n"
    "· **연결 해제** — 키트가 설정한 키와 설정을 되돌립니다. OAuth 권한은 해당 서비스에서 해제합니다.\n"
    "· **일반 선톡 켜기** / **선톡 끄기** — 하루 한 번 짧은 글쓰기. 테스트 채널에서만 켜세요.\n"
    "· **OMH 설정** — 위임 모델·추론 강도·작업별 보정. OMH를 업데이트하면 꺼지므로 건드리지 마세요.\n"
    "· **OmniRoute 연결** — 심화 Compose를 먼저 배포한 뒤에만. 대시보드 열기 → 모델 고르기 → "
    "**이 화면의 적용하기(재시작)**까지 세 단계가 모두 필요합니다.\n"
    "· **이미지 연결** — 이미지 읽기를 실제로 시험한 모델만 등록합니다.\n"
    "· **추가 기능** — JS로 그려지는 페이지를 읽는 도구(디스크 약 1GB)."
)


def wizard_text(status):
    mark = lambda done: '✅' if done else '⬜'
    return ('**설정 순서** — 위에서부터 하나씩 누르세요.\n'
            f"{mark(status['model'])} 1. 대화 모델 연결 (ChatGPT 로그인 또는 API 키)\n"
            f"{mark(status['gemini'])} 2. Gemini 키 입력 (영상 요약용, 무료)\n"
            f"{mark(status['kits'])} 3. 직무 선택\n"
            f"{mark(status['recommended'])} 4. 권장 설정 적용 — OMH·역할 프로필(조사·코딩·콘텐츠)을 설치하고 재시작합니다\n"
            '끝나면 `/doctor`와 실제 질문 하나로 확인합니다. PC 옵시디언 노트는 **PC 옵시디언에서 노트 보기**, '
            '나머지 기능은 **고급 설정**을 누르세요.')


class WizardView(OwnedView):
    def __init__(self, packs, channel_id=None, owner_id=None, timeout=900):
        from readiness import wizard_status
        super().__init__(owner_id, timeout=timeout)
        self.packs, self.channel_id = packs, channel_id
        self.status = wizard_status(ENV_FILE.parent)
        style = lambda done: discord.ButtonStyle.success if done else discord.ButtonStyle.secondary
        self.add_item(WizardButton('codex', '1. ChatGPT로 로그인', 0, style(self.status['model'])))
        self.add_item(WizardButton('api', '1. API 키로 연결', 0, style(self.status['model'])))
        self.add_item(WizardButton('gemini', '2. Gemini 키', 1, style(self.status['gemini'])))
        kits = KitSelect(); kits.row = 2; kits.placeholder = '3. 직무 선택'
        self.add_item(kits)
        self.add_item(WizardButton('recommended', '4. 권장 설정 적용 (재시작)', 3, discord.ButtonStyle.primary))
        self.add_item(WizardButton('notes', 'PC 옵시디언에서 노트 보기 (선택)', 4, discord.ButtonStyle.secondary))
        self.add_item(WizardButton('advanced', '고급 설정', 4, discord.ButtonStyle.secondary))

    def refresh(self):
        pass

    def fresh(self):
        return WizardView(self.packs, self.channel_id, self.owner_id)


class WizardButton(discord.ui.Button):
    def __init__(self, action, label, row, style):
        super().__init__(label=label, style=style, row=row, custom_id='kit:wiz:' + action)
        self.action = action

    async def callback(self, interaction):
        a, view, root = self.action, self.view, ENV_FILE.parent
        if a == 'gemini':
            return await interaction.response.send_modal(PackModal(next(p for p in view.packs if p.id == 'base'), view))
        if a == 'api':
            return await interaction.response.send_message(
                '사용할 API 제공자를 고르세요. 키와 모델을 한 번에 입력합니다.',
                view=ApiProviderView(view.owner_id, view.packs), ephemeral=True)
        if a == 'notes':
            from onboarding import sync_guide
            return await interaction.response.send_message(sync_guide(),
                view=NotesView(view.owner_id), ephemeral=True)
        if a == 'advanced':
            # Two messages on purpose: what each optional feature *is* (with whether it is on),
            # then what each button does. One message cannot hold both under Discord's limit.
            from onboarding import feature_guide
            await interaction.response.defer(ephemeral=True, thinking=True)
            await interaction.followup.send(feature_guide(root), ephemeral=True)
            return await interaction.followup.send(
                ADVANCED_GUIDE, view=HomeView(view.packs, channel_id=view.channel_id,
                                              owner_id=view.owner_id), ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        if a == 'codex':
            from oauth_login import login_codex
            from model_setup import RECOMMENDED, select_model
            async def notify(text): await interaction.followup.send(text, ephemeral=True)
            ok, msg = await login_codex(root, notify)
            if ok:
                ok, msg = await asyncio.to_thread(select_model, root, 'openai-codex', RECOMMENDED['openai-codex'])
                msg = (f"ChatGPT 로그인과 대화 모델({RECOMMENDED['openai-codex']}) 연결을 확인했습니다." if ok else
                       msg + ' 로그인은 저장됐습니다. 고급 설정 → 두뇌 선택에서 모델 ID를 직접 넣어 주세요.')
            nxt = view.fresh()
            return await interaction.followup.send(msg + '\n\n' + wizard_text(nxt.status), view=nxt, ephemeral=True)
        if a == 'recommended':
            return await run_recommended(interaction, view)


async def run_recommended(interaction, view):
    """OMH + role profiles on the student's own model, then the normal apply-and-restart."""
    from pathlib import Path
    from readiness import wizard_status
    status = wizard_status(ENV_FILE.parent)
    todo = [label for key, label in (('model', '1. 대화 모델'), ('gemini', '2. Gemini 키'), ('kits', '3. 직무'))
            if not status[key]]
    if todo:
        return await interaction.followup.send('먼저 끝내야 할 단계: ' + ', '.join(todo), ephemeral=True)
    from config_store import read
    from model_setup import delegation_route
    from upstream_omh import install_upstream_omh
    from roles import ensure_roles
    root = ENV_FILE.parent
    await interaction.followup.send('권장 설정을 설치합니다. 1~3분 걸립니다.', ephemeral=True)
    try:
        route, _ = delegation_route(read(root))
        if not route:
            return await interaction.followup.send('대화 모델 설정이 없습니다. 1번부터 다시 설정해 주세요.', ephemeral=True)
        version = Path('/opt/kit/RELEASE_VERSION').read_text().strip().split('-k')[0]
        omh = await asyncio.to_thread(install_upstream_omh, root, routing=route, host_version=version)
        roles = await asyncio.to_thread(ensure_roles, root)
    except Exception as exc:
        log.exception("recommended setup failed")
        return await interaction.followup.send(
            f'권장 설정을 끝내지 못했습니다 ({type(exc).__name__}). 다시 누르면 이어서 설치합니다.', ephemeral=True)
    report = 'OMH: ' + omh['message'] + '\n역할 프로필: ' + ', '.join(roles)
    if omh['status'] == 'failed' or any('못했' in r for r in roles):
        return await interaction.followup.send(report[:1800] + '\n다시 누르면 이어서 설치합니다.', ephemeral=True)
    await interaction.followup.send(report[:1800], ephemeral=True)
    await apply_and_restart(interaction, view.channel_id)


class ApiProviderView(OwnedView):
    def __init__(self, owner_id, packs):
        super().__init__(owner_id, timeout=600)
        self.add_item(ApiProviderSelect(packs))


class ApiProviderSelect(discord.ui.Select):
    PACKS = {'commandcode': 'sub-commandcode', 'opencode-go': 'sub-opencode-go'}

    def __init__(self, packs):
        self.packs = {p.id: p for p in packs}
        super().__init__(placeholder='API 제공자', options=[
            discord.SelectOption(label='Command Code', value='commandcode'),
            discord.SelectOption(label='OpenCode Go', value='opencode-go')])

    async def callback(self, interaction):
        provider = self.values[0]
        await interaction.response.send_modal(ApiModelModal(provider, self.packs[self.PACKS[provider]]))


class ApiModelModal(discord.ui.Modal):
    def __init__(self, provider, pack):
        from model_setup import RECOMMENDED, PROVIDERS
        super().__init__(title=PROVIDERS[provider] + ' 연결')
        self.provider, self.pack = provider, pack
        self.key = discord.ui.TextInput(label=pack.keys[0].label[:45], max_length=512)
        self.model = discord.ui.TextInput(label='모델 ID (권장값이 채워져 있으면 그대로)', max_length=200,
                                          default=RECOMMENDED.get(provider) or None)
        self.add_item(self.key); self.add_item(self.model)

    async def on_submit(self, interaction):
        from model_setup import select_model
        await interaction.response.defer(ephemeral=True, thinking=True)
        entries = [(self.pack.keys[0], str(self.key).strip())]
        results = await _verify(entries)
        bad = [msg for _, ok, msg in results if not ok]
        if bad:
            return await interaction.followup.send(f'{CROSS} 키 확인 실패 — 저장하지 않았습니다: ' + bad[0], ephemeral=True)
        lines = await asyncio.to_thread(_apply, entries, self.pack.config)
        ok, msg = await asyncio.to_thread(select_model, ENV_FILE.parent, self.provider, str(self.model).strip())
        report = [l for l in (lines or []) if l]
        await interaction.followup.send('\n'.join(report + [(TICK if ok else CROSS) + ' ' + msg]), ephemeral=True)


class NotesView(OwnedView):
    def __init__(self, owner_id):
        super().__init__(owner_id, timeout=900)

    @discord.ui.button(label='PC 장치 ID 입력')
    async def pair(self, interaction, button):
        await interaction.response.send_modal(TextActionModal('sync', 'PC 노트 동기화', '내 PC Syncthing 기기 ID', max_length=63))


class OmniChoiceView(OwnedView):
    def __init__(self, owner_id):
        super().__init__(owner_id, timeout=900)

    @discord.ui.button(label='1. 대시보드 열기 (15분)', style=discord.ButtonStyle.primary, row=0)
    async def dashboard(self, interaction, button):
        await interaction.response.send_modal(OmniPasswordModal('dashboard', self.owner_id))

    @discord.ui.button(label='2. 모델 고르기', style=discord.ButtonStyle.primary, row=0)
    async def pick(self, interaction, button):
        await interaction.response.send_modal(OmniPasswordModal('pick', self.owner_id))

    @discord.ui.button(label='ID 직접 입력', row=1)
    async def typed(self, interaction, button):
        await interaction.response.send_modal(OmniModeModal())

    @discord.ui.button(label='API 키 하나로 연결', row=1)
    async def single(self, interaction, button):
        await interaction.response.send_modal(OmniModal())

    @discord.ui.button(label='모드 끄기 (직접 연결로)', row=1)
    async def leave(self, interaction, button):
        from omniroute_mode import leave_mode
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ok, msg = await asyncio.to_thread(leave_mode, ENV_FILE.parent)
        except Exception as exc:
            msg = f'되돌리지 못했습니다 ({type(exc).__name__}). 기존 설정은 그대로입니다.'
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label='대시보드 링크 닫기', row=2)
    async def close(self, interaction, button):
        await interaction.response.send_modal(OmniPasswordModal('close', self.owner_id))


class OmniPasswordModal(discord.ui.Modal):
    """The dashboard password lives only in this process, for the few minutes the task needs it."""

    def __init__(self, purpose, owner_id):
        super().__init__(title='OmniRoute 대시보드 비밀번호')
        self.purpose, self.owner_id = purpose, owner_id
        self.password = discord.ui.TextInput(label='KIT_OMNIROUTE_PASSWORD로 정한 비밀번호', max_length=200)
        self.add_item(self.password)

    async def on_submit(self, interaction):
        import omniroute_mode as om
        pw, root = str(self.password), ENV_FILE.parent
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.purpose == 'close':
            ok, msg = await asyncio.to_thread(om.close_dashboard, root, pw)
            return await interaction.followup.send(msg, ephemeral=True)
        if self.purpose == 'pick':
            ok, rows = await asyncio.to_thread(om.list_models, root, pw)
            if not ok:
                return await interaction.followup.send(CROSS + ' ' + rows, ephemeral=True)
            return await interaction.followup.send(
                '대화용 모델(필수)과 강한 작업용 모델(선택, 비우면 대화용과 같게)을 고른 뒤 **연결**을 누르세요. 목록 순서가 우선순위입니다.',
                view=ModelPickView(self.owner_id, pw, rows), ephemeral=True)
        ok, url = await asyncio.to_thread(om.open_dashboard, root, pw)
        if not ok:
            return await interaction.followup.send(CROSS + ' ' + url, ephemeral=True)
        await interaction.followup.send(
            f'대시보드 링크 (본인만 보입니다, {om.TUNNEL_MINUTES}분 뒤 자동으로 닫힘, 필요하면 언제든 다시 열 수 있음):\n{url}\n'
            '같은 비밀번호로 로그인해 계정을 연결한 뒤, 다시 /setup → 고급 설정 → OmniRoute 연결 → **2. 모델 고르기**를 누르세요. '
            '링크를 다른 사람에게 보내지 마세요.', ephemeral=True)

        async def close_later():
            await asyncio.sleep(om.TUNNEL_MINUTES * 60)
            result = await asyncio.to_thread(om.close_if_due, root, pw)
            if result is None:
                return
            ok, msg = result
            try:
                await interaction.followup.send(('대시보드 링크를 닫았습니다.' if ok else msg), ephemeral=True)
            except Exception:
                pass  # the interaction token expires after 15 minutes; closing already happened
        asyncio.get_event_loop().create_task(close_later())


class ModelPickView(OwnedView):
    def __init__(self, owner_id, password, rows):
        super().__init__(owner_id, timeout=600)
        self.password, self.order = password, [value for value, _ in rows]
        options = [discord.SelectOption(label=label, value=value) for value, label in rows]
        self.chat_select = discord.ui.Select(placeholder='대화용 모델 (1~5개)', min_values=1,
                                             max_values=min(5, len(options)), options=options, row=0)
        self.strong_select = discord.ui.Select(placeholder='강한 작업용 모델 (선택, 0~5개)', min_values=0,
                                               max_values=min(5, len(options)), options=list(options), row=1)
        self.chat_select.callback = self._chosen
        self.strong_select.callback = self._chosen
        self.add_item(self.chat_select); self.add_item(self.strong_select)

    async def _chosen(self, interaction):
        await interaction.response.defer()

    @discord.ui.button(label='연결', style=discord.ButtonStyle.success, row=2)
    async def connect(self, interaction, button):
        from omniroute_mode import connect_mode
        # Priority is the list order, whatever order the student clicked in.
        chat, strong = (sorted(sel.values, key=self.order.index) for sel in (self.chat_select, self.strong_select))
        if not chat:
            return await interaction.response.send_message('대화용 모델을 하나 이상 고르세요.', ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, msg = await asyncio.to_thread(connect_mode, ENV_FILE.parent, self.password, ','.join(chat), ','.join(strong))
        await interaction.followup.send((TICK if ok else CROSS) + ' ' + msg[:1800], ephemeral=True)
        if ok:
            self.password = ''
            self.stop()


class OmniModeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='OmniRoute 모드')
        self.password = discord.ui.TextInput(label='OmniRoute 대시보드 비밀번호', max_length=200)
        self.chat = discord.ui.TextInput(label='대화용 모델 (쉼표로, 최대 5개, 앞이 우선)', max_length=600,
                                         style=discord.TextStyle.paragraph, placeholder='codex/gpt-6-luna, command-code/deepseek/deepseek-v4.1-flash')
        self.strong = discord.ui.TextInput(label='강한 작업용 모델 (비우면 대화용과 같게)', max_length=600, required=False,
                                           style=discord.TextStyle.paragraph, placeholder='codex/gpt-6-sol, claude/claude-sonnet-5')
        for item in (self.password, self.chat, self.strong):
            self.add_item(item)

    async def on_submit(self, interaction):
        from omniroute_mode import connect_mode
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, msg = await asyncio.to_thread(connect_mode, ENV_FILE.parent, str(self.password), str(self.chat), str(self.strong))
        await interaction.followup.send((TICK if ok else CROSS) + ' ' + msg[:1800], ephemeral=True)
