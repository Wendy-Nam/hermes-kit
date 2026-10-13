#!/usr/bin/env python3
"""End-to-end, evidence-first runners for the four workshop scenarios.

No scenario sends mail/DM, writes a CRM, bypasses source controls, or silently
labels a template as AI output.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

import sources
import vault_flow
from paths import resolve_hermes


SCENARIOS = {
    "job_signal": ("jobs", "job_posting"),
    "funding_signal": ("funding", "funding_signal"),
    "tender_watch": ("tenders", "procurement"),
    "overseas_partner": ("overseas", "overseas_partner"),
}
OLD_TO_SCENARIO = {old: scenario for scenario, (old, _kind) in SCENARIOS.items()}
MAX_RECORDS = 200
MAX_DRAFT = 12000


def _read_json(path: str | Path, label: str, limit: int = 8 * 1024 * 1024) -> object:
    target = Path(path).expanduser().absolute()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > limit:
        raise ValueError(f"{label}: 8MiB 이하 일반 파일이 필요합니다.")
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: UTF-8 JSON을 읽을 수 없습니다.") from exc


def load_config(path: str | Path) -> dict:
    data = _read_json(path, "config", 1024 * 1024)
    if not isinstance(data, dict):
        raise ValueError("config는 JSON 객체여야 합니다.")
    for field in ("product", "customer"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"config.{field}가 필요합니다.")
    workflows = data.get("workflows", [])
    if not isinstance(workflows, list) or not workflows or any(value not in OLD_TO_SCENARIO for value in workflows):
        raise ValueError("config.workflows에는 jobs/funding/tenders/overseas 중 하나 이상이 필요합니다.")
    for field in ("source_path", "source_mode", "jobs_provider", "jobs_query", "ats_provider",
                  "ats_board", "ats_company", "campaign_name", "draft_language", "draft_mode",
                  "drafts_path"):
        if field in data and (not isinstance(data[field], str) or len(data[field]) > 1000
                              or any(ord(char) < 32 for char in data[field])):
            raise ValueError(f"config.{field}는 문자열이어야 합니다.")
    if data.get("ats_provider", "") not in ("", *sources.ATS_URLS):
        raise ValueError("ats_provider는 greenhouse/lever/ashby 중 하나여야 합니다.")
    if data.get("jobs_provider", "") not in ("", "ats", "wanted", "saramin", "both"):
        raise ValueError("jobs_provider는 ats/wanted/saramin/both 중 하나여야 합니다.")
    if len(data.get("jobs_query", "")) > 200:
        raise ValueError("jobs_query는 200자 이하여야 합니다.")
    if data.get("source_mode", "") not in ("", "sample", "file", "live"):
        raise ValueError("source_mode는 sample/file/live 중 하나여야 합니다.")
    if data.get("draft_mode", "") not in ("", "template", "hermes", "provided"):
        raise ValueError("draft_mode는 template/hermes/provided 중 하나여야 합니다.")
    if data.get("draft_language", "ko") not in ("ko", "en"):
        raise ValueError("draft_language는 ko 또는 en이어야 합니다.")
    return data


def _sample(scenario: str, retrieved_at: str) -> sources.SourceResult:
    rows = {
        "job_signal": [{"company": "샘플정밀", "title": "해외영업 담당자 채용",
                        "url": "https://example.com/jobs/101", "source_id": "sample-job-101",
                        "source": "synthetic-workshop", "location": "서울", "stack": "CRM, English"}],
        "funding_signal": [{"company": "샘플로보틱스", "title": "시리즈 A 투자 유치",
                            "url": "https://example.com/funding/201", "source_id": "sample-funding-201",
                            "source": "synthetic-workshop", "description": "생산 자동화 확장"}],
        "tender_watch": [{"company": "샘플공공기관", "title": "해외 판로개척 지원 용역",
                          "url": "https://example.com/tenders/301", "source_id": "sample-tender-301",
                          "source": "synthetic-workshop", "location": "대한민국"}],
        "overseas_partner": [{"company": "Sample Medical GmbH", "title": "Korea supplier partner candidate",
                              "url": "https://example.com/partners/401", "source_id": "sample-partner-401",
                              "source": "synthetic-workshop", "location": "Germany"}],
    }[scenario]
    if scenario == "job_signal":
        return sources.normalize_job_rows(rows, retrieved_at, "synthetic-workshop")
    return sources.normalize_typed_rows(rows, SCENARIOS[scenario][1], retrieved_at, "synthetic-workshop")


def acquire(scenario: str, mode: str, config: dict, source_path: str | None,
            retrieved_at: str) -> sources.SourceResult:
    old, record_type = SCENARIOS[scenario]
    if mode == "sample":
        result = _sample(scenario, retrieved_at)
    elif mode == "file":
        path = source_path or config.get("source_path")
        if not path:
            raise ValueError("file source_mode에는 --source-path 또는 config.source_path가 필요합니다.")
        candidate = Path(path).expanduser().absolute()
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("source_path는 심볼릭 링크가 아닌 일반 파일이어야 합니다.")
        result = (sources.import_jobs(path, "auto", retrieved_at) if scenario == "job_signal"
                  else sources.import_typed(path, "auto", record_type, retrieved_at))
    elif scenario == "job_signal":
        jobs_provider = config.get("jobs_provider", "")
        if jobs_provider == "ats":
            provider, board, company = (config.get("ats_provider", ""), config.get("ats_board", ""),
                                        config.get("ats_company", ""))
            if not provider or not board or not company:
                return sources.SourceResult("failed", "ats-live", errors=[
                    "jobs_provider=ats에는 공개 ATS의 ats_provider, ats_board slug, ats_company가 필요합니다. credential은 넣지 마세요."
                ])
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", board):
                raise ValueError("ats_board는 공개 board slug 형식이어야 합니다.")
            result = sources.collect_ats(provider, board, company, 100, None, retrieved_at)
        elif jobs_provider in ("wanted", "saramin", "both"):
            query = config.get("jobs_query", "").strip()
            if not query:
                return sources.SourceResult("failed", f"{jobs_provider}-live", errors=[
                    f"jobs_provider={jobs_provider}에는 jobs_query가 필요합니다."
                ])
            if jobs_provider == "wanted":
                result = sources.collect_wanted(query, 50, None, retrieved_at)
            elif jobs_provider == "saramin":
                result = sources.collect_saramin(query, 50, None, retrieved_at)
            else:
                result = sources.combine_job_search([
                    sources.collect_wanted(query, 50, None, retrieved_at),
                    sources.collect_saramin(query, 50, None, retrieved_at),
                ])
        else:
            return sources.SourceResult("failed", "jobs-live", errors=[
                "live job_signal에는 jobs_provider=ats/wanted/saramin/both 중 하나가 필요합니다."
            ])
    elif scenario == "funding_signal":
        result = sources.collect_funding(1, 20, None, retrieved_at)
    else:
        return sources.SourceResult("failed", f"{scenario}-live", errors=[
            f"{scenario} live adapter는 아직 지원하지 않습니다. 공식 export를 file 모드로 제공하세요; 로그인·차단 우회는 하지 않습니다."
        ])
    return sources.apply_config_filters(result, config, old)


def score_records(records: list[dict], config: dict) -> dict[str, dict]:
    profile_terms = list(dict.fromkeys(term.casefold() for term in re.split(
        r"[,;|/\s]+", config["product"] + " " + config["customer"] + " " + config.get("keywords", ""))
        if len(term.strip()) >= 2))
    scores = {}
    for record in records:
        searchable = " ".join(str(record.get(key) or "") for key in
                              ("company", "title", "description", "location")).casefold()
        matched = [term for term in profile_terms if term in searchable]
        known = sum(bool(record.get(key)) for key in ("company", "title", "url", "published_at", "location"))
        coverage = round(known / 5 * 100)
        fit = "supported" if matched else "unknown"
        urgency = "unknown"
        published = sources.normalize_date(record.get("published_at"))
        if published:
            try:
                observed = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).days
                urgency = "recent_candidate" if 0 <= age <= 30 else "not_recent_or_future" if age > 30 or age < 0 else "unknown"
            except ValueError:
                pass
        scores[record["source_id"]] = {
            "fit": fit, "urgency": urgency, "coverage": coverage,
            "matched_profile_terms": matched,
            "rationale": ("프로필 용어 일치: " + ", ".join(matched)) if matched else
                         "제품·고객 프로필과 직접 일치하는 표현이 없어 적합도는 unknown",
        }
    return scores


def _provided_drafts(path: str | None) -> dict[str, dict]:
    if not path:
        raise ValueError("provided draft-mode에는 --drafts-file이 필요합니다.")
    raw = _read_json(path, "drafts-file")
    mapping = raw.get("drafts") if isinstance(raw, dict) else None
    if not isinstance(mapping, dict) or len(mapping) > MAX_RECORDS:
        raise ValueError("drafts-file은 {drafts:{source_id: body}} 계약이어야 합니다.")
    result = {}
    for source_id, body in mapping.items():
        if (not isinstance(source_id, str) or not source_id or not isinstance(body, str)
                or not body.strip() or len(body) > MAX_DRAFT
                or any(ord(char) < 32 and char not in "\n\t\r" for char in body)):
            raise ValueError("draft source_id/body 형식 또는 길이가 잘못되었습니다.")
        result[source_id] = {"mode": "provided", "body": body.strip()}
    return result


def _hermes_drafts(records: list[dict], config: dict, home: Path, runner=subprocess.run) -> dict[str, dict]:
    try:
        executable = resolve_hermes(home, required=True)
    except (FileNotFoundError, ValueError):
        raise ValueError("draft-mode hermes를 선택했지만 Hermes 실행 파일이 없습니다.")
    result = {}
    env = dict(os.environ, HERMES_HOME=str(home))
    with tempfile.TemporaryDirectory(prefix="outbound-drafts-") as temporary:
        for index, record in enumerate(records):
            prompt = Path(temporary) / f"prompt-{index}.txt"
            prompt.write_text(
                "아래 공개 근거만 사용해 과장 없는 콜드 아웃리치 초안 본문만 작성하세요. 발송하지 마세요.\n"
                f"언어: {config.get('draft_language') or 'ko'}\n제품: {config['product']}\n"
                f"고객: {config['customer']}\n회사: {record.get('company') or '미확인'}\n"
                f"신호: {record['title']}\n근거 URL: {record['url']}\n", encoding="utf-8")
            completed = runner([str(executable), "chat", "--query-file", str(prompt), "--oneshot", "--quiet", "--format", "text"],
                               env=env, capture_output=True, text=True, timeout=180, check=False)
            body = completed.stdout.strip()
            if (completed.returncode or not body or len(body) > MAX_DRAFT
                    or any(ord(char) < 32 and char not in "\n\t\r" for char in body)):
                raise ValueError(f"Hermes draft 생성 실패: source_id={record['source_id']}")
            result[record["source_id"]] = {"mode": "hermes", "body": body}
    return result


def _brief(config: dict) -> str:
    return f"""# Outbound Brief

