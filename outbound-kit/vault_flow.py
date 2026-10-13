#!/usr/bin/env python3
"""Deterministic, Markdown-only Obsidian workflow for outbound evidence.

This runner never sends messages and never claims its draft template is AI-generated.
Human-owned Inbox and Review notes are create-only. Generated notes carry a marker and
preserve the text inside their user-notes block across reconciliations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
VAULT_MARKER = ".hermes-outbound-vault.json"
STATE = ".hermes-outbound/state.json"
MACHINE_MARK = "<!-- hermes-outbound:machine-owned:v1 -->"
USER_START = "<!-- user-notes:start -->"
USER_END = "<!-- user-notes:end -->"
SOURCE_STATES = {"ok", "empty", "blocked", "failed", "invalid_response"}
RECORD_TYPES = {"job_posting", "funding_signal", "procurement", "overseas_partner", "news", "other"}
DECISIONS = {"pending", "approved", "rejected"}
MAX_INPUT = 8 * 1024 * 1024


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _slug(value: str, limit: int = 36) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value.strip().lower()).strip("-")
    return (text or "record")[:limit].rstrip("-")


def _safe_text(value: object, field: str, limit: int = 4000, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이어야 합니다.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field}: 값이 필요합니다.")
    if len(value) > limit or any(ord(c) < 32 and c not in "\t" for c in value):
        raise ValueError(f"{field}: 허용 길이 또는 문자 범위를 벗어났습니다.")
    return value


def _safe_multiline(value: object, field: str, limit: int = 20000, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이어야 합니다.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if required and not value:
        raise ValueError(f"{field}: 값이 필요합니다.")
    if len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{field}: 허용 길이 또는 문자 범위를 벗어났습니다.")
    return value


def _url(value: object, field: str) -> str:
    value = _safe_text(value, field, 2000, required=True)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
        raise ValueError(f"{field}: 공개 http(s) URL이 필요합니다.")
    return value


def _path(path: str | Path, *, existing_file: bool = False) -> Path:
    candidate = Path(path).expanduser().absolute()
    if candidate.is_symlink():
        raise ValueError(f"심볼릭 링크 경로는 사용할 수 없습니다: {candidate}")
    if existing_file:
        if not candidate.is_file() or candidate.stat().st_size > MAX_INPUT:
            raise ValueError("입력은 8MiB 이하의 일반 파일이어야 합니다.")
    return candidate


def _assert_managed_path(vault: Path, target: Path) -> None:
    try:
        target.relative_to(vault)
    except ValueError:
        raise ValueError("볼트 밖 경로는 쓸 수 없습니다.") from None
    current = target
    while current != vault:
        if current.exists() and current.is_symlink():
            raise ValueError(f"관리 경로의 심볼릭 링크를 거부했습니다: {current}")
        current = current.parent
    if vault.exists() and vault.is_symlink():
        raise ValueError("볼트가 심볼릭 링크입니다.")


def _atomic(path: Path, text: str) -> bool:
    if path.is_symlink():
        raise ValueError(f"심볼릭 링크 파일을 갱신하지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if old == text:
        return False
    fd, temporary = tempfile.mkstemp(prefix=".vault-flow-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


def _create_human(path: Path, text: str) -> bool:
    """Create a human-owned note once. Existing content is never read-modify-written."""
    if path.is_symlink():
        raise ValueError(f"사람 소유 노트가 심볼릭 링크입니다: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"노트 경로가 일반 파일이 아닙니다: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return True


def _user_notes(old: str) -> str:
    start, end = old.find(USER_START), old.find(USER_END)
    if start < 0 or end < 0 or end < start:
        return ""
    return old[start + len(USER_START):end].strip("\n")


def _machine_note(path: Path, generated: str) -> bool:
    """Reconcile a generated note while preserving its explicit custom-text block."""
    notes = ""
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"생성 노트 경로를 안전하게 갱신할 수 없습니다: {path}")
        old = path.read_text(encoding="utf-8")
        if MACHINE_MARK not in old:
            raise ValueError(f"사람이 만든 파일을 덮어쓰지 않습니다: {path}")
        notes = _user_notes(old)
    text = (MACHINE_MARK + "\n" + generated.rstrip() + "\n\n" + USER_START + "\n" +
            notes + ("\n" if notes else "") + USER_END + "\n")
    return _atomic(path, text)


def _vault(vault: str | Path, require_initialized: bool = True) -> Path:
    root = _path(vault)
    if require_initialized:
        marker = root / VAULT_MARKER
        if not marker.is_file() or marker.is_symlink():
            raise ValueError("초기화된 Hermes Outbound 볼트가 아닙니다. 먼저 init을 실행하세요.")
    return root


def init_vault(vault: str | Path, brief: str | None = None) -> Path:
    root = _vault(vault, require_initialized=False)
    if root.exists() and not root.is_dir():
        raise ValueError("볼트 경로가 디렉터리가 아닙니다.")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("Inbox", "Accounts", "Evidence", "Scores", "Drafts", "Review", "Runs", ".hermes-outbound"):
        target = root / name
        _assert_managed_path(root, target)
        if target.exists() and (target.is_symlink() or not target.is_dir()):
            raise ValueError(f"볼트 디렉터리 충돌: {target}")
        target.mkdir(exist_ok=True)
    for target in (root / VAULT_MARKER, root / STATE, root / "Dashboard.md", root / "Inbox/Brief.md"):
        _assert_managed_path(root, target)
    _atomic(root / VAULT_MARKER, json.dumps({"schema_version": 1, "kind": "hermes-outbound-vault"},
                                            ensure_ascii=False, indent=2) + "\n")
    brief_text = (brief if brief is not None else
                  (ROOT / "pack/vault/Inbox/Brief.md").read_text(encoding="utf-8"))
    _create_human(root / "Inbox/Brief.md", _safe_multiline(brief_text, "brief", 20000, required=True) + "\n")
    if not (root / STATE).exists():
        _atomic(root / STATE, json.dumps({"schema_version": 1, "runs": {}, "accounts": {}},
                                         ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _render_dashboard(root, {"schema_version": 1, "runs": {}, "accounts": {}})
    return root


def _load_envelope(path: str | Path | None) -> tuple[dict, str]:
    source = _path(path or ROOT / "pack/vault/seed/normalized-records.json", existing_file=True)
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"입력 JSON을 읽을 수 없습니다: {exc.msg}") from None
    if not isinstance(raw, dict) or raw.get("status") not in SOURCE_STATES:
        raise ValueError("입력은 status/source/records/errors를 가진 source envelope여야 합니다.")
    envelope_source = _safe_text(raw.get("source"), "source", 200, required=True)
    records = raw.get("records")
    errors = raw.get("errors", [])
    if not isinstance(records, list) or not isinstance(errors, list):
        raise ValueError("records와 errors는 배열이어야 합니다.")
    safe_errors = [_safe_text(x, "errors[]", 1000) for x in errors]
    normalized = {"status": raw["status"], "source": envelope_source,
                  "records": [_normalize_record(r, envelope_source) for r in records],
                  "errors": safe_errors}
    if raw["status"] != "ok" and records:
        raise ValueError("ok가 아닌 source envelope은 records를 포함할 수 없습니다.")
    return normalized, str(source)


def _normalize_record(raw: object, envelope_source: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("각 record는 객체여야 합니다.")
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("record.evidence 객체가 필요합니다.")
    record_type = _safe_text(raw.get("record_type"), "record_type", 40, required=True)
    if record_type not in RECORD_TYPES:
        raise ValueError(f"지원하지 않는 record_type: {record_type}")
    source = _safe_text(raw.get("source") or envelope_source, "record.source", 200, required=True)
    source_id = _safe_text(raw.get("source_id"), "source_id", 500, required=True)
    company = _safe_text(raw.get("company"), "company", 300)
    candidate = _safe_text(raw.get("company_candidate"), "company_candidate", 300)
    title = _safe_text(raw.get("title"), "title", 1000, required=True)
    url = _url(raw.get("url"), "url")
    ev_source = _safe_text(evidence.get("source"), "evidence.source", 200, required=True)
    ev_url = _url(evidence.get("url"), "evidence.url")
    ev_source_id = _safe_text(evidence.get("source_id"), "evidence.source_id", 500, required=True)
    if ev_source != source or ev_source_id != source_id or ev_url != url:
        raise ValueError("evidence의 source/source_id/url은 record와 일치해야 합니다.")
    raw_hash = _safe_text(evidence.get("raw_sha256"), "evidence.raw_sha256", 64, required=True)
    if not re.fullmatch(r"[a-fA-F0-9]{64}", raw_hash):
        raise ValueError("evidence.raw_sha256는 64자리 SHA-256이어야 합니다.")
    stack = raw.get("stack")
    if stack is not None and (not isinstance(stack, list) or any(not isinstance(x, str) for x in stack)):
        raise ValueError("stack은 문자열 배열 또는 null이어야 합니다.")
    if stack is not None:
        stack = [_safe_text(x, "stack[]", 200, required=True) for x in stack]
    return {
        "schema_version": _safe_text(str(raw.get("schema_version", "1")), "schema_version", 40, required=True),
        "record_type": record_type, "source": source, "source_id": source_id,
        "company": company or None, "company_candidate": candidate,
        "company_confidence": raw.get("company_confidence"), "title": title, "url": url,
        "published_at": _safe_text(raw.get("published_at"), "published_at", 80),
        "stack": stack, "location": _safe_text(raw.get("location"), "location", 500),
        "description": _safe_text(raw.get("description"), "description", 4000),
        "evidence": {"source": ev_source, "url": ev_url, "source_id": ev_source_id,
                     "retrieved_at": _safe_text(evidence.get("retrieved_at"), "evidence.retrieved_at", 80),
                     "raw_sha256": raw_hash.lower()},
    }


def _read_state(root: Path) -> dict:
    path = root / STATE
    if path.is_symlink() or not path.is_file():
        raise ValueError("볼트 상태 파일을 안전하게 읽을 수 없습니다.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != 1 or not isinstance(state.get("accounts"), dict):
        raise ValueError("볼트 상태 파일 형식이 잘못되었습니다.")
    return state


def _review(path: Path, draft_hash: str) -> tuple[str, str]:
    if not path.exists():
        return "pending", "review_note_missing"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Review 노트를 안전하게 읽을 수 없습니다: {path}")
    text = path.read_text(encoding="utf-8")
    decision_match = re.search(r"(?m)^decision:\s*(pending|approved|rejected)\s*$", text)
    hash_match = re.search(r"(?m)^approved_draft_hash:\s*['\"]?([a-f0-9]*)['\"]?\s*$", text)
    decision = decision_match.group(1) if decision_match else "pending"
    approved_hash = hash_match.group(1) if hash_match else ""
    if decision == "approved" and approved_hash != draft_hash:
        return "invalidated", "draft_hash_changed_or_missing"
    return decision, "hash_matches" if decision == "approved" else decision


def _review_template(account_id: str, company: str, draft_hash: str) -> str:
    return f"""---
