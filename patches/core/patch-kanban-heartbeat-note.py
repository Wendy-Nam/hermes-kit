#!/usr/bin/env python3
"""칸반 워커 프롬프트: heartbeat를 진행 보고 채널로 쓰게 한다 (2026-09-24).

대상: /opt/hermes/agent/prompt_builder.py — Lifecycle 3번 항목(블록 전체 치환).

기존 문구는 "긴 subprocess 중에만, 짧은 작업은 생략"이라 워커가 heartbeat를 거의
안 불렀다(14일 95건, note 없는 것 다수). patch-kanban-progress-notify.py 이후 note가
붙은 heartbeat는 구독 Discord 스레드로 올라가므로(태스크당 10분 1회), 마일스톤마다
note를 붙여 부르도록 바꾼다. 1시간 규칙(reclaim)은 그대로 둔다.

규칙: 전체 블록 치환, 임시파일 → py_compile → 교체, 멱등, 백업.

hermes-kit: ported from the author's server; applied at image build (no backup copy).
"""
import os, py_compile, sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/agent/prompt_builder.py"
MARK = "Report progress with heartbeats"

OLD = (
    '    "3. **Heartbeat on long operations.** Call `kanban_heartbeat(note=...)` every few minutes during long subprocesses "\n'
    '    "(training, encoding, crawling). Skip heartbeats for short tasks. **If your task may run longer than 1 hour, you "\n'
)
NEW = (
    '    "3. **Report progress with heartbeats.** Call `kanban_heartbeat(note=...)` at each milestone (a sub-step, batch "\n'
    '    "or file finished) and every few minutes during long subprocesses (training, encoding, crawling). ALWAYS pass a "\n'
    '    "one-line `note` in the user\'s language saying what is done and what is next (e.g. \\"샷 카드 20/42 매핑 완료 — "\n'
    '    "나머지 매핑 중\\"): notes are posted to the requester\'s chat thread (at most one per 10 minutes per task), so a "\n'
    '    "heartbeat without a note is invisible to them. Skip heartbeats only for tasks that finish within a couple of "\n'
    '    "minutes. **If your task may run longer than 1 hour, you "\n'
)

src = open(TARGET, encoding="utf-8").read()
if MARK in src:
    print("already patched")
    sys.exit(0)
if src.count(OLD) != 1:
    sys.exit("앵커 불일치(%d) — 업스트림 변경, 수동 확인" % src.count(OLD))
tmp = TARGET + ".tmp-heartbeat-note"
open(tmp, "w", encoding="utf-8").write(src.replace(OLD, NEW, 1))
try:
    py_compile.compile(tmp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(tmp)
    sys.exit("컴파일 실패 — 원본 유지: %s" % e)
os.replace(tmp, TARGET)
print("patched → gateway 재시작 필요")
