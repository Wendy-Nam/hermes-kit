"""Role worker profiles the orchestrator hands kanban cards to.

The default profile talks to the student and orchestrates: short in-turn subtasks go through OMH
delegation, long or resumable work becomes a kanban card assigned to one of these roles. Kanban
spawns `hermes -p <role>` per card, so a role needs no gateway, no bot token and no channel.

Roles run on the student's own main model and keys. They are re-synced from the default profile on
every apply and boot, so a model or key change never leaves a role on a stale or missing credential.
"""
import os
import subprocess
import tempfile
from pathlib import Path

HERMES = '/opt/hermes/.venv/bin/hermes'
MARK = '<!-- kit: role -->'
ROLES = {
    'research': '조사·자료 정리 담당이다. 웹과 문서에서 자료를 찾고, 출처와 근거를 붙여 정리한다.',
    'coder': '코드·파일·자동화 담당이다. 스크립트와 파일을 만들고 직접 실행해 결과를 검증한다.',
    'creator': '글·문서·콘텐츠 산출물 담당이다. 초안, 보고서, 발표 자료, 게시물 원고를 만든다.',
}
# Copied from the default profile so a role runs on the same model, aux route and provider defs.
SHARED_CONFIG = ('model', 'providers', 'delegation')
# Channel credentials stay with the default profile: two profiles holding one bot token collide.
CHANNEL_PREFIXES = ('DISCORD_',)

SOUL = MARK + '''
# {role} — 백그라운드 역할 프로필

너는 {desc} 사용자와 직접 대화하지 않고, 오케스트레이터가 만든 kanban 카드만 처리한다.

- 카드의 원하는 결과·완료 조건·산출물 위치를 먼저 확인한다. 빠진 정보가 결과를 바꾸면 카드에 질문을 남기고 block한다.
- 실제로 실행하고 확인한 것만 완료로 보고한다. 확인하지 못한 부분은 그렇다고 적는다. 도구 결과를 지어내지 않는다.
- 완료할 때 산출물 경로와 확인 근거를 카드에 남긴다.
- 키·토큰을 요구하거나 외부로 보내지 않는다. 메시지 발송·결제·삭제·게시는 하지 않고 초안까지만 만든다.
- 노트는 볼트에 쓴다: 개인 `/opt/data/vaults/personal`, 업무 `/opt/data/vaults/work`.
'''

ROLE_RULE = ('\n\n<!-- kit: roles -->\n## 역할 프로필에 맡기기\n'
             '- 이번 답변 안에 끝나는 병렬 하위 작업은 OMH 위임으로 처리한다.\n'
             '- 오래 걸리거나 여러 단계이거나 재시작 뒤에도 이어져야 하는 일은 kanban 카드로 만들어 역할 프로필에 배정한다: '
             '`research`(조사·출처 정리), `coder`(코드·파일·자동화·실행 검증), `creator`(글·문서·콘텐츠 산출물).\n'
             '- 카드에는 원하는 결과·완료 조건·산출물 위치를 적는다. 카드가 끝나면 산출물과 근거를 직접 확인한 뒤에만 완료라고 말한다.\n')


def _profile(root, role):
    return Path(root) / 'profiles' / role


def _name(line):
    key = line.split('=', 1)[0].strip()
    if key.startswith('export') and key[6:7].isspace():
        key = key[6:].strip()
    return key


def _atomic(path, text, mode=None):
    fd, tmp = tempfile.mkstemp(prefix='.kit-', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def ensure_roles(data_dir, *, hermes=HERMES):
    """Create missing role profiles and the orchestrator rule. Returns one line per role."""
    root = Path(data_dir)
    rows = []
    for role, desc in ROLES.items():
        home = _profile(root, role)
        if not home.is_dir():
            env = {**os.environ, 'HERMES_HOME': str(root), 'HOME': str(root)}
            r = subprocess.run([hermes, 'profile', 'create', role, '--clone', '--no-alias',
                                '--description', desc], env=env, capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not home.is_dir():
                rows.append(f'{role}: 만들지 못했습니다')
                continue
        soul = home / 'SOUL.md'
        # A role SOUL stays kit-owned only while it keeps the marker; a student's rewrite is kept.
        if not soul.is_file() or MARK in soul.read_text(encoding='utf-8'):
            _atomic(soul, SOUL.format(role=role, desc=desc))
        rows.append(f'{role}: 준비됨')
    soul = root / 'SOUL.md'
    try:
        # The orchestrator is told about the roles only once every one of them exists.
        if all(_profile(root, r).is_dir() for r in ROLES) and soul.is_file() and '<!-- kit: roles -->' not in soul.read_text(encoding='utf-8'):
            with soul.open('a', encoding='utf-8') as f:
                f.write(ROLE_RULE)
    except (OSError, UnicodeDecodeError):
        pass
    sync_roles(root)
    return rows


def sync_roles(data_dir):
    """Give every existing role the default profile's model, providers and non-channel keys."""
    from config_store import read, write
    root = Path(data_dir)
    config = read(root)
    env_lines = []
    env_file = root / '.env'
    if env_file.is_file():
        env_lines = [line for line in env_file.read_text(encoding='utf-8').splitlines()
                     if not _name(line).startswith(CHANNEL_PREFIXES)]
    synced = []
    for role in ROLES:
        home = _profile(root, role)
        if not home.is_dir() or home.is_symlink():
            continue
        write(home, {key: config.get(key) for key in SHARED_CONFIG}, remember=False)
        _atomic(home / '.env', '\n'.join(env_lines) + '\n', 0o600)
        synced.append(role)
    return synced