account_id: {account_id}
decision: pending
approved_draft_hash: ""
---
# 검토 — {company}

이 노트는 사람이 관리하며 러너가 덮어쓰지 않습니다.

1. `[[Drafts/{account_id}]]`의 근거·표현·수신 대상을 확인합니다.
2. 승인하려면 `decision: approved`로 바꾸고 Draft 노트의 `draft_content_hash`를 `approved_draft_hash`에 복사합니다.
3. 초안이 바뀌면 해시가 달라져 승인이 자동 무효화됩니다. 거절은 `decision: rejected`로 기록합니다.

생성 당시 초안 해시: `{draft_hash}`

## 사람 메모

- 실제 발송은 자동으로 실행되지 않습니다.
"""


def _account_id(record: dict) -> str:
    company = record["company"]
    return "acct-" + _slug(company) + "-" + _digest({"company": company.casefold()})[:10]


def _evidence_id(record: dict) -> str:
    return "ev-" + _digest({"source": record["source"], "source_id": record["source_id"]})[:14]


def _next_task(stage: str, review_state: str = "") -> str:
    if stage == "identity_blocked": return "회사 후보를 확인하고 source record의 company를 확정"
    if stage == "evidence": return "출처가 완전한지 확인"
    if stage == "score": return "점수 근거를 검토"
    if stage == "draft": return "초안 생성 상태 확인"
    if review_state == "pending": return "Review에서 초안을 검토하고 결정"
    if review_state == "invalidated": return "변경된 초안을 다시 검토하고 새 해시로 승인"
    if review_state == "rejected": return "거절 사유를 기록하거나 초안 조건 수정"
    if review_state == "approved": return "승인 완료; 자동 발송 없음"
    return "입력과 상태 확인"


def run_flow(vault: str | Path, input_path: str | Path | None = None, *,
             profile: dict | None = None, drafts: dict | None = None,
             scores: dict | None = None, run_id: str | None = None) -> dict:
    root = _vault(vault)
    envelope, input_name = _load_envelope(input_path)
    input_digest = _digest(envelope)
    run_id = run_id or "run-" + input_digest[:14]
    if not re.fullmatch(r"run-[a-zA-Z0-9._-]{6,80}", run_id):
        raise ValueError("run_id 형식이 잘못되었습니다.")
    profile = profile or {}
    drafts = drafts or {}
    scores = scores or {}
    state = _read_state(root)
    result = {"run_id": run_id, "source": envelope["source"], "source_status": envelope["status"],
              "errors": envelope["errors"], "input_digest": input_digest, "input": input_name,
              "accounts": [], "completed": False}

    if envelope["status"] == "ok":
        for record in envelope["records"]:
            if not record["company"]:
                result["accounts"].append({"source_id": record["source_id"], "company_candidate": record["company_candidate"],
                                            "stage": "identity_blocked", "next_task": _next_task("identity_blocked")})
                continue
            account_id, evidence_id = _account_id(record), _evidence_id(record)
            account_path = root / f"Accounts/{account_id}.md"
            evidence_path = root / f"Evidence/{evidence_id}.md"
            score_path = root / f"Scores/{account_id}.md"
            draft_path = root / f"Drafts/{account_id}.md"
            review_path = root / f"Review/{account_id}.md"
            for target in (account_path, evidence_path, score_path, draft_path, review_path):
                _assert_managed_path(root, target)
            stack = ", ".join(record["stack"] or []) or "미확인"
            previous = state["accounts"].get(account_id, {})
            evidence_ids = list(dict.fromkeys([*previous.get("evidence_ids", []), evidence_id]))
            evidence_links = "\n".join(f"  - [[Evidence/{item}]]" for item in evidence_ids)
            _machine_note(account_path, f"""# Account — {record['company']}

