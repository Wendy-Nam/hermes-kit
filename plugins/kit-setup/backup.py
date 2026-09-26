"""Weekly backup of the things a student would miss, and nothing else.

The exclusion list is the whole point: .env, auth.json and messenger sessions hold keys and
live logins. A backup that quietly swept them up would be a plaintext key archive sitting in a
vault that syncs to a laptop. Keys are re-entered through /setup instead.

Runs from a cron with no_agent: true, so it never spends tokens and never fails the job.
"""
import logging
import tarfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

# What is worth restoring if the VPS dies: notes, config, the persona, the schedule.
INCLUDE = ("memories", "config.yaml", "SOUL.md", "cron", "profiles", "vaults")
# Never, under any circumstance. Checked against every path in the archive, not just the top.
EXCLUDE_NAMES = {".env", "auth.json", ".env.backup", "auth_tokens.json", "sessions",
                 "cookies.json", "credentials.json", "auth", "executors"}
KEEP = 4


def _excluded(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in EXCLUDE_NAMES or p.endswith(".env") for p in parts)


def build(data_dir: Path, dest: Path) -> tuple[bool, str]:
    """Write one dated tarball and prune the old ones. Returns (ok, message)."""
    data_dir, dest = Path(data_dir), Path(dest)
    if not data_dir.is_dir():
        return False, f"데이터 디렉터리가 없습니다: {data_dir}"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    out = dest / f"{stamp}.tar.gz"
    if out.exists():
        return False, f"오늘 백업이 이미 있습니다: {out.name}"

    members, skipped = 0, 0
    try:
        with tarfile.open(out, "w:gz") as tf:
            for name in INCLUDE:
                src = data_dir / name
                if not src.exists():
                    continue
                for f in ([src] if src.is_file() else sorted(src.rglob("*"))):
                    if not f.is_file():
                        continue
                    rel = f.relative_to(data_dir)
                    if _excluded(str(rel)):
                        skipped += 1
                        continue
                    tf.add(f, arcname=str(rel), recursive=False)
                    members += 1
    except Exception as e:
        out.unlink(missing_ok=True)      # never leave a truncated archive that looks valid
        log.warning("backup failed: %s", e)
        return False, f"백업 실패: {type(e).__name__}"

    if members == 0:
        out.unlink(missing_ok=True)
        return False, "백업할 파일이 없습니다"

    for old in sorted(dest.glob("*.tar.gz"), reverse=True)[KEEP:]:
        old.unlink(missing_ok=True)
    kb = out.stat().st_size // 1024
    note = f" (키·로그인 {skipped}개 제외)" if skipped else ""
    return True, f"백업 완료: {out.name} ({members}개 파일, {kb}KB){note}"


def install_cron(data_dir: Path) -> tuple[bool, str]:
    """Register the weekly no-agent job. Idempotent: re-running does not duplicate it."""
    import json

    jobs_file = Path(data_dir) / "cron" / "jobs.json"
    jobs_file.parent.mkdir(parents=True, exist_ok=True)
    jobs = json.loads(jobs_file.read_text()) if jobs_file.exists() else []
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", [])
    if any(j.get("id") == "kit-backup" for j in jobs):
        return False, "백업 크론이 이미 있습니다"
    jobs.append({
        "id": "kit-backup",
        "name": "hermes-kit 주간 백업",
        "schedule": "0 4 * * 1",          # Monday 04:00 local
        "no_agent": True,                 # LLM을 쓰지 않는다 — 토큰도, 실패도 없다
        "command": f"{Path(__file__).with_name('backup.py')}",
    })
    jobs_file.write_text(json.dumps(jobs, ensure_ascii=False, indent=2))
    return True, "주간 백업 크론을 등록했습니다 (월요일 04:00, LLM 미사용)"
