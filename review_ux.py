"""User-facing labels and 4-step review UX helpers (DB codes unchanged)."""

from __future__ import annotations

from typing import Any

from versioning import ROLE_ADMIN, ROLE_CHECKER, ROLE_MAKER

# UI display labels — internal status codes stay the same
STATUS_UI_LABELS = {
    "RECEIVED": "접수",
    "DOCUMENT_REQUESTED": "자료 보완",
    "IN_REVIEW": "검토 중",
    "CHECKER_REVIEW": "승인 담당자 확인 대기",
    "CHANGES_REQUESTED": "보완 요청",
    "APPROVED": "검토 완료",
    "CLOSED": "종결",
}

ROLE_UI_LABELS = {
    ROLE_MAKER: "검토 담당자",
    ROLE_CHECKER: "승인 담당자",
    ROLE_ADMIN: "관리자",
}

STEP_LABELS = {
    1: "자료 등록",
    2: "AI 검토",
    3: "담당자 확인",
    4: "검토 완료",
}

# Risk severity → user buckets
SEVERITY_BUCKET = {
    "high": "중요",
    "medium": "확인 필요",
    "low": "확인 필요",
}


def role_label(role: str | None) -> str:
    return ROLE_UI_LABELS.get(role or "", role or "—")


def status_label(status: str | None) -> str:
    return STATUS_UI_LABELS.get(status or "", status or "—")


def has_maker_opinion(comments: list[dict[str, Any]]) -> bool:
    return any(
        c.get("comment_type") in {"MAKER_OPINION", "MAKER_REVISION"}
        for c in comments
    )


def determine_review_step(
    case: dict[str, Any],
    documents: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    comments: list[dict[str, Any]] | None = None,
) -> int:
    """Map case + artifacts to UI step 1–4 (DB status codes unchanged)."""
    status = case.get("status") or "RECEIVED"
    comments = comments or []
    has_docs = bool(documents)
    has_analysis = bool(analyses)
    has_opinion = has_maker_opinion(comments)

    if status in {"CHECKER_REVIEW", "APPROVED", "CLOSED"}:
        return 4
    if status == "CHANGES_REQUESTED":
        return 3
    if status == "DOCUMENT_REQUESTED":
        return 1
    if status == "RECEIVED" and not has_docs:
        return 1
    if not has_docs:
        return 1
    if not has_analysis:
        return 2
    if status == "IN_REVIEW" and not has_opinion:
        # Prefer AI results screen first, then move to maker confirm via UI
        return 2
    if status == "IN_REVIEW" and has_opinion:
        return 3
    if has_analysis and not has_opinion:
        return 2
    if has_analysis:
        return 3
    return 1


def next_action_label(
    case: dict[str, Any],
    documents: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    comments: list[dict[str, Any]] | None = None,
) -> str:
    status = case.get("status") or "RECEIVED"
    comments = comments or []
    if status == "CLOSED":
        return "종결"
    if status == "APPROVED":
        return "검토 완료"
    if status == "CHECKER_REVIEW":
        return "승인 담당자 확인 대기"
    if status == "CHANGES_REQUESTED":
        return "보완 의견 확인"
    if status == "DOCUMENT_REQUESTED":
        return "자료 보완 확인"
    if not documents:
        return "기업자료 등록"
    if not analyses:
        return "AI 검토 시작"
    if not has_maker_opinion(comments):
        return "AI 검토 결과 확인"
    return "담당자 의견 확인"


def classify_risk_signals(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Split risk signals into 중요 / 확인 필요 / 자료 보완 buckets."""
    important: list[dict[str, Any]] = []
    needs_check: list[dict[str, Any]] = []
    missing_docs: list[dict[str, Any]] = []
    for sig in signals or []:
        rule = (sig.get("rule_id") or "").upper()
        title = (sig.get("title") or "") + " " + (sig.get("description") or "")
        bucket_hint = sig.get("user_bucket")
        if bucket_hint == "자료 보완" or "미기재" in title or "확인되지 않" in title or "MISSING" in rule or "NOT_FOUND" in rule:
            missing_docs.append(sig)
        elif sig.get("severity") == "high" or bucket_hint == "중요":
            important.append(sig)
        else:
            needs_check.append(sig)
    return {"중요": important, "확인 필요": needs_check, "자료 보완": missing_docs}


def collect_review_questions(
    signals: list[dict[str, Any]],
    memo: dict[str, Any] | None = None,
    limit: int = 5,
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sig in signals or []:
        for q in sig.get("questions") or []:
            text = str(q).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
            if len(out) >= limit:
                return out
        q1 = (sig.get("review_question") or "").strip()
        if q1 and q1 not in seen:
            seen.add(q1)
            out.append(q1)
        if len(out) >= limit:
            return out
    memo = memo or {}
    for q in memo.get("questions") or memo.get("follow_up_questions") or []:
        text = str(q).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= limit:
            break
    return out[:limit]


def format_amount_short(amount: Any) -> str:
    if amount is None or amount == "":
        return "—"
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if abs(v) >= 100_000_000:
        return f"{v / 100_000_000:,.0f}억 원"
    if abs(v) >= 10_000:
        return f"{v / 10_000:,.0f}만 원"
    return f"{v:,.0f}원"


def case_subtitle(case: dict[str, Any]) -> str:
    purpose = case.get("fund_purpose") or "—"
    amount = format_amount_short(case.get("application_amount"))
    due = case.get("due_date") or "—"
    if due and len(due) >= 10:
        due = due.replace("-", ".")[:10]
    return f"{purpose} {amount} · 검토기한 {due}"


def step_states(current_step: int, case: dict[str, Any]) -> dict[int, str]:
    """Return per-step visual state: done | current | pending | warn."""
    status = case.get("status")
    states: dict[int, str] = {}
    for s in (1, 2, 3, 4):
        if status == "DOCUMENT_REQUESTED" and s == 1:
            states[s] = "warn"
        elif status == "CHANGES_REQUESTED" and s == 3:
            states[s] = "warn"
        elif s < current_step:
            states[s] = "done"
        elif s == current_step:
            states[s] = "current"
        else:
            states[s] = "pending"
    if status in {"APPROVED", "CLOSED"}:
        for s in (1, 2, 3, 4):
            states[s] = "done"
    return states
