"""새 기업 검토 (create case) view."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import streamlit as st

from case_management import CaseError, create_case
from dart_client import DartClient
from database import list_users
from versioning import PRIORITIES, ROLE_CHECKER, ROLE_MAKER


def render_create_review(*, current_user: dict[str, Any], load_company: Callable | None = None) -> None:
    st.markdown("## 새 기업 검토")
    st.caption("기본정보만 입력해도 시작할 수 있습니다. 세부 항목은 추가정보에서 입력하세요.")

    makers = [u for u in list_users() if u["role"] == ROLE_MAKER]
    checkers = [u for u in list_users() if u["role"] == ROLE_CHECKER]

    company_name = st.text_input("기업명 *")
    application_amount = st.number_input("신청금액 *", min_value=0.0, step=1_000_000.0)
    fund_purpose = st.text_input("자금용도 *")
    loan_product = st.text_input("신청상품 *")
    due_date = st.date_input("검토기한", value=date.today())
    maker_id = st.selectbox(
        "검토 담당자 *",
        [u["user_id"] for u in makers],
        format_func=lambda x: f"{next(u['display_name'] for u in makers if u['user_id']==x)} ({x})",
    )
    checker_id = st.selectbox(
        "승인 담당자 *",
        [u["user_id"] for u in checkers],
        format_func=lambda x: f"{next(u['display_name'] for u in checkers if u['user_id']==x)} ({x})",
    )

    with st.expander("추가정보 입력"):
        stock_or_dart = st.text_input("종목코드 또는 DART 코드")
        application_date = st.date_input("접수일", value=date.today())
        priority = st.selectbox("우선순위", list(PRIORITIES), index=1)
        notes = st.text_area("비고")

    if st.button("기업 검토 시작", type="primary"):
        if not (company_name or "").strip():
            st.error("기업명은 필수입니다.")
            return
        if not (fund_purpose or "").strip() or not (loan_product or "").strip():
            st.error("자금용도·신청상품은 필수입니다.")
            return

        company_id = None
        stock_code = None
        q = (stock_or_dart or "").strip()
        if q:
            if q.isdigit() or len(q) == 6:
                stock_code = q.zfill(6) if q.isdigit() else q
            co = DartClient().search_company(company_name) or DartClient().search_company(q)
            if co:
                company_id = co.get("corp_code")
                stock_code = co.get("stock_code") or stock_code
        else:
            co = DartClient().search_company(company_name)
            if co:
                company_id = co.get("corp_code")
                stock_code = co.get("stock_code")

        try:
            case = create_case(
                {
                    "company_name": company_name.strip(),
                    "company_id": company_id,
                    "stock_code": stock_code,
                    "application_amount": application_amount,
                    "fund_purpose": fund_purpose.strip(),
                    "loan_product": loan_product.strip(),
                    "application_date": application_date.isoformat(),
                    "due_date": due_date.isoformat(),
                    "priority": priority,
                    "maker_id": maker_id,
                    "checker_id": checker_id,
                    "notes": notes or "",
                },
                created_by=current_user["user_id"],
            )
            st.session_state.selected_case_id = case["case_id"]
            st.session_state.nav_page = "review_flow"
            st.session_state.review_step_override = 1
            if load_company and (stock_code or company_name):
                load_company(stock_code or company_name)
            st.success(f"기업 검토가 시작되었습니다: {case['company_name']}")
            st.rerun()
        except CaseError as exc:
            st.error(str(exc))
