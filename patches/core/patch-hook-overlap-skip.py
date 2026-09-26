#!/usr/bin/env python3
"""Hermes hermes_cli/plugins_dispatch.py 로컬 패치 (이미지 레이어 — 컨테이너 재생성 시 재실행, root로).

배경: bounded 훅(pre_tool_call 등)은 같은 콜백의 동시 호출을 스킵하는데, upstream은
타임아웃과 동시호출(overlap)을 구분하지 않고 둘 다 fail-closed(=차단 지시)로 처리한다.
동시호출은 다른 세션에서 같은 콜백이 정상 실행 중인 경우라 stall이 아니라 오탐이다 —
이걸로 차단하면 멀쩡한 도구 호출이 막힌다(2026-09-18 실측 overlap 스킵 18k건/일,
그 안에 OMH 정책 훅 포함).

수정 3점 (v0.21.2 plugins_dispatch.py 기준):
1. overlap 스킵은 전용 센티넬 _HOOK_SKIPPED_OVERLAP 로 반환 → invoke_hook에서 무조건
   스킵(차단 지시 없음). 진짜 타임아웃만 fail-closed 유지.
2. 타임아웃으로 워커를 버릴 때 running 슬롯도 해제 (버려진 워커가 영원히 안 돌아오면
   키가 영구 pin됨 — suppression 윈도우가 재진입을 막으니 해제해도 안전).
   _release_token()은 락을 다시 잡아서(재진입 불가) 여기서 호출 금지, 인라인 pop.
3. 관련 docstring에 overlap 시맨틱 명시.

멱등.
"""
from pathlib import Path

p = Path("/opt/hermes/hermes_cli/plugins_dispatch.py")
s = p.read_text()

# --- 1. sentinel definition ---
sentinel_anchor = "_HOOK_SKIPPED = object()  # returned by _run_hook_callback_bounded on skip/timeout\n"
sentinel_add = (
    "_HOOK_SKIPPED_OVERLAP = object()  # local patch: overlap skip (concurrent same-callback\n"
    "# invocation elsewhere) is a false positive, not a stall — never fail-closed.\n"
)
if "_HOOK_SKIPPED_OVERLAP" in s:
    print("already patched (sentinel present)")
else:
    assert s.count(sentinel_anchor) == 1, "sentinel anchor not unique"
    s = s.replace(sentinel_anchor, sentinel_anchor + sentinel_add)
    print("patched (sentinel)")

# --- 2. overlap branch returns distinct sentinel ---
overlap_old = """            if (suppressed_until is not None and suppressed_until > time.monotonic()) or running:
                logger.warning(
                    "Hook '%s' callback %s skipped after previous "
                    "timeout or while still running", hook_name, callback_name)
                return _HOOK_SKIPPED"""
overlap_new = """            timed_out = suppressed_until is not None and suppressed_until > time.monotonic()
            if timed_out or running:
                logger.warning(
                    "Hook '%s' callback %s skipped: %s",
                    hook_name,
                    callback_name,
                    ("previous timeout (suppressed)" if timed_out
                     else "still running (concurrent overlap — false positive, not blocking)"))
                # Local patch: fail closed ONLY for a genuine timeout. Overlap means the
                # same callback is legitimately running in another session.
                return _HOOK_SKIPPED if timed_out else _HOOK_SKIPPED_OVERLAP"""
if "_HOOK_SKIPPED_OVERLAP" in s and "concurrent overlap" in s:
    print("already patched (overlap branch)")
else:
    assert s.count(overlap_old) == 1, "overlap anchor not unique"
    s = s.replace(overlap_old, overlap_new)
    print("patched (overlap branch)")

# --- 3. invoke_hook: overlap never blocks ---
invoke_old = """                    if ret is _HOOK_SKIPPED:
                        if fail_closed:  # policy hook: fail closed with a block directive
                            results.append({"action": "block", "message": _PRE_TOOL_CALL_TIMEOUT_BLOCK_MESSAGE})
                        continue"""
invoke_new = """                    if ret is _HOOK_SKIPPED_OVERLAP:
                        continue  # local patch: overlap is a false positive — skip without blocking
                    if ret is _HOOK_SKIPPED:
                        if fail_closed:  # policy hook: fail closed with a block directive
                            results.append({"action": "block", "message": _PRE_TOOL_CALL_TIMEOUT_BLOCK_MESSAGE})
                        continue"""
if "overlap is a false positive" in s:
    print("already patched (invoke_hook)")
else:
    assert s.count(invoke_old) == 1, "invoke_hook anchor not unique"
    s = s.replace(invoke_old, invoke_new)
    print("patched (invoke_hook)")

# --- 4. release running slot on timeout-abandon ---
timeout_old = """        if not done.wait(timeout=timeout):  # do not join — that would reintroduce the hang
            with self._hook_timeout_lock:
                # See #6622.
                self._hook_timeout_suppressed_until[callback_key] = (
                    time.monotonic() + self._hook_timeout_suppression_seconds)"""
timeout_new = """        if not done.wait(timeout=timeout):  # do not join — that would reintroduce the hang
            with self._hook_timeout_lock:
                # See #6622.
                self._hook_timeout_suppressed_until[callback_key] = (
                    time.monotonic() + self._hook_timeout_suppression_seconds)
                # Local patch: the worker is abandoned, not joined, so drop its running
                # slot now — a worker that never returns must not pin the key forever
                # (the suppression window above guards re-entry). Inline pop, NOT
                # _release_token() (it re-acquires this non-reentrant lock).
                if self._hook_running_callbacks.get(callback_key) is token:
                    self._hook_running_callbacks.pop(callback_key, None)"""
if "must not pin the key forever" in s:
    print("already patched (slot release)")
else:
    assert s.count(timeout_old) == 1, "timeout anchor not unique"
    s = s.replace(timeout_old, timeout_new)
    print("patched (slot release)")

p.write_text(s)
print("done")
