"""Finance Intelligence — Streamlit MVP."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from agent_workflow import run_workflow, step_save_approved
from config import REVIEW_STATUSES, USE_DART_MOCK
from dart_client import DartClient
from database import init_db, list_analyses
from document_parser import extract_business_fields, parse_uploaded_file
from financial_analysis import calculate_ratios

# --- Page config & theme ---
st.set_page_config(
    page_title="Finance Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stApp { background-color: #0f1724; color: #e2e8f0; }
    [data-testid="stSidebar"] { background-color: #111827; }
    .fi-card {
        background: #1a2332; border: 1px solid #2dd4bf33;
        border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
    }
    .fi-title { color: #2dd4bf; font-weight: 700; font-size: 1.1rem; }
    .fi-muted { color: #94a3b8; font-size: 0.85rem; }
    .fi-high { color: #f87171; }
    .fi-medium { color: #fbbf24; }
    .fi-low { color: #34d399; }
    .fi-disclaimer {
        background: #1e293b; border-left: 4px solid #2dd4bf;
        padding: 10px 14px; margin: 10px 0; font-size: 0.9rem;
    }
</style>
""",
    unsafe_allow_html=True,
)

init_db()

if "company_query" not in st.session_state:
    st.session_state.company_query = "005930"
if "workflow_state" not in st.session_state:
    st.session_state.workflow_state = None
if "financials" not in st.session_state:
    st.session_state.financials = pd.DataFrame()
if "company" not in st.session_state:
    st.session_state.company = {}
if "upload_fields" not in st.session_state:
    st.session_state.upload_fields = {}
if "disclosures" not in st.session_state:
    st.session_state.disclosures = []

# Auto-load default company once
if not st.session_state.company and st.session_state.company_query:
    _client = DartClient()
    _co = _client.search_company(st.session_state.company_query)
    if _co:
        st.session_state.company = _co
        st.session_state.financials = _client.get_financials(_co["corp_code"])
        st.session_state.disclosures = _client.get_recent_disclosures(_co["corp_code"])