- campaign: {config.get('campaign_name') or '기본 캠페인'}
- product: {config['product']}
- customer: {config['customer']}
- language: {config.get('draft_language') or 'ko'}

공개 근거만 사용하고 회사 동일성·최신성·적합성을 사람이 검토합니다. 자동 발송은 금지됩니다.
"""


def _atomic_json(path: Path, value: object) -> None:
    if path.is_symlink():
        raise ValueError(f"출력 링크를 덮어쓰지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".workflow-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def run(config_path: str, home: str, output: str, vault: str, *, scenario: str | None,
        source_mode: str | None, source_path: str | None, draft_mode: str | None,
        drafts_file: str | None, runner=subprocess.run) -> dict:
    config = load_config(config_path)
    source_mode = source_mode or config.get("source_mode")
    if source_mode not in ("sample", "file", "live"):
        raise ValueError("source_mode를 CLI --source-mode 또는 config.source_mode로 명시하세요 (sample/file/live).")
    draft_mode = draft_mode or config.get("draft_mode")
    if draft_mode not in ("template", "hermes", "provided"):
        raise ValueError("draft_mode를 CLI --draft-mode 또는 config.draft_mode로 명시하세요 (template/hermes/provided).")
    drafts_file = drafts_file or config.get("drafts_path")
    if scenario and SCENARIOS[scenario][0] not in config["workflows"]:
        raise ValueError(f"scenario {scenario}는 config.workflows에서 선택되지 않았습니다.")
    selected = [scenario] if scenario else [OLD_TO_SCENARIO[item] for item in config["workflows"]]
    if source_mode == "file" and len(selected) != 1:
        raise ValueError("file 모드는 --scenario 하나를 지정해야 source_path 의미가 명확합니다.")
    provided = _provided_drafts(drafts_file) if draft_mode == "provided" else {}
    now = datetime.now(timezone.utc)
    retrieved_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    prepared = []
    for item in selected:
        envelope = acquire(item, source_mode, config, source_path, retrieved_at)
        if envelope.status != "ok":
            if envelope.status == "empty":
                prepared.append((item, envelope, {}, {})); continue
            raise ValueError("; ".join(envelope.errors) or f"{item} source {envelope.status}")
        if len(envelope.records) > MAX_RECORDS:
            raise ValueError(f"{item}: record 한도 {MAX_RECORDS}개를 초과했습니다.")
        scores = score_records(envelope.records, config)
        if draft_mode == "provided":
            missing = [r["source_id"] for r in envelope.records if r["source_id"] not in provided]
            if missing: raise ValueError("provided draft 누락: " + ", ".join(missing[:10]))
            drafts = {sid: provided[sid] for sid in scores}
        elif draft_mode == "hermes":
            drafts = _hermes_drafts(envelope.records, config, Path(home).expanduser().absolute(), runner=runner)
        else:
            drafts = {}
        prepared.append((item, envelope, scores, drafts))

    output_root = Path(output).expanduser().absolute()
    if any(path.is_symlink() for path in (output_root, *output_root.parents)):
        raise ValueError("output 또는 상위 경로의 심볼릭 링크는 사용할 수 없습니다.")
    vault_flow.init_vault(vault, _brief(config))
    results = []
    for index, (item, envelope, scores, drafts) in enumerate(prepared):
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        digest = hashlib.sha256(sources.canonical_json(envelope.to_dict())).hexdigest()[:10]
        run_id = f"run-{stamp}-{index}-{item}-{digest}-{uuid.uuid4().hex[:8]}"
        envelope_path = output_root / f"{run_id}-source.json"
        _atomic_json(envelope_path, envelope.to_dict())
        profile = {key: config.get(key, "") for key in ("product", "customer", "campaign_name", "draft_language")}
        vault_result = vault_flow.run_flow(vault, envelope_path, profile=profile, drafts=drafts,
                                           scores=scores, run_id=run_id)
        artifact = {
            "schema_version": "hermes_outbound_workflow/v1", "run_id": run_id,
            "scenario": item, "source_mode": source_mode, "draft_mode": draft_mode,
            "campaign_name": config.get("campaign_name") or "", "profile": profile,
            "records": envelope.records, "scores": scores,
            "sourceEvidence": [record["evidence"] for record in envelope.records],
            "source_status": envelope.status, "vault": vault_result,
            "automatic_send": False,
        }
        _atomic_json(output_root / f"{run_id}.json", artifact)
        results.append(artifact)
    return {"schema_version": "hermes_outbound_workflow_batch/v1", "runs": results,
            "automatic_send": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run prescribed Hermes outbound scenarios without sending")
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("run")
    command.add_argument("--config", required=True); command.add_argument("--home", required=True)
    command.add_argument("--output", required=True); command.add_argument("--vault", required=True)
    command.add_argument("--scenario", choices=tuple(SCENARIOS))
    command.add_argument("--source-mode", choices=("sample", "file", "live"))
    command.add_argument("--source-path")
    command.add_argument("--draft-mode", choices=("template", "hermes", "provided"))
    command.add_argument("--drafts-file")
    draft_import = sub.add_parser("draft-import", help="validate a host-AI/person-provided draft JSON contract")
    draft_import.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "draft-import":
            drafts = _provided_drafts(args.input)
            print(json.dumps({"schema_version": "hermes_outbound_draft_import/v1",
                              "status": "valid", "draft_count": len(drafts),
                              "source_ids": sorted(drafts)}, ensure_ascii=False, indent=2))
            return 0
        result = run(args.config, args.home, args.output, args.vault, scenario=args.scenario,
                     source_mode=args.source_mode, source_path=args.source_path,
                     draft_mode=args.draft_mode, drafts_file=args.drafts_file)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "user_message": str(exc),
                          "next_action": "입력 파일·선택한 source/draft mode·전용 Hermes 설치 상태를 확인하세요."},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
