"""4-step enterprise review flow view."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from agent_workflow import WorkflowState, run_workflow, step_save_approved
from audit_service import list_audit_logs, write_audit
from case_management import (
    CaseError,
    add_comment,
    can_request_checker,
    enrich_case_row,
    get_case,
    list_comments,
    transition_status,
)
from database import get_analysis, get_user, list_analyses
from document_parser import extract_business_fields, get_field_entries, parse_uploaded_file
from document_registry import build_manifest, list_documents, register_document
from reproduction import assess_reproducibility
from review_ux import (
    STEP_LABELS,
    case_subtitle,
    classify_risk_signals,
    collect_review_questions,
    determine_review_step,
    role_label,
    status_label,
    step_states,
)
from ui_helpers import (
    format_disclosures_display,
    format_financials_display,
    format_ratios_table,
    generate_markdown_report,
    report_filename,
)
from versioning import ROLE_ADMIN, ROLE_CHECKER, ROLE_MAKER

FIELD_LABELS = {
    "company_overview": "기업 개요",
    "business_purpose": "사업 목적",
    "fund_purpose": "자금 사용 목적",
    "revenue_outlook": "매출 전망",
    "cost_outlook": "비용 전망",
    "repayment_plan": "상환 계획",
    "major_customers": "주요 거래처",
    "core_capabilities": "핵심 기술 및 사업 역량",
    "risk_factors": "위험요인",
    "unverified_items": "문서에서 확인되지 않은 항목",
}


def _case() -> dict[str, Any] | None:
    cid = st.session_state.get("selected_case_id")
    if not cid:
        return None
    raw = get_case(cid)
    return enrich_case_row(raw) if raw else None


def render_progress_bar(current_step: int, case: dict[str, Any]) -> None:
    states = step_states(current_step, case)
    parts = []
    for s in (1, 2, 3, 4):
        label = STEP_LABELS[s]
        stt = states[s]
        if stt == "done":
            css = "fi-prog-done"
            mark = "✓"
        elif stt == "current":
            css = "fi-prog-current"
            mark = str(s)
        elif stt == "warn":
            css = "fi-prog-warn"
            mark = "!"
        else:
            css = "fi-prog-pending"
            mark = str(s)
        parts.append(f'<span class="fi-prog {css}"><b>{mark}</b> {s}. {label}</span>')
        if s < 4:
            parts.append('<span class="fi-prog-sep">━━━</span>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_case_header(case: dict[str, Any]) -> None:
    st.markdown(f"### {case['company_name']} 기업 검토")
    left, right = st.columns([4, 1])
    with left:
        st.caption(case_subtitle(case))
    with right:
        st.markdown(
            f'<span class="fi-badge">{status_label(case.get("status"))}</span>',
            unsafe_allow_html=True,
        )


def _is_maker(user: dict, case: dict) -> bool:
    return user.get("role") == ROLE_MAKER and user.get("user_id") == case.get("maker_id")


def _is_checker(user: dict, case: dict) -> bool:
    return user.get("role") == ROLE_CHECKER and user.get("user_id") == case.get("checker_id")


def _is_admin(user: dict) -> bool:
    return user.get("role") == ROLE_ADMIN


# ---------- Step 1 ----------
def render_step_documents(case: dict[str, Any], user: dict[str, Any]) -> None:
    st.markdown("#### 자료 등록")
    can_edit = _is_maker(user, case) or _is_admin(user)
    locked = case.get("status") in {"APPROVED", "CLOSED"}

    uploads = st.file_uploader(
        "사업계획서 · 재무제표 업로드",
        type=["pdf", "docx", "xlsx", "csv", "txt"],
        accept_multiple_files=True,
        disabled=locked or not can_edit,
    )
    cached: list[tuple[str, bytes]] = []
    if uploads and can_edit and not locked:
        for f in uploads:
            content = f.getvalue() if hasattr(f, "getvalue") else f.read()
            cached.append((f.name, content))
            doc, dup = register_document(
                case_id=case["case_id"],
                filename=f.name,
                content=content,
                uploaded_by=user["user_id"],
            )
            write_audit(
                action="DOCUMENT_DUPLICATE" if dup else "DOCUMENT_UPLOADED",
                actor_id=user["user_id"],
                actor_role=user.get("role"),
                case_id=case["case_id"],
                entity_type="document",
                entity_id=doc.get("document_id"),
                after={"filename": f.name, "sha256": (doc.get("sha256") or "")[:16]},
            )
            if dup:
                st.warning(f"이미 등록된 파일과 내용이 같습니다: {f.name}")
            else:
                st.success(f"등록됨: {f.name}")
            # field extract for later AI
            parsed = parse_uploaded_file(f.name, content)
            fields = extract_business_fields(parsed)
            merged = st.session_state.get("upload_fields") or {}
            for key in FIELD_LABELS:
                entries = get_field_entries({key: fields.get(key)} if fields.get(key) else {}, key)
                if not entries and fields.get(key):
                    entries = [
                        {
                            "source_file": f.name,
                            "content": fields[key].get("content", ""),
                            "evidence": fields[key].get("evidence", []),
                        }
                    ]
                for entry in entries:
                    entry["source_file"] = f.name
                    merged.setdefault(key, []).append(entry)
            st.session_state.upload_fields = merged
        st.session_state.cached_uploads = cached

    docs = list_documents(case["case_id"])
    if not docs:
        st.info("사업계획서나 재무자료를 등록하면 AI가 문서 간 수치와 내용을 비교합니다.")
    else:
        st.markdown("##### 등록된 문서")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "파일명": d["filename"],
                        "문서 종류": (d.get("file_type") or "—").upper(),
                        "등록일": str(d.get("uploaded_at") or "")[:16],
                        "등록자": d.get("uploaded_by") or "—",
                        "상태": "등록됨",
                    }
                    for d in docs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    # missing hints (soft)
    names = " ".join(d["filename"].lower() for d in docs)
    missing = []
    if docs:
        if "상환" not in names and "repay" not in names:
            missing.append("상환계획 관련 문서가 보이지 않을 수 있습니다.")
    else:
        missing = ["사업계획서 또는 재무자료를 등록해 주세요."]
    if missing:
        st.markdown("##### 확인이 필요한 자료")
        for m in missing:
            st.caption(f"· {m}")

    with st.expander("문서 관리정보 보기"):
        if not docs:
            st.caption("문서 없음")
        else:
            for d in docs:
                st.write(
                    f"{d['filename']} · sha={(d.get('sha256') or '')[:12]}… · "
                    f"v{d.get('source_version')} · size={d.get('file_size')}"
                )

    can_start = bool(docs) and can_edit and not locked
    if st.button("AI 검토 시작", type="primary", disabled=not can_start):
        if case.get("status") in {"RECEIVED", "DOCUMENT_REQUESTED"}:
            try:
                transition_status(case["case_id"], "IN_REVIEW", actor_id=user["user_id"], reason="AI 검토 시작")
            except CaseError:
                pass
        q = case.get("stock_code") or case.get("company_name") or st.session_state.get("company_query", "")
        uploads_bytes = list(st.session_state.get("cached_uploads") or [])
        if not uploads_bytes:
            for d in docs:
                path = d.get("storage_path")
                if path and Path(path).exists():
                    uploads_bytes.append((d["filename"], Path(path).read_bytes()))
        with st.spinner("AI 검토 실행 중…"):
            state = run_workflow(q, uploads_bytes)
            st.session_state.workflow_state = state
            if state.company:
                st.session_state.company = state.company
                st.session_state.financials = state.financials
                st.session_state.disclosures = state.disclosures
            if state.workflow_status != "NEEDS_MORE_INFORMATION":
                aid = step_save_approved(
                    state,
                    approved=False,
                    case_id=case["case_id"],
                    created_by=user["user_id"],
                    document_manifest=build_manifest(case["case_id"]),
                )
                st.session_state.last_analysis_id = aid
        st.session_state.review_step_override = 2
        st.rerun()


# ---------- Step 2 ----------
def render_step_ai(case: dict[str, Any], user: dict[str, Any]) -> None:
    st.markdown("#### AI 검토")
    analyses = list_analyses(case_id=case["case_id"], limit=1)
    ws = st.session_state.get("workflow_state")
    signals = []
    memo = {}
    if analyses:
        signals = analyses[0].get("risk_signals") or []
        memo = analyses[0].get("review_memo") or {}
    elif ws:
        signals = ws.risk_signals or []
        memo = ws.review_memo or {}

    if not analyses and not ws:
        st.info("아직 AI 검토 결과가 없습니다. 1단계에서 「AI 검토 시작」을 눌러 주세요.")
        return

    if ws and ws.workflow_status == "NEEDS_MORE_INFORMATION":
        st.warning("추가 자료가 필요합니다. AI가 결론을 내기 전에 자료가 부족합니다.")
        for q in ws.missing_inputs or []:
            st.caption(f"· {q}")

    buckets = classify_risk_signals(signals)
    st.markdown('<div class="fi-card"><div class="fi-section-title">AI가 먼저 확인한 내용</div>', unsafe_allow_html=True)
    for bucket, color_cls in (("중요", "fi-high"), ("확인 필요", "fi-medium"), ("자료 보완", "fi-muted-status")):
        items = buckets.get(bucket) or []
        if not items and bucket != "중요":
            continue
        for i, sig in enumerate(items):
            title = sig.get("title") or sig.get("description") or "—"
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f'<span class="{color_cls}">**{bucket}**</span>  {title}', unsafe_allow_html=True)
            with cols[1]:
                btn = "질문 보기" if bucket == "자료 보완" else "근거 보기"
                with st.expander(btn, expanded=False):
                    for ev in sig.get("evidence") or []:
                        loc = ev.get("location") or ev.get("page") or ev.get("sheet") or "위치 확인 불가"
                        st.write(
                            f"- 출처: {ev.get('source_file') or ev.get('source') or '—'} · "
                            f"위치: {loc} · 발췌: {str(ev.get('excerpt') or ev.get('value') or '')[:160]}"
                        )
                    for q in sig.get("questions") or []:
                        st.caption(f"질문: {q}")
                    if not (sig.get("evidence") or sig.get("questions")):
                        st.caption(sig.get("description") or "위치 확인 불가")
        if not items and bucket == "중요":
            st.caption("중요로 분류된 위험 신호가 없습니다.")
    st.markdown("</div>", unsafe_allow_html=True)

    questions = collect_review_questions(signals, memo)
    st.markdown('<div class="fi-card"><div class="fi-section-title">담당자가 확인할 질문</div>', unsafe_allow_html=True)
    if questions:
        for i, q in enumerate(questions, 1):
            st.write(f"{i}. {q}")
    else:
        st.caption("추가 확인 질문이 없습니다.")
    st.markdown("</div>", unsafe_allow_html=True)

    # Hidden detail expanders
    financials = st.session_state.get("financials")
    if financials is None or (hasattr(financials, "empty") and financials.empty):
        if ws is not None:
            financials = ws.financials
    disclosures = st.session_state.get("disclosures") or (ws.disclosures if ws else [])

    with st.expander("원본 재무정보 보기"):
        if financials is not None and not getattr(financials, "empty", True):
            st.dataframe(format_financials_display(financials), use_container_width=True, hide_index=True)
            ratios = (analyses[0].get("ratios") if analyses else None) or (ws.ratios if ws else {})
            if ratios:
                st.dataframe(format_ratios_table(ratios), use_container_width=True, hide_index=True)
        else:
            st.caption("재무 데이터 없음")

    with st.expander("공시 목록 보기"):
        if disclosures:
            st.dataframe(format_disclosures_display(disclosures), use_container_width=True, hide_index=True)
        else:
            st.caption("공시 없음")

    with st.expander("분석 근거 상세"):
        st.write(memo.get("summary") or (analyses[0].get("ai_memo_original") if analyses else "—"))
        if analyses:
            st.caption(f"자료 확인 수준: {(memo.get('overall_status') or '—')}")

    err = ws and ws.workflow_status in {"FAILED", "NEEDS_MORE_INFORMATION"}
    with st.expander("AI 처리 과정 보기", expanded=bool(err)):
        if ws:
            for k, v in (ws.step_statuses or {}).items():
                st.caption(f"{k}: {v}")
        else:
            st.caption("세션에 처리 과정이 없습니다. 저장된 분석만 있습니다.")

    can_edit = _is_maker(user, case) or _is_admin(user)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("자료 보완 요청", disabled=not can_edit or case.get("status") in {"APPROVED", "CLOSED"}):
            try:
                transition_status(
                    case["case_id"], "DOCUMENT_REQUESTED", actor_id=user["user_id"], reason="자료 보완 요청"
                )
                st.session_state.review_step_override = 1
                st.rerun()
            except CaseError as exc:
                st.error(str(exc))
    with b2:
        if st.button("검토 의견 작성", type="primary", disabled=not can_edit):
            st.session_state.review_step_override = 3
            st.rerun()


# ---------- Step 3 ----------
def render_step_maker(case: dict[str, Any], user: dict[str, Any]) -> None:
    st.markdown("#### 담당자 확인")
    can_edit = _is_maker(user, case) or _is_admin(user)
    locked = case.get("status") in {"APPROVED", "CLOSED", "CHECKER_REVIEW"}

    analyses = list_analyses(case_id=case["case_id"], limit=1)
    analysis = analyses[0] if analyses else {}
    ai_text = analysis.get("ai_memo_original") or (analysis.get("review_memo") or {}).get("summary") or ""
    questions = collect_review_questions(analysis.get("risk_signals") or [], analysis.get("review_memo") or {})

    st.markdown("##### AI 검토 메모")
    st.write(ai_text or "—")

    st.markdown("##### 담당자 의견")
    opinion = st.text_area(
        "AI 분석에 대한 의견 · 추가 확인 · 요청 자료",
        value=analysis.get("maker_memo_revised") or analysis.get("user_edits") or "",
        height=140,
        disabled=not can_edit or locked,
        key="maker_opinion_box",
    )
    revised_ai = st.text_area(
        "수정이 필요한 AI 내용 (선택)",
        height=80,
        disabled=not can_edit or locked,
        key="maker_ai_revise",
    )
    q_edit = st.text_area(
        "기업에 확인할 질문 (수정·추가)",
        value="\n".join(questions),
        height=100,
        disabled=not can_edit or locked,
        key="maker_questions_box",
    )

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button("자료 보완 요청", disabled=not can_edit or locked):
            try:
                transition_status(
                    case["case_id"], "DOCUMENT_REQUESTED", actor_id=user["user_id"], reason="자료 보완"
                )
                st.session_state.review_step_override = 1
                st.rerun()
            except CaseError as exc:
                st.error(str(exc))
    with b2:
        if st.button("임시 저장", disabled=not can_edit or locked):
            if not (opinion or "").strip():
                st.error("담당자 의견을 입력해 주세요.")
            else:
                try:
                    add_comment(
                        case_id=case["case_id"],
                        author_id=user["user_id"],
                        author_role=user.get("role") or ROLE_MAKER,
                        comment_type="MAKER_OPINION",
                        comment=opinion,
                        analysis_id=analysis.get("analysis_id"),
                        original_text=ai_text,
                        revised_text=revised_ai or opinion,
                    )
                    # also persist on analysis if workflow present
                    ws = st.session_state.get("workflow_state")
                    if ws:
                        step_save_approved(
                            ws,
                            user_edits=opinion,
                            approved=False,
                            case_id=case["case_id"],
                            created_by=user["user_id"],
                            document_manifest=build_manifest(case["case_id"]),
                        )
                    st.success("임시 저장되었습니다.")
                except CaseError as exc:
                    st.error(str(exc))
    with b3:
        if st.button(
            "승인 담당자에게 전달",
            type="primary",
            disabled=not can_edit or locked or case.get("status") == "CHECKER_REVIEW",
        ):
            if not (opinion or "").strip():
                st.error("담당자 의견이 필요합니다.")
            else:
                try:
                    add_comment(
                        case_id=case["case_id"],
                        author_id=user["user_id"],
                        author_role=user.get("role") or ROLE_MAKER,
                        comment_type="MAKER_OPINION",
                        comment=opinion + (("\n\n확인 질문:\n" + q_edit) if q_edit.strip() else ""),
                        analysis_id=analysis.get("analysis_id"),
                        original_text=ai_text,
                        revised_text=revised_ai or opinion,
                    )
                    fresh = get_case(case["case_id"]) or case
                    st_now = fresh.get("status")
                    if st_now in {"RECEIVED", "DOCUMENT_REQUESTED", "CHANGES_REQUESTED"}:
                        transition_status(
                            case["case_id"], "IN_REVIEW", actor_id=user["user_id"], reason="담당자 검토 재개"
                        )
                    ok2, issues2 = can_request_checker(case["case_id"])
                    if not ok2:
                        for iss in issues2:
                            st.warning(iss)
                    else:
                        transition_status(
                            case["case_id"],
                            "CHECKER_REVIEW",
                            actor_id=user["user_id"],
                            reason="승인 담당자에게 전달",
                        )
                        st.session_state.review_step_override = 4
                        st.success("승인 담당자에게 전달되었습니다.")
                        st.rerun()
                except CaseError as exc:
                    st.error(str(exc))
        ok, issues = can_request_checker(case["case_id"])
        if not ok and can_edit:
            for iss in issues:
                st.caption(f"· {iss}")


# ---------- Step 4 ----------
def render_step_checker(case: dict[str, Any], user: dict[str, Any]) -> None:
    st.markdown("#### 검토 확인·완료")
    analyses = list_analyses(case_id=case["case_id"], limit=1)
    if not analyses:
        st.info("분석 결과가 없습니다.")
        return
    analysis = analyses[0]
    comments = list_comments(case["case_id"])
    ai_text = analysis.get("ai_memo_original") or (analysis.get("review_memo") or {}).get("summary") or ""
    maker_text = analysis.get("maker_memo_revised") or analysis.get("user_edits") or ""
    maker_comments = [c for c in comments if c.get("comment_type") in {"MAKER_OPINION", "MAKER_REVISION"}]
    if maker_comments and not maker_text:
        maker_text = maker_comments[0].get("comment") or ""

    if case.get("status") in {"APPROVED", "CLOSED"}:
        st.success("이 기업 검토는 완료되었습니다.")
        st.caption("「검토 완료」는 대출 승인·거절이 아닙니다.")
        st.markdown("##### 최종 검토 메모")
        st.write(ai_text or "—")
        maker = get_user(case.get("maker_id") or "") or {}
        checker = get_user(case.get("checker_id") or "") or {}
        st.write(f"검토 담당자: {maker.get('display_name') or case.get('maker_id')}")
        st.write(f"승인 담당자: {checker.get('display_name') or case.get('checker_id')}")
        st.write(f"완료 시각: {case.get('closed_at') or case.get('updated_at')}")
        with st.expander("변경 이력 보기"):
            logs = list_audit_logs(case_id=case["case_id"], limit=30)
            for lg in logs:
                st.caption(f"{lg['created_at'][:19]} · {lg.get('actor_id')} · {lg['action']}")
        with st.expander("이전 분석과 비교"):
            for a in list_analyses(case_id=case["case_id"], limit=5):
                if st.button(f"v{a.get('analysis_version')} 비교", key=f"repro4_{a['analysis_id']}"):
                    r = assess_reproducibility(a["analysis_id"], case["case_id"])
                    st.info(r["status"])
                    st.caption(r.get("note"))
        return

    can_act = _is_checker(user, case) or _is_admin(user)
    if not can_act:
        st.info("승인 담당자만 이 단계에서 확인·완료할 수 있습니다.")
        st.markdown("##### 검토 내용 (읽기)")
        st.write("**AI 원본**")
        st.write(ai_text or "—")
        st.write("**검토 담당자 의견**")
        st.write(maker_text or "—")
        return

    st.markdown("##### 검토 내용")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**AI 원본 메모**")
        st.write(ai_text or "—")
    with c2:
        st.markdown("**검토 담당자 의견**")
        st.write(maker_text or "—")

    st.markdown("**주요 위험 신호**")
    for sig in (analysis.get("risk_signals") or [])[:6]:
        st.write(f"- {sig.get('title') or sig.get('description')}")

    prev_req = [c for c in comments if c.get("comment_type") == "CHECKER_CHANGES_REQUESTED"]
    if prev_req:
        st.markdown("**이전 보완 요청**")
        for c in prev_req[:3]:
            st.caption(f"· {c.get('comment')}")

    st.markdown("##### 승인 담당자 동작")
    st.caption("「검토 완료」는 대출 승인·거절이 아니라, 자료와 검토 메모를 확인 완료했다는 뜻입니다.")
    reason = st.text_area("의견 (보완 요청 시 필수)", key="checker_reason_box")
    confirm1 = st.checkbox("AI 결과가 대출 승인·거절 판단이 아님을 확인했습니다.")
    confirm2 = st.checkbox("주요 근거자료를 확인했습니다.")
    confirm3 = st.checkbox("검토 담당자와 승인 담당자가 분리되어 있음을 확인했습니다.")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("보완 요청", disabled=case.get("status") != "CHECKER_REVIEW"):
            if not (reason or "").strip():
                st.error("보완 요청 시 의견은 필수입니다.")
            else:
                try:
                    add_comment(
                        case_id=case["case_id"],
                        author_id=user["user_id"],
                        author_role=user.get("role") or ROLE_CHECKER,
                        comment_type="CHECKER_CHANGES_REQUESTED",
                        comment=reason,
                        analysis_id=analysis["analysis_id"],
                        original_text=ai_text,
                        revised_text=maker_text,
                    )
                    transition_status(
                        case["case_id"], "CHANGES_REQUESTED", actor_id=user["user_id"], reason=reason
                    )
                    write_audit(
                        action="CHECKER_CHANGES_REQUESTED",
                        actor_id=user["user_id"],
                        actor_role=user.get("role"),
                        case_id=case["case_id"],
                        analysis_id=analysis["analysis_id"],
                        reason=reason,
                    )
                    st.session_state.review_step_override = 3
                    st.success("보완 요청이 전달되었습니다.")
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))
    with b2:
        if st.button("검토 완료", type="primary", disabled=case.get("status") != "CHECKER_REVIEW"):
            if not (confirm1 and confirm2 and confirm3):
                st.error("확인 항목을 모두 선택해 주세요.")
            else:
                try:
                    add_comment(
                        case_id=case["case_id"],
                        author_id=user["user_id"],
                        author_role=user.get("role") or ROLE_CHECKER,
                        comment_type="CHECKER_APPROVAL",
                        comment=reason or "검토 완료",
                        analysis_id=analysis["analysis_id"],
                    )
                    transition_status(
                        case["case_id"], "APPROVED", actor_id=user["user_id"], reason=reason or "검토 완료"
                    )
                    write_audit(
                        action="CHECKER_APPROVED",
                        actor_id=user["user_id"],
                        actor_role=user.get("role"),
                        case_id=case["case_id"],
                        analysis_id=analysis["analysis_id"],
                        reason=reason,
                    )
                    st.success("검토가 완료되었습니다. (대출 승인 아님)")
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))

    ws = st.session_state.get("workflow_state")
    if analyses and isinstance(ws, WorkflowState):
        try:
            doc_names = []
            for d in ws.documents or []:
                if isinstance(d, dict):
                    doc_names.append(d.get("filename") or d.get("name") or d.get("original_name") or "문서")
                else:
                    doc_names.append(str(d))
            analysis_date = (analyses[0].get("analysis_date") if analyses else None) or date.today().isoformat()
            company = ws.company or st.session_state.get("company") or {
                "corp_name": case.get("company_name") or "기업"
            }
            md = generate_markdown_report(
                company=company,
                analysis_date=str(analysis_date)[:10],
                documents=doc_names,
                financials=ws.financials if isinstance(ws.financials, pd.DataFrame) else pd.DataFrame(),
                ratios=ws.ratios or {},
                risk_signals=ws.risk_signals or [],
                cross_checks=ws.cross_checks or [],
                review_memo=ws.review_memo or {},
                evidence=ws.evidence or [],
            )
            st.download_button(
                "Markdown 보고서 다운로드",
                md,
                file_name=report_filename(company, str(analysis_date)[:10]),
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Markdown 보고서를 만들지 못했습니다: {exc}")


def render_review_flow(*, current_user: dict[str, Any]) -> None:
    case = _case()
    if not case:
        st.warning("기업 검토를 선택해 주세요. 「내 검토 업무」에서 열어 주세요.")
        return

    docs = list_documents(case["case_id"])
    analyses = list_analyses(case_id=case["case_id"], limit=5)
    comments = list_comments(case["case_id"])
    auto_step = determine_review_step(case, docs, analyses, comments)
    override = st.session_state.get("review_step_override")
    step = override if override in (1, 2, 3, 4) else auto_step
    # Clamp: can't jump to 4 without checker status unless approved
    if step == 4 and case.get("status") not in {"CHECKER_REVIEW", "APPROVED", "CLOSED"}:
        if override == 4:
            pass
        else:
            step = min(step, 3)

    render_case_header(case)
    render_progress_bar(step, case)
    st.markdown("")

    # Manual step nav for flexibility within allowed range
    nav = st.columns(4)
    for i, col in enumerate(nav, 1):
        with col:
            disabled = False
            if i == 2 and not docs and not analyses:
                disabled = True
            if i >= 3 and not analyses and not st.session_state.get("workflow_state"):
                disabled = True
            if st.button(f"{i}. {STEP_LABELS[i]}", key=f"nav_step_{i}", disabled=disabled):
                st.session_state.review_step_override = i
                st.rerun()

    if step == 1:
        render_step_documents(case, current_user)
    elif step == 2:
        render_step_ai(case, current_user)
    elif step == 3:
        render_step_maker(case, current_user)
    else:
        render_step_checker(case, current_user)

    with st.expander("변경 이력 · 관리 정보"):
        logs = list_audit_logs(case_id=case["case_id"], limit=20)
        for lg in logs[:15]:
            st.caption(f"{lg['created_at'][:19]} · {lg.get('actor_id')} · {lg['action']}")
        st.write(f"검토번호: {case.get('case_number')}")
        st.write(f"검토 담당자: {case.get('maker_id')} · 승인 담당자: {case.get('checker_id')}")
        if analyses:
            a = analyses[0]
            st.write(
                f"분석 v{a.get('analysis_version')} · "
                f"{a.get('model_provider')}/{a.get('model_name')} · "
                f"prompt={a.get('prompt_version')}"
            )
