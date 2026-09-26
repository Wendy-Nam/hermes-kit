#!/usr/bin/env python3
"""Patch kanban notifier watcher interval from 5s to 30s to prevent CPU busy-wait."""

from pathlib import Path

target_file = Path('/opt/hermes/gateway/kanban_watchers.py')
if not target_file.exists():
    print('Target not found:', target_file)
    exit(0)

content = target_file.read_text(encoding='utf-8')
target = 'async def _kanban_notifier_watcher(self, interval: float = 5.0) -> None:'
replacement = 'async def _kanban_notifier_watcher(self, interval: float = 30.0) -> None:'

if target in content:
    content = content.replace(target, replacement)
    target_file.write_text(content, encoding='utf-8')
    print('done kanban interval patch')
elif replacement in content:
    print('already patched: kanban interval')
else:
    print('WARN: pattern not found in kanban_watchers.py')
