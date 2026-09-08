"""Reproduce past analyses: compare snapshots, versions, and re-run."""

from __future__ import annotations

from typing import Any

from database import get_analysis
from document_registry import build_manifest
from versioning import PROMPT_VERSION, RULE_VERSION, WORKFLOW_VERSION
from config import LLM_MODEL, LLM_PROVIDER


REPRODUCIBLE = "REPRODUCIBLE"
PARTIALLY_REPRODUCIBLE = "PARTIALLY_REPRODUCIBLE"
NOT_REPRODUCIBLE = "NOT_REPRODUCIBLE"


def assess_reproducibility(analysis_id: str, case_id: str | None = None) -> dict[str, Any]:
    analysis = get_analysis(analysis_id)
    if not analysis:
        return {
            "status": NOT_REPRODUCIBLE,
            "reasons": ["분석을 찾을 수 없습니다."],
            "version_diff": {},
            "document_diff": {},
        }

    reasons: list[str] = []
    snapshot = analysis.get("input_snapshot") or {}
    manifest = analysis.get("document_manifest") or []

    if not snapshot and not manifest:
        reasons.append("입력 snapshot과 문서 Manifest가 없습니다.")

    version_diff = {
        "prompt_version": {
            "then": analysis.get("prompt_version"),
            "now": PROMPT_VERSION,
            "match": analysis.get("prompt_version") == PROMPT_VERSION,
        },
        "rule_version": {
            "then": analysis.get("rule_version"),
            "now": RULE_VERSION,
            "match": analysis.get("rule_version") == RULE_VERSION,
        },
        "workflow_version": {
            "then": analysis.get("workflow_version"),
            "now": WORKFLOW_VERSION,
            "match": analysis.get("workflow_version") == WORKFLOW_VERSION,
        },
        "model": {
            "then": f"{analysis.get('model_provider')}/{analysis.get('model_name')}",
            "now": f"{LLM_PROVIDER}/{LLM_MODEL}",
            "match": (
                analysis.get("model_provider") == LLM_PROVIDER
                and analysis.get("model_name") == LLM_MODEL
            ),
        },
    }

    cid = case_id or analysis.get("case_id")
    current_manifest = build_manifest(cid) if cid else []
    then_hashes = {m.get("sha256") for m in manifest if m.get("sha256")}
    now_hashes = {m.get("sha256") for m in current_manifest if m.get("sha256")}
    document_diff = {
        "missing_now": sorted(then_hashes - now_hashes),
        "added_now": sorted(now_hashes - then_hashes),
        "unchanged": sorted(then_hashes & now_hashes),
    }
    if then_hashes and then_hashes - now_hashes:
        reasons.append("당시 문서 해시 일부가 현재 건에 없습니다.")

    version_mismatch = any(not v.get("match") for v in version_diff.values())
    if version_mismatch:
        reasons.append("모델·프롬프트·규칙 버전이 현재와 다릅니다.")

    if not snapshot and not manifest:
        status = NOT_REPRODUCIBLE
    elif reasons:
        status = PARTIALLY_REPRODUCIBLE
    else:
        status = REPRODUCIBLE

    return {
        "status": status,
        "reasons": reasons,
        "version_diff": version_diff,
        "document_diff": document_diff,
        "snapshot": snapshot,
        "manifest": manifest,
        "note": "LLM 출력은 비결정적일 수 있어 동일 텍스트를 보장하지 않습니다.",
    }


def compare_analyses(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev_rules = {s.get("rule_id") for s in previous.get("risk_signals") or []}
    curr_rules = {s.get("rule_id") for s in current.get("risk_signals") or []}
    return {
        "new_risks": sorted(curr_rules - prev_rules),
        "resolved_risks": sorted(prev_rules - curr_rules),
        "prev_status": (previous.get("review_memo") or {}).get("overall_status"),
        "curr_status": (current.get("review_memo") or {}).get("overall_status"),
        "prev_summary": (previous.get("review_memo") or {}).get("summary")
        or previous.get("ai_memo_original"),
        "curr_summary": (current.get("review_memo") or {}).get("summary")
        or current.get("ai_memo_original"),
    }