- account_id: `{account_id}`
- 회사 식별 신뢰도: `{record['company_confidence']}`
- 기술 스택: {stack}
- 전체 근거 ({len(evidence_ids)}건):
{evidence_links}
- 점수: [[Scores/{account_id}]]
- 초안: [[Drafts/{account_id}]]
- 사람 검토: [[Review/{account_id}]]
""")
            ev = record["evidence"]
            _machine_note(evidence_path, f"""# Evidence — {record['company']}

- evidence_id: `{evidence_id}`
- 유형: `{record['record_type']}`
- 제목: {record['title']}
- source: `{ev['source']}`
- source_id: `{ev['source_id']}`
- 원문: {ev['url']}
- 게시 시각: `{record['published_at'] or '미확인'}`
- 수집 시각: `{ev['retrieved_at'] or '미확인'}`
- raw_sha256: `{ev['raw_sha256']}`

이 노트는 출처가 있는 사실 후보를 보관합니다. 채용공고나 투자 소식은 구매 예산의 증명이 아닙니다.
""")
            coverage_fields = [record["company"], record["title"], record["url"], record["published_at"],
                               ev["source"], ev["source_id"], ev["retrieved_at"], ev["raw_sha256"]]
            coverage = round(sum(bool(x) for x in coverage_fields) / len(coverage_fields) * 100)
            score = scores.get(record["source_id"], {})
            fit = score.get("fit", "unknown")
            urgency = score.get("urgency", "unknown")
            rationale = _safe_text(score.get("rationale"), "score.rationale", 2000) or "프로필 기반 점수 없음"
            _machine_note(score_path, f"""# Evidence score — {record['company']}

