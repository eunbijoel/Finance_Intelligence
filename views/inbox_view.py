"""내 검토 업무 inbox view."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from case_management import enrich_case_row, inbox_summary, list_cases, list_comments
from database import list_analyses, list_users
from document_registry import list_documents
from review_ux import (
    STEP_LABELS,
    determine_review_step,
    next_action_label,
    status_label,
)
from versioning import CASE_STATUSES, PRIORITIES, ROLE_CHECKER, ROLE_MAKER


def _open_case(case: dict[str, Any], load_company: Callable | None = None) -> None:
    st.session_state.selected_case_id = case["case_id"]
    st.session_state.nav_page = "review_flow"
    st.session_state.review_step_override = None
    if load_company:
        q = case.get("stock_code") or case.get("company_name")
        if q:
            load_company(q)


def render_inbox(*, current_user: dict[str, Any], load_company: Callable | None = None) -> None:
    st.markdown("## 내 검토 업무")
    st.caption("지금 확인해야 할 기업 검토를 먼저 보여 줍니다.")

    all_active = [
        c
        for c in list_cases(limit=500)
        if c.get("status") not in {"APPROVED", "CLOSED"}
    ]
    uid = current_user.get("user_id")
    role = current_user.get("role")

    # Prefer assigned cases
    mine = []
    others = []
    for c in all_active:
        if role == ROLE_MAKER and c.get("maker_id") == uid:
            mine.append(c)
        elif role == ROLE_CHECKER and c.get("checker_id") == uid:
            mine.append(c)
        elif role == "ADMIN":
            mine.append(c)
        else:
            others.append(c)
    ordered = mine + others if role != "ADMIN" else all_active

    need_action = 0
    need_docs = 0
    waiting_checker = 0
    for c in ordered:
        docs = list_documents(c["case_id"])
        analyses = list_analyses(case_id=c["case_id"], limit=1)
        comments = list_comments(c["case_id"])
        action = next_action_label(c, docs, analyses, comments)
        if c.get("status") == "CHECKER_REVIEW":
            waiting_checker += 1
        if c.get("status") == "DOCUMENT_REQUESTED" or action in {"기업자료 등록", "자료 보완 확인"}:
            need_docs += 1
        if role == ROLE_CHECKER:
            if c.get("checker_id") == uid and c.get("status") == "CHECKER_REVIEW":
                need_action += 1
        elif role == ROLE_MAKER:
            if c.get("maker_id") == uid and c.get("status") not in {"CHECKER_REVIEW", "APPROVED", "CLOSED"}:
                need_action += 1
        else:
            need_action += 1

    c1, c2, c3 = st.columns(3)
    c1.metric("확인해야 할 검토", need_action)
    c2.metric("자료가 부족한 검토", need_docs)
    c3.metric("승인 담당자 확인 대기", waiting_checker)

    with st.expander("상세 현황 보기"):
        summary = inbox_summary()
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("전체 진행 건", summary["active"])
        d2.metric("자료 보완 필요", summary["document_requested"])
        d3.metric("승인 담당자 대기", summary["checker_review"])
        d4.metric("기한 경과", summary["overdue"])
        d5.metric("중요 위험 보유", summary["high_risk"])

    with st.expander("검색·필터"):
        f1, f2, f3, f4 = st.columns(4)
        search = f1.text_input("기업명 / 검토번호")
        status = f2.selectbox("상태", ["(전체)"] + list(CASE_STATUSES))
        priority = f3.selectbox("우선순위", ["(전체)"] + list(PRIORITIES))
        overdue_only = f4.checkbox("기한 경과만")
        makers = ["(전체)"] + [u["user_id"] for u in list_users() if u["role"] == ROLE_MAKER]
        checkers = ["(전체)"] + [u["user_id"] for u in list_users() if u["role"] == ROLE_CHECKER]
        m1, m2 = st.columns(2)
        maker_f = m1.selectbox("검토 담당자", makers)
        checker_f = m2.selectbox("승인 담당자", checkers)

    filtered = list_cases(
        search=search or None,
        status=None if not status or status == "(전체)" else status,
        priority=None if not priority or priority == "(전체)" else priority,
        maker_id=None if maker_f == "(전체)" else maker_f,
        checker_id=None if checker_f == "(전체)" else checker_f,
        overdue_only=overdue_only,
    )
    filtered = [c for c in filtered if c.get("status") not in {"APPROVED", "CLOSED"}]

    # Sort: mine first
    def _sort_key(c: dict[str, Any]) -> tuple:
        assigned = 0
        if role == ROLE_MAKER and c.get("maker_id") == uid:
            assigned = 0
        elif role == ROLE_CHECKER and c.get("checker_id") == uid:
            assigned = 0
        else:
            assigned = 1
        return (assigned, c.get("due_date") or "9999")

    filtered = sorted(filtered, key=_sort_key)

    if not filtered:
        st.info("진행 중인 기업 검토가 없습니다. 「새 기업 검토」로 시작하세요.")
        return

    rows = []
    meta: list[dict[str, Any]] = []
    for c in filtered:
        c = enrich_case_row(c)
        docs = list_documents(c["case_id"])
        analyses = list_analyses(case_id=c["case_id"], limit=1)
        comments = list_comments(c["case_id"])
        step = determine_review_step(c, docs, analyses, comments)
        action = next_action_label(c, docs, analyses, comments)
        rows.append(
            {
                "기업": c["company_name"],
                "지금 할 일": action,
                "기한": c.get("due_date") or "—",
                "진행 단계": f"{step}. {STEP_LABELS[step]}",
            }
        )
        meta.append(c)

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("#### 검토 열기")
    for c in meta[:40]:
        docs = list_documents(c["case_id"])
        analyses = list_analyses(case_id=c["case_id"], limit=1)
        comments = list_comments(c["case_id"])
        action = next_action_label(c, docs, analyses, comments)
        label = f"{c['company_name']} · {action} · {status_label(c.get('status'))}"
        if st.button(label, key=f"open_{c['case_id']}", use_container_width=True):
            _open_case(c, load_company)
            st.rerun()
