"""Optional OMH acceptance against checksum-pinned upstream, with no model requests.

Network access is used only by the existing source/package installer. All route
and hook tests are local, and no real credentials or user homes are mounted.
"""
from copy import deepcopy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile

import yaml

KIT_ROOT = Path('/opt/kit/plugins/kit-setup')
sys.path.insert(0, str(KIT_ROOT if KIT_ROOT.is_dir() else Path(__file__).resolve().parents[1] / 'plugins/kit-setup'))
from upstream_omh import CATEGORIES, install_upstream_omh


def host_routing_supported():
    """Whether this interpreter is the shipped Hermes runtime with native routing.

    The optional enhancement patches `omh_delegate_route` only where the host's
    `delegate_task(routing=...)` exists. A bare `python3` cannot answer that
    question, and the plugin correctly refuses to prepare a route there, so the
    check runs first and fails with the interpreter to use instead.
    """
    try:
        from tools.delegate_tool import delegate_task, DELEGATE_TASK_SCHEMA
    except ImportError:
        return False
    return ('routing' in inspect.signature(delegate_task).parameters
            and 'routing' in DELEGATE_TASK_SCHEMA.get('parameters', {}).get('properties', {}))

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


def invoke(registry, data, action, **arguments):
    result = registry.tools['omh_delegate_route']({'action': action, **arguments},
        hermes_home=str(data), omh_home=str(data / '.omh'), session_id='kit-smoke-session')
    return json.loads(result) if isinstance(result, str) else result


assert host_routing_supported(), (
    'this smoke needs the shipped Hermes runtime: run it inside the image with '
    '/opt/hermes/.venv/bin/python, not a bare python3 (the host itself provides '
    'delegate_task(routing=...), and the optional enhancement is refused without it)')

with tempfile.TemporaryDirectory(prefix='kit-omh-acceptance-') as directory:
    data = Path(directory)
    os.environ.update(HOME=directory, HERMES_HOME=directory, OMH_HOME=str(data / '.omh'))
    main = {'default': 'fixture-main', 'provider': 'openai'}
    config = {'model': main, 'plugins': {'enabled': []},
              'delegation': {'max_iterations': 250}, 'student_marker': 'keep'}
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
    result = install_upstream_omh(data,
        routing={'model': 'gpt-6-sol', 'provider': 'openai', 'reasoning_effort': 'medium'},
        host_version='0.21.2')
    assert result['status'] == 'installed', result
    basic = load_plugin(data, 'basic')
    missing = {'goal': 'Synthetic local inspection'}
    hook_args = {'tool_name': 'delegate_task', 'args': missing,
                 'hermes_home': directory, 'omh_home': str(data / '.omh'), 'session_id': 'kit-smoke-session'}
    assert basic.hooks['pre_tool_call'](**hook_args) is None
    assert yaml.safe_load((data / 'config.yaml').read_text())['model'] == main
    for relative, content in untouched.items():
        assert (data / relative).read_bytes() == content, relative

    from omh_enhancements import PINNED_FILES, enable_enhanced_omh, disable_enhanced_omh
    basic_files = {name: (data / name).read_bytes() for name in PINNED_FILES}
    primary = {'model': 'gpt-6-sol', 'provider': 'openai', 'reasoning_effort': 'medium', 'kind': 'model'}
    secondary = {'model': 'claude-sonnet-5', 'provider': 'anthropic', 'reasoning_effort': 'high', 'kind': 'model'}
    categories = {category: [deepcopy(primary)] for category in CATEGORIES}
    categories['deep'] = [deepcopy(primary), deepcopy(secondary)]
    categories['writing'] = [deepcopy(secondary)]
    result = enable_enhanced_omh(data, category_routes=categories, require_route=True)
    assert result['status'] in {'installed', 'enabled', 'configured'}, result
    enhanced = load_plugin(data, 'enhanced')
    after_config = (data / 'config.yaml').read_bytes()
    parsed = yaml.safe_load(after_config)
    assert parsed['model'] == main
    assert parsed['delegation']['max_iterations'] == 250
    assert parsed['student_marker'] == 'keep'
    for relative, content in untouched.items():
        assert (data / relative).read_bytes() == content, relative

    blocked = enhanced.hooks['pre_tool_call'](**hook_args)
    assert blocked['action'] == 'block', blocked
    for action in ('list', 'stop', 'steer'):
        directive = enhanced.hooks['pre_tool_call'](**dict(hook_args, args={'action': action}))
        assert not directive or directive.get('action') != 'block', (action, directive)

    selected = invoke(enhanced, data, 'set', category='deep')
    routing = selected['delegate_args']['routing']
    assert routing == {key: primary[key] for key in ('model', 'provider', 'reasoning_effort')}, selected
    assert (data / 'config.yaml').read_bytes() == after_config
    original = {'goal': 'Synthetic local inspection', 'routing': routing, 'context': 'Preserve context'}
    saved = deepcopy(original)
    directive = enhanced.hooks['pre_tool_call'](**dict(hook_args, args=original))
    assert original == saved
    assert not directive or directive.get('action') != 'block', directive
    if directive and directive.get('action') == 'modify':
        merged = dict(original, **directive['args'])
        assert merged['routing'] == routing
        assert 'Preserve context' in merged['context']
        again = enhanced.hooks['pre_tool_call'](**dict(hook_args, args=merged))
        assert not again or again.get('action') != 'modify', again

    other_session = enhanced.hooks['pre_tool_call'](**dict(hook_args, args=original, session_id='other-session'))
    assert other_session['action'] == 'block', other_session
    fallback = invoke(enhanced, data, 'fallback', category='deep', previous_routing=routing)
    assert fallback['delegate_args']['routing'] == {key: secondary[key] for key in ('model', 'provider', 'reasoning_effort')}, fallback
    exhausted = invoke(enhanced, data, 'fallback', category='deep', previous_routing=fallback['delegate_args']['routing'])
    assert exhausted['status'] == 'exhausted', exhausted
    assert 'delegate_args' not in exhausted
    assert (data / 'config.yaml').read_bytes() == after_config

    unselected = dict(routing, model='unselected-model')
    blocked = enhanced.hooks['pre_tool_call'](**dict(hook_args, args=dict(original, routing=unselected)))
    assert blocked['action'] == 'block', blocked
    # The enhanced route tool must never overwrite shared profile defaults.
    invoke(enhanced, data, 'clear')
    assert (data / 'config.yaml').read_bytes() == after_config
    for relative, content in untouched.items():
        assert (data / relative).read_bytes() == content, relative
    restored = disable_enhanced_omh(data)
    assert restored['status'] == 'disabled', restored
    for name, content in basic_files.items():
        assert (data / name).read_bytes() == content, name
    restored_plugin = load_plugin(data, 'restored')
    assert restored_plugin.hooks['pre_tool_call'](**hook_args) is None
    assert (data / 'config.yaml').read_bytes() == after_config
print('OMH enhanced: real upstream install/register, explicit route guard, calibration and isolated config passed')
