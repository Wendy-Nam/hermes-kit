"""OMH acceptance against checksum-pinned upstream on the shipped Hermes runtime.

No model requests. Network is used only by the upstream source/package installer.
Checks that the kit's routing documents drive upstream `omh_delegate_route` for
every task type, that calibration reaches the child context for high-effort
routes without ever blocking, and that bot profiles and the main model stay intact.
"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

import yaml

KIT_ROOT = Path('/opt/kit/plugins/kit-setup')
sys.path.insert(0, str(KIT_ROOT if KIT_ROOT.is_dir() else Path(__file__).resolve().parents[1] / 'plugins/kit-setup'))
from upstream_omh import CATEGORIES, WORKFLOW_SKILLS, install_upstream_omh
from omh_enhancements import (DEFAULT_EFFORTS, HOOK_FILE, RECEIPT, disable_enhanced_omh,
                              enable_enhanced_omh, sync_base_route)


class Registration:
    def __init__(self):
        self.tools = {}
        self.hooks = {}

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = handler

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def load_plugin(data, suffix):
    root = data / 'plugins/omh'
    name = 'kit_omh_acceptance_' + suffix
    spec = importlib.util.spec_from_file_location(name, root / '__init__.py',
        submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    registry = Registration()
    module.register(registry)
    assert 'omh_delegate_route' in registry.tools
    assert 'pre_tool_call' in registry.hooks
    return registry


with tempfile.TemporaryDirectory(prefix='kit-omh-acceptance-') as directory:
    data = Path(directory)
    os.environ.update(HOME=directory, HERMES_HOME=directory, OMH_HOME=str(data / '.omh'))
    main = {'default': 'fixture-main', 'provider': 'openai-codex'}
    config = {'model': main, 'plugins': {'enabled': []},
              'delegation': {'max_iterations': 250, 'provider': 'gemini', 'model': 'gemini-3-flash'},
              'student_marker': 'keep'}
    (data / 'config.yaml').write_text(yaml.safe_dump(config))
    untouched = {
        '.env': b'FIXTURE_NOT_A_REAL_KEY=synthetic-value\n',
        'profiles/work/config.yaml': b'model:\n  default: fixture-work\n',
        'profiles/work/.env': b'FIXTURE_WORK=synthetic-profile-value\n',
    }
    for relative, content in untouched.items():
        path = data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def assert_student_state():
        parsed = yaml.safe_load((data / 'config.yaml').read_text())
        assert parsed['model'] == main, parsed['model']
        assert parsed['delegation']['max_iterations'] == 250
        assert parsed['student_marker'] == 'keep'
        for relative, content in untouched.items():
            assert (data / relative).read_bytes() == content, relative

    result = install_upstream_omh(data, routing={'model': 'gemini-3-flash', 'provider': 'gemini'},
                                  host_version='0.21.2')
    assert result['status'] == 'installed', result
    assert '보정이 켜졌습니다' in result['message'], result
    assert (data / RECEIPT).is_file()
    assert_student_state()
    import glob, subprocess
    skills = {Path(p).parent.name for p in glob.glob(str(data / '.omh/skills/*/*/SKILL.md'))}
    assert set(WORKFLOW_SKILLS) <= skills and 'omh-plan' in skills, sorted(skills)
    cli = str((data / '.local/bin/omh').resolve())
    subprocess.run([cli, '--hermes-home', directory, '--omh-home', str(data / '.omh'), 'install', '--json'],
                   check=True, capture_output=True)
    assert skills == {Path(p).parent.name for p in glob.glob(str(data / '.omh/skills/*/*/SKILL.md'))}

    plugin = load_plugin(data, 'enhanced')
    session = {'session_id': 'kit-smoke-session', 'task_id': 'kit-smoke-session'}

    def route(action, **arguments):
        raw = plugin.tools['omh_delegate_route']({'action': action, **arguments}, **session)
        return json.loads(raw) if isinstance(raw, str) else raw

    def delegation():
        parsed = yaml.safe_load((data / 'config.yaml').read_text())['delegation']
        return {k: parsed.get(k) for k in ('provider', 'model', 'reasoning_effort')}

    def dispatch(args):
        return plugin.hooks['pre_tool_call'](tool_name='delegate_task', args=args, **session)

    # Upstream routes every task type to the aux model at OMH's recommended effort.
    for category in CATEGORIES:
        prepared = route('set', category=category)
        assert prepared.get('status') not in ('error',), (category, prepared)
        assert delegation() == {'provider': 'gemini', 'model': 'gemini-3-flash',
                                'reasoning_effort': DEFAULT_EFFORTS[category]}, (category, delegation())
    route('clear')

    # High effort: native calibration is appended to every child, input untouched, idempotent.
    route('set', category='ultrabrain')
    original = {'tasks': [{'goal': 'Synthetic local inspection', 'context': 'Preserve context'},
                          {'goal': 'Second lane'}]}
    saved = deepcopy(original)
    directive = dispatch(original)
    assert original == saved
    assert directive and directive['action'] == 'modify', directive
    contexts = [task['context'] for task in directive['args']['tasks']]
    assert contexts[0].startswith('Preserve context') and all('calibration' in c.lower() for c in contexts), contexts
    again = dispatch(dict(original, **directive['args']))
    assert not again or again.get('action') != 'modify', again
    for action in ('list', 'stop', 'steer'):
        directive = dispatch({'action': action})
        assert not directive or directive.get('action') != 'block', (action, directive)

    # Low effort: nothing to add, and nothing blocks.
    route('set', category='quick')
    assert dispatch({'tasks': [{'goal': 'Synthetic'}]}) is None
    route('clear')

    # Per-task chains accumulate; upstream fallback walks them and then restores the baseline.
    deep = [{'provider': 'openai-codex', 'model': 'gpt-6-astra', 'reasoning_effort': 'high'},
            {'provider': 'gemini', 'model': 'gemini-3-pro', 'reasoning_effort': 'high'}]
    writing = [{'provider': 'gemini', 'model': 'gemini-3-pro', 'reasoning_effort': 'medium'}]
    assert enable_enhanced_omh(data, category_routes={'deep': deep})['status'] == 'enabled'
    assert enable_enhanced_omh(data, category_routes={'writing': writing})['status'] == 'enabled'
    plugin = load_plugin(data, 'chains')
    route('set', category='deep')
    assert delegation() == {k: deep[0][k] for k in ('provider', 'model', 'reasoning_effort')}, delegation()
    fallback = route('fallback', category='deep')
    assert delegation() == {k: deep[1][k] for k in ('provider', 'model', 'reasoning_effort')}, (fallback, delegation())
    route('set', category='writing')
    assert delegation()['model'] == 'gemini-3-pro' and delegation()['reasoning_effort'] == 'medium', delegation()
    route('set', category='architect')
    assert delegation()['model'] == 'gemini-3-flash', delegation()
    route('clear')
    assert delegation() == {'provider': 'gemini', 'model': 'gemini-3-flash', 'reasoning_effort': None}, delegation()

    # A changed aux model follows into every task type the student did not assign.
    assert sync_base_route(data, 'opencode-go', 'kimi-k3')['status'] == 'synced'
    plugin = load_plugin(data, 'synced')
    route('set', category='capable')
    assert delegation()['model'] == 'kimi-k3', delegation()
    route('set', category='deep')
    assert delegation()['model'] == 'gpt-6-astra', delegation()
    route('clear')
    assert_student_state()

    restored = disable_enhanced_omh(data)
    assert restored['status'] == 'disabled', restored
    assert b'kit-enhanced-omh' not in (data / HOOK_FILE).read_bytes()
    plugin = load_plugin(data, 'restored')
    route('set', category='ultrabrain')
    assert delegation()['model'] == 'kimi-k3', delegation()
    assert dispatch({'goal': 'Synthetic local inspection'}) is None
    route('clear')
    assert_student_state()
print('OMH: real upstream install, per-task routes, fallback, fail-open calibration and isolated profiles passed')
