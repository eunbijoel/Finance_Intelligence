"""Finance Intelligence tests."""

from __future__ import annotations

import pandas as pd
import pytest

from agent_workflow import step_verify_evidence, WorkflowState
from financial_analysis import calculate_ratios, compare_analyses, detect_risk_signals
from database import init_db, save_analysis, get_latest_analysis


@pytest.fixture
def sample_financials() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "year": 2022,
                "revenue": 1000,
                "operating_income": 100,
                "net_income": 80,
                "total_assets": 2000,
                "total_liabilities": 800,
                "total_equity": 1200,
                "operating_cash_flow": 120,
                "current_assets": 500,
                "current_liabilities": 300,
                "short_term_borrowings": 100,
                "accounts_receivable": 150,
            },
            {
                "year": 2023,
                "revenue": 1100,
                "operating_income": 90,
                "net_income": 70,
                "total_assets": 2100,
                "total_liabilities": 900,
                "total_equity": 1200,
                "operating_cash_flow": -50,
                "current_assets": 480,
                "current_liabilities": 320,
                "short_term_borrowings": 110,
                "accounts_receivable": 200,
            },
            {
                "year": 2024,
                "revenue": 1200,
                "operating_income": 85,
                "net_income": 60,
                "total_assets": 2200,
                "total_liabilities": 1100,
                "total_equity": 1100,
                "operating_cash_flow": -30,
                "current_assets": 450,
                "current_liabilities": 400,
                "short_term_borrowings": 180,
                "accounts_receivable": 280,
            },
        ]
    )


def test_ratio_calculation(sample_financials):
    ratios = calculate_ratios(sample_financials)
    latest = ratios["latest"]
    assert latest["debt_ratio"]["value"] == pytest.approx(100.0, rel=0.1)
    assert latest["current_ratio"]["value"] == pytest.approx(112.5, rel=0.1)
    assert latest["operating_margin"]["value"] == pytest.approx(7.08, rel=0.1)


def test_missing_values_handled():
    df = pd.DataFrame([{"year": 2024, "revenue": 1000}])
    ratios = calculate_ratios(df)
    assert ratios["latest"]["debt_ratio"]["value"] is None
    assert "없음" in ratios["latest"]["debt_ratio"]["reason"]


def test_cf_negative_2y_rule(sample_financials):
    ratios = calculate_ratios(sample_financials)
    signals = detect_risk_signals(sample_financials, ratios)
    ids = {s["rule_id"] for s in signals}
    assert "CF_NEGATIVE_2Y" in ids


def test_plan_revenue_mismatch(sample_financials):
    ratios = calculate_ratios(sample_financials)
    doc = {
        "revenue_outlook": {"content": "2024년 매출 5,000억원 전망"},
        "fund_purpose": {"content": "설비투자"},
        "repayment_plan": {"content": "영업현금흐름 상환"},
    }
    signals = detect_risk_signals(sample_financials, ratios, doc)
    ids = {s["rule_id"] for s in signals}
    assert "PLAN_FINANCIAL_MISMATCH" in ids or "PLAN_REVENUE_OPTIMISTIC" in ids


def test_needs_more_information_when_no_evidence():
    state = WorkflowState()
    state = step_verify_evidence(state)
    assert state.workflow_status == "NEEDS_MORE_INFORMATION"
    assert state.missing_items


def test_compare_analyses():
    init_db()
    prev = {
        "risk_signals": [{"rule_id": "CF_NEGATIVE_2Y"}],
        "ratios": {"latest": {"debt_ratio": {"value": 80}}},
        "review_memo": {"summary": "이전 메모"},
    }
    curr = {
        "risk_signals": [{"rule_id": "DEBT_RATIO_SURGE"}],
        "ratios": {"latest": {"debt_ratio": {"value": 100}}},
        "review_memo": {"summary": "새 메모"},
        "new_disclosures": [{"report_nm": "사업보고서"}],
    }
    diff = compare_analyses(prev, curr)
    assert "CF_NEGATIVE_2Y" in diff["resolved_risk_signals"]
    assert "DEBT_RATIO_SURGE" in diff["new_risk_signals"]
    assert diff["worsened_ratios"]


def test_save_and_reload_analysis(tmp_path, monkeypatch):
    import config
    import database

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    init_db()
    aid = save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트기업",
            "ratios": {"latest": {}},
            "risk_signals": [],
            "review_memo": {"summary": "v1"},
            "evidence": [],
            "approved": True,
        }
    )
    latest = get_latest_analysis("00126380")
    assert latest is not None
    assert latest["analysis_id"] == aid
