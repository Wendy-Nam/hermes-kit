"""Offline conversation ZIP import. No LLM calls, extraction or network access."""
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_JSON = 40 * 1024 * 1024
MAX_ENTRIES = 10000


def _safe_path(path: Path, root: Path):
    """Reject existing symlink components, even those pointing inside the vault."""
    root = root.absolute()
    path = path.absolute()
    path.relative_to(root)
    for part in (root, *root.parents):
        if part.is_symlink():
            raise ValueError("symlink")
    cur = root
    for part in path.relative_to(root).parts:
        cur /= part
        if cur.is_symlink():
            raise ValueError("symlink")


def _text(message):
    content = message.get("content") or message.get("text", "")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = content.get("parts", [])
    if isinstance(content, list):
        return "\n".join(p if isinstance(p, str) else p.get("text", "")
                         for p in content if isinstance(p, str) or
                         (isinstance(p, dict) and isinstance(p.get("text"), str)))
    return ""


def _conversation(row):
    if not isinstance(row, dict):
        raise ValueError("invalid conversation")
    if isinstance(row.get("mapping"), dict):
        source = "chatgpt"
        mapping = row["mapping"]
        node = row.get("current_node")
        if node is None:
            raise ValueError("ChatGPT current_node missing")
        chain, seen = [], set()
        while node is not None:
            if node in seen or node not in mapping:
                raise ValueError("invalid branch")
            seen.add(node)
            item = mapping[node]
            if item.get("message"):
                message = item["message"]
                role = message.get("author", {}).get("role", "unknown")
                if role in ("user", "assistant"):
                    chain.append((role, _text(message)))
            node = item.get("parent")
        chain.reverse()
    elif isinstance(row.get("chat_messages"), list):
        source = "claude"
        chain = [(m.get("sender", "unknown"), _text(m)) for m in row["chat_messages"]
                 if isinstance(m, dict)]
    else:
        raise ValueError("unsupported export")
    identifier = row.get("id") or row.get("uuid") or row.get("conversation_id")
    if not identifier:
        raise ValueError("conversation id missing")
    filename = hashlib.sha256(str(identifier).encode()).hexdigest() + ".md"
    title = str(row.get("title") or row.get("name") or "제목 없음").replace("\n", " ")[:300]
    lines = ["# 가져온 대화", "", f"출처: {source}", "", "제목:", ""]
    # Fenced text prevents exported HTML, remote images and instructions from
    # becoming executable/rendered markup in a Markdown viewer.
    for role, text in [("title", title), *chain]:
        role = role if role in ("title", "user", "human", "assistant") else "unknown"
        text = str(text)
        fence = "`" * max(3, max((len(s) for s in re.findall(r'`+', text)), default=0) + 1)
        lines.extend([f"## {role}", "", fence + "text", text, fence, ""])
    return source, filename, "\n".join(lines)


def import_export(archive: Path, data_dir: Path = Path("/opt/data")) -> tuple[bool, str]:
    """Read personal/Inbox/import/*.zip, write only personal/Archive/{source}.

    Existing changed files are preserved, including previous imports. A conflict
    needs an explicit user decision; no automatic overwrite or model ingestion.
    """
    created = skipped = conflicts = 0
    try:
        data_dir = Path(data_dir).absolute()
        archive = Path(archive).absolute()
        inbox = data_dir / "vaults/personal/Inbox/import"
        if archive.parent != inbox or archive.suffix.lower() != ".zip":
            raise ValueError("private inbox ZIP required")
        _safe_path(archive, data_dir)
        if archive.stat().st_size > MAX_ARCHIVE:
            raise ValueError("archive too large")
        planned = {}
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise ValueError("archive limits")
            names = set()
            for info in infos:
                path = PurePosixPath(info.filename)
                if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                        or ":" in info.filename or info.filename in names
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise ValueError("unsafe archive")
                names.add(info.filename)
            candidates = [i for i in infos if PurePosixPath(i.filename).name == "conversations.json"]
            if len(candidates) != 1 or candidates[0].file_size > MAX_JSON:
                raise ValueError("one conversations.json required")
            with z.open(candidates[0]) as f:
                raw = f.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("JSON too large")
            conversations = json.loads(raw)
            if not isinstance(conversations, list) or len(conversations) > MAX_ENTRIES:
                raise ValueError("invalid conversations")
            for row in conversations:
                source, filename, content = _conversation(row)
                dest = data_dir / "vaults/personal/Archive" / source / filename
                _safe_path(dest, data_dir)
                if dest in planned and planned[dest] != content:
                    raise ValueError("duplicate conversation id")
                planned[dest] = content
        # All input and output paths validate before the first file is written.
        for dest, content in planned.items():
            _safe_path(dest, data_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if dest.read_text(encoding="utf-8") == content:
                    skipped += 1
                else:
                    conflicts += 1
                continue
            # Exclusive create never replaces user edits or a competing import.
            try:
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                conflicts += 1
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            created += 1
        return True, (f"가져오기 완료: 새 대화 {created}개, 동일 내용 {skipped}개 건너뜀, "
                      f"변경된 기존 파일 {conflicts}개 보존. 개인 볼트 Archive 폴더에 저장했습니다. "
                      "LLM 호출이나 대화 전송은 하지 않았습니다.")
    except Exception:
        return False, ("가져오지 못했습니다. 개인 볼트 Inbox/import의 ChatGPT·Claude 내보내기 ZIP인지, "
                       "파일 크기와 경로가 올바른지 확인해 주세요. "
                       f"이번 실행에서 이미 저장된 대화는 {created}개이며 기존 파일은 덮어쓰지 않았습니다.")
