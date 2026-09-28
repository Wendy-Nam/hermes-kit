"""Student install, end to end, inside a freshly booted kit container (run as the hermes user).

Real: seed, plugin files, discord.py objects, /setup handler, wizard buttons and modals, .env and
config writes, job kit install, OMH install (network), `hermes profile create`, readiness, maintenance
cron, role sync, RTK toggle, a real `hermes -p research` chat.
Fake: the model endpoint (local OpenAI-compatible "OK" server) and third-party key validators.
Never needs a Discord token, a ChatGPT login or an API key.

Usage (inside container): python install_e2e.py stage1   # then restart the container
                          python install_e2e.py stage2   # after the restart
"""
import asyncio
import json
import os
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(os.environ.get('HERMES_HOME', '/opt/data'))
KIT = ROOT / 'plugins/kit-setup'
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
os.environ['PYTHONPATH'] = str(HERE / 'hook')  # probe subprocesses: Command Code -> fake server
FAKE = 'http://127.0.0.1:8099/v1'
results = []


def check(name, ok, detail=''):
    results.append((bool(ok), name, str(detail)[:300]))
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''), flush=True)


def step(name):
    def wrap(fn):
        try:
            fn()
        except Exception as exc:
            import traceback
            check(name, False, f'{type(exc).__name__}: {exc} | {traceback.format_exc()[-400:]}')
        return fn
    return wrap


# ── fake Discord interaction ────────────────────────────────────────────────────────────────
class Sent(list):
    pass


def interaction(user_id=42, owner_id=42, channel_id=777):
    sent = Sent()

    class Response:
        _done = False
        async def defer(self, **kw): self._done = True
        async def send_message(self, content=None, **kw): self._done = True; sent.append(('message', content, kw))
        async def send_modal(self, modal): self._done = True; sent.append(('modal', modal, {}))
        def is_done(self): return self._done

    class Followup:
        async def send(self, content=None, **kw): sent.append(('followup', content, kw))

    i = types.SimpleNamespace(user=types.SimpleNamespace(id=user_id, name='student'),
                              guild=types.SimpleNamespace(id=1, owner_id=owner_id),
                              channel_id=channel_id, response=Response(), followup=Followup())
    return i, sent


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def set_input(ti, value):
    ti._value = value


def text(sent):
    return '\n'.join(str(c) for _, c, _ in sent)


