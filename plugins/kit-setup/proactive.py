"""Opt-in daily light conversation. Scheduler executes a memory-free model worker."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

KEY = 'kit-proactive'
FILE = '.kit-proactive.json'


def _save(home, data):
    fd, temporary = tempfile.mkstemp(prefix='.proactive-', dir=home)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, home / FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)


def status(data_dir):
    try:
        data = json.loads((Path(data_dir) / FILE).read_text())
        return data if isinstance(data, dict) else {'enabled': False}
    except (OSError, ValueError):
        return {'enabled': False}


def _find(jobs):
    return next((j for j in jobs if (j.get('origin') or {}).get('kit_job') == KEY), None)


def enable(data_dir, channel_id, time, topic):
    home = Path(data_dir).resolve()
    if not re.fullmatch(r'[0-9]{17,20}', str(channel_id)):
        return False, '채널 ID는 17~20자리 숫자여야 합니다'
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time or ''):
        return False, '시간은 HH:MM 형식으로 입력해 주세요'
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
        return False, '주제는 1~200자로 입력해 주세요'
    try:
        import yaml
        config = yaml.safe_load((home / 'config.yaml').read_text()) or {}
        model = config.get('model') or {}
        if not isinstance(model, dict) or not model.get('provider') or not model.get('default'):
            return False, '먼저 /setup에서 대화 모델을 연결해 주세요'
        from cron.jobs import use_cron_store, list_jobs, create_job, update_job
        from cron.scheduler_provider import resolve_cron_scheduler
        from maintenance import write_wrapper
        with (home / '.kit-maintenance.lock').open('a') as lock, use_cron_store(home):
            fcntl.flock(lock, fcntl.LOCK_EX)
            wrapper = write_wrapper(home, KEY, Path(__file__))
            hour, minute = time.split(':')
            schedule = f'{int(minute)} {int(hour)} * * *'
            job = _find(list_jobs(include_disabled=True))
            fields = {'schedule': schedule, 'script': str(wrapper), 'no_agent': True,
                      'enabled_toolsets': [], 'max_turns': 1, 'context_from': [],
                      'deliver': f'discord:{channel_id}', 'failure_deliver': 'local',
                      'workdir': str(home), 'provider': model['provider'], 'model': model['default']}
            # Pause first. An interrupted setup must never execute a partially configured job.
            if job:
                update_job(job['id'], {'enabled': False})
            else:
                job = create_job(prompt='', schedule=schedule, name='키트 재미 선톡',
                                 no_agent=True, script=str(wrapper), paused=True,
                                 origin={'owner': 'plugin:kit-setup', 'kit_job': KEY})
            _save(home, {'enabled': False, 'job_id': job['id'], 'channel_id': str(channel_id),
                         'time': time, 'topic': topic.strip(),
                         'provider': model['provider'], 'model': model['default']})
            fields.update({'enabled': True, 'state': 'scheduled', 'paused_reason': None, 'paused_at': None})
            updated = update_job(job['id'], fields)
            resolve_cron_scheduler().register_job(updated)
            data = status(home); data['enabled'] = True; _save(home, data)
        return True, f'하루 한 번 {time}에 선택한 채널로 짧은 선톡을 보냅니다'
    except Exception as exc:
        return False, f'선톡 설정 실패 ({type(exc).__name__})'


def disable(data_dir):
    home = Path(data_dir).resolve()
    try:
        from cron.jobs import use_cron_store, list_jobs, update_job
        with (home / '.kit-maintenance.lock').open('a') as lock, use_cron_store(home):
            fcntl.flock(lock, fcntl.LOCK_EX)
            # Runner checks metadata before generation and again before output.
            data = status(home); data['enabled'] = False; _save(home, data)
            job = _find(list_jobs(include_disabled=True))
            if job:
                update_job(job['id'], {'enabled': False})
        return True, '선톡을 껐습니다'
    except Exception as exc:
        return False, f'선톡 해제 실패 ({type(exc).__name__})'


def main():
    home = Path(os.environ.get('HERMES_HOME') or '/opt/data')
    data = status(home)
    if not data.get('enabled'):
        return 0
    try:
        import yaml
        current = (yaml.safe_load((home / 'config.yaml').read_text()) or {}).get('model', {})
        if current.get('provider') != data.get('provider') or current.get('default') != data.get('model'):
            raise ValueError('model changed; setup again')
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('model_worker.py')), 'proactive'],
                                input=json.dumps({'topic': data['topic']}, ensure_ascii=False),
                                text=True, capture_output=True, timeout=90, check=False)
        if result.returncode:
            raise RuntimeError('model worker failed')
        # The worker may emit library logs. Only one explicitly typed protocol record is accepted.
        records = []
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get('kit_event') == 'proactive':
                records.append(item)
        if len(records) != 1 or not isinstance(records[0].get('text'), str) or not records[0]['text'].strip():
            raise ValueError('invalid worker reply')
        latest = status(home)
        if latest != data or not latest.get('enabled'):
            return 0
        # Bound delivery length and prevent Discord mass mentions.
        text = records[0]['text'].strip()[:700].replace('@', '@\u200b')
        print(text)
        return 0
    except Exception:
        print('선톡 생성 실패: 모델 연결을 /doctor로 확인해 주세요', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
