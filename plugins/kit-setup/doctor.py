"""Self-diagnosis, with no LLM in the loop.

A student who is stuck sends this to their instructor. Two consequences shape the design:
the output must not contain a key, a token, a channel id or an email, and it must name the
*cause* rather than dump a status list. "키가 거부됐습니다" is actionable; "gemini: FAIL" is not.

Every check is independent and returns a Finding, so one broken thing cannot hide the rest.
"""
import asyncio
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OK, WARN, BAD, SKIP = "ok", "warn", "bad", "skip"
ICON = {OK: "🟢", WARN: "🟡", BAD: "🔴", SKIP: "⚪"}


@dataclass
class Finding:
    name: str
    status: str
    detail: str

    def line(self) -> str:
        return f"{ICON[self.status]} **{self.name}** — {self.detail}"


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def check_kit_version(data_dir: Path) -> Finding:
    want = _read(Path("/opt/kit/VERSION")).strip()
    have = _read(data_dir / ".kit-version").strip()
    if not want:
        return Finding("키트 버전", SKIP, "판독할 수 없습니다")
    if not have:
        return Finding("키트 버전", WARN, f"시드 미완료 (이미지 {want})")
    if want != have:
        return Finding("키트 버전", WARN, f"이미지 {want} / 시드 {have} — Hostinger에서 재배포하세요")
    return Finding("키트 버전", OK, want)


def check_disk(data_dir: Path) -> Finding:
    try:
        used = shutil.disk_usage(data_dir)
    except OSError as e:
        return Finding("디스크", SKIP, f"확인 불가 ({type(e).__name__})")
    free_gb = used.free / 1024 ** 3
    pct = 100 * used.used / used.total if used.total else 0
    if free_gb < 1:
        return Finding("디스크", BAD, f"여유 {free_gb:.1f}GB — 로그와 백업을 확인하세요")
    if pct > 85:
        return Finding("디스크", WARN, f"{pct:.0f}% 사용, 여유 {free_gb:.1f}GB")
    return Finding("디스크", OK, f"여유 {free_gb:.1f}GB")


def check_env_file(env_file: Path) -> Finding:
    if not env_file.exists():
        return Finding("설정 파일", BAD, ".env 가 없습니다 — /setup 을 실행해 주세요")
    mode = os.stat(env_file).st_mode & 0o777
    if mode & 0o077:
        return Finding("설정 파일", BAD, f".env 권한이 {oct(mode)[2:]} — 600 이어야 합니다")
    return Finding("설정 파일", OK, ".env 존재, 권한 600")


def check_gateway(process) -> Finding:
    """`process` is a psutil-like object; None means the caller could not determine it."""
    if process is None:
        return Finding("게이트웨이", SKIP, "확인할 수 없습니다")
    if not getattr(process, "is_running", bool)():
        return Finding("게이트웨이", BAD, "가동 중이 아닙니다 — 컨테이너 로그를 확인하세요")
    try:
        age = int(time.time() - process.create_time())
    except Exception:
        return Finding("게이트웨이", OK, "가동 중")
    if age < 120:
        return Finding("게이트웨이", WARN, f"방금 재시작됨 ({age}초) — 설정 적용 중일 수 있습니다")
    return Finding("게이트웨이", OK, f"가동 중 ({age // 3600}시간 {(age % 3600) // 60}분)")


def check_keys(env: dict, env_file: Path) -> list[Finding]:
    """Re-run the Task 6 validators against stored keys. Values are never printed."""
    import validators as v

    from packs import load_packs

    out = []
    for pack in load_packs(v.VALIDATORS):
        if not pack.required:
            continue
        for spec in pack.keys:
            value = env.get(spec.env)
            if not value:
                out.append(Finding(spec.label, BAD, "키가 없습니다 — /setup 으로 입력해 주세요"))
                continue
            try:
                ok, msg = v.VALIDATORS[spec.validator](value)
            except Exception as e:
                out.append(Finding(spec.label, BAD, f"확인 중 오류 ({type(e).__name__})"))
                continue
            out.append(Finding(spec.label, OK if ok else BAD, msg))
    return out


def check_optional(url: str, name: str, timeout: int = 5) -> Finding:
    """Ping an optional add-on service. Absent is not an error — it just was not installed."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hermes-kit"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Finding(name, OK if r.status == 200 else WARN, f"HTTP {r.status}")
    except urllib.error.HTTPError as e:
        return Finding(name, WARN, f"HTTP {e.code}")
    except Exception:
        return Finding(name, SKIP, "설치되지 않았습니다 (선택 항목)")


# Every alternative is a way a secret leaks into a chat: a provider key shape, a Discord
# snowflake (channel id), an email, or a KEY=value pair. The (?i) flag has to sit at the very
# start of the pattern — inline mid-pattern it is a TypeError, not a no-op.
_SECRETISH = re.compile(
    r"(?i)"
    r"(?:sk-|gsk_|AIza|ghp_|xox[bp]-|apify_api_)[A-Za-z0-9_\-]{6,}"
    r"|\b\d{17,19}\b"                    # Discord snowflakes
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"      # IPv4 (the instructor's own server address)
    r"|[\w.+-]+@[\w-]+\.[\w.]+"         # emails
    r"|(?:token|key|secret|password)\s*[:=]\s*\S+",
)


def mask(text: str) -> str:
    """Redact anything that looks like a credential before the text leaves the machine."""
    return _SECRETISH.sub("`[가림]`", text)


def report(findings) -> str:
    worst = BAD if any(f.status == BAD for f in findings) else \
        WARN if any(f.status == WARN for f in findings) else OK
    body = "\n".join(f.line() for f in findings)
    return f"**hermes-kit 진단**\n{body}\n\n요약: {ICON[worst]} " + {
        BAD: "문제가 있습니다. 위의 🔴 항목부터 확인해 주세요.",
        WARN: "전부 정상은 아니지만 사용은 가능합니다.",
        OK: "모든 항목 정상입니다.",
    }[worst]


def copy_for_instructor(findings) -> str:
    """The same report as plain text, safe to paste into a chat with the instructor."""
    return mask("\n".join(f"{ICON[f.status]} {f.name}: {f.detail}" for f in findings))


def collect(data_dir: Path, env_file: Path, process=None) -> list[Finding]:
    """Run every check. Order is what a student reads first: setup, then keys, then extras."""
    from env_store import get_env

    env = get_env(env_file) if env_file.exists() else {}
    findings = [check_kit_version(data_dir), check_env_file(env_file), check_disk(data_dir),
                check_gateway(process)]
    findings += check_keys(env, env_file)
    findings.append(check_optional("http://freellmapi:3001/api/ping", "freellmapi 심화팩"))
    return findings


async def doctor_command(interaction, data_dir: Path, env_file: Path, process=None):
    """`/doctor` — ephemeral report, plus a copyable plain-text version for the instructor.

    Owner-only, same rule as /setup. The report is masked, but it still says which packs are
    configured and which keys the provider accepted, and every run re-checks those keys over
    the network. A guild member spamming it would burn the student's quota and rate limits.
    """
    from views import DoctorView

    import owner as owner_mod

    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("서버에서만 실행할 수 있습니다.", ephemeral=True)
        return
    if interaction.user.id != guild.owner_id and not owner_mod.is_approved(interaction.user.id):
        await interaction.response.send_message("이 서버의 소유자만 실행할 수 있습니다.",
                                                ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    findings = await asyncio.to_thread(collect, data_dir, env_file, process)
    await interaction.followup.send(report(findings)[:1900], view=DoctorView(findings),
                                   ephemeral=True)

