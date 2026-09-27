#!/usr/bin/env python3
"""Kanban 스레드 알림: 진행상황 보고 + 크래시 재깨움 루프 차단 (2026-09-24).

대상: /opt/hermes/gateway/kanban_watchers_notifier.py

1) 시작(claimed)과 진행 노트(heartbeat note)도 구독 스레드에 흘린다.
   지금까지는 종료성 이벤트만 알려서 태스크를 던지면 끝날 때까지 스레드가 조용했다.
   진행 노트는 태스크당 10분에 1회로 스로틀한다. 노트 없는 heartbeat는 조용히 넘긴다.
   둘 다 알림만 하고 에이전트를 깨우지는 않는다(_WAKE_KINDS 밖).
2) crashed는 알림만 하고 깨우지 않는다. 재시도는 디스패처가 하고, 한도에 걸리면
   gave_up이 깨운다. 9/23: 사이클마다 crashed+gave_up 두 번씩 30만 토큰 세션을 깨웠다.
3) crashed/gave_up 알림에 워커 로그의 마지막 에러 줄을 붙이고, gave_up 깨움 turn의
   handoff로도 넘긴다. 9/23: 에이전트는 "pid not alive"만 보고 401 원인을 모른 채
   태스크를 7번 다시 풀었다.

규칙: 전체 블록 치환, 임시파일 → py_compile → 교체, 멱등, 백업.

hermes-kit: ported from the author's server; applied at image build (no backup copy).
"""
import os, py_compile, sys

TARGET = "/opt/hermes/gateway/kanban_watchers_notifier.py"
MARK = "hermes-patch: kanban-progress"

REPLACEMENTS = [
    # 1+2) kind 목록: crashed를 깨움에서 빼고, 알림 kind에 claimed/heartbeat 추가
    (
        '_WAKE_KINDS = ("completed", "gave_up", "crashed", "timed_out", "blocked", "review_requested", "changes_requested", "block_loop_detected")\n',
        '# hermes-patch: kanban-progress (2026-09-24) — crashed는 알림만(재시도는 디스패처, 한도 도달 시 gave_up이 깨움).\n'
        '_WAKE_KINDS = ("completed", "gave_up", "timed_out", "blocked", "review_requested", "changes_requested", "block_loop_detected")\n'
        '# 시작·진행 노트도 스레드로 흘린다(깨우지 않음). 진행 노트는 태스크당 10분에 1회.\n'
        'NOTIFY_KINDS = TERMINAL_KINDS + ("claimed", "heartbeat")\n'
        '_PROGRESS_MIN_INTERVAL = 600\n'
        '_last_progress_ping: dict = {}\n',
    ),
    (
        'thread_id=sub.get("thread_id") or "", kinds=TERMINAL_KINDS,\n',
        'thread_id=sub.get("thread_id") or "", kinds=NOTIFY_KINDS,\n',
    ),
    # 3) 포맷터: 로그 에러 힌트 + 시작/진행
    (
        'def _fmt_completed(ev, n) -> tuple:\n',
        'def _worker_error_hint(n) -> str:\n'
        '    """워커 로그 끝에서 마지막 에러 줄(비밀값 마스킹). 없거나 실패하면 ""."""\n'
        '    try:\n'
        '        from agent.redact import redact_sensitive_text\n'
        '        from hermes_cli.kanban_db import read_worker_log\n'
        '        tail = read_worker_log(n.task_id, tail_bytes=8000, board=n.board_slug) or ""\n'
        '    except Exception:\n'
        '        return ""\n'
        '    lines = [s.strip() for s in reversed(tail.splitlines())]\n'
        '    # 구체적 원인 줄(📝 Error: HTTP 401: Invalid API key) 우선, 없으면 일반 에러 줄.\n'
        '    for pick in (lambda s: s.startswith("📝 Error:"),\n'
        '                 lambda s: s.startswith(("❌", "Error:", "Traceback")) or "Error" in s[:40]):\n'
        '        for s in lines:\n'
        '            if pick(s):\n'
        '                return redact_sensitive_text(s)[:200]\n'
        '    return ""\n'
        '\n'
        '\n'
        'def _fmt_failure(ev, n, lead: str) -> tuple:\n'
        '    hint = _worker_error_hint(n)\n'
        '    msg = lead + (f"\\n원인: {hint}" if hint else "")\n'
        '    # gave_up 깨움 turn에 원인을 넘긴다 — 같은 원인이면 다시 풀기 전에 원인부터 고치게.\n'
        '    handoff = f"워커 실패 원인: {hint} — 같은 원인이면 재시도 전에 원인부터 해결할 것" if hint else None\n'
        '    return msg, handoff, None\n'
        '\n'
        '\n'
        'def _fmt_heartbeat(ev, n) -> tuple:\n'
        '    import time\n'
        '    note = _payload(ev, "note")\n'
        '    now = time.time()\n'
        '    if not note or now - _last_progress_ping.get(n.task_id, 0) < _PROGRESS_MIN_INTERVAL:\n'
        '        return None, None, None\n'
        '    _last_progress_ping[n.task_id] = now\n'
        '    return f"⏳ {n.head} 진행 중 — {str(note)[:300]}", None, None\n'
        '\n'
        '\n'
        'def _fmt_completed(ev, n) -> tuple:\n',
    ),
    (
        '    "gave_up": lambda ev, n: (\n'
        '        f"✖ {n.head} gave up after repeated spawn failures{_clip(ev, \'error\', _NL, 200)}", None, None,\n'
        '    ),\n'
        '    "crashed": lambda ev, n: (f"✖ {n.head} worker crashed (pid gone); dispatcher will retry", None, None),\n',
        '    "gave_up": lambda ev, n: _fmt_failure(\n'
        '        ev, n, f"✖ {n.head} gave up after repeated spawn failures{_clip(ev, \'error\', _NL, 200)}"),\n'
        '    "crashed": lambda ev, n: _fmt_failure(ev, n, f"✖ {n.head} worker crashed (pid gone); dispatcher will retry"),\n'
        '    "claimed": lambda ev, n: (f"▶ {n.head} 작업 시작 — {n.title}", None, None),\n'
        '    "heartbeat": _fmt_heartbeat,\n',
    ),
]

src = open(TARGET, encoding="utf-8").read()
if MARK in src:
    print("already patched")
    sys.exit(0)
for old, _ in REPLACEMENTS:
    if src.count(old) != 1:
        sys.exit("앵커 불일치(%d): %r — 업스트림 변경, 수동 확인" % (src.count(old), old[:70]))
new = src
for old, rep in REPLACEMENTS:
    new = new.replace(old, rep, 1)

tmp = TARGET + ".tmp-kanban-progress"
open(tmp, "w", encoding="utf-8").write(new)
try:
    py_compile.compile(tmp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(tmp)
    sys.exit("컴파일 실패 — 원본 유지: %s" % e)
os.replace(tmp, TARGET)
print("patched → gateway 재시작 필요")
