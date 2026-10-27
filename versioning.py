"""Version constants for prompts, rules, and workflow reproducibility."""

from __future__ import annotations

PROMPT_VERSION: str = "credit-review-prompt-v1"
RULE_VERSION: str = "financial-risk-rules-v1"
WORKFLOW_VERSION: str = "case-workflow-v1"
SYSTEM_PROMPT_TEMPLATE: str = (
    "You are a financial credit review assistant for Korean corporate analysis. "
    "Never invent numbers or facts. Use only the evidence provided in the prompt. "
    "Respond in Korean unless asked otherwise."
)

# Prototype roles — not real SSO/LDAP authentication
ROLE_MAKER: str = "MAKER"
ROLE_CHECKER: str = "CHECKER"
ROLE_ADMIN: str = "ADMIN"

CASE_STATUSES: tuple[str, ...] = (
    "RECEIVED",
    "DOCUMENT_REQUESTED",
    "IN_REVIEW",
    "CHECKER_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "CLOSED",
)

CASE_STATUS_LABELS: dict[str, str] = {
    "RECEIVED": "접수",
    "DOCUMENT_REQUESTED": "자료 보완 요청",
    "IN_REVIEW": "Maker 검토 중",
    "CHECKER_REVIEW": "Checker 검토 대기",
    "CHANGES_REQUESTED": "수정 요청",
    "APPROVED": "검토 승인",
    "CLOSED": "종결",
}

PRIORITIES: tuple[str, ...] = ("LOW", "NORMAL", "HIGH", "URGENT")

# Allowed status transitions: from -> set of to
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "RECEIVED": {"IN_REVIEW", "DOCUMENT_REQUESTED", "CLOSED"},
    "DOCUMENT_REQUESTED": {"IN_REVIEW", "CLOSED"},
    "IN_REVIEW": {"DOCUMENT_REQUESTED", "CHECKER_REVIEW", "CLOSED"},
    "CHECKER_REVIEW": {"CHANGES_REQUESTED", "APPROVED"},
    "CHANGES_REQUESTED": {"IN_REVIEW", "CHECKER_REVIEW"},
    "APPROVED": {"CLOSED"},
    "CLOSED": set(),
}