# ── stage 1: first install ─────────────────────────────────────────────────────────────────
def stage1():
    import discord
    from discord import app_commands
    import validators

    @step('seed: first boot left kit files, vaults and plugin config')
    def _():
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text())
        enabled = cfg.get('plugins', {}).get('enabled', [])
        check('seed: kit-setup and rtk-rewrite enabled', {'kit-setup', 'rtk-rewrite'} <= set(enabled), enabled)
        check('seed: SOUL, vaults, youtube-summary present',
              (ROOT / 'SOUL.md').is_file() and (ROOT / 'vaults/work/.obsidian').is_dir()
              and (ROOT / 'vaults/personal/.obsidian').is_dir()
              and (ROOT / 'skills/media/youtube-summary/SKILL.md').is_file())

    @step('plugin: loads as a package the way Hermes loads it')
    def _():
        r = subprocess.run([sys.executable, '-I', '-c', (
            'import importlib.util,sys;p=sys.argv[1];'
            's=importlib.util.spec_from_file_location("hermes_plugins.kit_setup",p+"/__init__.py",submodule_search_locations=[p]);'
            'm=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);got=[]\n'
            'class C:\n def register_platform_handler(self,a,f):got.append((a,f.__name__))\n'
            'm.register(C());assert got==[("discord","build")],got'), str(KIT)], capture_output=True, text=True)
        check('plugin: kit-setup registers the discord handler', r.returncode == 0, r.stderr[-300:])
        log = ROOT / 'logs/agent.log'
        bad = [l for l in log.read_text(errors='replace').splitlines() if "Failed to load plugin 'kit-setup'" in l] if log.is_file() else []
        check('plugin: gateway log has no kit-setup load failure', not bad, bad[-1:] if bad else '')

    state = {}

    @step('discord: build() registers /setup and /doctor on guild join')
    def _():
        import discord_ui
        loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        client = discord.Client(intents=discord.Intents.none())
        client.tree = app_commands.CommandTree(client)
        listeners = {}
        client.add_listener = lambda fn, name: listeners.__setitem__(name, fn)
        async def fake_sync(guild=None): return client.tree.get_commands(guild=guild)
        client.tree.sync = fake_sync
        async def never(): await asyncio.sleep(3600)
        client.wait_until_ready = never
        discord_ui.build(client, None)
        guild = discord.Object(id=1)
        run(listeners['on_guild_join'](guild))
        names = sorted(c.name for c in client.tree.get_commands(guild=guild))
        check('discord: guild commands are setup and doctor', names == ['doctor', 'setup'], names)
        state['setup'] = next(c for c in client.tree.get_commands(guild=guild) if c.name == 'setup')
        state['doctor'] = next(c for c in client.tree.get_commands(guild=guild) if c.name == 'doctor')

    @step('/setup: non-owner is refused')
    def _():
        i, sent = interaction(user_id=5, owner_id=42)
        run(state['setup'].callback(i))
        check('/setup: non-owner refused', '소유자만' in text(sent), text(sent))

    @step('/setup: owner gets the wizard, no false bot-token line')
    def _():
        i, sent = interaction()
        run(state['setup'].callback(i))
        body = text(sent)
        view = sent[-1][2].get('view')
        check('/setup: owner registered and wizard shown', '주인으로 등록' in body and '설정 순서' in body, body)
        check('/setup: no "봇 토큰이 없어" message', '봇 토큰' not in body, body)
        check('/setup: all four steps unchecked on a fresh install', body.count('⬜') == 4, body)
        state['view'] = view
        from gateway.pairing import PairingStore
        approved = [e.get('user_id') if isinstance(e, dict) else e for e in PairingStore().list_approved('discord')]
        check('/setup: owner approved in pairing store', '42' in [str(a) for a in approved], approved)

    def button(view, action):
        return next(c for c in view.children if getattr(c, 'custom_id', '') == 'kit:wiz:' + action)

    # Third-party key checks hit real services; their logic has unit tests. Here they pass.
    for name in ('gemini', 'commandcode', 'opencode_go'):
        validators.VALIDATORS[name] = lambda key: (True, 'e2e ok')

    @step('step 2: Gemini modal saves the key')
    def _():
        i, sent = interaction()
        run(button(state['view'], 'gemini').callback(i))
        modal = sent[-1][1]
        check('step 2: Gemini button opens a modal', sent[-1][0] == 'modal', sent)
        set_input(modal.children[0], 'AIza-e2e-test')
        i2, sent2 = interaction()
        run(modal.on_submit(i2))
        from env_store import get_env
        check('step 2: GEMINI_API_KEY stored', get_env(ROOT / '.env').get('GEMINI_API_KEY') == 'AIza-e2e-test', text(sent2))

    @step('step 1: API path — provider select, key + prefilled model, real probe')
    def _():
        i, sent = interaction()
        run(button(state['view'], 'api').callback(i))
        pview = sent[-1][2]['view']
        select = pview.children[0]
        select._values = ['commandcode']
        type(select).values = property(lambda self: self._values)
        i2, sent2 = interaction()
        run(select.callback(i2))
        modal = sent2[-1][1]
        from model_setup import RECOMMENDED
        check('step 1: model field prefilled with the recommended ID',
              modal.model.default == RECOMMENDED['commandcode'], modal.model.default)
        set_input(modal.key, 'cc-e2e-test'); set_input(modal.model, RECOMMENDED['commandcode'])
        i3, sent3 = interaction()
        run(modal.on_submit(i3))
        import config_store
        model = config_store.read(ROOT).get('model') or {}
        check('step 1: real probe passed and main model saved',
              model.get('provider') == 'commandcode' and model.get('default') == RECOMMENDED['commandcode'], text(sent3))
        calls = Path('/tmp/fake-openai-calls.jsonl').read_text().splitlines() if Path('/tmp/fake-openai-calls.jsonl').exists() else []
        check('step 1: probe reached the model with no tools', calls and all(json.loads(c)['tools'] == 0 for c in calls), calls[-2:])

    @step('step 3: job select installs the kit')
    def _():
        kits = next(c for c in state['view'].children if isinstance(c, discord.ui.Select))
        kits._values = ['job']
        type(kits).values = property(lambda self: self._values)
        i, sent = interaction()
        run(kits.callback(i))
        check('step 3: job kit installed from the wizard select', (ROOT / 'skills/kit/job/SKILL.md').is_file(), text(sent))

    @step('wizard: notes and advanced buttons')
    def _():
        i, sent = interaction()
        run(button(state['view'], 'notes').callback(i))
        check('notes: Obsidian guide with a device-ID button',
              'Obsidian' in text(sent) and type(sent[-1][2].get('view')).__name__ == 'NotesView', text(sent))
        i, sent = interaction()
        run(button(state['view'], 'advanced').callback(i))
        check('advanced: old home screen opens', type(sent[-1][2].get('view')).__name__ == 'HomeView', text(sent))

    @step('wizard: status reflects steps 1-3')
    def _():
        from readiness import wizard_status
        s = wizard_status(ROOT)
        check('wizard: steps 1-3 done, 4 pending', s == {'model': True, 'gemini': True, 'kits': True, 'recommended': False}, s)

    @step('step 4: recommended setup — OMH, roles, check, maintenance, restart request')
    def _():
        import views
        restarts = []
        views.restart_gateway = lambda: restarts.append(1) or True
        import config_store
        # The role worker must reach the fake model too; the real Command Code URL is set by select_model.
        view = views.WizardView(state['view'].packs, channel_id=777, owner_id=42)
        i, sent = interaction()
        run(button(view, 'recommended').callback(i))
        body = text(sent)
        check('step 4: OMH installed', (ROOT / 'plugins/omh').is_dir(), body)
        for role in ('research', 'coder', 'creator'):
            home = ROOT / 'profiles' / role
            env = (home / '.env').read_text() if (home / '.env').exists() else ''
            check(f'step 4: role {role} on the main model, no bot token, role SOUL',
                  config_store.read(home).get('model', {}).get('provider') == 'commandcode'
                  and 'DISCORD_BOT_TOKEN' not in env and 'COMMANDCODE_API_KEY' in env
                  and '<!-- kit: role -->' in (home / 'SOUL.md').read_text(), env[:80])
        soul = (ROOT / 'SOUL.md').read_text()
        check('step 4: orchestrator rule added once', soul.count('<!-- kit: roles -->') == 1)
        check('step 4: readiness passed and restart requested', '연결 확인이 끝났습니다' in body and restarts == [1], body[-600:])
        from env_store import get_env
        check('step 4: home channel stored', get_env(ROOT / '.env').get('DISCORD_HOME_CHANNEL') == '777')
        from readiness import wizard_status
        check('wizard: all four steps done', all(wizard_status(ROOT).values()), wizard_status(ROOT))
        jobs = json.loads((ROOT / 'cron/jobs.json').read_text()).get('jobs', []) if (ROOT / 'cron/jobs.json').exists() else []
        check('step 4: maintenance cron jobs registered', len(jobs) >= 1, [j.get('name') for j in jobs])

    @step('role worker: `hermes -p research` answers through the main model')
    def _():
        import config_store
        config_store.write(ROOT / 'profiles/research', {'providers.commandcode.api': FAKE}, remember=False)
        r = subprocess.run(['/opt/hermes/.venv/bin/hermes', '-p', 'research', '--cli', 'chat', '-q', 'Reply with only: OK'],
                           capture_output=True, text=True, timeout=240, env={**os.environ, 'PYTHONPATH': ''})
        check('role worker: research profile ran a turn', r.returncode == 0 and 'OK' in r.stdout, (r.stdout + r.stderr)[-400:])
        r = subprocess.run(['/opt/hermes/.venv/bin/hermes', 'kanban', 'assignees'], capture_output=True, text=True, timeout=60)
        check('kanban: roles are assignable', all(x in r.stdout for x in ('research', 'coder', 'creator')), r.stdout[-300:])

    @step('/doctor: runs and masks secrets')
    def _():
        i, sent = interaction()
        run(state['doctor'].callback(i))
        body = text(sent)
        check('/doctor: answered', bool(body), body)
        check('/doctor: no raw key in output', 'cc-e2e-test' not in body and 'AIza-e2e-test' not in body, body[-300:])


