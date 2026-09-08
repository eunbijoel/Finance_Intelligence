"""완료된 검토 view."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st

from audit_service import list_audit_logs
from case_management import enrich_case_row, list_cases, list_comments
from database import get_user, list_analyses
from document_registry import list_documents
from reproduction import assess_reproducibility
from review_ux import status_label
from versioning import ROLE_CHECKER, ROLE_MAKER


def render_completed(*, current_user: dict[str, Any], load_company: Callable | None = None) -> None:
    st.markdown("## 완료된 검토")
    st.caption("검토 완료·종결된 건입니다. 결과는 직접 수정하지 않고, 필요하면 새 분석 버전을 만드세요.")

    cases = [
        enrich_case_row(c)
        for c in list_cases(limit=300)
        if c.get("status") in {"APPROVED", "CLOSED"}
    ]
    if not cases:
        st.info("완료된 검토가 없습니다.")
        return

    rows = []
    for c in cases:
        maker = get_user(c.get("maker_id") or "") or {}
        checker = get_user(c.get("checker_id") or "") or {}
        done_at = c.get("closed_at") or c.get("updated_at") or "—"
        rows.append(
            {
                "기업": c["company_name"],
                "검토 완료일": str(done_at)[:16],
                "검토 담당자": maker.get("display_name") or c.get("maker_id") or "—",
                "승인 담당자": checker.get("display_name") or c.get("checker_id") or "—",
                "최종 검토 상태": status_label(c.get("status")),
                "case_id": c["case_id"],
            }
        )
    st.dataframe(pd.DataFrame(rows).drop(columns=["case_id"]), use_container_width=True, hide_index=True)

    for c in cases[:40]:
        if st.button(f"상세 보기 · {c['company_name']}", key=f"done_{c['case_id']}"):
            st.session_state.selected_case_id = c["case_id"]
            st.session_state.nav_page = "completed_detail"
            st.rerun()


def render_completed_detail(*, current_user: dict[str, Any]) -> None:
    from case_management import get_case

    cid = st.session_state.get("selected_case_id")
    case = enrich_case_row(get_case(cid)) if cid and get_case(cid) else None
    if not case:
        st.warning("선택된 검토가 없습니다.")
        return

    st.markdown(f"## {case['company_name']} · 완료된 검토")
    st.caption("「검토 완료」는 대출 승인·거절이 아닙니다. 자료와 검토 메모 확인이 끝났다는 뜻입니다.")

    analyses = list_analyses(case_id=case["case_id"], limit=10)
    comments = list_comments(case["case_id"])
    latest = analyses[0] if analyses else {}

    st.markdown("#### 최종 검토 메모")
    st.write(
        (latest.get("review_memo") or {}).get("summary")
        or latest.get("ai_memo_original")
        or "—"
    )

    st.markdown("#### 주요 위험 및 확인 결과")
    for sig in (latest.get("risk_signals") or [])[:8]:
        st.write(f"- [{sig.get('severity', '—')}] {sig.get('title') or sig.get('description')}")

    st.markdown("#### 담당자 의견")
    maker_notes = [
        c for c in comments if c.get("comment_type") in {"MAKER_OPINION", "MAKER_REVISION"}
    ]
    if maker_notes:
        for c in maker_notes[:5]:
            st.write(f"- {c.get('comment')}")
    else:
        st.write(latest.get("maker_memo_revised") or latest.get("user_edits") or "—")

    st.markdown("#### 승인 담당자 의견")
    checker_notes = [
        c for c in comments if c.get("comment_type") in {"CHECKER_APPROVAL", "CHECKER_CHANGES_REQUESTED"}
    ]
    if checker_notes:
        for c in checker_notes[:5]:
            st.write(f"- [{c.get('comment_type')}] {c.get('comment')}")
    else:
        st.caption("의견 없음")

    with st.expander("변경 이력"):
        logs = list_audit_logs(case_id=case["case_id"], limit=40)
        if not logs:
            st.caption("이력 없음")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "시각": lg["created_at"][:19],
                            "행위자": lg.get("actor_id"),
                            "내용": lg["action"],
                            "사유": (lg.get("reason") or "")[:60],
                        }
                        for lg in logs
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("이전 분석과 비교"):
        if not analyses:
            st.caption("분석 없음")
        else:
            for a in analyses[:5]:
                st.write(
                    f"v{a.get('analysis_version')} · {str(a.get('created_at') or '')[:16]}"
                )
                if st.button("이 분석과 현재 조건 비교", key=f"repro_done_{a['analysis_id']}"):
                    result = assess_reproducibility(a["analysis_id"], case["case_id"])
                    st.info(f"상태: {result['status']}")
                    for r in result.get("reasons") or []:
                        st.caption(f"· {r}")
                    st.caption(result.get("note") or "")

    with st.expander("관리·기술 정보"):
        st.write(f"검토번호: {case.get('case_number')}")
        st.write(f"상태코드: {case.get('status')}")
        if latest:
            st.write(f"분석 버전: {latest.get('analysis_version')}")
            st.write(f"모델: {latest.get('model_provider')}/{latest.get('model_name')}")

    if st.button("목록으로"):
        st.session_state.nav_page = "completed"
        st.rerun()
