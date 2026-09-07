"""Finance Intelligence tests — v1 + v2."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from agent_workflow import step_verify_evidence, WorkflowState
from dart_client import disclosure_date_range
from document_parser import merge_document_fields, extract_business_fields, parse_uploaded_file
from financial_analysis import (
    calculate_ratios,
    compare_analyses,
    detect_risk_signals,
    run_cross_validation as fa_cross_validate,
    verify_claims,
    compute_yoy_changes,
    _extract_numeric_from_text,
)
from database import init_db, save_analysis, get_latest_analysis, get_analysis
from ui_helpers import format_krw_amount, generate_markdown_report


@pytest.fixture
def sample_financials() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"year": 2022, "revenue": 1000, "operating_income": 100, "net_income": 80,
             "total_assets": 2000, "total_liabilities": 800, "total_equity": 1200,
             "operating_cash_flow": 120, "current_assets": 500, "current_liabilities": 300,
             "short_term_borrowings": 100, "accounts_receivable": 150},
            {"year": 2023, "revenue": 1100, "operating_income": 90, "net_income": 70,
             "total_assets": 2100, "total_liabilities": 900, "total_equity": 1200,
             "operating_cash_flow": -50, "current_assets": 480, "current_liabilities": 320,
             "short_term_borrowings": 110, "accounts_receivable": 200},
            {"year": 2024, "revenue": 1200, "operating_income": 85, "net_income": 60,
             "total_assets": 2200, "total_liabilities": 1100, "total_equity": 1100,
             "operating_cash_flow": -30, "current_assets": 450, "current_liabilities": 400,
             "short_term_borrowings": 180, "accounts_receivable": 280},
        ]
    )


def test_ratio_calculation(sample_financials):
    ratios = calculate_ratios(sample_financials)
    latest = ratios["latest"]
    assert latest["debt_ratio"]["value"] == pytest.approx(100.0, rel=0.1)
    assert latest["current_ratio"]["value"] == pytest.approx(112.5, rel=0.1)


def test_missing_values_handled():
    df = pd.DataFrame([{"year": 2024, "revenue": 1000}])
    ratios = calculate_ratios(df)
    assert ratios["latest"]["debt_ratio"]["value"] is None


def test_cf_negative_2y_rule(sample_financials):
    ratios = calculate_ratios(sample_financials)
    signals = detect_risk_signals(sample_financials, ratios)
    assert "CF_NEGATIVE_2Y" in {s["rule_id"] for s in signals}


def test_plan_revenue_mismatch(sample_financials):
    ratios = calculate_ratios(sample_financials)
    doc = {
        "revenue_outlook": [{"source_file": "plan.txt", "content": "2024년 매출 5,000억원 전망", "evidence": []}],
        "fund_purpose": [{"source_file": "plan.txt", "content": "설비투자", "evidence": []}],
        "repayment_plan": [{"source_file": "plan.txt", "content": "영업현금흐름 상환", "evidence": []}],
    }
    signals = detect_risk_signals(sample_financials, ratios, doc)
    ids = {s["rule_id"] for s in signals}
    assert "PLAN_FINANCIAL_MISMATCH" in ids or "PLAN_REVENUE_OPTIMISTIC" in ids


def test_needs_more_information_when_no_evidence():
    state = WorkflowState()
    state = step_verify_evidence(state)
    assert state.workflow_status == "NEEDS_MORE_INFORMATION"


def test_compare_analyses():
    prev = {"risk_signals": [{"rule_id": "CF_NEGATIVE_2Y"}], "ratios": {"latest": {"debt_ratio": {"value": 80}}}, "review_memo": {"summary": "이전"}}
    curr = {"risk_signals": [{"rule_id": "DEBT_RATIO_SURGE"}], "ratios": {"latest": {"debt_ratio": {"value": 100}}}, "review_memo": {"summary": "새"}, "new_disclosures": [{"report_nm": "사업보고서"}]}
    diff = compare_analyses(prev, curr)
    assert "CF_NEGATIVE_2Y" in diff["resolved_risk_signals"]
    assert "DEBT_RATIO_SURGE" in diff["new_risk_signals"]


def test_save_and_reload_analysis(tmp_path, monkeypatch):
    import config, database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    init_db()
    aid = save_analysis({"company_id": "00126380", "company_name": "테스트기업", "ratios": {}, "risk_signals": [], "review_memo": {"summary": "v1"}, "evidence": [], "approved": True})
    latest = get_latest_analysis("00126380")
    assert latest and latest["analysis_id"] == aid
    loaded = get_analysis(aid)
    assert loaded["company_name"] == "테스트기업"


def test_disclosure_date_range_dynamic():
    ref = date(2026, 9, 4)
    begin, end = disclosure_date_range(ref)
    assert end == "20260904"
    assert begin == "20240904"


def test_format_krw_amount():
    assert "조" in format_krw_amount(17_057_876_000_000)
    assert "억" in format_krw_amount(762_712_000_000)
    assert format_krw_amount(None) == "확인 불가"


def test_yoy_changes(sample_financials):
    changes = compute_yoy_changes(sample_financials)
    rev = next(c for c in changes if c["metric"] == "revenue")
    assert rev["change_pct"] == pytest.approx(9.1, rel=0.1)


def test_merge_multi_document_fields():
    f1 = {"revenue_outlook": {"content": "2027년 520억원", "evidence": [{"source_file": "a.pdf"}]}, "unverified_items": {"content": "없음", "evidence": []}}
    f2 = {"revenue_outlook": {"content": "2027년 480억원", "evidence": [{"source_file": "b.xlsx"}]}, "unverified_items": {"content": "없음", "evidence": []}}
    merged = merge_document_fields([f1, f2])
    assert len(merged["revenue_outlook"]) == 2


def test_doc_revenue_conflict_cross_check(sample_financials):
    doc = {
        "revenue_outlook": [
            {"source_file": "a.pdf", "content": "2024년 매출 520억원", "evidence": []},
            {"source_file": "b.xlsx", "content": "2024년 매출 480억원", "evidence": []},
        ]
    }
    checks = fa_cross_validate(sample_financials, doc)
    conflict = [c for c in checks if c.get("check_id") == "DOC_REVENUE_MISMATCH"]
    assert conflict


def test_different_year_not_simple_mismatch(sample_financials):
    doc = {"revenue_outlook": [{"source_file": "plan.pdf", "content": "2026년 매출 520억원", "evidence": []}]}
    checks = fa_cross_validate(sample_financials, doc, {"corp_name": "테스트"})
    rev_checks = [c for c in checks if c.get("check_id") == "REVENUE_PLAN_VS_ACTUAL"]
    assert any("기준연도" in c.get("reason", "") for c in rev_checks)


def test_unsupported_claim():
    verifications = verify_claims(pd.DataFrame(), [], {"revenue_outlook": [{"source_file": "x", "content": "매출 전망", "evidence": []}]}, [])
    assert any(v["status"] == "unsupported" for v in verifications)


def test_numeric_extraction_units():
    parsed = _extract_numeric_from_text("2025년 매출 520억원 목표")
    assert parsed and parsed.get("amount") == 52_000_000_000


def test_markdown_report_generation(sample_financials):
    md = generate_markdown_report(
        company={"corp_name": "테스트(주)"},
        analysis_date="2026-09-04",
        documents=["plan.pdf"],
        financials=sample_financials,
        ratios=calculate_ratios(sample_financials),
        risk_signals=[],
        cross_checks=[],
        review_memo={"summary": "요약", "sections": {}},
        evidence=[],
    )
    assert "면책" in md
    assert "테스트" in md


def test_ollama_default_config():
    import config
    assert config.LLM_PROVIDER == "ollama"
    assert config.LLM_MODEL == "gemma4:31b"
    assert "11434" in config.OLLAMA_BASE_URL


def test_suggest_companies_limit_and_order():
    from dart_client import DartClient

    client = DartClient(use_mock=True)
    suggestions = client.suggest_companies("삼성", limit=5)
    assert 1 <= len(suggestions) <= 5
    assert all("삼성" in s.get("corp_name", "") for s in suggestions)
    # Exact-ish / prefix matches should come before looser ones; first item should be a Samsung company
    assert suggestions[0]["corp_name"].startswith("삼성")


def test_suggest_companies_stock_code():
    from dart_client import DartClient

    client = DartClient(use_mock=True)
    suggestions = client.suggest_companies("005930", limit=3)
    assert suggestions
    assert suggestions[0]["stock_code"] == "005930"
    assert client.search_company("삼성전자") is not None
