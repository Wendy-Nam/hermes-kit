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
        from env_store import set_env
        from readiness import check
        from maintenance import install_all
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, messages = await asyncio.to_thread(check, ENV_FILE.parent)
        if not ok:
            await interaction.followup.send("아직 적용할 수 없습니다:\n" + "\n".join(messages), ephemeral=True)
            return
        results = await asyncio.to_thread(install_all, ENV_FILE.parent)
        failed = [msg for _, msg in results if '실패' in msg]
        if failed:
            await interaction.followup.send("유지보수 설정을 완료하지 못했습니다:\n" + "\n".join(failed), ephemeral=True)
            return
        channel_id = str(self.home.channel_id or "")
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
        self.role=discord.ui.TextInput(label='용도: main(대화) / aux(보조·위임)',default='main',max_length=4)
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
                'OMH 기본 팩을 설치하면 모든 작업 종류가 보조 모델로 위임되고, OMH 권장 추론 강도와 모델별 보정이 켜집니다. '
                '작업을 고르면 그 작업만 다른 모델과 대체 모델(최대 5개)로 바꿀 수 있습니다. 저장은 작업별로 누적됩니다. '
                '본인이 연결한 제공자만 쓰며, 모델마다 짧은 테스트 요청을 한 번씩 보냅니다. '
                '설정 뒤 적용하기로 재시작하세요. 기본 대화 모델은 바꾸지 않습니다.',
                view=OmhOptionsView(interaction.user.id,self.home),ephemeral=True)
        if a=='extras':
            from crawl4ai_setup import status
            installed=status(ENV_FILE.parent).get('installed')
            return await interaction.response.send_message(
                'Cline 무료 후보: 공개 가격이 0인 모델 목록을 조회합니다.\n'
                'JS 페이지 추출기: 스크립트로 내용을 그리는 페이지를 로컬 브라우저로 읽는 보조 도구입니다. '
                '디스크 약 1GB를 쓰고, 기본 웹 읽기가 빈 결과를 줄 때만 사용합니다. 현재: '+('설치됨' if installed else '미설치'),
                view=ExtrasView(interaction.user.id,self.home),ephemeral=True)
        if a=='model':return await interaction.response.send_modal(ModelModal())
        if a=='sync':return await interaction.response.send_modal(TextActionModal(a,'PC 노트 동기화','내 PC Syncthing 기기 ID',max_length=63))
        if a=='import':return await interaction.response.send_modal(TextActionModal(a,'대화 ZIP 가져오기','personal/Inbox/import의 ZIP 파일명',max_length=180))
        if a=='proactive':return await interaction.response.send_modal(ProactiveModal(self.home.channel_id))
        if a=='omni':return await interaction.response.send_modal(OmniModal())
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
            elif a=='cline':
                from cline_catalog import fetch_catalog,inspect_catalog
                snapshot=await asyncio.to_thread(fetch_catalog)
                rows=inspect_catalog(snapshot)
                candidates=[mid for mid,row in rows.items() if row['status']=='zero_advertised']
                from datetime import datetime
                from zoneinfo import ZoneInfo
                checked=datetime.fromtimestamp(snapshot['checked_at'],ZoneInfo('Asia/Seoul')).strftime('%m/%d %H:%M KST')
                msg=('Cline 공개 가격이 0인 후보 · '+checked+'\n'+
                     '\n'.join(candidates)+'\n캐시 가격 미표기는 무료 보장이 아닙니다. 이미지·음악 모델도 포함될 수 있습니다. 대시보드에서 본인 계정을 연결한 뒤 모델의 도구 사용을 별도로 확인하세요. 유료 모델을 자동 대체 경로에 넣지 마세요.')
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
                c=read(ENV_FILE.parent);route=c.get('delegation') or {};model=c.get('model') or {}
                if not route.get('model') or not route.get('provider'):
                    msg='보조 제공자·모델을 먼저 설정하세요. OMH는 그 경로만 사용하도록 설치합니다.'
                else:
                    row=await asyncio.to_thread(install_upstream_omh,ENV_FILE.parent,routing={'model':route['model'],'provider':route['provider']},host_version=Path('/opt/kit/RELEASE_VERSION').read_text().strip().split('-k')[0])
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
            placeholder='low / medium / high / xhigh / max · high 이상에서 보정 적용')
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
        self.add_item(ActionButton('cline','Cline 무료 후보',0,home))
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
