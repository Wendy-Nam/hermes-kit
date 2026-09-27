"""Install kit jobs through Hermes' locked, normalized scheduler API only."""
import fcntl
import os
import tempfile
from pathlib import Path


def write_wrapper(data_dir, key, script):
    scripts = data_dir / 'scripts'
    scripts.mkdir(exist_ok=True)
    wrapper = scripts / (key + '.py')
    body = ('import os, runpy, sys\n'
            + 'sys.path.insert(0, ' + repr(str(Path(script).resolve().parent)) + ')\n'
            + 'os.environ["HERMES_HOME"] = ' + repr(str(data_dir)) + '\n'
            + 'runpy.run_path(' + repr(str(Path(script).resolve())) + ', run_name="__main__")\n')
    fd, temporary = tempfile.mkstemp(dir=scripts, prefix='.kit-script-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(body)
        os.replace(temporary, wrapper)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return wrapper


def install_job(data_dir, key, name, schedule, script, deliver="local"):
    data_dir = Path(data_dir).resolve()
    try:
        from cron.jobs import use_cron_store, list_jobs
        from cron.scheduler import create_job_with_scheduler_registration
        from cron.scheduler_provider import resolve_cron_scheduler
        data_dir.mkdir(parents=True, exist_ok=True)
        # Separate lock avoids nesting the scheduler's own .jobs.lock.
        with (data_dir / '.kit-maintenance.lock').open('a') as lock, use_cron_store(data_dir):
            fcntl.flock(lock, fcntl.LOCK_EX)
            wrapper = write_wrapper(data_dir, key, script)
            existing = next((j for j in list_jobs(include_disabled=True)
                             if j.get('id') == key or (j.get('origin') or {}).get('kit_job') == key), None)
            if existing:
                # Register again to recover a previous provider-registration failure. Do not
                # re-enable a job intentionally paused by the operator.
                if existing.get('enabled', True):
                    resolve_cron_scheduler().register_job(existing)
                return False, f'{name}: 이미 등록되어 있습니다'
            create_job_with_scheduler_registration(
                prompt='', name=name, schedule=schedule, script=str(wrapper),
                no_agent=True, workdir=str(data_dir), deliver=deliver,
                failure_deliver='auto', origin={'owner': 'plugin:kit-setup', 'kit_job': key})
        return True, f'{name}: 등록 완료'
    except Exception as exc:
        return False, f'{name}: 등록 실패 ({type(exc).__name__})'


def install_all(data_dir):
    import backup
    import updates
    return [backup.install_cron(data_dir), updates.install_cron(data_dir)]
