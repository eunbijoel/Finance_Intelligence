"""Finance Intelligence — simplified review UX shell."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from config import USE_DART_MOCK
from dart_client import DartClient
from database import get_user, init_db, list_analyses, list_users
from review_ux import role_label
from versioning import PROMPT_VERSION, RULE_VERSION, WORKFLOW_VERSION
from views.completed_view import render_completed, render_completed_detail
from views.create_review_view import render_create_review
from views.inbox_view import render_inbox
from views.review_flow_view import render_review_flow

st.set_page_config(
    page_title="Finance Intelligence",
    page_icon="FI",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    [data-theme="dark"] .fi-card { background: #1a2332; border: 1px solid #2dd4bf33; border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; }
    [data-theme="light"] .fi-card { background: #f8fafc; border: 1px solid #0d948833; border-radius: 10px; padding: 16px 18px; margin-bottom: 14px; color: #0f172a; }
    .fi-title { color: #0d9488; font-weight: 700; font-size: 1.15rem; margin-bottom: 0.25rem; }
    [data-theme="dark"] .fi-subtitle { color: #94a3b8; font-size: 0.85rem; }
    [data-theme="light"] .fi-subtitle { color: #64748b; font-size: 0.85rem; }
    .fi-high { color: #f87171; }
    .fi-medium { color: #fb923c; }
    .fi-muted-status { color: #94a3b8; }
    [data-theme="dark"] .fi-badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; background: #1e3a5f; color: #93c5fd; border: 1px solid #3b82f655; }
    [data-theme="light"] .fi-badge { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem; background: #dbeafe; color: #1d4ed8; }
    .fi-section-title { font-weight: 600; margin-bottom: 10px; }
    .fi-prog { display: inline-block; padding: 8px 12px; margin: 4px 2px; border-radius: 6px; font-size: 0.85rem; }
    .fi-prog-done { color: #34d399; border-bottom: 3px solid #34d399; }
    .fi-prog-current { color: #e2e8f0; border-bottom: 3px solid #60a5fa; font-weight: 600; }
    .fi-prog-pending { color: #64748b; }
    .fi-prog-warn { color: #fbbf24; border-bottom: 3px solid #fbbf24; }
    .fi-prog-sep { color: #334155; margin: 0 4px; }
    [data-theme="light"] .fi-prog-current { color: #0f172a; }
    [data-theme="light"] .fi-prog-sep { color: #cbd5e1; }
    section[data-testid="stSidebar"] .stButton button { text-align: left; }
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
    ("current_user_id", "maker01"),
    ("selected_case_id", None),
    ("nav_page", "inbox"),
    ("review_step_override", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def _current_user() -> dict[str, Any]:
    uid = st.session_state.current_user_id
    return get_user(uid) or {"user_id": uid, "display_name": uid, "role": "MAKER"}


def _load_company_query(query: str) -> None:
    client = DartClient()
    company = client.search_company(query)
    if not company:
        return
    st.session_state.company_query = company.get("stock_code") or company.get("corp_name") or query
    st.session_state.company = company
    st.session_state.financials = client.get_financials(company["corp_code"])
    st.session_state.disclosures = client.get_recent_disclosures(company["corp_code"])
    st.session_state.viewing_history = False


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown('<div class="fi-title">Finance Intelligence</div>', unsafe_allow_html=True)
        if USE_DART_MOCK:
            st.caption("샘플 데이터 모드")

        page = st.session_state.nav_page
        if st.button("내 검토 업무", use_container_width=True, type="primary" if page == "inbox" else "secondary"):
            st.session_state.nav_page = "inbox"
            st.session_state.review_step_override = None
            st.rerun()
        if st.button("새 기업 검토", use_container_width=True, type="primary" if page == "create" else "secondary"):
            st.session_state.nav_page = "create"
            st.rerun()
        if st.button("완료된 검토", use_container_width=True, type="primary" if page in {"completed", "completed_detail"} else "secondary"):
            st.session_state.nav_page = "completed"
            st.rerun()

        user = _current_user()
        st.markdown("---")
        st.caption(f"{user.get('display_name')} · {role_label(user.get('role'))}")

        with st.expander("관리 정보", expanded=False):
            st.caption("프로토타입용입니다. 실제 SSO/LDAP 로그인이 아닙니다.")
            users = list_users()
            options = {f"{u['display_name']} ({role_label(u['role'])})": u["user_id"] for u in users}
            labels = list(options.keys())
            current = st.session_state.current_user_id
            idx = 0
            for i, uid in enumerate(options.values()):
                if uid == current:
                    idx = i
                    break
            chosen = st.selectbox("현재 사용자", labels, index=idx)
            st.session_state.current_user_id = options[chosen]

            st.markdown("**버전**")
            st.caption(f"Prompt: {PROMPT_VERSION}")
            st.caption(f"Rule: {RULE_VERSION}")
            st.caption(f"Workflow: {WORKFLOW_VERSION}")

            st.markdown("**기업 검색 (건 없이)**")
            query = st.text_input("기업명 / 종목코드", value=st.session_state.company_query, key="admin_search")
            if st.button("조회", key="admin_search_btn"):
                _load_company_query(query)
                st.success("기업 데이터를 불러왔습니다. 검토 흐름에서 활용할 수 있습니다.")
            client = DartClient()
            suggestions = client.suggest_companies(query, limit=5) if (query or "").strip() else []
            for sug in suggestions:
                code = (sug.get("stock_code") or "").strip() or "—"
                label = f"{sug.get('corp_name', '—')} · {code}"
                if st.button(label, key=f"sug_{sug.get('corp_code')}_{code}"):
                    _load_company_query(code if code != "—" else sug.get("corp_name", ""))
                    st.rerun()

            st.markdown("**분석 이력 (레거시)**")
            for a in list_analyses(limit=5):
                if st.button(
                    f"{a['company_name'][:12]} · {a['analysis_date']}",
                    key=f"leg_{a['analysis_id']}",
                ):
                    st.session_state.selected_analysis = a
                    st.session_state.nav_page = "legacy_history"
                    st.rerun()


def render_legacy_history() -> None:
    a = st.session_state.selected_analysis
    if not a:
        st.info("이력이 없습니다.")
        return
    st.markdown("## 저장된 분석 (레거시)")
    memo = a.get("review_memo") or {}
    st.write(a.get("company_name"), a.get("analysis_date"), memo.get("overall_status"))
    st.write(memo.get("summary") or "—")
    if st.button("내 검토 업무로"):
        st.session_state.nav_page = "inbox"
        st.rerun()


def main() -> None:
    render_sidebar()
    user = _current_user()
    page = st.session_state.nav_page

    if page == "create":
        render_create_review(current_user=user, load_company=_load_company_query)
    elif page == "completed":
        render_completed(current_user=user, load_company=_load_company_query)
    elif page == "completed_detail":
        render_completed_detail(current_user=user)
    elif page == "review_flow":
        render_review_flow(current_user=user)
    elif page == "legacy_history":
        render_legacy_history()
    else:
        render_inbox(current_user=user, load_company=_load_company_query)


if __name__ == "__main__":
    main()
