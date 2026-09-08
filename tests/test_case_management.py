"""Case management, Maker–Checker, audit, documents, reproduction tests."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

import audit_service
import config
import database
from case_management import (
    CaseError,
    add_comment,
    can_request_checker,
    create_case,
    get_case,
    list_cases,
    transition_status,
)
from database import (
    get_analysis,
    init_db,
    list_analyses,
    next_analysis_version,
    save_analysis,
)
from document_registry import compute_sha256, find_duplicate, register_document
from reproduction import (
    NOT_REPRODUCIBLE,
    PARTIALLY_REPRODUCIBLE,
    REPRODUCIBLE,
    assess_reproducibility,
)
from versioning import ALLOWED_TRANSITIONS, PROMPT_VERSION, RULE_VERSION, WORKFLOW_VERSION


SECRET_KEYS = {"api_key", "API_KEY", "password", "token", "secret", "LLM_API_KEY"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "case.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    init_db()
    return db_path


def _payload(**overrides):
    base = {
        "company_name": "테스트SME",
        "company_id": "00126380",
        "stock_code": "005930",
        "application_amount": 1_000_000_000,
        "fund_purpose": "운전자금",
        "loan_product": "일반자금대출",
        "application_date": date.today().isoformat(),
        "due_date": (date.today() + timedelta(days=14)).isoformat(),
        "priority": "NORMAL",
        "maker_id": "maker01",
        "checker_id": "checker01",
        "notes": "unit test",
    }
    base.update(overrides)
    return base


def test_create_and_get_case(db):
    case = create_case(_payload(), created_by="maker01")
    assert case["case_id"]
    assert case["case_number"].startswith(f"CR-{date.today().strftime('%Y%m%d')}-")
    assert case["status"] == "RECEIVED"
    loaded = get_case(case["case_id"])
    assert loaded["company_name"] == "테스트SME"


def test_case_number_unique(db):
    a = create_case(_payload(company_name="A"), created_by="maker01")
    b = create_case(_payload(company_name="B"), created_by="maker01")
    assert a["case_number"] != b["case_number"]
    nums = {c["case_number"] for c in list_cases()}
    assert len(nums) == 2


def test_maker_checker_same_person_blocked(db):
    with pytest.raises(CaseError, match="동일 사용자"):
        create_case(_payload(maker_id="maker01", checker_id="maker01"), created_by="admin01")


def test_allowed_transitions(db):
    case = create_case(_payload(), created_by="maker01")
    cid = case["case_id"]
    transition_status(cid, "IN_REVIEW", actor_id="maker01")
    assert get_case(cid)["status"] == "IN_REVIEW"
    transition_status(cid, "CHECKER_REVIEW", actor_id="maker01")
    assert get_case(cid)["status"] == "CHECKER_REVIEW"
    transition_status(cid, "APPROVED", actor_id="checker01", reason="ok")
    assert get_case(cid)["status"] == "APPROVED"
    transition_status(cid, "CLOSED", actor_id="admin01")
    assert get_case(cid)["status"] == "CLOSED"


def test_disallowed_transition_blocked(db):
    case = create_case(_payload(), created_by="maker01")
    with pytest.raises(CaseError, match="상태 전환 불가"):
        transition_status(case["case_id"], "APPROVED", actor_id="checker01")


def test_maker_cannot_approve(db):
    case = create_case(_payload(), created_by="maker01")
    cid = case["case_id"]
    transition_status(cid, "IN_REVIEW", actor_id="maker01")
    transition_status(cid, "CHECKER_REVIEW", actor_id="maker01")
    with pytest.raises(CaseError, match="Checker만"):
        transition_status(cid, "APPROVED", actor_id="maker01", reason="nope")


def test_checker_changes_request_requires_comment(db):
    case = create_case(_payload(), created_by="maker01")
    with pytest.raises(CaseError, match="필수"):
        add_comment(
            case_id=case["case_id"],
            author_id="checker01",
            author_role="CHECKER",
            comment_type="CHECKER_CHANGES_REQUESTED",
            comment="   ",
        )


def test_document_sha256_and_duplicate(db, tmp_path):
    case = create_case(_payload(), created_by="maker01")
    content = b"business plan content"
    sha = compute_sha256(content)
    assert len(sha) == 64
    doc1, dup1 = register_document(
        case_id=case["case_id"], filename="plan.txt", content=content, uploaded_by="maker01"
    )
    assert not dup1
    assert doc1["sha256"] == sha
    doc2, dup2 = register_document(
        case_id=case["case_id"], filename="plan_copy.txt", content=content, uploaded_by="maker01"
    )
    assert dup2
    assert doc2["document_id"] == doc1["document_id"]
    assert find_duplicate(case["case_id"], sha) is not None


def test_analysis_version_increments(db):
    case = create_case(_payload(), created_by="maker01")
    cid = case["case_id"]
    v1 = next_analysis_version(cid)
    save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": v1,
            "review_memo": {"summary": "v1"},
            "ai_memo_original": "AI original",
            "maker_memo_revised": None,
        }
    )
    v2 = next_analysis_version(cid)
    assert v2 == v1 + 1
    save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": v2,
            "review_memo": {"summary": "v2"},
            "ai_memo_original": "AI original",
            "maker_memo_revised": "Maker edit",
        }
    )
    rows = list_analyses(case_id=cid)
    assert len(rows) == 2
    assert {r["analysis_version"] for r in rows} == {v1, v2}


def test_ai_and_maker_memo_separated(db):
    case = create_case(_payload(), created_by="maker01")
    aid = save_analysis(
        {
            "company_id": "x",
            "company_name": "테스트SME",
            "case_id": case["case_id"],
            "analysis_version": 1,
            "review_memo": {"summary": "AI TEXT"},
            "ai_memo_original": "AI TEXT",
            "maker_memo_revised": "MAKER TEXT",
            "user_edits": "MAKER TEXT",
        }
    )
    loaded = get_analysis(aid)
    assert loaded["ai_memo_original"] == "AI TEXT"
    assert loaded["maker_memo_revised"] == "MAKER TEXT"
    assert loaded["ai_memo_original"] != loaded["maker_memo_revised"]


def test_audit_log_created(db):
    case = create_case(_payload(), created_by="maker01")
    logs = audit_service.list_audit_logs(case_id=case["case_id"])
    assert any(lg["action"] == "CASE_CREATED" for lg in logs)
    transition_status(case["case_id"], "IN_REVIEW", actor_id="maker01")
    logs2 = audit_service.list_audit_logs(case_id=case["case_id"])
    assert any(lg["action"] == "STATUS_CHANGED" for lg in logs2)


def test_audit_has_no_update_delete_api():
    names = dir(audit_service)
    for forbidden in ("update_audit", "delete_audit", "update_audit_log", "delete_audit_log"):
        assert forbidden not in names
    assert "write_audit" in names
    assert "list_audit_logs" in names


def test_snapshot_excludes_secrets(db):
    snapshot = {
        "company": {"corp_code": "001"},
        "risk_thresholds": {"debt_ratio": 200},
        "financial_years": [2023, 2024],
    }
    assert not (SECRET_KEYS & set(snapshot.keys()))
    blob = str(snapshot).lower()
    for s in ("api_key", "password", "bearer ", "sk-"):
        assert s not in blob


def test_reproducibility_assessment(db):
    case = create_case(_payload(), created_by="maker01")
    cid = case["case_id"]
    content = b"doc-for-repro"
    register_document(case_id=cid, filename="a.txt", content=content, uploaded_by="maker01")
    from document_registry import build_manifest

    aid = save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": 1,
            "prompt_version": PROMPT_VERSION,
            "rule_version": RULE_VERSION,
            "workflow_version": WORKFLOW_VERSION,
            "model_provider": config.LLM_PROVIDER,
            "model_name": config.LLM_MODEL,
            "input_snapshot": {"company": {"corp_code": "00126380"}},
            "document_manifest": build_manifest(cid),
            "review_memo": {"summary": "x"},
        }
    )
    result = assess_reproducibility(aid, cid)
    assert result["status"] in {REPRODUCIBLE, PARTIALLY_REPRODUCIBLE}

    empty_id = save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": 2,
            "review_memo": {},
        }
    )
    bad = assess_reproducibility(empty_id, cid)
    assert bad["status"] == NOT_REPRODUCIBLE


def test_legacy_analysis_without_case_id(db):
    aid = save_analysis(
        {
            "company_id": "legacy",
            "company_name": "레거시기업",
            "review_memo": {"summary": "old"},
            "risk_signals": [],
        }
    )
    loaded = get_analysis(aid)
    assert loaded is not None
    assert loaded.get("case_id") in (None, "")
    rows = list_analyses(company_id="legacy")
    assert len(rows) == 1


def test_approved_edit_creates_new_version(db):
    case = create_case(_payload(), created_by="maker01")
    cid = case["case_id"]
    a1 = save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": 1,
            "approved": True,
            "ai_memo_original": "orig",
            "review_memo": {"summary": "orig"},
        }
    )
    a2 = save_analysis(
        {
            "company_id": "00126380",
            "company_name": "테스트SME",
            "case_id": cid,
            "analysis_version": next_analysis_version(cid),
            "approved": False,
            "ai_memo_original": "orig",
            "maker_memo_revised": "edited",
            "review_memo": {"summary": "orig"},
        }
    )
    assert a1 != a2
    assert get_analysis(a1)["ai_memo_original"] == "orig"
    assert get_analysis(a2)["maker_memo_revised"] == "edited"
    assert len(list_analyses(case_id=cid)) == 2


def test_case_analysis_isolation(db):
    c1 = create_case(_payload(company_name="SME1"), created_by="maker01")
    c2 = create_case(_payload(company_name="SME2"), created_by="maker01")
    save_analysis(
        {
            "company_id": "a",
            "company_name": "SME1",
            "case_id": c1["case_id"],
            "analysis_version": 1,
            "review_memo": {"summary": "only1"},
        }
    )
    save_analysis(
        {
            "company_id": "b",
            "company_name": "SME2",
            "case_id": c2["case_id"],
            "analysis_version": 1,
            "review_memo": {"summary": "only2"},
        }
    )
    r1 = list_analyses(case_id=c1["case_id"])
    r2 = list_analyses(case_id=c2["case_id"])
    assert len(r1) == 1 and r1[0]["review_memo"]["summary"] == "only1"
    assert len(r2) == 1 and r2[0]["review_memo"]["summary"] == "only2"


def test_transition_map_covers_statuses():
    from versioning import CASE_STATUSES

    for s in CASE_STATUSES:
        assert s in ALLOWED_TRANSITIONS


def test_can_request_checker_prechecks(db):
    case = create_case(_payload(), created_by="maker01")
    ok, issues = can_request_checker(case["case_id"])
    assert not ok
    assert any("분석" in i for i in issues)
