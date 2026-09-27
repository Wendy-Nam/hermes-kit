#!/usr/bin/env python3
"""Never record an iteration-limit fallback as successful cron completion."""
from pathlib import Path
import argparse, os, py_compile, shutil, tempfile, time
MARKER = "hermes-kit: incomplete cron fallback is failure"
OLD = '''    if max_iteration_summary:
        logger.warning(
            "Job '%s' reached the iteration limit but produced a final fallback response; "
            "delivering the response instead of failing the cron run",
            job_name)
'''
NEW = '''    if max_iteration_summary:
        # hermes-kit: incomplete cron fallback is failure; retain the useful partial report.
        raise RuntimeError(
            f"Cron incomplete: {turn_exit_reason}. Partial report: {final_response_text}")
'''
def patch(source):
    if MARKER in source:
        if NEW not in source:
            raise RuntimeError("partial cron outcome patch detected")
        return source
    if source.count(OLD) != 1:
        raise RuntimeError("cron fallback anchor drift")
    return source.replace(OLD, NEW, 1)
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('/opt/hermes'))
    parser.add_argument('--check', action='store_true', help='Validate without applying')
    args=parser.parse_args()
    target=args.root/'cron/scheduler.py'
    original=target.read_text(); updated=patch(original)
    if updated==original:
        print('already patched'); return
    compile(updated,str(target),'exec')
    if args.check:
        print('patch ready'); return
    with tempfile.NamedTemporaryFile(dir=target.parent,suffix='.py',delete=False,mode='w') as f:
        temporary=Path(f.name); f.write(updated)
    try:
        py_compile.compile(str(temporary),doraise=True)
        shutil.copystat(target,temporary)
        st=target.stat(); os.chown(temporary,st.st_uid,st.st_gid)
        shutil.copy2(target,str(target)+'.bak-'+str(time.time_ns())+'-iteration-outcome')
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)
    print('patched cron iteration outcome')
if __name__=='__main__': main()
