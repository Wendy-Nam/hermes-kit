#!/usr/bin/env python3
"""Safe manual-run and opt-in scheduler operations for Hermes Outbound Kit.

Planning is the default.  Persistent jobs are only changed by ``install --apply``
or ``disable --apply`` after a matching manual workflow success exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform as host_platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import kit


ROOT = Path(__file__).resolve().parent
STATE_VERSION = 1
TASK_NAME = "HermesOutbound"
SYSTEMD_STEM = "hermes-outbound"
LAUNCHD_LABEL = "com.hermes.outbound"
SCHEDULE_FIELDS = {"schedule_enabled", "schedule_frequency", "schedule_time", "timezone"}
RUNTIME_FIELDS = {"drafts_path"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f"상태 경로의 심볼릭 링크는 허용하지 않습니다: {path}")
    fd, temporary = tempfile.mkstemp(prefix=".operations-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_config(path: str | Path) -> dict:
    raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8-sig"))
    try:
        data = kit.validate(raw)
    except ValueError:
        # Transitional compatibility while the root schema and this helper land
        # together: only the three explicitly owned schedule fields may be
        # removed before validating the existing kit fields.
        if not isinstance(raw, dict) or set(raw) - set(kit.FIELDS) - SCHEDULE_FIELDS - RUNTIME_FIELDS:
            raise
        kit.validate({key: value for key, value in raw.items()
                      if key not in SCHEDULE_FIELDS and key not in RUNTIME_FIELDS})
        data = raw
    enabled = data.get("schedule_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("schedule_enabled: true/false 값이 필요합니다.")
    if data.get("schedule_frequency", "daily") not in {"daily", "hourly"}:
        raise ValueError("schedule_frequency: daily/hourly 중 선택하세요.")
    schedule_time = data.get("schedule_time", "09:00") or "09:00"
    if not isinstance(schedule_time, str) or not __import__("re").fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", schedule_time):
        raise ValueError("schedule_time: 예를 들어 09:00처럼 입력하세요.")
    tz_name = data.get("timezone", "Asia/Seoul")
    if not isinstance(tz_name, str) or len(tz_name) > 100:
        raise ValueError("timezone: IANA timezone 이름이 필요합니다.")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("timezone: 시스템이 인식하는 IANA timezone 이름이 필요합니다.") from None
    return data


def canonical_contract(config: str | Path, home: str | Path, output: str | Path,
                       vault: str | Path, workflow: str | Path | None = None) -> dict:
    paths = {
        "config": Path(config).expanduser().resolve(),
        "home": Path(home).expanduser().resolve(),
        "output": Path(output).expanduser().resolve(),
        "vault": Path(vault).expanduser().resolve(),
        "workflow": Path(workflow or ROOT / "workflow.py").expanduser().resolve(),
    }
    config_bytes = paths["config"].read_bytes()
    data = load_config(paths["config"])
    def optional_path(field: str) -> str:
        value = data.get(field, "")
        if not value:
            return ""
        path = Path(value).expanduser()
        # workflow.py runs from ROOT; make that behavior explicit and stable in
        # the scheduler rather than relying on a future service cwd.
        return str((path if path.is_absolute() else ROOT / path).resolve())
    run_options = {
        "scenario": data.get("scenario", "") or "",
        "source_mode": data.get("source_mode", "sample") or "sample",
        "source_path": optional_path("source_path"),
        "draft_mode": data.get("draft_mode", "template") or "template",
        "drafts_path": optional_path("drafts_path"),
    }
    if run_options["source_mode"] == "file" and not run_options["source_path"]:
        raise ValueError("source_mode=file에는 source_path가 필요합니다.")
    if run_options["draft_mode"] == "provided" and not run_options["drafts_path"]:
        raise ValueError("draft_mode=provided에는 drafts_path가 필요합니다.")
    contract = {
        "schema_version": 1,
        "python": str(Path(sys.executable).resolve()),
        **{key: str(value) for key, value in paths.items()},
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "run_options": run_options,
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    contract["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
    return contract


def workflow_argv(contract: dict) -> list[str]:
    """The exact workflow.py CLI contract; never invoke through a shell."""
    argv = [
        contract["python"], contract["workflow"], "run",
        "--config", contract["config"], "--home", contract["home"],
        "--output", contract["output"], "--vault", contract["vault"],
    ]
    options = contract["run_options"]
    if options["scenario"]:
        argv.extend(["--scenario", options["scenario"]])
    argv.extend(["--source-mode", options["source_mode"]])
    if options["source_path"]:
        argv.extend(["--source-path", options["source_path"]])
    argv.extend(["--draft-mode", options["draft_mode"]])
    if options["drafts_path"]:
        argv.extend(["--drafts-file", options["drafts_path"]])
    return argv


def scheduler_argv(contract: dict, state_dir: str | Path) -> list[str]:
    return [
        contract["python"], str(Path(__file__).resolve()), "run-once",
        "--config", contract["config"], "--home", contract["home"],
        "--output", contract["output"], "--vault", contract["vault"],
        "--state-dir", str(Path(state_dir).expanduser().resolve()), "--scheduled",
    ]


def _platform(value: str | None = None) -> str:
    if value:
        return value
    return {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
        host_platform.system(), "unsupported")


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def render_descriptor(kind: str, argv: list[str], frequency: str, tz_name: str,
                      schedule_time: str = "09:00",
                      working_dir: str | Path = ROOT) -> tuple[str, str]:
    hour, minute = (int(value) for value in schedule_time.split(":"))
    if kind == "linux":
        service = "\n".join([
            "[Unit]", "Description=Hermes Outbound one-shot workflow", "",
            "[Service]", "Type=oneshot", f"WorkingDirectory={_systemd_quote(str(working_dir))}",
            f"Environment={_systemd_quote('TZ=' + tz_name)}",
            "ExecStart=" + " ".join(_systemd_quote(item) for item in argv), "",
        ])
        timer = "\n".join([
            "[Unit]", "Description=Hermes Outbound interval schedule", "",
            "[Timer]", (f"OnCalendar=*-*-* *:{minute:02d}:00 {tz_name}" if frequency == "hourly" else
                        f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00 {tz_name}"),
            "Persistent=true",
            f"Unit={SYSTEMD_STEM}.service", "", "[Install]", "WantedBy=timers.target", "",
        ])
        return service, timer
    if kind == "darwin":
        payload = {
            "Label": LAUNCHD_LABEL,
            "ProgramArguments": argv,
            "WorkingDirectory": str(working_dir),
            "EnvironmentVariables": {"TZ": tz_name},
            "StartCalendarInterval": ({"Minute": minute} if frequency == "hourly" else
                                      {"Hour": hour, "Minute": minute}),
            "RunAtLoad": False,
            "ProcessType": "Background",
        }
        return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True).decode(), ""
    if kind == "windows":
        arguments = subprocess.list2cmdline(argv[1:])
        xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Hermes Outbound interval workflow</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2026-01-01T{hour:02d}:{minute:02d}:00</StartBoundary><Enabled>true</Enabled>
    <Repetition><Interval>{"PT1H" if frequency == "hourly" else "PT24H"}</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
  </TimeTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT1H</ExecutionTimeLimit></Settings>
  <Actions Context="Author"><Exec><Command>{xml_escape(argv[0])}</Command><Arguments>{xml_escape(arguments)}</Arguments><WorkingDirectory>{xml_escape(str(working_dir))}</WorkingDirectory></Exec></Actions>
</Task>'''
        return xml, ""
    raise ValueError(f"지원하지 않는 scheduler platform: {kind}")


def descriptor_paths(kind: str) -> tuple[Path, Path | None]:
    user_home = Path.home()
    if kind == "linux":
        base = user_home / ".config" / "systemd" / "user"
        return base / f"{SYSTEMD_STEM}.service", base / f"{SYSTEMD_STEM}.timer"
    if kind == "darwin":
        return user_home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist", None
    if kind == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", user_home / "AppData" / "Local")) / "HermesOutbound"
        return base / "HermesOutbound.xml", None
    raise ValueError(f"지원하지 않는 scheduler platform: {kind}")


def build_plan(config_path: str | Path, home: str | Path, output: str | Path,
               vault: str | Path, state_dir: str | Path, kind: str | None = None) -> dict:
    data = load_config(config_path)
    contract = canonical_contract(config_path, home, output, vault)
    resolved_kind = _platform(kind)
    command = scheduler_argv(contract, state_dir)
    first, second = render_descriptor(
        resolved_kind, command, data.get("schedule_frequency", "daily"),
        data.get("timezone", "Asia/Seoul"),
        data.get("schedule_time", "09:00") or "09:00",
    )
    target, second_target = descriptor_paths(resolved_kind)
    return {
        "schema_version": 1,
        "action": "plan",
        "changes_applied": False,
        "schedule_enabled": data.get("schedule_enabled", False),
        "frequency": data.get("schedule_frequency", "daily"),
        "schedule_time": data.get("schedule_time", "09:00") or "09:00",
        "timezone": data.get("timezone", "Asia/Seoul"),
        "platform": resolved_kind,
        "execution_location": data.get("install_location", "local"),
        "contract": contract,
        "workflow": {"label": "agentoutbound:run", "argv": workflow_argv(contract)},
        "scheduler": {
            "argv": command,
            "targets": [str(path) for path in (target, second_target) if path],
            "descriptor_sha256": [hashlib.sha256(text.encode()).hexdigest()
                                  for text in (first, second) if text],
        },
        "gateway_lifecycle": {
            "implemented_by": "Hermes v0.21.7 CLI help; not executed by operations.py",
            "environment": {"HERMES_HOME": contract["home"]},
            "foreground": ["hermes", "gateway", "run"],
            "service_commands": [["hermes", "gateway", verb]
                                 for verb in ("install", "start", "status", "stop")],
        },
        "gates": [
            "run-once must complete successfully with this exact contract",
            "install must be called explicitly with --apply",
            "an existing differing scheduler is preserved",
        ],
        "platform_time_note": ("systemd OnCalendar includes the configured IANA timezone"
                               if resolved_kind == "linux" else
                               "launchd/Task Scheduler trigger uses the host timezone; verify it matches the configured timezone"),
        "descriptor_preview": [first, second] if second else [first],
    }


class RunLock:
    def __init__(self, path: Path):
        self.path = path
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RuntimeError("workflow already running or a stale lock requires review") from None
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "started_at": _now()}, stream)
        self.held = True
        return self

    def __exit__(self, *_):
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser().resolve() / "operations.json"


def read_state(state_dir: str | Path) -> dict:
    path = _state_path(state_dir)
    if not path.exists():
        return {"schema_version": STATE_VERSION}
    if path.is_symlink():
        raise ValueError("운영 상태 파일이 심볼릭 링크입니다.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != STATE_VERSION:
        raise ValueError("운영 상태 receipt 형식이 잘못되었습니다.")
    return value


def _append_log(state_dir: str | Path, event: dict) -> None:
    """Keep only metadata, never subprocess output, command lines, or config values."""
    path = Path(state_dir).expanduser().resolve() / "operations.log.jsonl"
    rows: list[str] = []
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("운영 로그 경로의 심볼릭 링크는 허용하지 않습니다.")
    if path.exists():
        rows = path.read_text(encoding="utf-8").splitlines()[-99:]
    safe = {key: event[key] for key in ("at", "event", "status", "exit_code") if key in event}
    rows.append(json.dumps(safe, separators=(",", ":")))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".operations-log-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(rows) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_once(config_path: str | Path, home: str | Path, output: str | Path,
             vault: str | Path, state_dir: str | Path, *, scheduled: bool = False,
             timeout: int = 3600, runner=subprocess.run) -> dict:
    data = load_config(config_path)
    if data.get("install_location", "local") == "remote":
        raise ValueError("remote 설치 계획을 이 기기에서 실행하지 않습니다. 서버 배포 후 서버의 local 설정으로 실행하세요.")
    contract = canonical_contract(config_path, home, output, vault)
    state_path = _state_path(state_dir)
    lock_path = state_path.parent / "workflow.lock"
    attempt = {"at": _now(), "contract_sha256": contract["contract_sha256"],
               "manual": not scheduled, "status": "running"}
    state = read_state(state_dir)
    state["last_attempt"] = attempt
    _atomic_json(state_path, state)
    _append_log(state_dir, {"at": attempt["at"], "event": "run", "status": "started"})
    try:
        with RunLock(lock_path):
            completed = runner(
                workflow_argv(contract), cwd=ROOT, timeout=timeout,
                stdin=subprocess.DEVNULL if scheduled else None,
                stdout=subprocess.DEVNULL if scheduled else None,
                stderr=subprocess.DEVNULL if scheduled else None,
                check=False,
            )
            code = int(completed.returncode)
    except subprocess.TimeoutExpired:
        code = 124
        status = "timeout"
    except RuntimeError:
        code = 75
        status = "overlap_blocked"
    except OSError:
        code = 1
        status = "launch_failed"
    else:
        status = "succeeded" if code == 0 else "failed"
    attempt = {**attempt, "finished_at": _now(), "status": status, "exit_code": code}
    state = read_state(state_dir)
    state["last_attempt"] = attempt
    if status == "succeeded":
        state["last_success"] = attempt
    _atomic_json(state_path, state)
    _append_log(state_dir, {"at": attempt["finished_at"], "event": "run", "status": status, "exit_code": code})
    return attempt


def _matching_manual_success(state: dict, contract: dict) -> bool:
    success = state.get("last_success") or {}
    return (success.get("status") == "succeeded" and success.get("manual") is True
            and success.get("contract_sha256") == contract["contract_sha256"])


def _write_preserving(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"기존 scheduler 링크를 보존했습니다: {path}")
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"기존 scheduler가 달라 보존했습니다: {path}")
        return "unchanged"
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
    return "created"


def install_schedule(plan: dict, state_dir: str | Path, *, apply: bool = False,
                     run_command=subprocess.run) -> dict:
    if plan.get("execution_location") == "remote":
        raise ValueError("remote 설치 계획에는 로컬 scheduler를 등록하지 않습니다. 서버 배포 후 서버에서 다시 plan하세요.")
    if not plan["schedule_enabled"]:
        raise ValueError("schedule_enabled=false: 자동 실행을 설치하지 않습니다.")
    state = read_state(state_dir)
    if not _matching_manual_success(state, plan["contract"]):
        raise ValueError("동일 config와 <KIT_HOME>/vault의 수동 run-once 성공 receipt가 먼저 필요합니다.")
    result = {"action": "install", "applied": False, "platform": plan["platform"],
              "targets": plan["scheduler"]["targets"]}
    if not apply:
        result["status"] = "planned_requires_explicit_apply"
        return result
    if plan["platform"] != _platform():
        raise ValueError("다른 OS용 scheduler는 이 기기에서 등록하지 않습니다.")
    descriptors = plan["descriptor_preview"]
    paths = [Path(item) for item in plan["scheduler"]["targets"]]
    if plan["platform"] == "windows":
        existing = run_command(
            ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/XML"],
            check=False, capture_output=True, text=True,
        )
        recorded = state.get("scheduler") or {}
        if existing.returncode == 0 and not (
            recorded.get("status") == "installed"
            and recorded.get("contract_sha256") == plan["contract"]["contract_sha256"]
        ):
            raise ValueError("기존 Windows Task가 다른 소유/계약일 수 있어 보존했습니다.")
        if existing.returncode not in (0, 1):
            raise RuntimeError(f"기존 Windows Task 확인 실패: exit {existing.returncode}")
    writes = [_write_preserving(path, content) for path, content in zip(paths, descriptors)]
    if plan["platform"] == "linux":
        commands = [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_STEM}.timer"],
        ]
    elif plan["platform"] == "darwin":
        commands = [["launchctl", "bootstrap", f"gui/{os.getuid()}", str(paths[0])]]
    else:
        commands = [["schtasks.exe", "/Create", "/TN", TASK_NAME, "/XML", str(paths[0]), "/F"]]
    for command in commands:
        completed = run_command(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"scheduler 등록 실패: {command[0]} exit {completed.returncode}")
    result.update(applied=True, status="installed", writes=writes)
    state["scheduler"] = {"status": "installed", "at": _now(),
                          "contract_sha256": plan["contract"]["contract_sha256"],
                          "platform": plan["platform"], "targets": result["targets"]}
    _atomic_json(_state_path(state_dir), state)
    return result


def disable_schedule(plan: dict, state_dir: str | Path, *, apply: bool = False,
                     run_command=subprocess.run) -> dict:
    result = {"action": "disable", "applied": False, "platform": plan["platform"],
              "targets": plan["scheduler"]["targets"]}
    if not apply:
        result["status"] = "planned_requires_explicit_apply"
        return result
    if plan["platform"] != _platform():
        raise ValueError("다른 OS용 scheduler는 이 기기에서 해제하지 않습니다.")
    paths = [Path(item) for item in result["targets"]]
    expected = plan["descriptor_preview"]
    state = read_state(state_dir)
    for path, content in zip(paths, expected):
        if path.exists() and (path.is_symlink() or path.read_text(encoding="utf-8") != content):
            raise ValueError(f"다른 scheduler 파일을 보존했습니다: {path}")
    if plan["platform"] == "linux":
        commands = [["systemctl", "--user", "disable", "--now", f"{SYSTEMD_STEM}.timer"]]
    elif plan["platform"] == "darwin":
        commands = [["launchctl", "bootout", f"gui/{os.getuid()}", str(paths[0])]]
    else:
        recorded = state.get("scheduler") or {}
        if not (recorded.get("status") == "installed"
                and recorded.get("contract_sha256") == plan["contract"]["contract_sha256"]):
            raise ValueError("이 계약으로 설치했다는 receipt가 없어 기존 Windows Task를 보존했습니다.")
        commands = [["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"]]
    for command in commands:
        completed = run_command(command, check=False, capture_output=True, text=True)
        if completed.returncode not in (0, 1):
            raise RuntimeError(f"scheduler 해제 실패: {command[0]} exit {completed.returncode}")
    for path in paths:
        if path.exists():
            path.unlink()
    state["scheduler"] = {"status": "disabled", "at": _now(), "platform": plan["platform"]}
    _atomic_json(_state_path(state_dir), state)
    result.update(applied=True, status="disabled")
    return result


def operation_status(plan: dict, state_dir: str | Path) -> dict:
    state = read_state(state_dir)
    targets = []
    for path_text, expected in zip(plan["scheduler"]["targets"], plan["descriptor_preview"]):
        path = Path(path_text)
        targets.append({"path": str(path), "status": "missing" if not path.exists() else
                        ("matching" if not path.is_symlink() and path.read_text(encoding="utf-8") == expected else "different_preserved")})
    return {"schema_version": 1, "platform": plan["platform"], "targets": targets,
            "last_attempt": state.get("last_attempt"), "last_success": state.get("last_success"),
            "scheduler": state.get("scheduler", {"status": "not_installed"})}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Outbound manual run and opt-in scheduler helper")
    parser.add_argument("action", choices=["plan", "run-once", "install", "status", "disable"])
    parser.add_argument("--config", default=str(ROOT / "setup.json"))
    parser.add_argument("--home", default=str(Path.home() / ".hermes-outbound"))
    parser.add_argument("--output", default=str(ROOT / "output"))
    parser.add_argument("--vault")
    parser.add_argument("--state-dir")
    parser.add_argument("--platform", choices=["linux", "darwin", "windows"])
    parser.add_argument("--apply", action="store_true", help="explicitly register/remove the persistent scheduler")
    parser.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve() if args.vault else home / "vault"
    state_dir = Path(args.state_dir).expanduser().resolve() if args.state_dir else home / ".operations"
    try:
        plan = build_plan(args.config, home, args.output, vault, state_dir, args.platform)
        if args.action == "plan":
            result = plan
        elif args.action == "run-once":
            result = run_once(args.config, home, args.output, vault, state_dir,
                              scheduled=args.scheduled, timeout=args.timeout)
        elif args.action == "install":
            result = install_schedule(plan, state_dir, apply=args.apply)
        elif args.action == "disable":
            result = disable_schedule(plan, state_dir, apply=args.apply)
        else:
            result = operation_status(plan, state_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "run-once" and result["status"] != "succeeded":
            return result["exit_code"] or 1
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
