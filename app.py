"""Finance Intelligence — AI 기업검토 Cockpit."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from agent_workflow import run_workflow, step_save_approved
from config import USE_DART_MOCK
from dart_client import DartClient
from database import init_db, list_analyses
from document_parser import extract_business_fields, get_field_entries, parse_uploaded_file
from financial_analysis import calculate_ratios, compute_ratio_changes, compute_yoy_changes
from ui_helpers import (
    build_action_items,
    build_what_changed,
    build_why_important,
    compute_evidence_coverage,
    format_disclosures_display,
    format_financials_display,
    format_krw_amount,
    format_ratios_table,
    generate_markdown_report,
    get_overall_status,
    report_filename,
    status_color_class,
)

st.set_page_config(page_title="Finance Intelligence", page_icon="FI", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
    .stApp { background-color: #0f1724; color: #e2e8f0; }
    [data-testid="stSidebar"] { background-color: #111827; }
    .fi-card { background: #1a2332; border: 1px solid #2dd4bf33; border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }
    .fi-card-sm { background: #1a2332; border-radius: 6px; padding: 10px 12px; text-align: center; }
    .fi-title { color: #2dd4bf; font-weight: 700; font-size: 1.25rem; }
    .fi-subtitle { color: #94a3b8; font-size: 0.9rem; }
    .fi-muted { color: #94a3b8; font-size: 0.85rem; }
    .fi-high { color: #f87171; }
    .fi-medium { color: #fbbf24; }
    .fi-low { color: #34d399; }
    .fi-muted-status { color: #64748b; }
    .fi-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; background: #334155; color: #e2e8f0; }
    .fi-badge-mock { background: #7c3aed33; color: #c4b5fd; border: 1px solid #7c3aed55; }
    .fi-disclaimer { background: #1e293b; border-left: 4px solid #2dd4bf; padding: 10px 14px; margin: 10px 0; font-size: 0.9rem; }
    .fi-step { display: inline-block; padding: 6px 10px; margin: 2px; border-radius: 4px; font-size: 0.75rem; background: #1e293b; }
    .fi-step-done { border-bottom: 2px solid #34d399; }
    .fi-step-warn { border-bottom: 2px solid #fbbf24; }
    .fi-step-fail { border-bottom: 2px solid #f87171; }
    .fi-header-name { font-size: 1.4rem; font-weight: 700; color: #f1f5f9; }
</style>
""",
    unsafe_allow_html=True,
)

init_db()

for key, default in [
    ("company_query", "005930"),
    ("workflow_state", None),
    ("financials", pd.DataFrame()),
    ("company", {}),
    ("upload_fields", {}),
    ("disclosures", []),
    ("cached_uploads", []),
    ("viewing_history", False),
    ("selected_analysis", None),
    ("active_tab", "cockpit"),
]:
    if key not in st.session_state:
        st.session_state[key] = default

if not st.session_state.company and st.session_state.company_query and not st.session_state.viewing_history:
    _client = DartClient()
    _co = _client.search_company(st.session_state.company_query)
    if _co:
        st.session_state.company = _co
        st.session_state.financials = _client.get_financials(_co["corp_code"])
        st.session_state.disclosures = _client.get_recent_disclosures(_co["corp_code"])

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

STEP_FLOW = [
    ("check_inputs", "입력 확인"),
    ("collect_dart_data", "DART 수집"),
    ("analyze_documents", "문서 분석"),
    ("calculate_ratios", "재무 계산"),
    ("cross_validate", "교차검증"),
    ("detect_risks", "위험 탐지"),
    ("verify_evidence", "근거 검증"),
    ("draft_memo", "메모 작성"),
    ("user_review", "사용자 검토"),
    ("save_approved", "승인·저장"),
]


def _data_source_label(company: dict) -> str:
    src = company.get("source", "mock" if USE_DART_MOCK else "dart")
    return "샘플 데이터" if src == "mock" or USE_DART_MOCK else "OpenDART"


