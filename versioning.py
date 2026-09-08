"""Version constants for prompts, rules, and workflow reproducibility."""

from __future__ import annotations

PROMPT_VERSION = "credit-review-prompt-v1"
RULE_VERSION = "financial-risk-rules-v1"
WORKFLOW_VERSION = "case-workflow-v1"
SYSTEM_PROMPT_TEMPLATE = (
    "You are a financial credit review assistant for Korean corporate analysis. "
    "Never invent numbers or facts. Use only the evidence provided in the prompt. "
    "Respond in Korean unless asked otherwise."
)

# Prototype roles — not real SSO/LDAP authentication
ROLE_MAKER = "MAKER"
ROLE_CHECKER = "CHECKER"
ROLE_ADMIN = "ADMIN"

CASE_STATUSES = (
    "RECEIVED",
    "DOCUMENT_REQUESTED",
    "IN_REVIEW",
    "CHECKER_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "CLOSED",
)

CASE_STATUS_LABELS = {
    "RECEIVED": "접수",
    "DOCUMENT_REQUESTED": "자료 보완 요청",
    "IN_REVIEW": "Maker 검토 중",
    "CHECKER_REVIEW": "Checker 검토 대기",
    "CHANGES_REQUESTED": "수정 요청",
    "APPROVED": "검토 승인",
    "CLOSED": "종결",
}

PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")

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
