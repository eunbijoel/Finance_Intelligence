"""Finance Intelligence — AI 기업 검토."""

from __future__ import annotations

from datetime import date
from typing import Any
import difflib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from agent_workflow import run_workflow, step_save_approved
from audit_service import list_audit_logs, write_audit
from case_management import (
    CaseError,
    add_comment,
    can_request_checker,
    create_case,
    enrich_case_row,
    get_case,
    inbox_summary,
    list_cases,
    list_comments,
    transition_status,
)
from config import USE_DART_MOCK
from dart_client import DartClient
from database import get_analysis, get_user, init_db, list_analyses, list_users
from document_parser import extract_business_fields, get_field_entries, parse_uploaded_file
from document_registry import build_manifest, list_documents, register_document
from financial_analysis import calculate_ratios, compute_ratio_changes, compute_yoy_changes
from reproduction import assess_reproducibility, compare_analyses as compare_repro
from versioning import (
    CASE_STATUS_LABELS,
    CASE_STATUSES,
    PRIORITIES,
    PROMPT_VERSION,
    ROLE_CHECKER,
    ROLE_MAKER,
    RULE_VERSION,
    WORKFLOW_VERSION,
)
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
    /* Streamlit Light/Dark 토글을 존중 — .stApp 배경은 건드리지 않음 */
    [data-theme="dark"] .fi-card { background: #1a2332; border: 1px solid #2dd4bf33; border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; }
    [data-theme="light"] .fi-card { background: #f8fafc; border: 1px solid #0d948833; border-radius: 8px; padding: 14px 16px; margin-bottom: 10px; color: #0f172a; }
    [data-theme="dark"] .fi-card-sm { background: #1a2332; border-radius: 6px; padding: 10px 12px; text-align: center; }
    [data-theme="light"] .fi-card-sm { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; text-align: center; color: #0f172a; }
    .fi-title { color: #0d9488; font-weight: 700; font-size: 1.25rem; }
    [data-theme="dark"] .fi-subtitle { color: #94a3b8; font-size: 0.9rem; }
    [data-theme="light"] .fi-subtitle { color: #64748b; font-size: 0.9rem; }
    [data-theme="dark"] .fi-muted { color: #94a3b8; font-size: 0.85rem; }
    [data-theme="light"] .fi-muted { color: #64748b; font-size: 0.85rem; }
    .fi-high { color: #dc2626; }
    .fi-medium { color: #d97706; }
    .fi-low { color: #059669; }
    .fi-muted-status { color: #64748b; }
    [data-theme="dark"] .fi-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; background: #334155; color: #e2e8f0; }
    [data-theme="light"] .fi-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; background: #e2e8f0; color: #334155; }
    .fi-badge-mock { background: #ede9fe; color: #6d28d9; border: 1px solid #c4b5fd; }
    [data-theme="dark"] .fi-badge-mock { background: #7c3aed33; color: #c4b5fd; border: 1px solid #7c3aed55; }
    [data-theme="dark"] .fi-disclaimer { background: #1e293b; border-left: 4px solid #2dd4bf; padding: 10px 14px; margin: 10px 0; font-size: 0.9rem; }
    [data-theme="light"] .fi-disclaimer { background: #ecfdf5; border-left: 4px solid #0d9488; padding: 10px 14px; margin: 10px 0; font-size: 0.9rem; color: #0f172a; }
    [data-theme="dark"] .fi-step { display: inline-block; padding: 6px 10px; margin: 2px; border-radius: 4px; font-size: 0.75rem; background: #1e293b; }
    [data-theme="light"] .fi-step { display: inline-block; padding: 6px 10px; margin: 2px; border-radius: 4px; font-size: 0.75rem; background: #f1f5f9; color: #0f172a; }
    .fi-step-done { border-bottom: 2px solid #059669; }
    .fi-step-warn { border-bottom: 2px solid #d97706; }
    .fi-step-fail { border-bottom: 2px solid #dc2626; }
    [data-theme="dark"] .fi-header-name { font-size: 1.4rem; font-weight: 700; color: #f1f5f9; }
    [data-theme="light"] .fi-header-name { font-size: 1.4rem; font-weight: 700; color: #0f172a; }
</style>
""",
    unsafe_allow_html=True,
)


def _is_light_theme() -> bool:
    try:
        theme_type = st.context.theme.type
        if theme_type:
            return theme_type == "light"
    except Exception:  # noqa: BLE001
        pass
    try:
        return str(st.get_option("theme.base")).lower() == "light"
    except Exception:  # noqa: BLE001
        return False


def _plotly_layout_kwargs(height: int = 300) -> dict[str, Any]:
    light = _is_light_theme()
    return {
        "template": "plotly_white" if light else "plotly_dark",
        "paper_bgcolor": "rgba(0,0,0,0)" if light else "#0f1724",
        "plot_bgcolor": "#f8fafc" if light else "#1a2332",
        "height": height,
        "margin": dict(l=20, r=20, t=30, b=20),
        "legend": dict(orientation="h"),
        "font": {"color": "#0f172a" if light else "#e2e8f0"},
    }

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
    ("active_tab", "inbox"),
    ("current_user_id", "maker01"),
    ("selected_case_id", None),
    ("nav_page", "inbox"),
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
    st.markdown('<div class="fi-subtitle">AI 기업 검토 · 심사역 검토 보조 (승인/거절 판단 아님)</div>', unsafe_allow_html=True)
    if USE_DART_MOCK:
        st.markdown('<span class="fi-badge fi-badge-mock">샘플 데이터 모드</span>', unsafe_allow_html=True)


def _load_company_into_session(company: dict[str, Any], client: DartClient | None = None) -> None:
    client = client or DartClient()
    st.session_state.company_query = company.get("stock_code") or company.get("corp_name") or ""
    st.session_state.viewing_history = False
    st.session_state.selected_analysis = None
    st.session_state.company = company
    st.session_state.financials = client.get_financials(company["corp_code"])
    st.session_state.disclosures = client.get_recent_disclosures(company["corp_code"])


def _current_user() -> dict[str, Any]:
    uid = st.session_state.current_user_id
    return get_user(uid) or {"user_id": uid, "display_name": uid, "role": "MAKER"}


def _selected_case() -> dict[str, Any] | None:
    cid = st.session_state.selected_case_id
    return enrich_case_row(get_case(cid)) if cid and get_case(cid) else None


def render_case_banner() -> None:
    case = _selected_case()
    user = _current_user()
    if case:
        label = CASE_STATUS_LABELS.get(case["status"], case["status"])
        st.info(
            f"심사 건 **{case['case_number']}** · {case['company_name']} · 상태: **{label}** · "
            f"현재 사용자: {user.get('display_name')} ({user.get('role')})  \n"
            "※ 「검토 승인」은 대출 승인이 아니라 **검토 메모·자료 검토 완료**를 의미합니다. "
            "(프로토타입 권한 — 실제 SSO/LDAP 아님)"
        )
    else:
        st.caption(
            f"현재 사용자: {user.get('display_name')} ({user.get('role')}) · "
            "심사 건을 선택하면 건 기반 워크플로로 동작합니다. (기존 기업 조회로도 사용 가능)"
        )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 현재 사용자")
        users = list_users()
        options = {f"{u['display_name']} ({u['role']})": u["user_id"] for u in users}
        labels = list(options.keys())
        current = st.session_state.current_user_id
        default_idx = 0
        for i, uid in enumerate(options.values()):
            if uid == current:
                default_idx = i
                break
        chosen = st.selectbox("사용자 선택 (프로토타입)", labels, index=default_idx)
        st.session_state.current_user_id = options[chosen]
        st.caption("실제 인증이 아닌 프로토타입용 사용자 전환입니다.")

        st.markdown("---")
        st.markdown("### 내비게이션")
        if st.button("심사 업무함", use_container_width=True):
            st.session_state.nav_page = "inbox"
            st.session_state.viewing_history = False
        if st.button("새 심사 건 생성", use_container_width=True):
            st.session_state.nav_page = "create_case"
        if st.button("기업·Agent 검토", use_container_width=True):
            st.session_state.nav_page = "workspace"
        if st.button("설정·버전", use_container_width=True):
            st.session_state.nav_page = "settings"

        st.markdown("---")
        st.markdown("### 기업 검색 (레거시 호환)")
        query = st.text_input("기업명 / 종목코드", value=st.session_state.company_query, key="search_box")
        client = DartClient()

        if st.button("조회", use_container_width=True):
            st.session_state.company_query = query
            st.session_state.viewing_history = False
            st.session_state.selected_analysis = None
            company = client.search_company(query)
            if company:
                _load_company_into_session(company, client)
                st.session_state.nav_page = "workspace"
            else:
                st.warning("기업을 찾을 수 없습니다.")

        suggestions = client.suggest_companies(query, limit=5) if (query or "").strip() else []
        if suggestions:
            st.caption("추천 기업")
            for sug in suggestions:
                code = (sug.get("stock_code") or "").strip() or "—"
                label = f"{sug.get('corp_name', '—')} · {code}"
                if st.button(label, key=f"sug_{sug.get('corp_code')}_{code}", use_container_width=True):
                    _load_company_into_session(sug, client)
                    st.session_state.nav_page = "workspace"
                    st.rerun()
        elif (query or "").strip():
            st.caption("추천 결과 없음")

        st.markdown("---")
        st.markdown("### 분석 이력 (레거시)")
        analyses = list_analyses(limit=10)
        if not analyses:
            st.caption("저장된 분석 없음")
        for a in analyses:
            status = (a.get("review_memo") or {}).get("overall_status", "—")
            label = f"{a['company_name'][:10]} · {a['analysis_date']} · {status[:8]}"
            if st.button(label, key=f"hist_{a['analysis_id']}", use_container_width=True):
                st.session_state.selected_analysis = a
                st.session_state.viewing_history = True
                st.session_state.nav_page = "legacy_history"


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
        st.session_state.active_tab = "review"
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


def render_review_home() -> None:
    st.markdown("## 기업 검토")
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
        fig.update_layout(**_plotly_layout_kwargs(300))
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
    user = _current_user()
    user_edits = st.text_area("Maker 추가 의견 / 수정 메모", height=80)
    case = _selected_case()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("분석 결과 저장 (버전 생성)"):
            manifest = build_manifest(case["case_id"]) if case else []
            # register any cached uploads into case
            if case:
                for fname, content in st.session_state.get("cached_uploads") or []:
                    _doc, dup = register_document(
                        case_id=case["case_id"],
                        filename=fname,
                        content=content,
                        uploaded_by=user["user_id"],
                    )
                    if dup:
                        write_audit(
                            action="DOCUMENT_DUPLICATE",
                            actor_id=user["user_id"],
                            actor_role=user.get("role"),
                            case_id=case["case_id"],
                            entity_type="document",
                            entity_id=_doc.get("document_id"),
                            reason=f"duplicate hash {_doc.get('sha256','')[:12]}",
                        )
                manifest = build_manifest(case["case_id"])
            aid = step_save_approved(
                ws,
                user_edits=user_edits,
                approved=False,
                case_id=case["case_id"] if case else None,
                created_by=user["user_id"],
                document_manifest=manifest,
            )
            if user_edits.strip() and case:
                add_comment(
                    case_id=case["case_id"],
                    author_id=user["user_id"],
                    author_role=user.get("role") or ROLE_MAKER,
                    comment_type="MAKER_OPINION",
                    comment=user_edits,
                    analysis_id=aid,
                    original_text=(ws.review_memo or {}).get("summary"),
                    revised_text=user_edits,
                )
            st.success(f"저장 완료 — analysis_id: {aid}")
    with col_b:
        if case and user.get("role") == ROLE_MAKER:
            ok, issues = can_request_checker(case["case_id"])
            if st.button("Checker 검토 요청", disabled=not ok):
                try:
                    transition_status(
                        case["case_id"],
                        "CHECKER_REVIEW",
                        actor_id=user["user_id"],
                        reason="Maker 검토 완료",
                    )
                    st.success("Checker 검토로 전환되었습니다.")
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))
            if not ok:
                for iss in issues:
                    st.caption(f"· {iss}")


def render_inbox() -> None:
    st.markdown("## 심사 업무함")
    st.caption("「검토 승인」= 대출 승인 아님. 검토 메모·자료 검토 완료를 의미합니다.")
    c1, c2, c3, c4, c5 = st.columns(5)
    summary = inbox_summary()
    c1.metric("전체 진행 건", summary["active"])
    c2.metric("자료 보완 필요", summary["document_requested"])
    c3.metric("Checker 대기", summary["checker_review"])
    c4.metric("기한 경과", summary["overdue"])
    c5.metric("중요 위험 보유", summary["high_risk"])

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    search = f1.text_input("기업명/심사번호")
    status = f2.selectbox("상태", ["(전체)"] + list(CASE_STATUSES))
    priority = f3.selectbox("우선순위", ["(전체)"] + list(PRIORITIES))
    makers = ["(전체)"] + [u["user_id"] for u in list_users() if u["role"] == ROLE_MAKER]
    checkers = ["(전체)"] + [u["user_id"] for u in list_users() if u["role"] == ROLE_CHECKER]
    maker_f = f4.selectbox("Maker", makers)
    checker_f = f5.selectbox("Checker", checkers)
    overdue_only = f6.checkbox("기한 경과만")

    cases = list_cases(
        search=search or None,
        status=None if status == "(전체)" else status,
        priority=None if priority == "(전체)" else priority,
        maker_id=None if maker_f == "(전체)" else maker_f,
        checker_id=None if checker_f == "(전체)" else checker_f,
        overdue_only=overdue_only,
    )
    if not cases:
        st.info("표시할 심사 건이 없습니다. 「새 심사 건 생성」으로 시작하세요.")
        return

    rows = []
    for c in cases:
        rows.append(
            {
                "심사번호": c["case_number"],
                "기업명": c["company_name"],
                "신청금액": c.get("application_amount"),
                "자금용도": (c.get("fund_purpose") or "")[:20],
                "신청상품": c.get("loan_product"),
                "Maker": c.get("maker_id"),
                "Checker": c.get("checker_id"),
                "상태": CASE_STATUS_LABELS.get(c["status"], c["status"]),
                "우선순위": c.get("priority"),
                "처리기한": c.get("due_date"),
                "D-Day": c.get("d_day"),
                "최근분석": (c.get("last_analysis_at") or "—")[:16],
                "고위험": c.get("high_risk_count", 0),
                "근거": c.get("evidence_coverage"),
                "case_id": c["case_id"],
            }
        )
    st.dataframe(pd.DataFrame(rows).drop(columns=["case_id"]), use_container_width=True, hide_index=True)
    st.markdown("#### 건 열기")
    for c in cases[:30]:
        label = f"{c['case_number']} · {c['company_name']} · {CASE_STATUS_LABELS.get(c['status'], c['status'])}"
        if st.button(label, key=f"open_{c['case_id']}"):
            st.session_state.selected_case_id = c["case_id"]
            st.session_state.nav_page = "case_detail"
            # preload company if stock/corp known
            q = c.get("stock_code") or c.get("company_name")
            if q:
                co = DartClient().search_company(q)
                if co:
                    _load_company_into_session(co)
            st.rerun()


def render_create_case() -> None:
    st.markdown("## 새 심사 건 생성")
    user = _current_user()
    makers = [u for u in list_users() if u["role"] == ROLE_MAKER]
    checkers = [u for u in list_users() if u["role"] == ROLE_CHECKER]
    with st.form("create_case_form"):
        company_name = st.text_input("기업명 *")
        stock_or_dart = st.text_input("종목코드 또는 DART 코드 (선택)")
        application_amount = st.number_input("신청금액 *", min_value=0.0, step=1_000_000.0)
        fund_purpose = st.text_input("자금용도 *")
        loan_product = st.text_input("신청상품 *")
        application_date = st.date_input("접수일", value=date.today())
        due_date = st.date_input("처리기한", value=date.today())
        priority = st.selectbox("우선순위", list(PRIORITIES), index=1)
        maker_id = st.selectbox("Maker *", [u["user_id"] for u in makers], format_func=lambda x: f"{x} / {[u['display_name'] for u in makers if u['user_id']==x][0]}")
        checker_id = st.selectbox("Checker *", [u["user_id"] for u in checkers], format_func=lambda x: f"{x} / {[u['display_name'] for u in checkers if u['user_id']==x][0]}")
        notes = st.text_area("비고")
        submitted = st.form_submit_button("생성")
    if submitted:
        if not fund_purpose.strip() or not loan_product.strip():
            st.error("자금용도·신청상품은 필수입니다.")
            return
        company_id = None
        stock_code = None
        if stock_or_dart.strip():
            q = stock_or_dart.strip()
            if q.isdigit() or len(q) == 6:
                stock_code = q.zfill(6) if q.isdigit() else q
            co = DartClient().search_company(q if not company_name else company_name) or DartClient().search_company(q)
            if co:
                company_id = co.get("corp_code")
                stock_code = co.get("stock_code") or stock_code
                if not company_name:
                    company_name = co.get("corp_name")
        try:
            case = create_case(
                {
                    "company_name": company_name,
                    "company_id": company_id,
                    "stock_code": stock_code,
                    "application_amount": application_amount,
                    "fund_purpose": fund_purpose,
                    "loan_product": loan_product,
                    "application_date": application_date.isoformat(),
                    "due_date": due_date.isoformat(),
                    "priority": priority,
                    "maker_id": maker_id,
                    "checker_id": checker_id,
                    "notes": notes,
                },
                created_by=user["user_id"],
            )
            st.success(f"생성 완료: {case['case_number']}")
            st.session_state.selected_case_id = case["case_id"]
            st.session_state.nav_page = "case_detail"
            st.rerun()
        except CaseError as exc:
            st.error(str(exc))


def render_case_detail() -> None:
    case = _selected_case()
    if not case:
        st.warning("선택된 심사 건이 없습니다. 업무함에서 선택하세요.")
        return
    user = _current_user()
    st.markdown(f"## 심사 건 상세 — {case['case_number']}")
    st.markdown(
        '<div class="fi-disclaimer">「검토 승인」은 대출 승인/거절이 아닙니다. '
        "AI·Maker 검토 자료가 Checker에 의해 검토 완료되었음을 의미합니다.</div>",
        unsafe_allow_html=True,
    )
    a, b, c, d = st.columns(4)
    a.metric("상태", CASE_STATUS_LABELS.get(case["status"], case["status"]))
    b.metric("우선순위", case.get("priority"))
    c.metric("Maker", case.get("maker_id"))
    d.metric("Checker", case.get("checker_id"))
    st.write(
        f"**기업:** {case['company_name']} · 종목 {case.get('stock_code') or '—'} · "
        f"DART {case.get('company_id') or '—'}  \n"
        f"**신청금액:** {case.get('application_amount')} · **용도:** {case.get('fund_purpose')} · "
        f"**상품:** {case.get('loan_product')}  \n"
        f"**접수:** {case.get('application_date')} · **기한:** {case.get('due_date')} (D-Day: {case.get('d_day')})"
    )

    st.markdown("#### 상태 전환")
    cols = st.columns(4)
    actions = [
        ("검토 시작", "IN_REVIEW"),
        ("자료 보완 요청", "DOCUMENT_REQUESTED"),
        ("검토 재개", "IN_REVIEW"),
        ("종결", "CLOSED"),
    ]
    for i, (label, status) in enumerate(actions):
        with cols[i]:
            if st.button(label, key=f"tr_{status}_{i}"):
                try:
                    transition_status(case["case_id"], status, actor_id=user["user_id"])
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))

    st.markdown("#### 제출 문서")
    docs = list_documents(case["case_id"])
    if docs:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "파일": d["filename"],
                        "SHA256": d["sha256"][:16] + "…",
                        "버전": d["source_version"],
                        "업로더": d.get("uploaded_by"),
                        "시각": d.get("uploaded_at"),
                    }
                    for d in docs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("업로드된 문서 없음 — 기업자료 검토 탭에서 업로드하세요.")

    st.markdown("#### 최신 분석")
    analyses = list_analyses(case_id=case["case_id"], limit=5)
    if analyses:
        latest = analyses[0]
        st.write(
            f"v{latest.get('analysis_version')} · {latest.get('created_at')} · "
            f"모델 {latest.get('model_provider')}/{latest.get('model_name')} · "
            f"prompt {latest.get('prompt_version')} · rule {latest.get('rule_version')}"
        )
        st.write((latest.get("review_memo") or {}).get("summary") or latest.get("ai_memo_original") or "—")
        st.caption(
            f"AI 원문 보존: {(latest.get('ai_memo_original') or '—')[:80]}… · "
            f"Maker 수정: {(latest.get('maker_memo_revised') or '—')[:80]}"
        )
    else:
        st.caption("아직 분석 없음")

    st.markdown("#### 검토 의견")
    for cm in list_comments(case["case_id"])[:10]:
        st.write(
            f"- [{cm.get('comment_type')}] {cm.get('author_id')} ({cm.get('author_role')}) "
            f"@ {cm.get('created_at')}: {(cm.get('comment') or '')[:120]}"
        )

    st.markdown("#### 감사로그 (최근)")
    for lg in list_audit_logs(case_id=case["case_id"], limit=8):
        st.caption(f"{lg['created_at']} · {lg.get('actor_id')} · {lg['action']}")

    if st.button("기업·Agent 검토로 이동"):
        st.session_state.nav_page = "workspace"
        st.rerun()


def render_checker_tab() -> None:
    st.markdown("## Checker 검토")
    case = _selected_case()
    user = _current_user()
    if not case:
        st.warning("심사 건을 먼저 선택하세요.")
        return
    if user.get("role") not in {ROLE_CHECKER, "ADMIN"}:
        st.warning("Checker(또는 ADMIN) 계정으로 전환하세요.")
    analyses = list_analyses(case_id=case["case_id"], limit=1)
    if not analyses:
        st.info("분석 결과가 없습니다.")
        return
    analysis = analyses[0]
    ai_text = analysis.get("ai_memo_original") or (analysis.get("review_memo") or {}).get("summary") or ""
    maker_text = analysis.get("maker_memo_revised") or analysis.get("user_edits") or ""
    comments = list_comments(case["case_id"])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### AI 원본 메모")
        st.write(ai_text or "—")
    with c2:
        st.markdown("#### Maker 의견/수정")
        st.write(maker_text or "—")

    if ai_text or maker_text:
        st.markdown("#### 차이 (difflib)")
        diff = difflib.unified_diff(
            (ai_text or "").splitlines(),
            (maker_text or ai_text or "").splitlines(),
            fromfile="AI",
            tofile="Maker",
            lineterm="",
        )
        st.code("\n".join(diff) or "(차이 없음)")

    st.markdown("#### 위험 신호")
    for sig in analysis.get("risk_signals") or []:
        render_risk_card(sig)
        with st.expander("원문 위치 확인"):
            for ev in sig.get("evidence") or []:
                loc = ev.get("location") or ev.get("page") or ev.get("sheet")
                st.write(
                    f"- 파일: {ev.get('source_file') or ev.get('source') or '—'} · "
                    f"위치: {loc or '위치 확인 불가'} · 발췌: {str(ev.get('excerpt') or ev.get('value') or '')[:120]}"
                )

    st.markdown("#### 이전 Checker 의견")
    for cm in comments:
        if cm.get("comment_type") in {"CHECKER_CHANGES_REQUESTED", "CHECKER_APPROVAL"}:
            st.write(f"- [{cm['comment_type']}] {cm.get('author_id')} @ {cm.get('created_at')}: {cm.get('comment')}")

    st.markdown("#### Checker 동작")
    reason = st.text_area("수정 요청 / 승인 의견", key="checker_reason")
    confirm1 = st.checkbox("AI 결과가 최종 금융 판단이 아님을 확인했습니다.")
    confirm2 = st.checkbox("주요 근거를 검토했습니다.")
    confirm3 = st.checkbox("Maker와 Checker가 분리되었음을 확인했습니다.")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("수정 요청"):
            if not (reason or "").strip():
                st.error("수정 요청 시 의견은 필수입니다.")
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
                        case["case_id"],
                        "CHANGES_REQUESTED",
                        actor_id=user["user_id"],
                        reason=reason,
                    )
                    write_audit(
                        action="CHECKER_CHANGES_REQUESTED",
                        actor_id=user["user_id"],
                        actor_role=user.get("role"),
                        case_id=case["case_id"],
                        analysis_id=analysis["analysis_id"],
                        reason=reason,
                    )
                    st.success("수정 요청이 반영되었습니다.")
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))
    with b2:
        if st.button("검토 승인"):
            if not (confirm1 and confirm2 and confirm3):
                st.error("승인 전 확인 체크박스를 모두 선택하세요.")
            else:
                try:
                    add_comment(
                        case_id=case["case_id"],
                        author_id=user["user_id"],
                        author_role=user.get("role") or ROLE_CHECKER,
                        comment_type="CHECKER_APPROVAL",
                        comment=reason or "검토 승인",
                        analysis_id=analysis["analysis_id"],
                    )
                    transition_status(
                        case["case_id"],
                        "APPROVED",
                        actor_id=user["user_id"],
                        reason=reason or "검토 승인",
                    )
                    write_audit(
                        action="CHECKER_APPROVED",
                        actor_id=user["user_id"],
                        actor_role=user.get("role"),
                        case_id=case["case_id"],
                        analysis_id=analysis["analysis_id"],
                        reason=reason,
                    )
                    st.success("검토 승인 완료 (대출 승인 아님).")
                    st.rerun()
                except CaseError as exc:
                    st.error(str(exc))


def render_audit_repro_tab() -> None:
    st.markdown("## 분석·감사 이력 / 결과 재현")
    case = _selected_case()
    if not case:
        st.warning("심사 건을 선택하세요.")
        return
    analyses = list_analyses(case_id=case["case_id"], limit=20)
    st.markdown("#### 분석 버전")
    for a in analyses:
        st.write(
            f"- v{a.get('analysis_version')} · {a.get('created_at')} · "
            f"{a.get('model_provider')}/{a.get('model_name')} · "
            f"prompt={a.get('prompt_version')} rule={a.get('rule_version')}"
        )
        if st.button("이 분석 재현성 확인", key=f"repro_{a['analysis_id']}"):
            result = assess_reproducibility(a["analysis_id"], case["case_id"])
            st.session_state[f"repro_result_{a['analysis_id']}"] = result
            write_audit(
                action="REPRODUCTION_CHECKED",
                actor_id=_current_user()["user_id"],
                actor_role=_current_user().get("role"),
                case_id=case["case_id"],
                analysis_id=a["analysis_id"],
                after={"status": result["status"]},
            )
        stored = st.session_state.get(f"repro_result_{a['analysis_id']}")
        if stored:
            st.info(f"재현 상태: **{stored['status']}** — {stored.get('note')}")
            for r in stored.get("reasons") or []:
                st.caption(f"· {r}")
            with st.expander("버전/문서 비교 상세"):
                st.json({"version_diff": stored.get("version_diff"), "document_diff": stored.get("document_diff")})
            if st.button("현재 조건으로 재실행", key=f"rerun_{a['analysis_id']}"):
                q = case.get("stock_code") or case.get("company_name")
                uploads = []
                for d in list_documents(case["case_id"]):
                    path = d.get("storage_path")
                    if path:
                        try:
                            from pathlib import Path
                            uploads.append((d["filename"], Path(path).read_bytes()))
                        except OSError:
                            pass
                state = run_workflow(q or case["company_name"], uploads)
                st.session_state.workflow_state = state
                if state.workflow_status != "NEEDS_MORE_INFORMATION":
                    aid = step_save_approved(
                        state,
                        approved=False,
                        case_id=case["case_id"],
                        created_by=_current_user()["user_id"],
                        document_manifest=build_manifest(case["case_id"]),
                    )
                    write_audit(
                        action="REPRODUCTION_RERUN",
                        actor_id=_current_user()["user_id"],
                        actor_role=_current_user().get("role"),
                        case_id=case["case_id"],
                        analysis_id=aid,
                        after={"from": a["analysis_id"], "to": aid},
                    )
                    new_a = get_analysis(aid)
                    st.json(compare_repro(a, new_a or {}))
                    st.success(f"재실행 저장: {aid}")

    st.markdown("#### 감사로그 (수정·삭제 불가)")
    logs = list_audit_logs(case_id=case["case_id"], limit=50)
    if not logs:
        st.caption("감사로그 없음")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "시각": lg["created_at"],
                        "행위자": lg.get("actor_id"),
                        "역할": lg.get("actor_role"),
                        "액션": lg["action"],
                        "사유": (lg.get("reason") or "")[:80],
                    }
                    for lg in logs
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


def render_settings() -> None:
    st.markdown("## 설정·버전 정보")
    st.write(f"- Prompt: `{PROMPT_VERSION}`")
    st.write(f"- Rule: `{RULE_VERSION}`")
    st.write(f"- Workflow: `{WORKFLOW_VERSION}`")
    st.caption("프로토타입 권한 모델입니다. 실제 SSO/LDAP/전자결재 연동은 포함되지 않습니다.")


def render_document_review() -> list[tuple[str, bytes]]:
    st.markdown("## 기업자료 검토")
    case = _selected_case()
    user = _current_user()
    uploads = st.file_uploader("PDF / DOCX / XLSX / CSV / TXT", type=["pdf", "docx", "xlsx", "csv", "txt"], accept_multiple_files=True)
    cached: list[tuple[str, bytes]] = []
    if not uploads:
        st.info("사업계획서 또는 관련 자료를 업로드하세요.")
        if case:
            docs = list_documents(case["case_id"])
            if docs:
                st.markdown("#### 등록된 문서")
                for d in docs:
                    st.write(f"- {d['filename']} · sha256={d['sha256'][:12]}… · v{d['source_version']}")
        return cached

    all_merged: dict[str, list] = {}
    for f in uploads:
        content = f.getvalue() if hasattr(f, "getvalue") else f.read()
        cached.append((f.name, content))
        if case:
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
                after={"filename": f.name, "sha256": doc.get("sha256")},
            )
            if dup:
                st.warning(f"중복 업로드: {f.name} (동일 SHA-256)")
            else:
                st.success(f"등록: {f.name}")
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
                for ev in entry.get("evidence") or []:
                    loc = ev.get("location") or ev.get("page") or ev.get("sheet") or "위치 확인 불가"
                    st.caption(f"근거 위치: {loc}")
    return cached


def main() -> None:
    render_header()
    render_sidebar()
    render_case_banner()

    if st.session_state.viewing_history and st.session_state.nav_page == "legacy_history":
        render_history_view()
        return

    page = st.session_state.nav_page
    if page == "create_case":
        render_create_case()
        return
    if page == "settings":
        render_settings()
        return
    if page == "inbox":
        render_inbox()
        return
    if page == "case_detail":
        render_case_detail()
        return

    # workspace: existing 3 tabs + checker + audit
    tab_review, tab_docs, tab_ws, tab_checker, tab_audit = st.tabs(
        ["기업 검토", "기업자료 검토", "Agent Workspace", "Checker 검토", "분석·감사 이력"]
    )
    with tab_docs:
        st.session_state.cached_uploads = render_document_review()
    with tab_review:
        render_review_home()
    with tab_ws:
        render_credit_workspace()
    with tab_checker:
        render_checker_tab()
    with tab_audit:
        render_audit_repro_tab()


if __name__ == "__main__":
    main()