- account_id: `{account_id}`
- evidence_coverage: `{coverage}%`
- profile_fit: `{fit}`
- urgency: `{urgency}`
- 근거 설명: {rationale}
- signal_type: `{record['record_type']}`
- 전체 근거 수: `{len(evidence_ids)}`

이 값은 필드 충족률이며 구매 가능성이나 영업 적합도 점수가 아닙니다. 실제 fit/urgency 판단에는 Inbox 브리프와 사람 검토가 필요합니다.
""")
            supplied = drafts.get(record["source_id"])
            if supplied:
                mode = _safe_text(supplied.get("mode"), "draft.mode", 20, required=True)
                body = _safe_multiline(supplied.get("body"), "draft.body", 12000, required=True)
                draft_body = f"> `{mode}` 모드 초안입니다. 자동 발송되지 않습니다.\n\n{body}"
            else:
                product = _safe_text(profile.get("product"), "profile.product", 1000) or "저희 제안"
                customer = _safe_text(profile.get("customer"), "profile.customer", 1000) or "해당 조직"
                language = _safe_text(profile.get("draft_language"), "profile.draft_language", 40) or "ko"
                draft_body = f"""> 합성 규칙 기반 초안 템플릿입니다. 실제 AI 생성 결과가 아니며 자동 발송되지 않습니다. 언어: `{language}`