def render_header() -> None:
    st.markdown('<div class="fi-title">Finance Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="fi-subtitle">AI 기업검토 Cockpit · 심사역 검토 보조 (승인/거절 판단 아님)</div>', unsafe_allow_html=True)
    if USE_DART_MOCK:
        st.markdown('<span class="fi-badge fi-badge-mock">샘플 데이터 모드</span>', unsafe_allow_html=True)


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 기업 검색")
        query = st.text_input("기업명 / 종목코드", value=st.session_state.company_query, key="search_box")
        if st.button("조회", use_container_width=True):
            st.session_state.company_query = query
            st.session_state.viewing_history = False
            st.session_state.selected_analysis = None
            client = DartClient()
            company = client.search_company(query)
            if company:
                st.session_state.company = company
                st.session_state.financials = client.get_financials(company["corp_code"])
                st.session_state.disclosures = client.get_recent_disclosures(company["corp_code"])
            else:
                st.warning("기업을 찾을 수 없습니다.")

        st.markdown("---")
        st.markdown("### 분석 이력")
        analyses = list_analyses(limit=20)
        if not analyses:
            st.caption("저장된 분석 없음")
        for a in analyses:
            status = (a.get("review_memo") or {}).get("overall_status", "—")
            label = f"{a['company_name'][:10]} · {a['analysis_date']} · {status[:8]}"
            if st.button(label, key=f"hist_{a['analysis_id']}", use_container_width=True):
                st.session_state.selected_analysis = a
                st.session_state.viewing_history = True
                st.session_state.active_tab = "history"


