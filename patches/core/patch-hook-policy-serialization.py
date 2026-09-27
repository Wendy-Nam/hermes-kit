#!/usr/bin/env python3
"""Patch PluginManager policy-hook overlap handling without spawning duplicate workers.

The existing overlap patch keeps observers fail-open on concurrent overlap. This
patch changes policy hooks only: a second ``pre_tool_call`` waits for the first
callback to finish within its own timeout budget, then runs the second request.
If the first worker remains hung through that deadline, normal fail-closed
timeout handling returns the block directive. A timed-out worker remains
registered until its thread really exits, bounding each callback to one worker.

hermes-kit: ported from the author's server (2026-09-26). It matters for students
because the OMH pre_tool_call hook is a policy hook. The image build runs it with no
arguments (apply to /opt/hermes); `--dry-run` prints the diff. Requires
patch-hook-overlap-skip first.
"""
from __future__ import annotations

import argparse
import difflib
import os
import shutil
import tempfile
from pathlib import Path


RESERVATION_OLD = '''        callback_name = getattr(cb, "__name__", repr(cb))
        callback_key = (hook_name, id(cb))
        token = object()
        with self._hook_timeout_lock:
            suppressed_until = self._hook_timeout_suppressed_until.get(callback_key)
            running = callback_key in self._hook_running_callbacks
            timed_out = suppressed_until is not None and suppressed_until > time.monotonic()
            if timed_out or running:
                logger.warning(
                    "Hook '%s' callback %s skipped: %s",
                    hook_name,
                    callback_name,
                    ("previous timeout (suppressed)" if timed_out
                     else "still running (concurrent overlap — false positive, not blocking)"))
                # Local patch: fail closed ONLY for a genuine timeout. Overlap means the
                # same callback is legitimately running in another session.
                return _HOOK_SKIPPED if timed_out else _HOOK_SKIPPED_OVERLAP
            if suppressed_until is not None:
                self._hook_timeout_suppressed_until.pop(callback_key, None)
            self._hook_running_callbacks[callback_key] = token
'''

RESERVATION_NEW = '''        callback_name = getattr(cb, "__name__", repr(cb))
        callback_key = (hook_name, id(cb))
        started_at = time.monotonic()
        waited_for_policy_overlap = False

        # A callback key owns at most one worker. Observers retain the local
        # overlap-skip behavior; policy calls wait on the live worker event.
        while True:
            token = object()
            done = threading.Event()
            overlap_event = None
            running_without_event = False
            with self._hook_timeout_lock:
                suppressed = getattr(self, "_hook_running_callback_events", None)
                if suppressed is None:
                    suppressed = {}
                    self._hook_running_callback_events = suppressed
                suppressed_until = self._hook_timeout_suppressed_until.get(callback_key)
                running = callback_key in self._hook_running_callbacks
                timed_out = suppressed_until is not None and suppressed_until > time.monotonic()
                if running:
                    overlap_event = suppressed.get(callback_key)
                    running_without_event = overlap_event is None
                elif timed_out and not waited_for_policy_overlap:
                    logger.warning(
                        "Hook '%s' callback %s skipped after previous timeout (suppressed)",
                        hook_name, callback_name)
                    return _HOOK_SKIPPED
                else:
                    if timeout - (time.monotonic() - started_at) <= 0:
                        logger.warning(
                            "Hook '%s' callback %s exhausted its timeout before worker start — blocking",
                            hook_name, callback_name)
                        return _HOOK_SKIPPED
                    if suppressed_until is not None:
                        self._hook_timeout_suppressed_until.pop(callback_key, None)
                    self._hook_running_callbacks[callback_key] = token
                    suppressed[callback_key] = done
                    break

            if hook_name in _HOOK_TIMEOUT_FAIL_CLOSED_HOOKS:
                remaining = timeout - (time.monotonic() - started_at)
                if (running_without_event or overlap_event is None
                        or not overlap_event.wait(timeout=max(0.0, remaining))):
                    logger.warning(
                        "Hook '%s' callback %s overlap wait timed out after %gs — blocking",
                        hook_name, callback_name, timeout)
                    return _HOOK_SKIPPED
                # The earlier callback has completed. Permit this request to run
                # even if that earlier worker had recorded a timeout suppression.
                with self._hook_timeout_lock:
                    self._hook_timeout_suppressed_until.pop(callback_key, None)
                waited_for_policy_overlap = True
                if time.monotonic() - started_at >= timeout:
                    return _HOOK_SKIPPED
                continue

            logger.warning(
                "Hook '%s' callback %s skipped: still running (concurrent overlap — false positive, not blocking)",
                hook_name, callback_name)
            return _HOOK_SKIPPED_OVERLAP
'''

DONE_SETUP_OLD = '''        context = contextvars.copy_context()
        done = threading.Event()
        outcome: Dict[str, Any] = {}
'''
DONE_SETUP_NEW = '''        context = contextvars.copy_context()
        outcome: Dict[str, Any] = {}
'''

RELEASE_OLD = '''        def _release_token() -> None:
            with self._hook_timeout_lock:
                if self._hook_running_callbacks.get(callback_key) is token:
                    self._hook_running_callbacks.pop(callback_key, None)
'''
RELEASE_NEW = '''        def _release_token() -> None:
            with self._hook_timeout_lock:
                if self._hook_running_callbacks.get(callback_key) is token:
                    self._hook_running_callbacks.pop(callback_key, None)
                events = getattr(self, "_hook_running_callback_events", {})
                if events.get(callback_key) is done:
                    events.pop(callback_key, None)
'''

