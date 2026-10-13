#!/usr/bin/env python3
"""Run all four synthetic outbound scenarios in a new, isolated local tree.

This is an offline workflow-quality smoke, not an engine, model, channel, or
desktop installation test.  It deliberately uses the rule-based template mode
and never sends a message.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest import mock
import urllib.request

import workflow


SCENARIOS = {
    "job_signal": "job_posting",
    "funding_signal": "funding_signal",
    "tender_watch": "procurement",
    "overseas_partner": "overseas_partner",
}


class SmokeError(ValueError):
    pass


def _new_root(requested: str | Path | None) -> Path:
    if requested is None:
        root = Path(tempfile.mkdtemp(prefix="hermes-outbound-offline-smoke-"))
    else:
        root = Path(requested).expanduser().absolute()
        if root.is_symlink():
            raise SmokeError("smoke root는 심볼릭 링크일 수 없습니다.")
        if root.exists():
            if not root.is_dir() or any(root.iterdir()):
                raise SmokeError("smoke root는 없거나 비어 있는 디렉터리여야 합니다.")
        else:
            root.mkdir(parents=True, mode=0o700)
    if os.name == "posix":
        os.chmod(root, 0o700)
    return root


def _network_blocked(*_args, **_kwargs):
    raise SmokeError("offline smoke 중 네트워크 접근 시도를 차단했습니다.")


@contextmanager
def offline_guard():
    """Fail closed if a future sample path accidentally starts networking."""
    with (mock.patch.object(socket, "socket", side_effect=_network_blocked),
          mock.patch.object(socket, "create_connection", side_effect=_network_blocked),
          mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=_network_blocked)):
        yield


def _check_run(run: dict, vault: Path) -> list[str]:
    scenario = run.get("scenario")
    if scenario not in SCENARIOS:
        raise SmokeError(f"알 수 없는 scenario 결과: {scenario}")
    if run.get("source_mode") != "sample" or run.get("draft_mode") != "template":
        raise SmokeError(f"{scenario}: offline sample/template 계약이 아닙니다.")
    if run.get("source_status") != "ok" or len(run.get("records", [])) != 1:
        raise SmokeError(f"{scenario}: 합성 source record 1건을 만들지 못했습니다.")
    if run.get("automatic_send") is not False:
        raise SmokeError(f"{scenario}: automatic_send=false 계약이 깨졌습니다.")

    record = run["records"][0]
    evidence = record.get("evidence") or {}
    if record.get("record_type") != SCENARIOS[scenario]:
        raise SmokeError(f"{scenario}: record_type이 다릅니다.")
    if record.get("source") != "synthetic-workshop" or evidence.get("source") != record.get("source"):
        raise SmokeError(f"{scenario}: synthetic provenance가 없습니다.")
    if evidence.get("source_id") != record.get("source_id") or evidence.get("url") != record.get("url"):
        raise SmokeError(f"{scenario}: evidence lineage가 record와 다릅니다.")
    raw_hash = evidence.get("raw_sha256", "")
    if len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash):
        raise SmokeError(f"{scenario}: raw evidence SHA-256이 없습니다.")

    score = (run.get("scores") or {}).get(record["source_id"])
    if not isinstance(score, dict) or score.get("fit") not in {"supported", "unknown"}:
        raise SmokeError(f"{scenario}: 보수적 fit 결과가 없습니다.")
    if not isinstance(score.get("coverage"), int) or not 0 <= score["coverage"] <= 100:
        raise SmokeError(f"{scenario}: coverage가 유효하지 않습니다.")

    flow = run.get("vault") or {}
    accounts = flow.get("accounts") or []
    if flow.get("outcome") != "review_required" or len(accounts) != 1:
        raise SmokeError(f"{scenario}: 사람 검토 게이트에 도달하지 못했습니다.")
    account = accounts[0]
    if account.get("review") != "pending" or account.get("stage") != "review":
        raise SmokeError(f"{scenario}: pending review 상태가 아닙니다.")
    account_id = account.get("account_id", "")
    paths = {
        "account": vault / f"Accounts/{account_id}.md",
        "evidence": vault / f"Evidence/{account['evidence_id']}.md",
        "score": vault / f"Scores/{account_id}.md",
        "draft": vault / f"Drafts/{account_id}.md",
        "review": vault / f"Review/{account_id}.md",
        "run": vault / f"Runs/{run['run_id']}.md",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise SmokeError(f"{scenario}: 볼트 단계 산출물 누락: {', '.join(missing)}")
    draft = paths["draft"].read_text(encoding="utf-8")
    review = paths["review"].read_text(encoding="utf-8")
    if ("실제 AI 생성 결과가 아니며 자동 발송되지 않습니다" not in draft
            or "decision: pending" not in review
            or account["draft_hash"] not in draft
            or account["draft_hash"] not in review):
        raise SmokeError(f"{scenario}: template/approval-hash 표시가 불완전합니다.")
    return [str(path.relative_to(vault)) for path in paths.values()]


def run_smoke(root: str | Path | None = None) -> dict:
    workspace = _new_root(root)
    home, output, vault = workspace / "home", workspace / "output", workspace / "vault"
    home.mkdir(mode=0o700)
    config = workspace / "setup.smoke.json"
    config.write_text(json.dumps({
        "product": "영업 자료 정리와 아웃바운드 검토를 돕는 서비스",
        "customer": "성장 중인 제조·공공·의료 조직",
        "campaign_name": "합성 오프라인 품질 점검",
        "draft_language": "ko",
        "workflows": ["jobs", "funding", "tenders", "overseas"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with offline_guard():
        batch = workflow.run(str(config), str(home), str(output), str(vault), scenario=None,
                             source_mode="sample", source_path=None, draft_mode="template",
                             drafts_file=None)
    runs = batch.get("runs") or []
    if [run.get("scenario") for run in runs] != list(SCENARIOS):
        raise SmokeError("네 시나리오가 고정 순서로 모두 실행되지 않았습니다.")
    if batch.get("automatic_send") is not False:
        raise SmokeError("batch automatic_send=false 계약이 깨졌습니다.")

    checks = []
    for run in runs:
        checks.append({
            "scenario": run["scenario"],
            "record_type": run["records"][0]["record_type"],
            "source_status": run["source_status"],
            "fit": run["scores"][run["records"][0]["source_id"]]["fit"],
            "coverage": run["scores"][run["records"][0]["source_id"]]["coverage"],
            "outcome": run["vault"]["outcome"],
            "artifacts": _check_run(run, vault),
        })
    dashboard = vault / "Dashboard.md"
    if not dashboard.is_file() or any(run["run_id"] not in dashboard.read_text(encoding="utf-8") for run in runs):
        raise SmokeError("Dashboard에 네 실행의 다음 작업이 모두 나타나지 않습니다.")
    if any(home.iterdir()):
        raise SmokeError("offline smoke가 빈 전용 Hermes home을 수정했습니다.")

    report = {
        "schema_version": "hermes_outbound_local_smoke/v1",
        "status": "passed",
        "scope": "synthetic_offline_workflow_quality_only",
        "root": str(workspace),
        "dedicated_home": str(home),
        "output": str(output),
        "vault": str(vault),
        "network_allowed": False,
        "engine_installed": False,
        "model_called": False,
        "messages_sent": False,
        "scenarios": checks,
        "not_proven": [
            "Hermes/OMH/OmniRoute 설치 또는 실제 모델 응답",
            "Telegram/Discord 왕복",
            "라이브 소스 가용성",
            "macOS/Windows GUI 또는 서버 데몬",
        ],
    }
    (workspace / "smoke-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run four isolated synthetic outbound workflow smokes")
    parser.add_argument("--root", help="new or empty directory; omitted creates and retains a private temp directory")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_smoke(args.root), ensure_ascii=False, indent=2))
        return 0
    except (SmokeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
