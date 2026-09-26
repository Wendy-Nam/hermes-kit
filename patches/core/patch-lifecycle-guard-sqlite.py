#!/usr/bin/env python3
"""Hermes cron/lifecycle_guard.py 로컬 패치 (이미지 레이어 — 컨테이너 재생성 시 재실행, root로).
버그: 터미널 명령 안의 경로 토큰을 '참조 스크립트'로 읽는데, 1MB 초과 파일은 fail-closed(=차단).
state.db(1.7GB)를 인라인 heredoc에서 열기만 해도 "cannot restart, stop, or uninstall the gateway"로
차단됨(2026-08-30~, 라이프 시그널 스윕·저녁 기록 크론 29회). SQLite 매직을 바이너리 목록에 추가해
스니프 단계에서 스킵. 멱등.

v0.21.2: 목록이 _BINARY_MAGIC_PREFIXES → _BINARY_MAGICS 로 개명됨. 양쪽 앵커 지원.
"""
from pathlib import Path

p = Path("/opt/hermes/cron/lifecycle_guard.py")
s = p.read_text()
entry = 'b"SQLite format 3\\x00"'
if entry in s:
    print("already patched")
else:
    new_anchor = 'b"PK\\x03\\x04",           # zip (also .jar/.whl/.egg)\n'
    old_anchor = '_BINARY_MAGIC_PREFIXES = (\n    b"\\x7fELF",\n'
    add = '    b"SQLite format 3\\x00",  # local patch: data files are not scripts (state.db false-positive)\n'
    if new_anchor in s:
        p.write_text(s.replace(new_anchor, new_anchor + add))
        print("patched (_BINARY_MAGICS layout)")
    elif old_anchor in s:
        p.write_text(s.replace(old_anchor, old_anchor + add))
        print("patched (legacy layout)")
    else:
        raise SystemExit("anchor missing — upstream changed; inspect binary magic list")
