"""Ported server patches behave on the shipped runtime (no network, no gateway).

- kanban: a crashed worker notifies without waking the agent; start and noted
  heartbeats reach the thread, heartbeats are throttled per task, and a failure
  message carries the redacted last error line from the worker log.
- hooks: a second policy (pre_tool_call) call waits for the running one instead
  of being skipped, so OMH governance never silently misses a tool call.
- prompt: kanban workers are told to heartbeat with a note.
"""
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, '/opt/hermes')
from gateway import kanban_watchers_notifier as notifier

assert 'crashed' not in notifier._WAKE_KINDS and 'gave_up' in notifier._WAKE_KINDS
assert {'claimed', 'heartbeat'} <= set(notifier.NOTIFY_KINDS)
note = SimpleNamespace(task_id='t1', head='Kanban t1', title='Synthetic', board_slug=None)
event = lambda kind, **payload: SimpleNamespace(kind=kind, payload=payload)
assert notifier._EVENT_FORMATTERS['claimed'](event('claimed'), note)[0].startswith('▶')
first = notifier._EVENT_FORMATTERS['heartbeat'](event('heartbeat', note='3/5 done'), note)[0]
assert first and '3/5 done' in first, first
assert notifier._EVENT_FORMATTERS['heartbeat'](event('heartbeat', note='4/5 done'), note)[0] is None
assert notifier._EVENT_FORMATTERS['heartbeat'](event('heartbeat'), SimpleNamespace(**{**vars(note), 'task_id': 't2'}))[0] is None
log = 'starting\n📝 Error: HTTP 401: Invalid API key sk-synthetic0123456789abcdef\n'
with patch('hermes_cli.kanban_db.read_worker_log', return_value=log):
    message, handoff, _ = notifier._EVENT_FORMATTERS['gave_up'](event('gave_up'), note)
assert '401' in message and '401' in handoff and 'sk-synthetic0123456789abcdef' not in message, message

from hermes_cli import plugins_dispatch
source = open(plugins_dispatch.__file__, encoding='utf-8').read()
assert '_POLICY_SERIALIZATION_DEADLINE_V2' in source and 'waited_for_policy_overlap' in source
from hermes_cli.plugins import PluginManager, get_plugin_manager
manager = get_plugin_manager()
calls, release = [], threading.Event()
def policy(**kwargs):
    calls.append(kwargs.get('tool_name'))
    if len(calls) == 1:
        release.wait(2)
    return None
manager._hooks.setdefault('pre_tool_call', []).append(policy)
results = []
def invoke(name):
    results.append(manager.invoke_hook('pre_tool_call', tool_name=name, args={}, session_id=name))
first_call = threading.Thread(target=invoke, args=('first',)); first_call.start()
time.sleep(0.3)
second_call = threading.Thread(target=invoke, args=('second',)); second_call.start()
time.sleep(0.3); release.set()
first_call.join(10); second_call.join(10)
manager._hooks['pre_tool_call'].remove(policy)
assert calls == ['first', 'second'], calls

from agent import prompt_builder
assert 'Report progress with heartbeats' in open(prompt_builder.__file__, encoding='utf-8').read()
print('ported patches: kanban notify/no crash wake, policy hook serialization, heartbeat prompt passed')