def render_history_view() -> None:
    st.markdown("## 저장된 분석 이력")
    a = st.session_state.selected_analysis
    if not a:
        st.info("사이드바에서 분석 이력을 선택하세요.")
        return

    memo = a.get("review_memo") or {}
    status = memo.get("overall_status", "—")
    st.markdown(f'<div class="fi-card"><span class="{status_color_class(status)}">● {status}</span></div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("기업", a.get("company_name", "—"))
    c2.metric("분석 기준일", a.get("analysis_date", "—"))
    c3.metric("승인 여부", "승인됨" if a.get("approved") else "미승인")

    st.markdown("#### 재무비율")
    ratios = a.get("ratios", {})
    if ratios.get("by_year"):
        st.dataframe(format_ratios_table(ratios), use_container_width=True, hide_index=True)

    st.markdown("#### 위험 신호")
    for sig in a.get("risk_signals") or []:
        sev = sig.get("severity", "low")
        cls = {"high": "fi-high", "medium": "fi-medium"}.get(sev, "fi-low")
        st.markdown(f'<div class="fi-card"><span class="{cls}">[{sev.upper()}] {sig.get("title")}</span><br>{sig.get("description")}</div>', unsafe_allow_html=True)

    st.markdown("#### 종합 검토 메모")
    st.markdown(memo.get("summary") or memo.get("sections", {}).get("10_summary_draft", "—"))

    if a.get("user_edits"):
        st.markdown("#### 사용자 수정사항")
        st.write(a["user_edits"])

    with st.expander("근거 목록"):
        for ev in a.get("evidence") or []:
            st.write(f"- {ev.get('source', '—')}: {str(ev)[:120]}")

    if st.button("현재 분석으로 돌아가기", type="primary"):
        st.session_state.viewing_history = False
        st.session_state.selected_analysis = None
        st.session_state.active_tab = "cockpit"
        st.rerun()


def render_company_header(company: dict) -> None:
    today = date.today().strftime("%Y.%m.%d")
    src = _data_source_label(company)
    mock_badge = '<span class="fi-badge fi-badge-mock">샘플 데이터</span> ' if src == "샘플 데이터" else ""
    st.markdown(
        f'<div class="fi-card">'
        f'<div class="fi-header-name">{company.get("corp_name", "—")}</div>'
        f'<div class="fi-muted">{company.get("stock_code", "—")} · {company.get("industry", "업종 미확인")} · 기준일 {today}</div>'
        f'<div class="fi-muted">DART {company.get("corp_code", "—")} · 데이터 출처: {src} {mock_badge}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_action_buttons() -> None:
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("AI 통합검토 실행", use_container_width=True):
        st.session_state.active_tab = "workspace"
        uploads = st.session_state.get("cached_uploads", [])
        st.session_state.workflow_state = run_workflow(st.session_state.company_query, uploads)
        st.rerun()
    if c2.button("기업자료 업로드", use_container_width=True):
        st.session_state.active_tab = "documents"
        st.rerun()
    if c3.button("검토보고서 보기", use_container_width=True):
        st.session_state.active_tab = "workspace"
        st.rerun()
    if c4.button("분석 이력 보기", use_container_width=True):
        st.session_state.active_tab = "history"
        st.rerun()


def render_status_cards(ws: Any, financials: pd.DataFrame, disclosures: list) -> None:
    status = get_overall_status(ws)
    high_count = sum(1 for s in (getattr(ws, "risk_signals", None) or []) if s.get("severity") == "high")
    memo = getattr(ws, "review_memo", None) or {}
    verifications = getattr(ws, "claim_verifications", None) or memo.get("claim_verifications") or []
    coverage = compute_evidence_coverage(memo, verifications)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="fi-card-sm"><div class="fi-muted">종합 검토 상태</div><div class="{status_color_class(status)}">{status}</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="fi-card-sm"><div class="fi-muted">중요 위험 신호</div><div class="fi-high">{high_count}건</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="fi-card-sm"><div class="fi-muted">최근 공시</div><div>{len(disclosures)}건</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="fi-card-sm"><div class="fi-muted">근거 충족도</div><div>{coverage}</div></div>', unsafe_allow_html=True)


def render_cockpit() -> None:
    st.markdown("## 기업 Intelligence Cockpit")
    company = st.session_state.company
    financials = st.session_state.financials
    disclosures = st.session_state.get("disclosures", [])
    ws = st.session_state.workflow_state
    ratios = calculate_ratios(financials) if not financials.empty else {"by_year": {}, "latest": {}}
    comparison = getattr(ws, "comparison", None) if ws else None

    if not company:
        st.warning("왼쪽 사이드바에서 기업을 검색하세요.")
        return

    render_company_header(company)
    render_action_buttons()
    render_status_cards(ws, financials, disclosures)

    yoy = compute_yoy_changes(financials) if ws else compute_yoy_changes(financials)
    ratio_ch = compute_ratio_changes(ratios)
    risk_signals = getattr(ws, "risk_signals", None) or [] if ws else []
    doc_fields = getattr(ws, "document_fields", None) or st.session_state.upload_fields or {}
    missing = getattr(ws, "missing_items", None) or [] if ws else []

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("#### 무엇이 달라졌나")
        changes = build_what_changed(financials, ratios, comparison, disclosures)
        if changes:
            for line in changes[:8]:
                st.write(f"- {line}")
        else:
            st.caption("비교 가능한 재무 변화 없음")
    with col_b:
        st.markdown("#### 왜 중요한가")
        for line in build_why_important(yoy, ratio_ch, risk_signals):
            st.write(f"- {line}")
    with col_c:
        st.markdown("#### 무엇을 확인해야 하나")
        for item in build_action_items(risk_signals, missing, doc_fields):
            st.write(f"- {item}")

    if risk_signals:
        st.markdown("#### 핵심 위험 신호")
        for sig in risk_signals[:5]:
            render_risk_card(sig)
    elif ws:
        st.markdown(
            '<div class="fi-card fi-muted">현재 확보된 자료와 적용된 규칙에서는 위험 신호가 탐지되지 않았습니다. '
            "이는 여신 위험이 없다는 의미가 아닙니다.</div>",
            unsafe_allow_html=True,
        )

    if not financials.empty:
        st.markdown("#### 재무 추이")
        fig = go.Figure()
        for col, name, color in [("revenue", "매출액", "#2dd4bf"), ("operating_income", "영업이익", "#60a5fa"), ("operating_cash_flow", "영업CF", "#fbbf24")]:
            if col in financials.columns:
                fig.add_trace(go.Scatter(x=financials["year"], y=financials[col], mode="lines+markers", name=name, line=dict(color=color)))
        fig.update_layout(template="plotly_dark", paper_bgcolor="#0f1724", plot_bgcolor="#1a2332", height=300, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 최근 중요 공시")
    disc_df = format_disclosures_display(disclosures)
    if not disc_df.empty:
        st.dataframe(disc_df, use_container_width=True, hide_index=True)
    else:
        st.caption("공시 없음")

    with st.expander("원본 재무정보"):
        st.dataframe(format_financials_display(financials), use_container_width=True, hide_index=True)
        st.dataframe(format_ratios_table(ratios), use_container_width=True, hide_index=True)


def render_risk_card(sig: dict[str, Any]) -> None:
    sev = sig.get("severity", "low")
    cls = {"high": "fi-high", "medium": "fi-medium"}.get(sev, "fi-low")
    ev_text = ", ".join(
        f"{e.get('period', e.get('metric', ''))}: {format_krw_amount(e.get('value')) if isinstance(e.get('value'), (int, float)) else e.get('value', '')}"
        for e in (sig.get("evidence") or [])[:3]
    )
    st.markdown(
        f'<div class="fi-card"><span class="{cls}">[{sev.upper()}] {sig.get("title")}</span>'
        f'<br>{sig.get("description")}<br><span class="fi-muted">근거: {ev_text or "—"}</span></div>',
        unsafe_allow_html=True,
    )
    with st.expander("검토 질문 · 근거"):
        st.write(sig.get("review_question", "—"))
        for e in sig.get("evidence") or []:
            st.write(f"- {e}")


def render_document_review() -> list[tuple[str, bytes]]:
    st.markdown("## 기업자료 검토")
    uploads = st.file_uploader("PDF / DOCX / XLSX / CSV / TXT", type=["pdf", "docx", "xlsx", "csv", "txt"], accept_multiple_files=True)
    cached: list[tuple[str, bytes]] = []
    if not uploads:
        st.info("사업계획서 또는 관련 자료를 업로드하세요.")
        return cached

    all_merged: dict[str, list] = {}
    for f in uploads:
        content = f.getvalue() if hasattr(f, "getvalue") else f.read()
        cached.append((f.name, content))
        parsed = parse_uploaded_file(f.name, content)
        fields = extract_business_fields(parsed)
        for key, label in FIELD_LABELS.items():
            entries = get_field_entries({key: fields.get(key)} if fields.get(key) else {}, key)
            if not entries and fields.get(key):
                entries = [{"source_file": f.name, "content": fields[key].get("content", ""), "evidence": fields[key].get("evidence", [])}]
            for entry in entries:
                entry["source_file"] = f.name
                all_merged.setdefault(key, []).append(entry)

    st.session_state.upload_fields = all_merged

    for key, label in FIELD_LABELS.items():
        entries = all_merged.get(key, [])
        if not entries:
            continue
        with st.expander(label, expanded=key in {"revenue_outlook", "fund_purpose"}):
            for entry in entries:
                st.markdown(f"**{entry.get('source_file', '—')}**")
                st.write(entry.get("content", "—"))
                parsed_num = entry.get("content", "")
                if "억" in parsed_num or "조" in parsed_num:
                    st.caption("추출된 수치는 교차검증 단계에서 검증됩니다.")
                for ev in entry.get("evidence") or []:
                    st.caption(f"근거: {ev.get('location', '위치 확인 불가')}")
    return cached


def render_step_flow(step_statuses: dict[str, str]) -> None:
    html_parts = []
    status_map = {
        "COMPLETED": "fi-step-done",
        "FAILED": "fi-step-fail",
        "NEEDS_MORE_INFORMATION": "fi-step-warn",
        "NEEDS_REVIEW": "fi-step-warn",
    }
    for key, label in STEP_FLOW:
        if key == "user_review":
            status = "NEEDS_REVIEW" if step_statuses.get("draft_memo") == "COMPLETED" else "PENDING"
        else:
            status = step_statuses.get(key, "PENDING")
        css = status_map.get(status, "")
        icon = {"COMPLETED": "✓", "FAILED": "✗", "NEEDS_MORE_INFORMATION": "?", "NEEDS_REVIEW": "!", "RUNNING": "…"}.get(status, "○")
        html_parts.append(f'<span class="fi-step {css}">{icon} {label}</span>')
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_credit_workspace() -> None:
    st.markdown("## Agent Review Workspace")
    st.markdown(
        '<div class="fi-disclaimer">검토 상태는 대출 승인·거절, 신용등급, 한도 산정을 의미하지 않습니다. 심사역 검토 보조용 초안입니다.</div>',
        unsafe_allow_html=True,
    )

    ws = st.session_state.workflow_state
    if not ws:
        if st.button("AI 통합검토 실행", type="primary"):
            uploads = st.session_state.get("cached_uploads", [])
            st.session_state.workflow_state = run_workflow(st.session_state.company_query, uploads)
            st.rerun()
        st.info("AI 통합검토를 실행하면 Agent가 DART 데이터와 업로드 문서를 통합 분석합니다.")
        return

    if ws.workflow_status == "NEEDS_MORE_INFORMATION":
        st.error("NEEDS_MORE_INFORMATION — 근거 부족")
        st.write("**부족한 자료:**", ws.missing_items)
        for q in ws.questions:
            st.write(f"- {q}")
        return

    memo = ws.review_memo or {}
    overall = memo.get("overall_status", "—")
    st.markdown(f'<div class="fi-card"><span class="{status_color_class(overall)}">● {overall}</span></div>', unsafe_allow_html=True)

    unsupported = memo.get("unsupported_claims") or []
    if unsupported:
        st.warning(f"근거 없는 주장 {len(unsupported)}건 — 검토 필요")

    st.markdown("#### Agent 진행")
    render_step_flow(ws.step_statuses)

    st.markdown("#### 핵심 요약")
    st.write(memo.get("summary", "—"))

    st.markdown("#### 중요 위험 신호")
    if ws.risk_signals:
        seen_q: set[str] = set()
        for sig in ws.risk_signals:
            render_risk_card(sig)
            seen_q.add(sig.get("review_question", ""))
    else:
        st.markdown(
            '<div class="fi-card fi-muted">현재 확보된 자료와 적용된 규칙에서는 위험 신호가 탐지되지 않았습니다. '
            "이는 여신 위험이 없다는 의미가 아닙니다.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("#### 추가 확인 질문")
    questions = list(dict.fromkeys([s.get("review_question") for s in ws.risk_signals if s.get("review_question")]))
    for q in questions[:5]:
        st.write(f"- {q}")

    if unsupported:
        st.markdown("#### 근거 없는 주장")
        for u in unsupported:
            st.write(f"- [{u.get('status')}] {u.get('claim', '')[:100]}")

    st.markdown("#### 교차검증 결과")
    for ck in ws.cross_checks:
        st.markdown(f"- **[{ck.get('status')}]** {ck.get('metric')}: {ck.get('reason', '')}")

    verifications = ws.claim_verifications or []
    if verifications:
        st.markdown("#### 근거 검증")
        for v in verifications:
            label = {"supported": "근거 확인", "partial": "일부 근거", "unsupported": "근거 없음"}.get(v.get("status"), v.get("status"))
            st.write(f"- **{label}**: {v.get('claim', '')[:80]}")

    with st.expander("세부 재무비율 · 검토 메모"):
        sections = memo.get("sections", {})
        for key in ["3_ratio_analysis", "10_summary_draft", "6_inconsistencies"]:
            st.markdown(f"**{key}**")
            st.write(sections.get(key, "—"))

    with st.expander("원본 데이터 보기"):
        st.json({"step_statuses": ws.step_statuses, "cross_checks": ws.cross_checks, "evidence_count": len(ws.evidence)})

    company = st.session_state.company
    report_md = generate_markdown_report(
        company=company,
        analysis_date=date.today().isoformat(),
        documents=[d.get("filename", "") for d in ws.documents],
        financials=ws.financials,
        ratios=ws.ratios,
        risk_signals=ws.risk_signals,
        cross_checks=ws.cross_checks,
        review_memo=memo,
        evidence=ws.evidence,
        what_changed=build_what_changed(ws.financials, ws.ratios, ws.comparison, ws.disclosures),
    )
    st.download_button("Markdown 보고서 다운로드", report_md, file_name=report_filename(company), mime="text/markdown")

    st.markdown("---")
    user_edits = st.text_area("사용자 수정 내용", height=80)
    if st.button("승인 후 저장"):
        aid = step_save_approved(ws, user_edits=user_edits, approved=True)
        st.success(f"저장 완료 — {aid}")


def main() -> None:
    render_header()
    render_sidebar()

    if st.session_state.viewing_history and st.session_state.active_tab == "history":
        render_history_view()
        return

    tab_cockpit, tab_docs, tab_ws = st.tabs(["기업검토 Cockpit", "기업자료 검토", "Agent Workspace"])

    with tab_docs:
        st.session_state.cached_uploads = render_document_review()
    with tab_cockpit:
        render_cockpit()
    with tab_ws:
        render_credit_workspace()


if __name__ == "__main__":
    main()