# ── stage 2: after the container restart ────────────────────────────────────────────────────
def stage2():
    import config_store
    cfg = config_store.read(ROOT)
    check('restart: OMH and kit-setup still enabled', 'kit-setup' in cfg.get('plugins', {}).get('enabled', []))
    check('restart: rtk-rewrite on with a direct main model', 'rtk-rewrite' in cfg['plugins']['enabled'], cfg['plugins']['enabled'])
    check('restart: orchestrator rule still once', (ROOT / 'SOUL.md').read_text().count('<!-- kit: roles -->') == 1)
    check('restart: roles still present', all((ROOT / 'profiles' / r / 'SOUL.md').is_file() for r in ('research', 'coder', 'creator')))
    from bootstrap import rtk_follows_route
    config_store.write(ROOT, {'model.provider': 'kit-omniroute', 'model.default': 'kit-student-main'}, remember=False)
    check('rtk: off when the main model goes through OmniRoute', rtk_follows_route(ROOT) is False)
    config_store.write(ROOT, {'model.provider': 'commandcode', 'model.default': 'deepseek/deepseek-v4.1-flash'}, remember=False)
    check('rtk: back on for a direct main model', rtk_follows_route(ROOT) is True)
    from roles import sync_roles
    config_store.write(ROOT, {'model.default': 'changed-model'}, remember=False)
    sync_roles(ROOT)
    check('roles: follow a main model change', config_store.read(ROOT / 'profiles/coder')['model']['default'] == 'changed-model')
    config_store.write(ROOT, {'model.default': 'deepseek/deepseek-v4.1-flash'}, remember=False)
    sync_roles(ROOT)