def _fmt_won(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    try:
        return f"{int(val):,}원"
    except (TypeError, ValueError):
        return str(val)


def render_header() -> None:
    st.markdown('<div class="fi-title">Finance Intelligence</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="fi-muted">AI 금융 리서치 워크벤치 · 심사역 검토 보조 (승인/거절 판단 아님)</div>',
        unsafe_allow_html=True,
    )
    if USE_DART_MOCK:
        st.warning(
            "DART API 키가 로드되지 않아 샘플(mock) 데이터를 사용 중입니다. "
            "`finance_intelligence/.env` 파일에 `DART_API_KEY=발급키`를 넣고 앱을 재시작하세요."
        )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 🔍 기업 검색")
        query = st.text_input("기업명 / 종목코드", value=st.session_state.company_query, key="search_box")
        if st.button("조회", use_container_width=True):
            st.session_state.company_query = query
            client = DartClient()
            company = client.search_company(query)
            if company:
                st.session_state.company = company
                st.session_state.financials = client.get_financials(company["corp_code"])
                st.session_state.disclosures = client.get_recent_disclosures(company["corp_code"])
            else:
                st.warning("기업을 찾을 수 없습니다.")

        st.markdown("---")
        st.markdown("### 📁 분석 이력")
        analyses = list_analyses(limit=20)
        if not analyses:
            st.caption("저장된 분석 없음")
        for a in analyses:
            status = (a.get("review_memo") or {}).get("overall_status", "—")
            label = f"{a['company_name'][:8]}… · {a['analysis_date']} · {status[:6]}"
            if st.button(label, key=f"hist_{a['analysis_id']}", use_container_width=True):
                st.session_state.selected_analysis = a


def render_dashboard() -> None:
    st.markdown("## 기업 대시보드")
    company = st.session_state.company
    financials = st.session_state.financials

    if not company:
        st.warning("왼쪽 사이드바에서 기업을 검색하세요. (예: 005930, 삼성전자)")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="fi-card"><b>{company.get("corp_name","—")}</b><br><span class="fi-muted">기업명</span></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="fi-card"><b>{company.get("stock_code","—")}</b><br><span class="fi-muted">종목코드</span></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="fi-card"><b>{company.get("corp_code","—")}</b><br><span class="fi-muted">DART 기업코드</span></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="fi-card"><b>{company.get("industry","—")}</b><br><span class="fi-muted">업종</span></div>', unsafe_allow_html=True)

    st.markdown("#### 최근 공시")
    disclosures = st.session_state.get("disclosures", [])
    if disclosures:
        st.dataframe(pd.DataFrame(disclosures), use_container_width=True, hide_index=True)
    else:
        st.caption("공시 없음")

    if financials.empty:
        st.warning("재무 데이터 없음")
        return

    st.markdown("#### 최근 3개년 주요 재무정보")
    display_cols = [
        "year", "revenue", "operating_income", "net_income",
        "total_assets", "total_liabilities", "total_equity", "operating_cash_flow",
    ]
    show = financials[[c for c in display_cols if c in financials.columns]].copy()
    st.dataframe(show, use_container_width=True, hide_index=True)

    ratios = calculate_ratios(financials)
    st.markdown("#### 재무비율 (Python 계산)")
    ratio_rows = []
    label_map = {
        "debt_ratio": "부채비율",
        "current_ratio": "유동비율",
        "operating_margin": "영업이익률",
        "net_margin": "순이익률",
        "roa": "ROA",
        "roe": "ROE",
        "ocf_to_short_term_debt": "영업CF/단기차입",
    }
    for year, yr_ratios in ratios.get("by_year", {}).items():
        for key, label in label_map.items():
            r = yr_ratios.get(key, {})
            if r.get("value") is not None:
                val = f"{r['value']}{r.get('unit','')}"
            else:
                val = f"계산 불가 — {r.get('reason','')}"
            ratio_rows.append({"연도": year, "비율": label, "값": val})
    st.dataframe(pd.DataFrame(ratio_rows), use_container_width=True, hide_index=True)

    st.markdown("#### 3개년 추이")
    fig = go.Figure()
    for col, name, color in [
        ("revenue", "매출액", "#2dd4bf"),
        ("operating_income", "영업이익", "#60a5fa"),
        ("operating_cash_flow", "영업CF", "#fbbf24"),
    ]:
        if col in financials.columns:
            fig.add_trace(
                go.Scatter(
                    x=financials["year"],
                    y=financials[col],
                    mode="lines+markers",
                    name=name,
                    line=dict(color=color),
                )
            )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0f1724",
        plot_bgcolor="#1a2332",
        height=360,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_document_review() -> list[tuple[str, bytes]]:
    st.markdown("## 기업자료 검토")
    uploads = st.file_uploader(
        "PDF / DOCX / XLSX / CSV / TXT",
        type=["pdf", "docx", "xlsx", "csv", "txt"],
        accept_multiple_files=True,
    )

    cached: list[tuple[str, bytes]] = []
    if not uploads:
        st.info("사업계획서 또는 관련 자료를 업로드하세요.")
        return cached

    for f in uploads:
        content = f.getvalue() if hasattr(f, "getvalue") else f.read()
        cached.append((f.name, content))
        parsed = parse_uploaded_file(f.name, content)
        fields = extract_business_fields(parsed)
        st.session_state.upload_fields = fields

        st.markdown(f"### 📄 {f.name}")
        field_labels = {
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
        for key, label in field_labels.items():
            block = fields.get(key, {})
            with st.expander(label, expanded=key in {"revenue_outlook", "fund_purpose"}):
                st.write(block.get("content", "—"))
                ev_list = block.get("evidence") or []
                if ev_list:
                    st.markdown("**근거**")
                    for ev in ev_list:
                        st.json(ev)
                else:
                    st.caption("근거 위치 정보 없음")
    return cached


def render_credit_workspace() -> None:
    st.markdown("## Credit Review Workspace")
    st.markdown(
        '<div class="fi-disclaimer">⚠️ 검토 상태(검토상 특이사항 없음 / 추가 확인 필요 / 중요 위험 신호 발견)는 '
        "대출 승인·거절, 신용등급, 한도 산정을 의미하지 않습니다. 심사역 검토 보조용 초안입니다.</div>",
        unsafe_allow_html=True,
    )

    col_l, col_r = st.columns([2, 1])
    with col_l:
        if st.button("🚀 Agent 분석 실행", type="primary", use_container_width=True):
            uploads = st.session_state.get("cached_uploads", [])
            state = run_workflow(st.session_state.company_query, uploads)
            st.session_state.workflow_state = state

    with col_r:
        ws = st.session_state.workflow_state
        if ws:
            st.metric("워크플로우 상태", ws.workflow_status)

    ws = st.session_state.workflow_state
    if not ws:
        st.info("Agent 분석 실행 버튼을 눌러 DART 데이터와 업로드 문서를 통합 검토하세요.")
        return

    if ws.workflow_status == "NEEDS_MORE_INFORMATION":
        st.error("NEEDS_MORE_INFORMATION — 근거 부족으로 결론을 생성하지 않았습니다.")
        st.write("**부족한 자료:**", ws.missing_items)
        st.write("**확인 질문:**")
        for q in ws.questions:
            st.write(f"- {q}")
        return

    st.markdown("#### Agent 단계 상태")
    step_labels = {
        "check_inputs": "1. 입력자료 확인",
        "collect_dart_data": "2. DART 수집",
        "analyze_documents": "3. 문서 분석",
        "calculate_ratios": "4. 재무비율 계산",
        "cross_validate": "5. 교차검증",
        "detect_risks": "6. 위험 신호",
        "verify_evidence": "7. 근거 검증",
        "draft_memo": "8. 메모 초안",
        "save_approved": "10. 저장",
    }
    for key, label in step_labels.items():
        status = ws.step_statuses.get(key, "PENDING")
        icon = {"COMPLETED": "✅", "RUNNING": "⏳", "FAILED": "❌", "NEEDS_MORE_INFORMATION": "⚠️"}.get(status, "⬜")
        st.write(f"{icon} {label}: **{status}**")

    memo = ws.review_memo or {}
    overall = memo.get("overall_status", "—")
    color_class = {
        "검토상 특이사항 없음": "fi-low",
        "추가 확인 필요": "fi-medium",
        "중요 위험 신호 발견": "fi-high",
    }.get(overall, "fi-muted")
    st.markdown(f'<div class="fi-card"><span class="{color_class}">● {overall}</span></div>', unsafe_allow_html=True)

    sections = memo.get("sections", {})
    section_titles = [
        ("1_company_overview", "1. 기업 및 신청 개요"),
        ("2_financial_status", "2. 주요 재무 현황"),
        ("3_ratio_analysis", "3. 재무비율 분석"),
        ("4_positive_factors", "4. 긍정 요인"),
        ("5_risk_signals", "5. 주요 위험 신호"),
        ("6_inconsistencies", "6. 불일치"),
        ("7_follow_up", "7. 추가 확인 사항"),
        ("8_additional_documents", "8. 추가 요청 자료"),
        ("9_reviewer_questions", "9. 심사역 검토 질문"),
        ("10_summary_draft", "10. 종합 검토 메모 초안"),
        ("11_evidence_index", "11. 근거 목록"),
    ]
    for key, title in section_titles:
        with st.expander(title):
            content = sections.get(key, "—")
            if isinstance(content, list):
                for item in content:
                    st.write(item)
            elif isinstance(content, str):
                st.markdown(content)
            else:
                st.json(content)

    st.markdown("#### 위험 신호")
    for sig in ws.risk_signals:
        sev = sig.get("severity", "low")
        cls = {"high": "fi-high", "medium": "fi-medium"}.get(sev, "fi-low")
        st.markdown(
            f'<div class="fi-card"><span class="{cls}">[{sev.upper()}] {sig.get("title")}</span>'
            f'<br>{sig.get("description")}<br><span class="fi-muted">Q: {sig.get("review_question")}</span></div>',
            unsafe_allow_html=True,
        )
        with st.expander("근거"):
            st.json(sig.get("evidence", []))

    if ws.comparison:
        st.markdown("#### 이전 분석 대비 변경")
        st.json(ws.comparison)

    st.markdown("---")
    user_edits = st.text_area("사용자 수정 내용", height=100)
    if st.button("✅ 승인 후 저장"):
        ws.review_memo["user_edits"] = user_edits
        aid = step_save_approved(ws, user_edits=user_edits, approved=True)
        st.success(f"저장 완료 — analysis_id: {aid}")


def main() -> None:
    render_header()
    render_sidebar()

    tab1, tab2, tab3 = st.tabs(["📊 대시보드", "📄 기업자료 검토", "🏦 Credit Review"])

    with tab2:
        st.session_state.cached_uploads = render_document_review()

    with tab1:
        render_dashboard()
    with tab3:
        render_credit_workspace()


if __name__ == "__main__":
    main()
