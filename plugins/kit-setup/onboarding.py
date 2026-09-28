"""What the optional features are for, in one screen instead of a list of key names.

The wizard's four numbered steps are the mandatory path. Everything else — app integrations, the
voice assistant, PC notes — is optional, and until now it was visible only as a key name in a
dropdown, which tells a student nothing about what the key buys them. This module renders one
line per optional feature: what it does, which key it needs, and whether it is set up already.

The text goes straight into a Discord message, so it must stay under the message limit and must
never contain a key *value* — only its name.
"""
from __future__ import annotations

from pathlib import Path

MESSAGE_LIMIT = 1900   # Discord rejects 2000; leave room for the view that follows the text

# id, one-line explanation, the key(s) that turn it on, and where the key is issued.
FEATURES = (
    ("composio", "Composio 앱 연동", "Gmail·캘린더·Notion 등 외부 앱을 켜고 메일·일정을 읽습니다. "
     "권한은 Composio에서 본인이 허용해야 합니다.", ("COMPOSIO_CONSUMER_KEY",), "https://connect.composio.dev"),
    ("voice", "음성 비서", "한국어 음성 비서입니다. 마이크로 녹음한 말을 텍스트로 받아 지시를 처리합니다.",
     ("GROQ_API_KEY",), "https://console.groq.com/keys"),
    ("sync", "PC 옵시디언 노트", "PC의 옵시디언에서 서버 볼트를 봅니다. 서버는 PC에 파일을 보내기만 합니다.",
     (), ""),
    ("proxy", "차단 우회", "차단된 사이트에 프록시로 접속합니다. 국내 서비스 등에서는 오히려 막힐 수 있습니다.",
     ("WEBSHARE_PROXY_USERNAME", "WEBSHARE_PROXY_PASSWORD"), "https://dashboard.webshare.io/"),
    ("scrape", "SNS·플랫폼 수집", "Apify로 SNS·플랫폼 데이터를 모읍니다. 과금되므로 필요한 학생만 씁니다.",
     ("APIFY_TOKEN",), "https://console.apify.com/settings/integrations"),
    ("aux-opencode", "보조 모델 (OpenCode Go)", "지시하는 봇이 하위 작업을 이 모델로 넘깁니다.",
     ("OPENCODE_GO_API_KEY",), "https://opencode.ai/go"),
    ("aux-commandcode", "보조 모델 (Command Code)", "위임할 작업을 싸게 처리하고 싶을 때 씁니다.",
     ("COMMANDCODE_API_KEY",), "https://commandcode.ai/pricing"),
)


def _env(data_dir) -> dict:
    from env_store import get_env

    try:
        return get_env(Path(data_dir) / ".env")
    except Exception:
        return {}


def _sync_state() -> str:
    """How many devices the server Syncthing knows, as a phrase a student can act on."""
    try:
        from syncthing_setup import paired_device_count

        count = paired_device_count()
    except Exception:
        return "확인 못 함"
    return "아직 PC 없음" if count <= 1 else f"연결된 장치 {count - 1}대"


def feature_lines(data_dir) -> list[str]:
    """One line per optional feature, in the order a student is most likely to want them.

    A key's *name* may appear (the student has to type it); its value never can.
    """
    env = _env(data_dir)
    lines = []
    for fid, title, what, keys, url in FEATURES:
        if fid == "sync":
            lines.append(f"**{title}** — {what} 현재: {_sync_state()}")
            continue
        if all(env.get(k) for k in keys):
            state = "설정됨"
        else:
            state = f"키 필요: {', '.join(keys)}" + (f" · 발급: {url}" if url else "")
        lines.append(f"**{title}** — {what} 현재: {state}")
    return lines


def feature_guide(data_dir) -> str:
    """The whole guide, guaranteed to fit one Discord message.

    A feature whose line would not fit is dropped rather than truncated mid-sentence, so the
    student is never left reading half a sentence and guessing. The head and tail are budgeted
    for first: a guide that overflows the limit fails at the worst possible moment — the first
    time a confused student presses the button.

    Dropping is announced. Silently shortening the list is how a student concludes the feature
    they wanted does not exist, which is the exact confusion this screen was built to remove.
    """
    head = ("**선택 기능 안내** — 설정 순서 1~4가 끝나도 됩니다. 아래는 필요할 때만 켜는 기능들입니다. "
            "키는 **서비스 키 입력 · 변경**에서 받고, PC 노트는 그 화면의 **PC 동기화** 버튼을 씁니다.\n")
    tail = "\n나머지 버튼(OMH·OmniRoute·이미지·추가 기능)은 각 화면 첫 줄에 설명이 있습니다."
    # The dropped-count line is budgeted up front, so announcing it can never push the message
    # over the limit — the failure this function exists to prevent. A negative budget is possible
    # if the limit is set below head+tail+note, so it is clamped: a negative budget would let a
    # line through on the first comparison alone.
    note = "\n· …중 {n}개는 길이 제한으로 생략됐습니다. 각 기능 화면 첫 줄에 설명이 있습니다."
    budget = max(0, MESSAGE_LIMIT - len(head) - len(tail) - len(note))
    all_lines = feature_lines(data_dir)
    lines, used, dropped = [], 0, 0
    for raw in all_lines:
        # Budget the prefixed line, not the bare one: "· " is two more characters per line, and
        # the count of lines is exactly what made the old estimate overshoot.
        line = "· " + raw
        if used + len(line) + 1 > budget:
            dropped += 1
            continue
        lines.append(line)
        used += len(line) + 1
    body = "\n".join(lines) + (note.format(n=dropped) if dropped else "")
    text = head + body + tail
    # The constant part alone is what Discord would reject, and a truncated answer here is the
    # one failure mode with no workaround for the student. Say so rather than send it anyway.
    return text if len(text) <= MESSAGE_LIMIT else (
        "**선택 기능 안내** — 길이 제한으로 목록을 담지 못했습니다. "
        "**고급 설정**의 각 기능 화면 첫 줄에 설명이 있습니다.")


def sync_guide() -> str:
    """The PC notes steps, shared by the wizard button and the advanced screen."""
    return ("**PC에서 옵시디언으로 노트 보기**\n"
            "1. PC에 Syncthing(https://syncthing.net/downloads/)과 Obsidian(https://obsidian.md)을 설치합니다.\n"
            "2. Syncthing 화면의 **동작 → ID 표시**에서 장치 ID를 복사하고 **PC 장치 ID 입력**에 붙여 넣습니다.\n"
            "3. PC Syncthing에 뜨는 서버 장치와 `hermes-work`·`hermes-personal` 공유를 수락하고, 빈 폴더 두 개를 고릅니다.\n"
            "4. Obsidian에서 **폴더를 보관소로 열기**로 두 폴더를 각각 엽니다. 플러그인 설정은 이미 들어 있습니다.\n"
            "서버 설정이 저장되었다는 메시지는 PC 수락이나 실제 파일 도착을 뜻하지 않습니다. "
            "PC에 파일이 보이면 끝입니다.")