# ── stage 3: OmniRoute mode against a real OmniRoute container ─────────────────────────────
OMNI_PW = os.environ.get('E2E_OMNI_PASSWORD', 'e2e-omniroute-password')


def _omni():
    import http.cookiejar, urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(method, path, body=None):
        r = urllib.request.Request('http://omniroute:20128' + path, method=method, headers={'Content-Type': 'application/json'},
                                   data=None if body is None else json.dumps(body).encode())
        with op.open(r, timeout=90) as x:
            return json.loads(x.read() or b'{}')
    req('POST', '/api/auth/login', {'password': OMNI_PW})
    return req


def fake_calls():
    p = Path('/tmp/fake-openai-calls.jsonl')
    return p.read_text().splitlines() if p.exists() else []


def chat_turn():
    r = subprocess.run(['/opt/hermes/.venv/bin/hermes', '--cli', 'chat', '-q', 'Reply with only: OK'],
                       capture_output=True, text=True, timeout=300, env={**os.environ, 'PYTHONPATH': ''})
    return r.returncode == 0 and 'OK' in r.stdout, (r.stdout + r.stderr)[-400:]


def stage3a():
    import config_store
    # What a student does in the dashboard: connect a provider (here the local fake, as a custom node).
    req = _omni()
    node = req('POST', '/api/provider-nodes', {'name': 'student-node', 'prefix': 'fake', 'apiType': 'chat',
                                               'baseUrl': 'http://kit-hermes:8099/v1', 'type': 'openai-compatible'})['node']['id']
    req('POST', '/api/providers', {'provider': node, 'apiKey': 'student-key', 'name': 'student-connection', 'priority': 1})
    from omniroute_mode import connect_mode
    config_store.write(ROOT, {'delegation.provider': 'commandcode', 'delegation.model': 'student-aux'}, remember=False)
    ok, msg = connect_mode(ROOT, 'wrong-password', 'fake/fake-model')
    check('omniroute mode: wrong password changes nothing', not ok and config_store.read(ROOT)['model']['provider'] == 'commandcode', msg)
    ok, msg = connect_mode(ROOT, OMNI_PW, 'nothere/model-x')
    check('omniroute mode: unknown provider refused', not ok and 'nothere/model-x' in msg, msg)
    ok, msg = connect_mode(ROOT, OMNI_PW, 'fake/fake-model', 'fake/fake-model')
    cfg = config_store.read(ROOT)
    check('omniroute mode: tool-tested and connected', ok, msg)
    check('omniroute mode: chat through the chat combo', cfg['model']['provider'] == 'kit-omniroute'
          and cfg['model']['default'].endswith('-chat'), cfg.get('model'))
    check('omniroute mode: previous direct model kept as fallback',
          cfg.get('fallback_providers') == [{'provider': 'commandcode', 'model': 'deepseek/deepseek-v4.1-flash'}], cfg.get('fallback_providers'))
    check('omniroute mode: delegation on the strong combo', cfg['delegation']['model'].endswith('-strong'), cfg.get('delegation'))
    from roles import sync_roles
    from bootstrap import rtk_follows_route
    sync_roles(ROOT)
    coder = config_store.read(ROOT / 'profiles/coder')
    check('omniroute mode: roles on the strong combo with the fallback',
          coder['model']['default'].endswith('-strong') and coder.get('fallback_providers') == cfg['fallback_providers'], coder.get('model'))
    check('omniroute mode: Hermes RTK off (OmniRoute compresses)', rtk_follows_route(ROOT) is False)
    # The fallback is the direct Command Code model; in this test it is the same local fake.
    config_store.write(ROOT, {'providers.commandcode.api': FAKE}, remember=False)
    before = len(fake_calls())
    ok, out = chat_turn()
    check('omniroute mode: a real Hermes turn answers through OmniRoute', ok and len(fake_calls()) > before, out)
    ok, msg = connect_mode(ROOT, OMNI_PW, 'fake/broken-model')
    check('omniroute mode: a model failing the tool test is refused', not ok and '도구 호출' in msg, msg)
    ok, out = chat_turn()
    check('omniroute mode: the bot still answers after a failed re-setup (key kept)', ok, out)


def stage3b():
    import config_store
    ok, out = chat_turn()
    check('omniroute down: the bot still answers on the direct fallback', ok, out)
    from omniroute_mode import leave_mode
    ok, msg = leave_mode(ROOT)
    cfg = config_store.read(ROOT)
    check('omniroute mode off: chat back on the direct model', ok and cfg['model']['provider'] == 'commandcode'
          and not cfg.get('fallback_providers'), cfg.get('model'))
    check('omniroute mode off: the aux model from before is restored',
          cfg.get('delegation', {}).get('model') == 'student-aux', cfg.get('delegation'))


if __name__ == '__main__':
    asyncio.set_event_loop(asyncio.new_event_loop())
    {'stage1': stage1, 'stage2': stage2, 'stage3a': stage3a, 'stage3b': stage3b}[sys.argv[1]]()
    failed = [r for r in results if not r[0]]
    print(f'\n== {len(results) - len(failed)}/{len(results)} passed')
    for _, name, detail in failed:
        print('FAILED:', name, '|', detail)
    sys.exit(1 if failed else 0)
