"""Offline regression against the scheduler and durable ledger in the shipped image."""
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Imports must not initialize state in the image's real /opt/data.
with tempfile.TemporaryDirectory() as directory:
    os.environ['HERMES_HOME'] = directory
    os.environ['HOME'] = directory
    from cron.scheduler import _final_response_from_result
    from cron import executions

    agent = Mock()
    agent._format_turn_completion_explanation.return_value = ''
    cases = [
        ({'failed': False, 'completed': False, 'turn_exit_reason': 'max_iterations_reached(8)',
          'final_response': 'Synthetic partial report: validation unfinished'}, 'failed'),
        ({'completed': False, 'turn_exit_reason': 'max_iterations_reached(8)'}, 'failed'),
        ({'failed': True, 'final_response': 'Synthetic API failure'}, 'failed'),
        ({'completed': False, 'final_response': 'Synthetic interrupted run'}, 'failed'),
        ({'completed': True, 'final_response': 'Synthetic completed report'}, 'completed'),
        ({'completed': True, 'final_response': ''}, 'completed'),
    ]
    with patch.object(executions, 'EXECUTIONS_FILE', Path(directory) / 'executions.db'):
        for index, (result, expected) in enumerate(cases):
            record = executions.create_execution(f'fixture-{index}', source='test')
            try:
                response = _final_response_from_result(result, 'fixture', 'Synthetic cron', agent)
                success, error = True, None
                assert response == result['final_response']
            except RuntimeError as exc:
                success, error = False, str(exc)
                if index == 0:
                    assert 'max_iterations_reached(8)' in error
                    assert result['final_response'] in error
            executions.finish_execution(record['id'], success=success, error=error)
            persisted = executions.get_execution(record['id'])
            assert persisted['status'] == expected, (index, persisted)
            if not success:
                assert persisted['error'] == error
print('cron outcomes: iteration-limit, failure, success and silence persist correctly (6 cases)')
