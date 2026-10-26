"""Case management: create, list, status transitions, Maker–Checker helpers."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from audit_service import write_audit
from database import get_connection, get_latest_analysis_for_case, get_user, list_analyses
from versioning import ALLOWED_TRANSITIONS, CASE_STATUSES, PRIORITIES, ROLE_CHECKER, ROLE_MAKER


class CaseError(Exception):
    """Domain validation / permission error."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_number_for_today(conn) -> str:
    today = date.today().strftime("%Y%m%d")
    prefix = f"CR-{today}-"
    row = conn.execute(
        "SELECT case_number FROM review_cases WHERE case_number LIKE ? ORDER BY case_number DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    if not row:
        seq = 1
    else:
        try:
            seq = int(str(row["case_number"]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"


def create_case(payload: dict[str, Any], created_by: str) -> dict[str, Any]:
    company_name = (payload.get("company_name") or "").strip()
    if not company_name:
        raise CaseError("기업명은 필수입니다.")
    maker_id = payload.get("maker_id")
    checker_id = payload.get("checker_id")
    if not maker_id:
        raise CaseError("Maker는 필수입니다.")
    if not checker_id:
        raise CaseError("Checker는 필수입니다.")
    if maker_id == checker_id:
        raise CaseError("동일 사용자를 Maker와 Checker로 지정할 수 없습니다.")
    if get_user(maker_id) is None or get_user(checker_id) is None:
        raise CaseError("존재하지 않는 사용자입니다.")

    amount = payload.get("application_amount")
    try:
        amount_f = float(amount) if amount is not None and amount != "" else None
    except (TypeError, ValueError) as exc:
        raise CaseError("신청금액은 숫자여야 합니다.") from exc
    if amount_f is not None and amount_f < 0:
        raise CaseError("신청금액은 0 이상이어야 합니다.")

    app_date = payload.get("application_date") or date.today().isoformat()
    due_date = payload.get("due_date") or ""
    if due_date and app_date and due_date < app_date:
        raise CaseError("처리기한은 접수일 이후여야 합니다.")

    priority = payload.get("priority") or "NORMAL"
    if priority not in PRIORITIES:
        raise CaseError(f"우선순위는 {PRIORITIES} 중 하나여야 합니다.")

    case_id = str(uuid.uuid4())
    now = _now_iso()
    with get_connection() as conn:
        case_number = _case_number_for_today(conn)
        # Ensure uniqueness under race: retry once
        for _ in range(3):
            exists = conn.execute(
                "SELECT 1 FROM review_cases WHERE case_number = ?", (case_number,)
            ).fetchone()
            if not exists:
                break
            case_number = _case_number_for_today(conn)
        conn.execute(
            """
            INSERT INTO review_cases (
                case_id, case_number, company_id, company_name, stock_code,
                application_amount, fund_purpose, loan_product,
                application_date, due_date, priority, status,
                maker_id, checker_id, created_by, created_at, updated_at,
                current_analysis_id, version, closed_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, NULL, ?)
            """,
            (
                case_id,
                case_number,
                payload.get("company_id") or None,
                company_name,
                payload.get("stock_code") or None,
                amount_f,
                payload.get("fund_purpose") or "",
                payload.get("loan_product") or "",
                app_date,
                due_date or None,
                priority,
                "RECEIVED",
                maker_id,
                checker_id,
                created_by,
                now,
                now,
                payload.get("notes") or "",
            ),
        )
    case = get_case(case_id)
    write_audit(
        action="CASE_CREATED",
        actor_id=created_by,
        actor_role=get_user(created_by)["role"] if get_user(created_by) else None,
        case_id=case_id,
        entity_type="review_case",
        entity_id=case_id,
        after={"case_number": case_number, "status": "RECEIVED", "company_name": company_name},
    )
    return case or {}


def get_case(case_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM review_cases WHERE case_id = ?", (case_id,)
        ).fetchone()
    return dict(row) if row else None


def list_cases(
    *,
    search: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    maker_id: str | None = None,
    checker_id: str | None = None,
    overdue_only: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM review_cases WHERE 1=1"
    params: list[Any] = []
    if search:
        q += " AND (company_name LIKE ? OR case_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if status:
        q += " AND status = ?"
        params.append(status)
    if priority:
        q += " AND priority = ?"
        params.append(priority)
    if maker_id:
        q += " AND maker_id = ?"
        params.append(maker_id)
    if checker_id:
        q += " AND checker_id = ?"
        params.append(checker_id)
    if overdue_only:
        today = date.today().isoformat()
        q += " AND due_date IS NOT NULL AND due_date < ? AND status NOT IN ('APPROVED','CLOSED')"
        params.append(today)
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    return [enrich_case_row(dict(r)) for r in rows]


def enrich_case_row(case: dict[str, Any]) -> dict[str, Any]:
    """Add D-Day, risk count, doc coverage, last analysis time."""
    case = dict(case)
    due = case.get("due_date")
    if due and case.get("status") not in {"APPROVED", "CLOSED"}:
        try:
            dday = (date.fromisoformat(due) - date.today()).days
            case["d_day"] = dday
            case["overdue"] = dday < 0
        except ValueError:
            case["d_day"] = None
            case["overdue"] = False
    else:
        case["d_day"] = None
        case["overdue"] = False

    analysis = None
    if case.get("current_analysis_id"):
        from database import get_analysis

        analysis = get_analysis(case["current_analysis_id"])
    if analysis is None and case.get("case_id"):
        analysis = get_latest_analysis_for_case(case["case_id"])
    if analysis:
        case["last_analysis_at"] = analysis.get("created_at")
        risks = analysis.get("risk_signals") or []
        case["high_risk_count"] = sum(1 for r in risks if r.get("severity") == "high")
        memo = analysis.get("review_memo") or {}
        case["evidence_coverage"] = memo.get("overall_status") or "—"
    else:
        case["last_analysis_at"] = None
        case["high_risk_count"] = 0
        case["evidence_coverage"] = "검토 전"
    return case


def inbox_summary(cases: list[dict[str, Any]] | None = None) -> dict[str, int]:
    cases = cases if cases is not None else list_cases(limit=500)
    return {
        "active": sum(1 for c in cases if c.get("status") not in {"CLOSED"}),
        "document_requested": sum(1 for c in cases if c.get("status") == "DOCUMENT_REQUESTED"),
        "checker_review": sum(1 for c in cases if c.get("status") == "CHECKER_REVIEW"),
        "overdue": sum(1 for c in cases if c.get("overdue")),
        "high_risk": sum(1 for c in cases if (c.get("high_risk_count") or 0) > 0),
    }


def transition_status(
    case_id: str,
    new_status: str,
    *,
    actor_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    if new_status not in CASE_STATUSES:
        raise CaseError(f"알 수 없는 상태: {new_status}")
    case = get_case(case_id)
    if not case:
        raise CaseError("심사 건을 찾을 수 없습니다.")
    old = case["status"]
    allowed = ALLOWED_TRANSITIONS.get(old, set())
    if new_status not in allowed:
        raise CaseError(f"상태 전환 불가: {old} → {new_status}")

    actor = get_user(actor_id)
    role = (actor or {}).get("role")
    _assert_transition_permission(case, old, new_status, actor_id, role)

    now = _now_iso()
    closed_at = now if new_status == "CLOSED" else None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE review_cases
            SET status = ?, updated_at = ?, version = version + 1,
                closed_at = COALESCE(?, closed_at)
            WHERE case_id = ?
            """,
            (new_status, now, closed_at, case_id),
        )
    write_audit(
        action="STATUS_CHANGED",
        actor_id=actor_id,
        actor_role=role,
        case_id=case_id,
        entity_type="review_case",
        entity_id=case_id,
        before={"status": old},
        after={"status": new_status},
        reason=reason,
    )
    return get_case(case_id) or {}


def _assert_transition_permission(
    case: dict[str, Any],
    old: str,
    new: str,
    actor_id: str,
    role: str | None,
) -> None:
    if role == "ADMIN":
        return
    # Checker approval / change request
    if new in {"APPROVED", "CHANGES_REQUESTED"}:
        if role != ROLE_CHECKER:
            raise CaseError("검토 승인·수정 요청은 Checker만 수행할 수 있습니다.")
        if case.get("checker_id") != actor_id:
            raise CaseError("본인에게 배정된 Checker 건만 처리할 수 있습니다.")
        if new == "APPROVED" and case.get("maker_id") == actor_id:
            raise CaseError("Maker와 Checker가 동일하면 승인할 수 없습니다.")
    # Maker actions
    if new in {"IN_REVIEW", "DOCUMENT_REQUESTED", "CHECKER_REVIEW"}:
        if role == ROLE_CHECKER and new == "CHECKER_REVIEW":
            raise CaseError("Checker 검토 요청은 Maker가 수행합니다.")
        if role == ROLE_MAKER and case.get("maker_id") != actor_id and role != "ADMIN":
            raise CaseError("본인에게 배정된 Maker 건만 처리할 수 있습니다.")


def set_current_analysis(case_id: str, analysis_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE review_cases
            SET current_analysis_id = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (analysis_id, _now_iso(), case_id),
        )


def can_request_checker(case_id: str) -> tuple[bool, list[str]]:
    """Pre-flight checks before Maker sends to Checker."""
    issues: list[str] = []
    case = get_case(case_id)
    if not case:
        return False, ["심사 건 없음"]
    if not case.get("checker_id"):
        issues.append("Checker가 지정되지 않았습니다.")
    analyses = list_analyses(case_id=case_id, limit=1)
    if not analyses:
        issues.append("분석이 최소 1회 실행되어야 합니다.")
    with get_connection() as conn:
        docs = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE case_id = ?", (case_id,)
        ).fetchone()
        if int(docs["c"] or 0) == 0:
            issues.append("제출 문서가 없습니다. 필수 문서 누락 여부를 확인하세요.")
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM review_comments
            WHERE case_id = ? AND comment_type IN ('MAKER_OPINION','MAKER_REVISION')
            """,
            (case_id,),
        ).fetchone()
    if int(row["c"] or 0) == 0:
        issues.append("Maker 검토 의견이 필요합니다.")
    return len(issues) == 0, issues


def add_comment(
    *,
    case_id: str,
    author_id: str,
    author_role: str,
    comment_type: str,
    comment: str,
    analysis_id: str | None = None,
    original_text: str | None = None,
    revised_text: str | None = None,
) -> str:
    if not (comment or "").strip() and comment_type in {
        "CHECKER_CHANGES_REQUESTED",
        "MAKER_OPINION",
    }:
        raise CaseError("의견 내용은 필수입니다.")
    comment_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO review_comments (
                comment_id, case_id, analysis_id, author_id, author_role,
                comment_type, original_text, revised_text, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comment_id,
                case_id,
                analysis_id,
                author_id,
                author_role,
                comment_type,
                original_text,
                revised_text,
                comment,
                _now_iso(),
            ),
        )
    write_audit(
        action="COMMENT_ADDED",
        actor_id=author_id,
        actor_role=author_role,
        case_id=case_id,
        analysis_id=analysis_id,
        entity_type="review_comment",
        entity_id=comment_id,
        after={"comment_type": comment_type},
        reason=(comment or "")[:200],
    )
    return comment_id


def list_comments(case_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM review_comments WHERE case_id = ? ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    return [dict(r) for r in rows]