안녕하세요. `{record['title']}` 관련 공개 정보를 확인했습니다.

저희 `{product}`가 `{customer}`의 현재 과제와 관련이 있는지 확인하고 싶습니다. 간단한 소개 자료를 보내드려도 괜찮을까요?

검토 전 확인: 회사 동일성, 원문 최신성, 제품 적합성, 실제 수신 대상, 과장 표현 여부."""
            draft_hash = hashlib.sha256(draft_body.encode("utf-8")).hexdigest()
            _machine_note(draft_path, f"""# Draft template — {record['company']}

- account_id: `{account_id}`
- draft_content_hash: `{draft_hash}`
- 전체 근거: {', '.join(f'[[Evidence/{item}]]' for item in evidence_ids)}
- 검토: [[Review/{account_id}]]

{draft_body}
""")
            _create_human(review_path, _review_template(account_id, record["company"], draft_hash))
            review_state, review_reason = _review(review_path, draft_hash)
            account_state = {"account_id": account_id, "company": record["company"],
                             "source_id": record["source_id"], "evidence_id": evidence_id,
                             "evidence_ids": evidence_ids,
                             "draft_hash": draft_hash, "review": review_state, "review_reason": review_reason,
                             "stage": "review", "next_task": _next_task("review", review_state)}
            state["accounts"][account_id] = account_state
            result["accounts"].append(account_state)
        result["completed"] = bool(result["accounts"]) and all(
            x.get("review") == "approved" for x in result["accounts"] if x.get("account_id")) and not any(
                x.get("stage") == "identity_blocked" for x in result["accounts"])
    # empty is a successful source observation, not a completed outbound workflow.
    result["outcome"] = ("completed" if result["completed"] else "empty" if envelope["status"] == "empty"
                         else "blocked" if envelope["status"] in {"blocked", "failed", "invalid_response"}
                         else "review_required")
    inbox_path = root / f"Inbox/{run_id}-source.md"
    _assert_managed_path(root, inbox_path)
    _machine_note(inbox_path, _inbox_receipt(result))
    result["inbox_note"] = f"Inbox/{run_id}-source"
    state.setdefault("runs", {})[run_id] = result
    receipt = _run_receipt(result)
    receipt_path, state_path = root / f"Runs/{run_id}.md", root / STATE
    _assert_managed_path(root, receipt_path); _assert_managed_path(root, state_path)
    _machine_note(receipt_path, receipt)
    _atomic(state_path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _render_dashboard(root, state)
    return result


def _run_receipt(result: dict) -> str:
    lines = [f"# Run — {result['run_id']}", "", f"- source: `{result['source']}`",
             f"- source_status: `{result['source_status']}`", f"- outcome: `{result['outcome']}`",
             f"- input_digest: `{result['input_digest']}`", f"- Inbox: [[{result.get('inbox_note', '')}]]",
             "", "## 단계 결과", ""]
    if result["errors"]:
        lines += ["### Source errors", ""] + [f"- {e}" for e in result["errors"]] + [""]
    if not result["accounts"]:
        lines.append("- 처리된 account 없음. `empty`와 source 실패는 서로 다른 상태로 보존됩니다.")
    for item in result["accounts"]:
        if item.get("account_id"):
            aid = item["account_id"]
            lines.append(f"- [[Accounts/{aid}|{item['company']}]] → [[Evidence/{item['evidence_id']}|Evidence]] → "
                         f"[[Scores/{aid}|Score]] → [[Drafts/{aid}|Draft]] → [[Review/{aid}|Review]] "
                         f"— `{item['review']}`; 다음: {item['next_task']}")
        else:
            lines.append(f"- `{item['source_id']}` 회사 식별 보류 — 다음: {item['next_task']}")
    lines += ["", "자동 발송은 수행되지 않았습니다."]
    return "\n".join(lines)


def _inbox_receipt(result: dict) -> str:
    """Machine-owned staging note; the human Brief and Review notes remain untouched."""
    lines = [f"# Source intake — {result['run_id']}", "", f"- source: `{result['source']}`",
             f"- status: `{result['source_status']}`", f"- input_digest: `{result['input_digest']}`", ""]
    if result["errors"]:
        lines += ["## Source errors", ""] + [f"- {item}" for item in result["errors"]] + [""]
    lines += ["## Records and gate", ""]
    if not result["accounts"]:
        lines.append("- record 없음. empty와 source 실패 상태는 Runs receipt에서 구분합니다.")
    for item in result["accounts"]:
        if item.get("account_id"):
            lines.append(f"- `{item['source_id'] if 'source_id' in item else item['evidence_id']}` → "
                         f"[[Accounts/{item['account_id']}|{item['company']}]]")
        else:
            candidate = item.get("company_candidate") or "후보명 없음"
            lines.append(f"- `{item['source_id']}` · 후보 `{candidate}` · **차단:** {item['next_task']}")
    return "\n".join(lines)


def _render_dashboard(root: Path, state: dict) -> None:
    accounts = list(state.get("accounts", {}).values())
    runs = list(state.get("runs", {}).values())
    lines = ["# Hermes Outbound Dashboard", "", "[[Inbox/Brief|1. Inbox 브리프]] → 2. Accounts → 3. Evidence → "
             "4. Scores → 5. Drafts → 6. Review → 7. Runs", "",
             "> Core Obsidian 기능만 사용합니다. 초안은 자동 발송되지 않습니다.", "",
             f"- Accounts: {len(accounts)}", f"- Runs: {len(runs)}", "", "## 계정별 산출물과 다음 작업", ""]
    if not accounts:
        lines.append("- 아직 계정이 없습니다. `vault_flow.py run`으로 합성 fixture 또는 정규화 source envelope을 처리하세요.")
    for item in sorted(accounts, key=lambda x: (x.get("company", ""), x.get("account_id", ""))):
        aid = item["account_id"]
        lines.append(f"- [[Accounts/{aid}|{item['company']}]] · [[Evidence/{item['evidence_id']}|Evidence]] · "
                     f"[[Scores/{aid}|Score]] · [[Drafts/{aid}|Draft]] · [[Review/{aid}|Review]] "
                     f"— 상태 `{item['review']}` — **다음:** {item['next_task']}")
    lines += ["", "## Runs", ""]
    if not runs:
        lines.append("- 아직 실행 receipt가 없습니다.")
    for run in sorted(runs, key=lambda x: x["run_id"]):
        lines.append(f"- [[{run.get('inbox_note', 'Inbox/Brief')}|Inbox]] → [[Runs/{run['run_id']}|{run['run_id']}]] "
                     f"— source `{run['source_status']}` / outcome `{run['outcome']}`")
        for item in run.get("accounts", []):
            if item.get("stage") == "identity_blocked":
                lines.append(f"  - 후보 `{item.get('company_candidate') or '이름 없음'}` — **다음:** {item['next_task']}")
    dashboard = root / "Dashboard.md"
    _assert_managed_path(root, dashboard)
    _machine_note(dashboard, "\n".join(lines))


def status(vault: str | Path) -> dict:
    root = _vault(vault)
    state = _read_state(root)
    counts = {name: 0 for name in ("pending", "approved", "rejected", "invalidated")}
    accounts = []
    for item in state.get("accounts", {}).values():
        review_state, reason = _review(root / f"Review/{item['account_id']}.md", item["draft_hash"])
        counts[review_state] = counts.get(review_state, 0) + 1
        accounts.append({**item, "review": review_state, "review_reason": reason,
                         "next_task": _next_task("review", review_state)})
    return {"vault": str(root), "runs": len(state.get("runs", {})), "accounts": len(accounts),
            "reviews": counts, "items": sorted(accounts, key=lambda x: x["account_id"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes outbound Obsidian workflow runner")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("init", "status", "run"):
        command = sub.add_parser(name)
        command.add_argument("--vault", required=True)
        if name == "run":
            command.add_argument("--input", help="normalized source envelope JSON; 생략하면 합성 fixture")
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            root = init_vault(args.vault)
            print(f"볼트 초기화 완료: {root}")
        elif args.action == "run":
            result = run_flow(args.vault, args.input)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(status(args.vault), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("오류: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
