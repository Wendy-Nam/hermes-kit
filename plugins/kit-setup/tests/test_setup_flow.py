import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bootstrap
import config_store
import env_store
import model_setup
import readiness

class SetupFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        env_store.set_env(self.root/'.env',{'GEMINI_API_KEY':'test'})
        config_store.write(self.root,{'model.provider':'gemini','model.default':'working'},remember=False)
    def test_upgrade_enables_setup_and_preserves_other_plugins(self):
        config_store.write(self.root,{'plugins.enabled':['rtk-rewrite']},remember=False)
        bootstrap.ensure_setup_enabled(self.root)
        bootstrap.ensure_setup_enabled(self.root)
        self.assertEqual(config_store.read(self.root)['plugins']['enabled'],['rtk-rewrite','kit-setup'])
    def test_hermes_rtk_is_off_only_while_the_main_model_goes_through_omniroute(self):
        (self.root/'plugins/rtk-rewrite').mkdir(parents=True)
        config_store.write(self.root,{'plugins.enabled':['kit-setup','rtk-rewrite']},remember=False)
        self.assertTrue(bootstrap.rtk_follows_route(self.root))
        config_store.write(self.root,{'model.provider':'omniroute','model.default':'hermes-chat'},remember=False)
        self.assertFalse(bootstrap.rtk_follows_route(self.root))
        self.assertEqual(config_store.read(self.root)['plugins']['enabled'],['kit-setup'])
        config_store.write(self.root,{'model.provider':'openai-codex'},remember=False)
        self.assertTrue(bootstrap.rtk_follows_route(self.root))
        self.assertEqual(config_store.read(self.root)['plugins']['enabled'],['kit-setup','rtk-rewrite'])
    def test_wizard_does_not_count_hermes_default_model_as_connected(self):
        config_store.write(self.root,{'model.provider':'auto','model.default':'anthropic/claude-opus-4.6'},remember=False)
        self.assertFalse(readiness.wizard_status(self.root)['model'])
        config_store.write(self.root,{'model.provider':'commandcode'},remember=False)
        self.assertTrue(readiness.wizard_status(self.root)['model'])
    def test_bad_new_model_does_not_replace_working_configuration(self):
        before=(self.root/'config.yaml').read_bytes()
        with patch.object(model_setup,'probe',return_value=(False,'rejected')):
            ok,_=model_setup.select_model(self.root,'gemini','bad-model')
        self.assertFalse(ok);self.assertEqual((self.root/'config.yaml').read_bytes(),before)
    def test_successful_selection_records_restore_baseline(self):
        with patch.object(model_setup,'probe',return_value=(True,'ok')):
            self.assertTrue(model_setup.select_model(self.root,'gemini','new-model')[0])
        self.assertEqual(config_store.read(self.root)['model']['default'],'new-model')
        snap=json.loads((self.root/'.kit-config-snapshot.json').read_text())
        self.assertEqual(snap['model.default'],'working')
    def test_env_concurrent_writers_preserve_all_keys(self):
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda i:env_store.set_env(self.root/'.env',{f'TEST_{i}':str(i)}),range(20)))
        self.assertEqual(len(env_store.get_env(self.root/'.env')),21)
    def test_model_check_never_surfaces_raw_worker_errors(self):
        result=subprocess.CompletedProcess([],1,'raw-secret','another-secret')
        with patch.object(model_setup.subprocess,'run',return_value=result):
            ok,msg=model_setup.probe(self.root)
        self.assertFalse(ok);self.assertNotIn('secret',msg)
    def test_readiness_checks_the_aux_model_only_when_one_is_set(self):
        skill=self.root/'skills/media/youtube-summary/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('skill')
        with patch.object(model_setup,'probe',return_value=(True,'main')) as check:
            self.assertTrue(readiness.check(self.root)[0])  # no aux: the main model delegates
        self.assertEqual(check.call_count,1)
        config_store.write(self.root,{'delegation.provider':'gemini','delegation.model':'aux'},remember=False)
        with patch.object(model_setup,'probe',side_effect=[(True,'main'),(False,'aux missing')]) as check:
            ok,rows=readiness.check(self.root)
        self.assertFalse(ok);self.assertIn('aux missing',rows[0]);self.assertEqual(check.call_count,2)
    def test_delegation_route_falls_back_to_the_main_model(self):
        self.assertEqual(model_setup.delegation_route(config_store.read(self.root)),({'provider':'gemini','model':'working'},False))
        config_store.write(self.root,{'delegation.provider':'opencode-go','delegation.model':'kimi-k3'},remember=False)
        self.assertEqual(model_setup.delegation_route(config_store.read(self.root)),({'provider':'opencode-go','model':'kimi-k3'},True))
    def test_failed_public_install_is_retried_without_core_version_change(self):
        (self.root/'.kit-version').write_text('2')
        with patch.object(bootstrap.subprocess,'run',side_effect=TimeoutError):
            first=bootstrap.retry_installation(self.root,seed_dir=self.root/'seed')
        self.assertEqual(first[-1]['status'],'failed')
        def install(*args,**kwargs):
            skill=self.root/'skills/media/youtube-summary/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('ready')
        with patch.object(bootstrap.subprocess,'run',side_effect=install) as runner:
            second=bootstrap.retry_installation(self.root,seed_dir=self.root/'seed')
        self.assertEqual(second[-1]['status'],'installed');self.assertEqual(runner.call_count,1)
    def test_proxy_is_verified_from_one_api_key(self):
        # One field, not a Username/Password pair: students pasted their dashboard
        # login into the old form often enough that both hints had to warn about it.
        import discord_ui,validators,packs
        proxy=next(p for p in packs.load_packs() if p.id=='proxy')
        self.assertEqual([k.env for k in proxy.keys],['WEBSHARE_API_KEY'])
        with patch.object(validators,'webshare_from_api_key',
            return_value=(True,'connected',{'WEBSHARE_PROXY_USERNAME':'u-rotate','WEBSHARE_PROXY_PASSWORD':'p'})):
            rows=asyncio.run(discord_ui._verify(list(zip(proxy.keys,['tok']))))
        self.assertTrue(all(r[1] for r in rows))
        # Row four carries what the caller should persist: the typed key plus the two
        # derived credentials. The message stays a status line and leaks neither.
        persisted={name:value for name,ok,_,value in rows if value is not None}
        self.assertEqual(persisted,{'WEBSHARE_API_KEY':'tok','WEBSHARE_PROXY_USERNAME':'u-rotate',
                                    'WEBSHARE_PROXY_PASSWORD':'p'})
        self.assertNotIn('u-rotate',[msg for _,_,msg,_ in rows][0])

    def test_a_failed_proxy_lookup_writes_nothing(self):
        import discord_ui,validators,packs,env_store
        proxy=next(p for p in packs.load_packs() if p.id=='proxy')
        with patch.object(validators,'webshare_from_api_key',return_value=(False,'키가 거부됐습니다',{})):
            rows=asyncio.run(discord_ui._verify(list(zip(proxy.keys,['bad']))))
        self.assertTrue(all(not r[1] for r in rows))
        # The typed key is still reported back, so the caller can store it; the two
        # derived credentials are absent, and a failed pack writes nothing at all.
        self.assertEqual([name for name,ok,_,value in rows if value is not None],['WEBSHARE_API_KEY'])
        self.assertNotIn('WEBSHARE_PROXY_PASSWORD',env_store.get_env(self.root/'.env'))
    def test_selected_kit_failed_upgrade_is_not_ready(self):
        folder=self.root/'skills/kit/job';folder.mkdir(parents=True);(folder/'SKILL.md').write_text('old')
        (self.root/'.kit-components.json').write_text(json.dumps({'schema_version':'kit-components/v1','selected_kits':['job'],'components':{},'last_results':{'job':{'status':'failed'}}}))
        row=next(r for r in bootstrap.component_status(self.root) if r['id']=='job')
        self.assertEqual(row['status'],'failed')

