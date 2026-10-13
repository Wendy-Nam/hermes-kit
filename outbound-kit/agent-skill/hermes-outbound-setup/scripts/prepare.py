#!/usr/bin/env python3
"""Interactive, secret-free setup.json preparation for Hermes Outbound Kit.

This helper deliberately collects only non-secret choices. Provider keys and bot tokens
belong in kit.py/services.py private prompts or official OAuth/device flows later.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Callable


SCRIPT = Path(__file__).resolve()
KIT_ROOT = SCRIPT.parents[3]
KIT_MODULE = KIT_ROOT / "kit.py"
PATHS_MODULE = KIT_ROOT / "paths.py"


def load_kit_validator():
    """Load the validator from this skill's kit root, independent of cwd/PYTHONPATH."""
    if not KIT_MODULE.is_file():
        raise RuntimeError(f"kit.py를 찾을 수 없습니다: {KIT_MODULE}")
    spec = importlib.util.spec_from_file_location("hermes_outbound_root_kit", KIT_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("kit.py validator를 불러올 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    # kit.py imports sibling modules (for example paths.py). Make only this
    # checkout discoverable while it loads, then restore the caller's path.
    root_text = str(KIT_ROOT)
    added = root_text not in sys.path
    if added:
        sys.path.insert(0, root_text)
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            sys.path.remove(root_text)
    validate = getattr(module, "validate", None)
    if not callable(validate):
        raise RuntimeError("kit.py에 callable validate(data)가 없습니다.")
    return validate


def load_paths_module():
    """Load the kit's canonical cross-platform path policy."""
    if not PATHS_MODULE.is_file():
        raise RuntimeError(f"paths.py를 찾을 수 없습니다: {PATHS_MODULE}")
    spec = importlib.util.spec_from_file_location("hermes_outbound_paths", PATHS_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("paths.py를 불러올 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


class Questions:
    def __init__(self, input_fn: InputFn = input, output_fn: OutputFn = print):
        self.input = input_fn
        self.output = output_fn

    def text(self, label: str, *, default: str = "", required: bool = False) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            value = self.input(f"{label}{suffix}: ").strip()
            value = value or default
            if required and not value:
                self.output("값을 입력해 주세요.")
                continue
            if len(value) > 1000 or any(ord(char) < 32 for char in value):
                self.output("한 줄, 1000자 이하로 입력해 주세요.")
                continue
            return value

    def choice(self, label: str, choices: tuple[str, ...], *, default: str) -> str:
        rendered = "/".join(choices)
        while True:
            value = self.input(f"{label} ({rendered}) [{default}]: ").strip().lower() or default
            if value in choices:
                return value
            self.output("지원하는 값 중 하나를 입력해 주세요: " + rendered)

    def integer(self, label: str, *, default: int, minimum: int, maximum: int) -> int:
        while True:
            raw = self.input(f"{label} [{default}]: ").strip()
            try:
                value = default if not raw else int(raw)
            except ValueError:
                self.output("숫자로 입력해 주세요.")
                continue
            if minimum <= value <= maximum:
                return value
            self.output(f"{minimum}~{maximum} 범위로 입력해 주세요.")

    def yes_no(self, label: str, *, default: bool = False) -> bool:
        shown = "yes" if default else "no"
        while True:
            value = self.input(f"{label} (yes/no) [{shown}]: ").strip().lower()
            if not value:
                return default
            if value in ("y", "yes"):
                return True
            if value in ("n", "no"):
                return False
            self.output("yes 또는 no로 입력해 주세요.")

    def multiple(self, label: str, choices: tuple[str, ...], *, default: tuple[str, ...] = ()) -> list[str]:
        rendered = ", ".join(choices)
        default_text = ",".join(default)
        while True:
            suffix = f" [{default_text}]" if default_text else " [없음]"
            raw = self.input(f"{label} — 쉼표로 선택 ({rendered}){suffix}: ").strip()
            if not raw:
                return list(default)
            values = [item.strip().lower() for item in raw.split(",") if item.strip()]
            if len(values) != len(set(values)):
                self.output("중복 없이 입력해 주세요.")
                continue
            unknown = [item for item in values if item not in choices]
            if unknown:
                self.output("지원하지 않는 값: " + ", ".join(unknown))
                continue
            return values


def _owner(questions: Questions, channel: str) -> str:
    while True:
        value = questions.text(f"내 {channel} 숫자 사용자 ID", required=True)
        if re.fullmatch(r"[1-9][0-9]{3,24}", value):
            return value
        questions.output("봇 토큰이 아니라 본인의 숫자 사용자 ID를 입력해 주세요.")


def collect_config(input_fn: InputFn = input, output_fn: OutputFn = print) -> dict:
    """Ask adaptive non-secret questions and return a root-validator-ready config."""
    q = Questions(input_fn, output_fn)
    q.output("Hermes Outbound를 함께 준비할게요. 키·토큰·비밀번호는 여기서 묻지 않습니다.")
    q.output("먼저 오늘 하고 싶은 일 하나를 고릅니다.")

    scenario = q.choice(
        "시나리오 (job_signal=채용 신호, funding_signal=투자 신호, "
        "tender_watch=입찰 확인, overseas_partner=해외 파트너)",
        ("job_signal", "funding_signal", "tender_watch", "overseas_partner"),
        default="job_signal")
    workflow_map = {"job_signal": ["jobs"], "funding_signal": ["funding"],
                    "tender_watch": ["tenders"], "overseas_partner": ["overseas"]}
    workflows = workflow_map[scenario]
    campaign_name = q.text("이 작업의 이름", default="첫 아웃바운드 캠페인", required=True)
    product = q.text("내가 제안하는 제품·서비스", required=True)
    customer = q.text("찾고 싶은 회사", required=True)
    draft_language = q.choice("초안 언어", ("ko", "en"), default="ko")
    draft_mode = q.choice(
        "첫 초안 방식 (template=연습용, hermes=연결한 AI, provided=내 문구)",
        ("template", "hermes", "provided"), default="template")
    drafts_path = (q.text("내가 준비한 초안 JSON 파일 경로", required=True)
                   if draft_mode == "provided" else "")
    source_mode = q.choice(
        "데이터 시작 방법 (sample=연습, file=내 파일, live=지원 공개 소스)",
        ("sample", "file", "live"), default="sample")
    source_path = q.text("사용할 CSV/JSON 파일 경로", required=True) if source_mode == "file" else ""
    ats_provider = ats_board = ats_company = jobs_provider = jobs_query = ""
    if source_mode == "live" and scenario == "job_signal":
        q.output("실시간 채용은 공개된 채용공고만 소량 조회합니다. 로그인이나 차단 우회는 하지 않습니다.")
        jobs_provider = q.choice(
            "채용 소스 (ats=회사 공개 채용판, wanted=원티드, saramin=사람인, both=원티드+사람인)",
            ("ats", "wanted", "saramin", "both"), default="ats")
        if jobs_provider == "ats":
            q.output("회사 공개 채용 페이지가 Greenhouse, Lever, Ashby 중 어디인지 확인해 주세요.")
            ats_provider = q.choice("공개 채용 게시판 종류", ("greenhouse", "lever", "ashby"),
                                    default="greenhouse")
            ats_board = q.text("공개 채용 게시판 식별자", required=True)
            ats_company = q.text("회사 이름", required=True)
        else:
            jobs_query = q.text("채용 사이트에서 찾을 직무·기술 검색어", required=True)
    job_keywords = q.text("채용 직무·기술 키워드") if "jobs" in workflows else ""
    funding_keywords = q.text("투자 소식 키워드") if "funding" in workflows else ""
    region = q.text("지역")
    exclude_keywords = q.text("제외 키워드")
    keywords = q.text("공통 검색 키워드")

    q.output("이제 Hermes를 내 컴퓨터에서 쓸지, 이미 준비된 서버에서 쓸지 정합니다.")
    install_location = q.choice("사용 장소 (local=내 컴퓨터, remote=준비된 서버)",
                                ("local", "remote"), default="local")
    target = "desktop" if install_location == "local" else "server"
    if install_location == "local":
        os_hint = q.choice("운영체제", ("auto", "macos", "windows", "linux"), default="auto")
        desktop_mode = q.choice("사용 화면 (app=Hermes Desktop, terminal=터미널)",
                                ("app", "terminal"), default="app")
        server_host = ""
        server_port = 22
        server_user = ""
        ssh_key_path = ""
        ssh_key_action = "existing"
    else:
        q.output("SSH는 이 컴퓨터에서 서버에 접속하는 방법입니다. 주소와 사용자 이름은 클라우드 화면에서 찾습니다.")
        q.output("SSH 키의 개인키는 내 컴퓨터에 두고, .pub 공개키만 서버에 등록합니다.")
        os_hint = q.choice("서버 운영체제", ("auto", "linux"), default="linux")
        desktop_mode = "terminal"
        server_host = q.text("서버 host/IP", required=True)
        server_port = q.integer("SSH port", default=22, minimum=1, maximum=65535)
        server_user = q.text("SSH 사용자", required=True)
        ssh_key_action = q.choice(
            "SSH key", ("existing", "generate"), default="existing")
        default_key = "~/.ssh/hermes_outbound_ed25519" if ssh_key_action == "generate" else ""
        ssh_key_path = q.text(
            "기존 private key 경로" if ssh_key_action == "existing" else "새 key 저장 경로",
            default=default_key,
            required=True,
        )

    paths = load_paths_module()
    if install_location == "remote":
        install_home = "~/.hermes-outbound"
    else:
        path_target = "windows" if os_hint == "windows" else "auto" if os_hint == "auto" else "posix"
        install_home = str(paths.default_home(path_target))
    output_path = q.text("결과를 저장할 폴더", default="~/hermes-outbound-results", required=True)

    model_provider = q.choice(
        "모델 제공자", ("chatgpt", "anthropic", "gemini", "openai-api", "other", "later"),
        default="chatgpt")
    if model_provider == "later":
        model_auth = "later"
    else:
        model_auth = q.choice(
            "모델 인증 방식", ("existing", "oauth", "device", "api-key", "later"),
            default="existing")

    channel = q.choice(
        "대화 채널", ("none", "telegram", "discord", "both"), default="none")
    telegram_owner = _owner(q, "Telegram") if channel in ("telegram", "both") else ""
    discord_owner = _owner(q, "Discord") if channel in ("discord", "both") else ""

    services = q.multiple(
        "선택 서비스", ("webshare", "groq", "apify", "composio"), default=())

    webshare_allowed_target = ""
    webshare_policy_ack = False
    if "webshare" in services:
        webshare_allowed_target = q.text("Webshare를 사용할 허용된 공개 source domain/URL")
        webshare_policy_ack = q.yes_no(
            "로그인·CAPTCHA·paywall·차단 우회에 사용하지 않는다는 정책을 확인했습니까?",
            default=False)

    groq_audio_consent = False
    if "groq" in services:
        groq_audio_consent = q.yes_no(
            "테스트 오디오가 Groq로 전송되는 데 동의합니까?", default=False)

    apify_actor_name = ""
    apify_budget_usd = ""
    apify_cost_ack = False
    if "apify" in services:
        apify_actor_name = q.text("검토할 Apify Actor 이름")
        while True:
            apify_budget_usd = q.text("수동 테스트 최대 예산 USD (예: 1.00, 미정이면 빈칸)")
            if not apify_budget_usd or re.fullmatch(r"\d{1,6}(?:\.\d{1,2})?", apify_budget_usd):
                break
            q.output("0 이상의 USD 금액을 소수 둘째 자리까지 입력해 주세요.")
        apify_cost_ack = q.yes_no(
            "Actor·입력·source 약관·예산·dataset 보존을 실행 전에 다시 검토합니까?",
            default=False)

    composio_apps: list[str] = []
    composio_scope_ack = False
    if "composio" in services:
        while True:
            raw_apps = q.text("연결할 Composio 앱 이름 (쉼표 구분, 예: Gmail, Sheets)")
            composio_apps = [item.strip() for item in raw_apps.split(",") if item.strip()]
            if (len(composio_apps) <= 20 and len(composio_apps) == len(set(composio_apps))
                    and all(re.fullmatch(r"[A-Za-z0-9 _-]{1,60}", item) for item in composio_apps)):
                break
            q.output("영문/숫자/공백/_/-로 된 앱 이름을 중복 없이 20개 이하로 입력해 주세요.")
        composio_scope_ack = q.yes_no(
            "앱별 OAuth scope를 확인하고 읽기/초안과 발송 권한을 분리합니까?",
            default=False)

    review_human_approval = q.yes_no(
        "메일·DM 자동 발송 없이 사람이 최종 승인합니까?", default=True)
    review_terms_costs = q.yes_no(
        "선택 source·서비스의 약관과 비용을 실제 실행 전에 확인했습니까?", default=False)
    review_no_secrets = q.yes_no(
        "키·토큰·비밀번호를 chat/setup.json/ZIP/Obsidian에 넣지 않겠습니까?", default=True)

    omh_enabled = q.yes_no(
        "권장 핵심 기능 OMH 역할 위임·모델 라우팅을 설치합니까?",
        default=True)
    if omh_enabled:
        omniroute_enabled = q.yes_no("선택 기능 OmniRoute 설치·라우팅을 요청합니까?", default=False)
    else:
        omniroute_enabled = False
        q.output("OmniRoute는 OMH와 함께 쓰는 선택 기능이라 이번 설정에서는 건너뜁니다.")
    vault_mode = q.choice(
        "결과 폴더 (new=새 Obsidian 볼트 권장, none=일반 폴더, existing=기존 볼트)",
        ("none", "new", "existing"), default="new")
    vault_path = ""
    vault_existing_approved = False
    if vault_mode != "none":
        default_vault = "~/hermes-outbound-vault" if vault_mode == "new" else ""
        vault_path = q.text("Vault 경로", default=default_vault, required=True)
        if vault_mode == "existing":
            vault_existing_approved = q.yes_no(
                "기존 파일은 덮어쓰지 않고 충돌 시 중단하는 조건으로 이 vault 사용을 승인합니까?",
                default=False,
            )

    schedule_enabled = q.yes_no("첫 수동 실행 뒤 예약 실행도 준비합니까?", default=False)
    schedule_frequency = "daily"
    schedule_time = ""
    timezone = "Asia/Seoul"
    if schedule_enabled:
        schedule_frequency = q.choice("예약 주기", ("daily", "hourly"), default="daily")
        schedule_time = (q.text("매일 실행 시각 (HH:MM)", default="09:00", required=True)
                         if schedule_frequency == "daily" else "")
        timezone = q.text("시간대", default="Asia/Seoul", required=True)
    gateway_enabled = (q.yes_no("선택한 메신저 봇을 계속 실행하도록 준비합니까?", default=False)
                       if channel != "none" else False)
    # Selected optional services are applied by their own reviewed installer step.
    # Keep this legacy profile field false instead of exposing a misleading
    # "server service" switch that the runtime does not consume.
    service_apply_enabled = False

    return {
        "version": 1,
        "target": target,
        "scenario": scenario,
        "campaign_name": campaign_name,
        "draft_language": draft_language,
        "draft_mode": draft_mode,
        "drafts_path": drafts_path,
        "source_mode": source_mode,
        "source_path": source_path,
        "ats_provider": ats_provider,
        "ats_board": ats_board,
        "ats_company": ats_company,
        "jobs_provider": jobs_provider,
        "jobs_query": jobs_query,
        "desktop_mode": desktop_mode,
        "install_location": install_location,
        "os_hint": os_hint,
        "install_home": install_home,
        "output_path": output_path,
        "server_host": server_host,
        "server_port": server_port,
        "server_user": server_user,
        "ssh_key_path": ssh_key_path,
        "ssh_key_action": ssh_key_action,
        "model_provider": model_provider,
        "model_auth": model_auth,
        "channel": channel,
        "telegram_owner": telegram_owner,
        "discord_owner": discord_owner,
        "product": product,
        "customer": customer,
        "keywords": keywords,
        "workflows": workflows,
        "job_keywords": job_keywords,
        "funding_keywords": funding_keywords,
        "region": region,
        "exclude_keywords": exclude_keywords,
        "services": services,
        # Typed, non-secret safety gates. Authentication preparation may proceed, but
        # provider-specific functional work remains blocked until reviewed later.
        "webshare_allowed_target": webshare_allowed_target,
        "webshare_policy_ack": webshare_policy_ack,
        "groq_audio_consent": groq_audio_consent,
        "apify_actor_name": apify_actor_name,
        "apify_budget_usd": apify_budget_usd,
        "apify_cost_ack": apify_cost_ack,
        "composio_apps": composio_apps,
        "composio_scope_ack": composio_scope_ack,
        "review_human_approval": review_human_approval,
        "review_terms_costs": review_terms_costs,
        "review_no_secrets": review_no_secrets,
        "omh_enabled": omh_enabled,
        "omniroute_enabled": omniroute_enabled,
        "vault_mode": vault_mode,
        "vault_path": vault_path,
        "vault_existing_approved": vault_existing_approved,
        "vault_collision_policy": "preview_stop",
        "schedule_enabled": schedule_enabled,
        "schedule_frequency": schedule_frequency,
        "schedule_time": schedule_time,
        "timezone": timezone,
        "gateway_enabled": gateway_enabled,
        "service_apply_enabled": service_apply_enabled,
        "routing_bindings_path": "",
    }


def _assert_secret_free(data: dict) -> None:
    forbidden = re.compile(r"(?:^|_)(?:token|password|secret|api_key|private_key)(?:$|_)", re.I)
    bad = sorted(key for key in data if forbidden.search(key) and key != "ssh_key_path")
    if bad:
        raise ValueError("비밀 필드는 setup.json에 저장할 수 없습니다: " + ", ".join(bad))


def create_config(path: Path, data: dict) -> Path:
    """Validate through root kit.py, then create a secret-free config without overwrite."""
    _assert_secret_free(data)
    validated = load_kit_validator()(data)
    destination = path.expanduser().absolute()
    if destination.is_symlink():
        raise ValueError("setup.json 대상이 심볼릭 링크입니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(text)
    return destination


def summary(data: dict) -> str:
    remote = ""
    if data["install_location"] == "remote":
        remote = f" / SSH {data['server_user']}@{data['server_host']}:{data['server_port']}"
    source = data["source_mode"]
    if data.get("jobs_provider"):
        source += f"({data['jobs_provider']})"
    return (
        f"작업={data['campaign_name']} / 시나리오={data['scenario']} / 데이터={source}\n"
        f"위치={data['install_location']}({data['os_hint']}, {data['desktop_mode']}){remote}\n"
        f"워크플로우={','.join(data['workflows']) or '없음'} / 채널={data['channel']}\n"
        f"서비스={','.join(data['services']) or '없음'} / Obsidian={data['vault_mode']}\n"
        f"모델={data['model_provider']}({data['model_auth']}) / "
        f"OMH={'사용' if data['omh_enabled'] else '미사용'} / "
        f"OmniRoute={'선택' if data['omniroute_enabled'] else '미선택'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hermes Outbound의 비밀 없는 설치 설정을 대화형으로 생성합니다.")
    parser.add_argument(
        "--output", default=str(KIT_ROOT / "setup.json"),
        help="create-only setup JSON path (default: kit root/setup.json)")
    args = parser.parse_args(argv)
    try:
        data = collect_config()
        print("\n설치 계획 요약\n" + summary(data))
        answer = input("이 비밀 없는 설정 파일을 생성할까요? (yes/no) [yes]: ").strip().lower()
        if answer not in ("", "y", "yes"):
            print("취소했습니다. 파일을 만들지 않았습니다.")
            return 2
        destination = create_config(Path(args.output), data)
        print(f"설정 생성 완료: {destination}")
        print("키·토큰은 저장하지 않았습니다. 다음 단계는 kit.py validate이며, 채널 토큰은 나중에 kit.py connect의 비공개 입력에서만 받습니다.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n입력을 취소했습니다. 비밀값이나 설정 파일을 저장하지 않았습니다.", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
