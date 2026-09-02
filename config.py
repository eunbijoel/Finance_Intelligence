"""Configuration and risk-rule thresholds."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
_default_db = DATA_DIR / "finance_intelligence.db"
DB_PATH = Path(os.getenv("FI_DB_PATH", str(_default_db)))

# Always load from project root — Streamlit cwd may differ from app directory.
load_dotenv(BASE_DIR / ".env")

DART_API_KEY = os.getenv("DART_API_KEY", "").strip()
# Ignore placeholder values from templates
if DART_API_KEY.lower() in {"your_opendart_api_key", "changeme", "xxx"}:
    DART_API_KEY = ""
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT_SEC = int(os.getenv("LLM_TIMEOUT_SEC", "120"))
MOCK_LLM = os.getenv("FI_MOCK_LLM", "false").lower() in {"1", "true", "yes"}

USE_DART_MOCK = not DART_API_KEY

# Risk rule thresholds — edit here to tune MVP rules
RISK_THRESHOLDS = {
    "debt_ratio_surge_pp": 15.0,
    "current_ratio_decline_pct": 15.0,
    "short_term_debt_surge_pct": 30.0,
    "receivables_vs_revenue_gap_pp": 20.0,
    "plan_revenue_optimism_pp": 25.0,
    "plan_financial_mismatch_pct": 10.0,
}

WORKFLOW_STATUSES = {
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "NEEDS_REVIEW",
    "NEEDS_MORE_INFORMATION",
}

REVIEW_STATUSES = {
    "검토상 특이사항 없음",
    "추가 확인 필요",
    "중요 위험 신호 발견",
    "분석 전",
}