class DiscordLayout(unittest.IsolatedAsyncioTestCase):
    async def test_layout_and_modal_limits(self):
        try:import discord
        except ImportError:self.skipTest('Discord SDK is tested inside the kit image')
        import views,packs
        view=views.HomeView(packs.load_packs(),owner_id=123,channel_id=456)
        self.assertLessEqual(len(view.children),25)
        ids=[c.custom_id for c in view.children if getattr(c,'custom_id',None)]
        self.assertEqual(len(ids),len(set(ids)))
        for cls in (views.ModelModal,views.OmniModal):
            self.assertLessEqual(len(cls().children),5)
        view.stop()
        wizard=views.WizardView(packs.load_packs(),owner_id=123,channel_id=456)
        ids=[c.custom_id for c in wizard.children if getattr(c,'custom_id',None)]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn('4. 권장 설정 적용',views.wizard_text(wizard.status))
        api=next(p for p in packs.load_packs() if p.id=='sub-commandcode')
        self.assertEqual(views.ApiModelModal('commandcode',api).model.default,model_setup.RECOMMENDED['commandcode'])
        wizard.stop()

class InviteCommand(unittest.IsolatedAsyncioTestCase):
    """/invite hands out the only way into a new server and PATCHes the Discord application, so
    it is held to exactly the terms /setup is. The old `guild is not None and …` guard skipped
    the check entirely in a DM, where guild is None."""

    def _interaction(self, guild, user_id):
        import discord_ui, owner

        class Response:
            def __init__(self): self.sent = []

            async def send_message(self, content, **kw): self.sent.append((content, kw))

            async def defer(self, **kw): pass

        class Followup:
            def __init__(self): self.sent = []

            async def send(self, content, **kw): self.sent.append((content, kw))

        import types
        followup = Followup()
        inter = types.SimpleNamespace(guild=guild, user=types.SimpleNamespace(id=user_id),
                                     channel_id=1, response=Response(), followup=followup)
        return inter, followup, discord_ui, owner

    async def test_dm_is_refused_before_any_check_is_skipped(self):
        inter, _, discord_ui, owner = self._interaction(None, 999)
        with patch.object(owner, "invite_link") as link:
            await discord_ui.invite_command(inter, Path("/tmp"))
        link.assert_not_called()
        self.assertIn("서버에서만", inter.response.sent[0][0])

    async def test_a_non_owner_is_refused_and_never_reaches_the_link(self):
        import types
        guild = types.SimpleNamespace(owner_id=1)
        inter, _, discord_ui, owner = self._interaction(guild, 2)
        with patch.object(owner, "is_approved", return_value=False), \
             patch.object(owner, "invite_link") as link:
            await discord_ui.invite_command(inter, Path("/tmp"))
        link.assert_not_called()
        self.assertIn("소유자만", inter.response.sent[0][0])

    async def test_the_owner_gets_the_link_and_it_is_never_cut_in_half(self):
        import types
        guild = types.SimpleNamespace(owner_id=1)
        inter, followup, discord_ui, owner = self._interaction(guild, 1)
        url = "https://discord.com/oauth2/authorize?client_id=1&permissions=8&scope=bot"
        # A long note must eat the space, never the URL: a truncated link looks valid and 404s.
        with patch.object(owner, "invite_link", return_value=(url, "설명 " * 900)):
            await discord_ui.invite_command(inter, Path("/tmp"))
        body = followup.sent[0][0]
        self.assertLessEqual(len(body), 1900)
        self.assertIn(url, body)

    async def test_no_token_gives_the_portal_recipe_and_no_half_link(self):
        import types
        guild = types.SimpleNamespace(owner_id=1)
        inter, followup, discord_ui, owner = self._interaction(guild, 1)
        with patch.object(owner, "invite_link", return_value=(None, "URL Generator 를 사용하세요")):
            await discord_ui.invite_command(inter, Path("/tmp"))
        body = followup.sent[0][0]
        self.assertIn("URL Generator", body)
        self.assertNotIn("client_id=", body)