TIMEOUT_OLD = '''                # Local patch: the worker is abandoned, not joined, so drop its running
                # slot now — a worker that never returns must not pin the key forever
                # (the suppression window above guards re-entry). Inline pop, NOT
                # _release_token() (it re-acquires this non-reentrant lock).
                if self._hook_running_callbacks.get(callback_key) is token:
                    self._hook_running_callbacks.pop(callback_key, None)
'''
TIMEOUT_NEW = '''                # Keep the timed-out worker represented until its finally block exits.
                # The older overlap patch said it "must not pin the key forever"; clearing
                # this live slot would instead allow repeated calls to spawn unbounded
                # hung workers. The suppression marker still makes timeout outcomes clear.
'''

THREAD_START_OLD = '''        thread = threading.Thread(target=_runner, name=f"hermes-hook-{callback_name}"[:40], daemon=True)
        try:
            thread.start()
'''
THREAD_START_NEW = '''        thread = threading.Thread(target=_runner, name=f"hermes-hook-{callback_name}"[:40], daemon=True)
        # _POLICY_SERIALIZATION_DEADLINE_V2: waiting and execution share one budget.
        if timeout - (time.monotonic() - started_at) <= 0:
            _release_token()
            logger.warning(
                "Hook '%s' callback %s exhausted its timeout before worker start — blocking",
                hook_name, callback_name)
            return _HOOK_SKIPPED
        try:
            thread.start()
'''

WAIT_OLD = '''        if not done.wait(timeout=timeout):  # do not join — that would reintroduce the hang
'''
WAIT_NEW = '''        remaining = max(0.0, timeout - (time.monotonic() - started_at))
        if not done.wait(timeout=remaining):  # do not join — that would reintroduce the hang
'''

RESERVATION_DEADLINE_OLD = '''                else:
                    if suppressed_until is not None:
                        self._hook_timeout_suppressed_until.pop(callback_key, None)
                    self._hook_running_callbacks[callback_key] = token
'''
RESERVATION_DEADLINE_NEW = '''                else:
                    if timeout - (time.monotonic() - started_at) <= 0:
                        logger.warning(
                            "Hook '%s' callback %s exhausted its timeout before worker start — blocking",
                            hook_name, callback_name)
                        return _HOOK_SKIPPED
                    if suppressed_until is not None:
                        self._hook_timeout_suppressed_until.pop(callback_key, None)
                    self._hook_running_callbacks[callback_key] = token
'''

POLICY_OVERLAP_OLD = '''                    if ret is _HOOK_SKIPPED_OVERLAP:
                        continue  # local patch: overlap is a false positive — skip without blocking
'''
POLICY_OVERLAP_NEW = '''                    if ret is _HOOK_SKIPPED_OVERLAP:
                        # The original local patch's phrase remains for safe reapplication.
                        if fail_closed:
                            results.append({"action": "block", "message": _PRE_TOOL_CALL_TIMEOUT_BLOCK_MESSAGE})
                        continue  # local patch: overlap is a false positive for observers; policy waited or blocks
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one exact anchor, found {count}")
    return source.replace(old, new, 1)


def patch_source(source: str) -> str:
    """Return patched source; require the installed overlap patch baseline."""
    if "_POLICY_SERIALIZATION_DEADLINE_V2" in source:
        return source
    if "_hook_running_callback_events" in source and "waited_for_policy_overlap" in source:
        # Upgrade the first serialization-patch revision in place if a dry run
        # or deployment used it before the shared-deadline review adjustment.
        result = replace_once(source, RESERVATION_DEADLINE_OLD,
                              RESERVATION_DEADLINE_NEW, "reservation deadline upgrade")
        result = replace_once(result, THREAD_START_OLD, THREAD_START_NEW, "worker start deadline")
        result = replace_once(result, WAIT_OLD, WAIT_NEW, "callback remaining timeout")
        compile(result, "hermes_cli/plugins_dispatch.py", "exec")
        return result
    if "_HOOK_SKIPPED_OVERLAP" not in source or "concurrent overlap" not in source:
        raise ValueError("expected patch-hook-overlap-skip baseline; apply that patch first")
    result = replace_once(source, RESERVATION_OLD, RESERVATION_NEW, "worker reservation")
    result = replace_once(result, DONE_SETUP_OLD, DONE_SETUP_NEW, "completion event")
    result = replace_once(result, RELEASE_OLD, RELEASE_NEW, "worker release")
    result = replace_once(result, TIMEOUT_OLD, TIMEOUT_NEW, "timeout occupancy")
    result = replace_once(result, POLICY_OVERLAP_OLD, POLICY_OVERLAP_NEW, "policy overlap fallback")
    result = replace_once(result, THREAD_START_OLD, THREAD_START_NEW, "worker start deadline")
    result = replace_once(result, WAIT_OLD, WAIT_NEW, "callback remaining timeout")
    compile(result, "hermes_cli/plugins_dispatch.py", "exec")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=Path("/opt/hermes"), type=Path,
                        help="Hermes installation root containing hermes_cli/plugins_dispatch.py")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate and print the proposed diff")
    mode.add_argument("--apply", action="store_true", help="validate, back up, then atomically write")
    args = parser.parse_args()
    root = args.root.resolve()
    target = (root / "hermes_cli" / "plugins_dispatch.py").resolve()
    if root not in target.parents or not target.is_file():
        parser.error(f"target not found beneath --root: {target}")

    original = target.read_text(encoding="utf-8")
    try:
        updated = patch_source(original)
        compile(updated, str(target), "exec")
    except (ValueError, SyntaxError) as exc:
        parser.error(str(exc))
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=str(target), tofile=str(target) + " (patched)"))
    if args.dry_run:
        print(diff or "Already patched; no changes.")
        return 0
    if not diff:
        print("Already patched; no changes.")
        return 0

    fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, target.stat().st_mode)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print(f"Patched {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
