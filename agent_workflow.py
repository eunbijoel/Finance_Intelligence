"""Step-based credit review workflow (LangGraph-ready independent steps)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT_SEC,
    MOCK_LLM,
    OLLAMA_BASE_URL,
    RISK_THRESHOLDS,
)
from dart_client import DartClient
from document_parser import extract_business_fields, merge_document_fields, parse_uploaded_file, get_field_primary_content
from financial_analysis import (
    calculate_ratios,
    compare_analyses,
    compute_ratio_changes,
    compute_yoy_changes,
    detect_risk_signals,
    run_cross_validation,
    verify_claims,
)
from database import get_latest_analysis, next_analysis_version, save_analysis
from versioning import (
    PROMPT_VERSION,
    RULE_VERSION,
    SYSTEM_PROMPT_TEMPLATE,
    WORKFLOW_VERSION,
)
import hashlib


class LLMConnectionError(Exception):
    pass


@dataclass
class WorkflowState:
    company_query: str = ""
    company: dict[str, Any] = field(default_factory=dict)
    financials: pd.DataFrame = field(default_factory=pd.DataFrame)
    disclosures: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    document_fields: dict[str, Any] = field(default_factory=dict)
    ratios: dict[str, Any] = field(default_factory=dict)
    risk_signals: list[dict[str, Any]] = field(default_factory=list)
    cross_checks: list[dict[str, Any]] = field(default_factory=list)
    claim_verifications: list[dict[str, Any]] = field(default_factory=list)
    yoy_changes: list[dict[str, Any]] = field(default_factory=list)
    ratio_changes: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    review_memo: dict[str, Any] = field(default_factory=dict)
    step_statuses: dict[str, str] = field(default_factory=dict)
    missing_items: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)
    workflow_status: str = "PENDING"
    errors: list[str] = field(default_factory=list)


# --- LLM adapter (Ollama default, OpenAI-compatible optional, mock fallback) ---


def llm_available() -> bool:
    if MOCK_LLM:
        return False
    if LLM_PROVIDER == "ollama":
        try:
            resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False
    return bool(LLM_BASE_URL and LLM_API_KEY)


def generate_text(prompt: str) -> str:
    if MOCK_LLM:
        return _mock_llm_response(prompt)
    if LLM_PROVIDER == "ollama":
        return _generate_ollama(prompt)
    if LLM_BASE_URL:
        return _generate_openai_compatible(prompt)
    return _mock_llm_response(prompt)


def _generate_ollama(prompt: str) -> str:
    system = SYSTEM_PROMPT_TEMPLATE
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    url = f"{OLLAMA_BASE_URL}/api/chat"
    try:
        resp = requests.post(url, json=payload, timeout=LLM_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        if content:
            return content.strip()
        # fallback for /api/generate-style response
        return (data.get("response") or "").strip() or _mock_llm_response(prompt)
    except Exception as exc:  # noqa: BLE001
        raise LLMConnectionError(f"Ollama call failed ({LLM_MODEL} @ {OLLAMA_BASE_URL}): {exc}") from exc


def _generate_openai_compatible(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You are a financial credit review assistant. Never invent numbers. Cite only provided evidence."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=LLM_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        raise LLMConnectionError(str(exc)) from exc


def _mock_llm_response(prompt: str) -> str:
    return (
        "[MOCK LLM] 근거에 기반한 검토 초안입니다. 실제 LLM 연결 시 더 상세한 서술이 생성됩니다.\n"
        "제공된 재무 수치와 문서 추출 결과만을 바탕으로 작성되었습니다."
    )


# --- Workflow steps ---


def step_check_inputs(state: WorkflowState, uploads: list[tuple[str, bytes]] | None = None) -> WorkflowState:
    state.step_statuses["check_inputs"] = "RUNNING"
    if not state.company_query.strip() and not (uploads or []):
        state.workflow_status = "NEEDS_MORE_INFORMATION"
        state.missing_items.append("기업명/종목코드 또는 분석 문서")
        state.questions.append("분석 대상 기업과 사업계획서를 입력해 주세요.")
        state.step_statuses["check_inputs"] = "NEEDS_MORE_INFORMATION"
        return state
    state.step_statuses["check_inputs"] = "COMPLETED"
    return state


def step_collect_dart_data(state: WorkflowState, dart: DartClient | None = None) -> WorkflowState:
    state.step_statuses["collect_dart_data"] = "RUNNING"
    client = dart or DartClient()
    company = client.search_company(state.company_query)
    if not company:
        state.workflow_status = "NEEDS_MORE_INFORMATION"
        state.missing_items.append("DART 기업 정보")
        state.questions.append("기업명 또는 종목코드를 다시 확인해 주세요.")
        state.step_statuses["collect_dart_data"] = "NEEDS_MORE_INFORMATION"
        return state
    state.company = company
    state.financials = client.get_financials(company["corp_code"])
    state.disclosures = client.get_recent_disclosures(company["corp_code"])
    state.evidence.append({"source": "DART", "type": "company_profile", "value": company})
    if state.financials.empty:
        state.missing_items.append("재무제표")
        state.questions.append("최근 재무제표 데이터를 확인할 수 없습니다. 공시 기간을 확인해 주세요.")
    state.step_statuses["collect_dart_data"] = "COMPLETED"
    return state


def step_analyze_documents(state: WorkflowState, uploads: list[tuple[str, bytes]] | None = None) -> WorkflowState:
    state.step_statuses["analyze_documents"] = "RUNNING"
    parsed_docs = []
    all_fields: list[dict[str, Any]] = []
    for filename, content in uploads or []:
        parsed = parse_uploaded_file(filename, content)
        fields = extract_business_fields(parsed)
        for ev in fields.get("unverified_items", {}).get("evidence") or []:
            pass
        # attach source filename to evidence
        for fk, fv in fields.items():
            if fk == "unverified_items":
                continue
            for ev in (fv or {}).get("evidence") or []:
                ev["source_file"] = filename
        all_fields.append(fields)
        parsed_docs.append({"filename": filename, "parsed": parsed, "fields": fields})
        for ev in _collect_doc_evidence(fields):
            state.evidence.append(ev)
    merged = merge_document_fields(all_fields) if all_fields else {}
    state.documents = parsed_docs
    state.document_fields = merged
    state.step_statuses["analyze_documents"] = "COMPLETED" if parsed_docs else "PENDING"
    return state


def step_calculate_ratios(state: WorkflowState) -> WorkflowState:
    state.step_statuses["calculate_ratios"] = "RUNNING"
    state.ratios = calculate_ratios(state.financials)
    state.evidence.append({"source": "계산", "type": "financial_ratios", "value": state.ratios})
    state.step_statuses["calculate_ratios"] = "COMPLETED" if state.ratios.get("by_year") else "FAILED"
    return state


def step_cross_validate(state: WorkflowState) -> WorkflowState:
    state.step_statuses["cross_validate"] = "RUNNING"
    state.cross_checks = run_cross_validation(state.financials, state.document_fields, state.company)
    for ck in state.cross_checks:
        state.evidence.append({"source": "교차검증", **ck})
    state.step_statuses["cross_validate"] = "COMPLETED"
    return state


def step_detect_risks(state: WorkflowState) -> WorkflowState:
    state.step_statuses["detect_risks"] = "RUNNING"
    state.risk_signals = detect_risk_signals(state.financials, state.ratios, state.document_fields)
    for sig in state.risk_signals:
        state.evidence.append({"source": "위험규칙", "rule_id": sig["rule_id"], "evidence": sig.get("evidence")})
    state.step_statuses["detect_risks"] = "COMPLETED"
    return state


def step_verify_evidence(state: WorkflowState) -> WorkflowState:
    state.step_statuses["verify_evidence"] = "RUNNING"
    has_financials = not state.financials.empty
    has_company = bool(state.company)
    if not has_company:
        state.workflow_status = "NEEDS_MORE_INFORMATION"
        state.missing_items.append("기업 식별 정보")
        state.questions.append("분석 대상 기업을 특정할 수 없습니다.")
        state.step_statuses["verify_evidence"] = "NEEDS_MORE_INFORMATION"
        return state
    if not has_financials and not state.documents:
        state.workflow_status = "NEEDS_MORE_INFORMATION"
        state.missing_items.extend(["재무제표", "사업계획서"])
        state.questions.append("재무정보 또는 사업계획서 중 하나 이상이 필요합니다.")
        state.step_statuses["verify_evidence"] = "NEEDS_MORE_INFORMATION"
        return state
    state.yoy_changes = compute_yoy_changes(state.financials)
    state.ratio_changes = compute_ratio_changes(state.ratios)
    state.claim_verifications = verify_claims(
        state.financials, state.yoy_changes, state.document_fields, state.cross_checks
    )
    unsupported = [v for v in state.claim_verifications if v.get("status") == "unsupported"]
    if unsupported:
        state.questions.extend([f"근거 확인 필요: {u['claim'][:60]}" for u in unsupported[:3]])
    state.step_statuses["verify_evidence"] = "COMPLETED"
    return state


def step_draft_memo(state: WorkflowState) -> WorkflowState:
    state.step_statuses["draft_memo"] = "RUNNING"
    if state.workflow_status == "NEEDS_MORE_INFORMATION":
        state.step_statuses["draft_memo"] = "NEEDS_MORE_INFORMATION"
        return state

    high_count = sum(1 for s in state.risk_signals if s.get("severity") == "high")
    medium_count = sum(1 for s in state.risk_signals if s.get("severity") == "medium")

    if high_count >= 1:
        overall = "중요 위험 신호 발견"
    elif medium_count >= 2 or state.missing_items:
        overall = "추가 확인 필요"
    else:
        overall = "검토상 특이사항 없음"

    latest = state.ratios.get("latest", {})
    ratio_lines = []
    for k, v in latest.items():
        if v.get("value") is not None:
            ratio_lines.append(f"- {k}: {v['value']}{v.get('unit', '')}")
        else:
            ratio_lines.append(f"- {k}: 계산 불가 ({v.get('reason', '')})")

    positives = []
    if (latest.get("current_ratio") or {}).get("value", 0) > 100:
        positives.append("유동비율이 100%를 상회합니다.")
    if (latest.get("operating_margin") or {}).get("value", 0) > 0:
        positives.append("영업이익률이 양수입니다.")

    memo = {
        "overall_status": overall,
        "disclaimer": "본 상태는 대출 승인/거절 또는 투자 추천을 의미하지 않으며, 심사역 검토 보조용 초안입니다.",
        "sections": {
            "1_company_overview": _section_company(state),
            "2_financial_status": _section_financials(state),
            "3_ratio_analysis": "\n".join(ratio_lines),
            "4_positive_factors": positives or ["확인된 긍정 요인 없음 — 추가 검토 필요"],
            "5_risk_signals": [f"[{s['severity']}] {s['title']}: {s['description']}" for s in state.risk_signals]
            or ["탐지된 위험 신호 없음"],
            "6_inconsistencies": [
                f"[{c.get('status')}] {c.get('metric')}: {c.get('reason', '')}" for c in state.cross_checks
            ] or ["교차검증 불일치 항목 없음"],
            "7_follow_up": list(dict.fromkeys([s["review_question"] for s in state.risk_signals]))[:5],
            "8_additional_documents": _additional_docs(state),
            "9_reviewer_questions": list(dict.fromkeys([s["review_question"] for s in state.risk_signals]))[:5],
            "10_summary_draft": _build_summary(state, overall),
            "11_evidence_index": state.evidence,
            "12_claim_verifications": state.claim_verifications,
            "13_intelligence": {
                "what_changed": [f"{c['label']} {c['change_pct']:+.1f}%" for c in state.yoy_changes],
                "why_important": [],
                "action_items": list(dict.fromkeys([s["review_question"] for s in state.risk_signals]))[:5],
            },
        },
        "claim_verifications": state.claim_verifications,
        "unsupported_claims": [v for v in state.claim_verifications if v.get("status") == "unsupported"],
        "summary": _build_summary(state, overall),
    }

    if llm_available():
        try:
            llm_text = generate_text(
                "다음 근거만 사용해 종합 검토 메모 초안을 5문장 이내로 작성하세요. 수치를 새로 만들지 마세요.\n"
                + json.dumps(
                    {
                        "company": state.company,
                        "ratios": state.ratios.get("latest"),
                        "risk_signals": state.risk_signals,
                    },
                    ensure_ascii=False,
                )
            )
            memo["sections"]["10_summary_draft"] = llm_text
            memo["summary"] = llm_text
        except LLMConnectionError:
            pass

    state.review_memo = memo
    state.workflow_status = "NEEDS_REVIEW"
    state.step_statuses["draft_memo"] = "COMPLETED"
    return state


def step_save_approved(
    state: WorkflowState,
    user_edits: str = "",
    approved: bool = False,
    *,
    case_id: str | None = None,
    created_by: str | None = None,
    document_manifest: list | None = None,
) -> str:
    state.step_statuses["save_approved"] = "RUNNING"
    summary = (state.review_memo or {}).get("summary") or ""
    years = []
    if not state.financials.empty and "year" in state.financials.columns:
        years = [int(y) for y in state.financials["year"].tolist()]
    input_snapshot = {
        "company": {
            "corp_code": state.company.get("corp_code"),
            "corp_name": state.company.get("corp_name"),
            "stock_code": state.company.get("stock_code"),
        },
        "financial_years": years,
        "risk_thresholds": RISK_THRESHOLDS,
        # never store secrets
    }
    analysis_version = next_analysis_version(case_id) if case_id else 1
    prompt_hash = hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
    record = {
        "company_id": state.company.get("corp_code", state.company_query),
        "company_name": state.company.get("corp_name", state.company_query),
        "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "documents": [d.get("filename") for d in state.documents],
        "ratios": state.ratios,
        "risk_signals": state.risk_signals,
        "review_memo": state.review_memo,
        "evidence": state.evidence,
        "user_edits": user_edits,
        "approved": approved,
        "case_id": case_id,
        "analysis_version": analysis_version,
        "created_by": created_by,
        "model_provider": LLM_PROVIDER,
        "model_name": LLM_MODEL,
        "prompt_version": PROMPT_VERSION,
        "rule_version": RULE_VERSION,
        "workflow_version": WORKFLOW_VERSION,
        "input_snapshot": input_snapshot,
        "document_manifest": document_manifest or [],
        "ai_memo_original": summary,
        "maker_memo_revised": user_edits or None,
        "prompt_hash": prompt_hash,
    }
    analysis_id = save_analysis(record)
    if case_id:
        from case_management import set_current_analysis
        from audit_service import write_audit
        from database import get_user

        set_current_analysis(case_id, analysis_id)
        actor = get_user(created_by) if created_by else None
        write_audit(
            action="ANALYSIS_RUN",
            actor_id=created_by,
            actor_role=(actor or {}).get("role"),
            case_id=case_id,
            analysis_id=analysis_id,
            entity_type="analysis",
            entity_id=analysis_id,
            after={"analysis_version": analysis_version, "approved": approved},
        )
    state.step_statuses["save_approved"] = "COMPLETED" if approved else "NEEDS_REVIEW"
    return analysis_id


def run_workflow(
    company_query: str,
    uploads: list[tuple[str, bytes]] | None = None,
    dart: DartClient | None = None,
) -> WorkflowState:
    state = WorkflowState(company_query=company_query, workflow_status="RUNNING")
    state = step_check_inputs(state, uploads)
    if state.workflow_status == "NEEDS_MORE_INFORMATION":
        return state
    state = step_collect_dart_data(state, dart)
    if state.workflow_status == "NEEDS_MORE_INFORMATION":
        return state
    state = step_analyze_documents(state, uploads)
    state = step_calculate_ratios(state)
    state = step_cross_validate(state)
    state = step_detect_risks(state)
    state = step_verify_evidence(state)
    if state.workflow_status == "NEEDS_MORE_INFORMATION":
        return state
    state = step_draft_memo(state)

    prev = get_latest_analysis(state.company.get("corp_code", ""))
    if prev:
        current_snapshot = {
            "risk_signals": state.risk_signals,
            "ratios": state.ratios,
            "review_memo": state.review_memo,
            "new_disclosures": state.disclosures[:2],
        }
        state.comparison = compare_analyses(prev, current_snapshot)

    state.workflow_status = "NEEDS_REVIEW"
    return state


def _section_company(state: WorkflowState) -> str:
    c = state.company
    return (
        f"기업명: {c.get('corp_name', 'N/A')}\n"
        f"종목코드: {c.get('stock_code', 'N/A')}\n"
        f"DART 코드: {c.get('corp_code', 'N/A')}\n"
        f"업종: {c.get('industry', '공시 미확인')}"
    )


def _section_financials(state: WorkflowState) -> str:
    if state.financials.empty:
        return "재무 데이터 없음"
    lines = []
    for _, row in state.financials.sort_values("year").iterrows():
        lines.append(
            f"{int(row['year'])} — 매출 {row.get('revenue', 'N/A'):,}, "
            f"영업이익 {row.get('operating_income', 'N/A'):,}, "
            f"OCF {row.get('operating_cash_flow', 'N/A'):,}"
        )
    return "\n".join(lines)


def _additional_docs(state: WorkflowState) -> list[str]:
    reqs = []
    unverified = get_field_primary_content(state.document_fields, "unverified_items")
    if not unverified:
        raw = state.document_fields.get("unverified_items")
        if isinstance(raw, dict):
            unverified = raw.get("content", "")
    if unverified and unverified != "없음":
        reqs.append(f"사업계획서 보완: {unverified}")
    if state.missing_items:
        reqs.extend(state.missing_items)
    return reqs or ["추가 요청 자료 없음"]


def _build_summary(state: WorkflowState, overall: str) -> str:
    return (
        f"[{overall}] {state.company.get('corp_name', state.company_query)} — "
        f"위험신호 {len(state.risk_signals)}건, "
        f"재무연도 {len(state.financials)}개 분석. "
        "본 결과는 심사역 검토 보조용 초안입니다."
    )


def _collect_doc_evidence(fields: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, val in fields.items():
        if isinstance(val, list):
            for entry in val:
                for ev in entry.get("evidence") or []:
                    out.append({"source": "문서", "field": key, **ev})
        elif isinstance(val, dict):
            for ev in val.get("evidence") or []:
                out.append({"source": "문서", "field": key, **ev})
    return out