class OnboardingCopy(unittest.TestCase):
    """The /setup and 고급 설정 copy is the only manual a student has. Discord rejects a
    message over 2000 characters outright, and an over-long guide fails at the worst
    possible moment: the first time a confused student presses the button."""

    def _views(self):
        import discord  # noqa: F401  (absent outside the gateway; the test skips below)
        from views import ADVANCED_GUIDE, wizard_text
        return ADVANCED_GUIDE, wizard_text

    def setUp(self):
        try:
            self.guide, self.wizard_text = self._views()
        except ImportError:
            self.skipTest("discord.py is not installed in this environment")

    def test_advanced_guide_fits_a_discord_message(self):
        self.assertLess(len(self.guide), 1900)

    def test_wizard_text_fits_a_discord_message(self):
        status = {'model': False, 'gemini': False, 'kits': False, 'recommended': False}
        self.assertLess(len(self.wizard_text(status)), 1900)

    def test_advanced_guide_names_every_button_on_the_home_screen(self):
        from views import HomeView  # noqa: F401  (import proves the module still loads)
        for label in ('서비스 키 입력 · 변경', '두뇌 선택', '연결 확인', '설치 재시도', 'PC 동기화',
                      '대화 가져오기', '지금 백업', '연결 해제', '일반 선톡 켜기', '선톡 끄기',
                      'OMH 설정', 'OmniRoute 연결', '이미지 연결', '추가 기능'):
            self.assertIn(label, self.guide, f"{label} is on HomeView but undocumented")

    def test_advanced_guide_keeps_the_omniroute_three_step_order(self):
        # The recurring failure is stopping after step 2 and reporting "nothing changed".
        guide = self.guide
        self.assertLess(guide.index('대시보드 열기'), guide.index('모델 고르기'))
        self.assertIn('적용하기(재시작)', guide)


if __name__=='__main__':unittest.main()
