"""Financial ratio calculation and rule-based risk detection."""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import RISK_THRESHOLDS
from document_parser import get_field_entries, get_field_primary_content


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def calculate_ratios(financials: pd.DataFrame) -> dict[str, Any]:
    """Compute financial ratios in Python (never via LLM)."""
    if financials.empty:
        return {"by_year": {}, "latest": {}, "notes": ["재무 데이터 없음"]}

    df = financials.sort_values("year").copy()
    by_year: dict[str, dict[str, Any]] = {}

    for _, row in df.iterrows():
        year = str(int(row["year"]))
        ratios: dict[str, Any] = {}

        debt_ratio = _safe_div(row.get("total_liabilities"), row.get("total_equity"))
        if debt_ratio is not None:
            ratios["debt_ratio"] = {"value": round(debt_ratio * 100, 2), "unit": "%"}
        else:
            ratios["debt_ratio"] = {"value": None, "reason": "부채 또는 자본 데이터 없음"}

        current_ratio = _safe_div(row.get("current_assets"), row.get("current_liabilities"))
        if current_ratio is not None:
            ratios["current_ratio"] = {"value": round(current_ratio * 100, 2), "unit": "%"}
        else:
            ratios["current_ratio"] = {"value": None, "reason": "유동자산 또는 유동부채 데이터 없음"}

        op_margin = _safe_div(row.get("operating_income"), row.get("revenue"))
        if op_margin is not None:
            ratios["operating_margin"] = {"value": round(op_margin * 100, 2), "unit": "%"}
        else:
            ratios["operating_margin"] = {"value": None, "reason": "매출 또는 영업이익 데이터 없음"}

        net_margin = _safe_div(row.get("net_income"), row.get("revenue"))
        if net_margin is not None:
            ratios["net_margin"] = {"value": round(net_margin * 100, 2), "unit": "%"}
        else:
            ratios["net_margin"] = {"value": None, "reason": "매출 또는 순이익 데이터 없음"}

        roa = _safe_div(row.get("net_income"), row.get("total_assets"))
        if roa is not None:
            ratios["roa"] = {"value": round(roa * 100, 2), "unit": "%"}
        else:
            ratios["roa"] = {"value": None, "reason": "순이익 또는 총자산 데이터 없음"}

        roe = _safe_div(row.get("net_income"), row.get("total_equity"))
        if roe is not None:
            ratios["roe"] = {"value": round(roe * 100, 2), "unit": "%"}
        else:
            ratios["roe"] = {"value": None, "reason": "순이익 또는 자본 데이터 없음"}

        ocf_to_debt = _safe_div(row.get("operating_cash_flow"), row.get("short_term_borrowings"))
        if ocf_to_debt is not None:
            ratios["ocf_to_short_term_debt"] = {"value": round(ocf_to_debt * 100, 2), "unit": "%"}
        else:
            ratios["ocf_to_short_term_debt"] = {
                "value": None,
                "reason": "영업현금흐름 또는 단기차입금 데이터 없음",
            }

        by_year[year] = ratios

    latest_year = str(int(df.iloc[-1]["year"]))
    return {"by_year": by_year, "latest": by_year.get(latest_year, {}), "notes": []}


def detect_risk_signals(
    financials: pd.DataFrame,
    ratios: dict[str, Any],
    document_fields: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Apply explicit Python rules for risk signal detection."""
    signals: list[dict[str, Any]] = []
    if financials.empty:
        return signals

    df = financials.sort_values("year")
    years = df["year"].tolist()
    by_year = ratios.get("by_year", {})
    doc = document_fields or {}
    rev_content = get_field_primary_content(doc, "revenue_outlook")
    plan_rev = _extract_numeric_from_text(rev_content) if rev_content else None
    if len(df) >= 2:
        last_two = df.tail(2)
        if all((row.get("operating_cash_flow") or 0) < 0 for _, row in last_two.iterrows()):
            evidence = []
            for _, row in last_two.iterrows():
                evidence.append(
                    {
                        "source": "재무제표",
                        "period": str(int(row["year"])),
                        "value": row.get("operating_cash_flow"),
                    }
                )
            signals.append(
                {
                    "rule_id": "CF_NEGATIVE_2Y",
                    "severity": "high",
                    "title": "영업현금흐름 2개년 연속 음수",
                    "description": "최근 2개 사업연도 영업현금흐름이 모두 음수로 확인됩니다.",
                    "evidence": evidence,
                    "review_question": "현금흐름 악화 원인과 개선 계획을 확인해 주세요.",
                }
            )

    # DEBT_RATIO_SURGE
    debt_vals = []
    for y in years:
        r = by_year.get(str(int(y)), {}).get("debt_ratio", {})
        if r.get("value") is not None:
            debt_vals.append((int(y), r["value"]))
    if len(debt_vals) >= 2:
        prev_y, prev_v = debt_vals[-2]
        curr_y, curr_v = debt_vals[-1]
        if curr_v - prev_v >= RISK_THRESHOLDS["debt_ratio_surge_pp"]:
            signals.append(
                {
                    "rule_id": "DEBT_RATIO_SURGE",
                    "severity": "medium",
                    "title": "부채비율 급증",
                    "description": f"부채비율이 {prev_y}년 {prev_v}%에서 {curr_y}년 {curr_v}%로 증가했습니다.",
                    "evidence": [
                        {"source": "재무비율", "period": str(prev_y), "value": prev_v},
                        {"source": "재무비율", "period": str(curr_y), "value": curr_v},
                    ],
                    "review_question": "부채 증가 원인과 상환 계획을 확인해 주세요.",
                }
            )

    # CURRENT_RATIO_DECLINE
    cr_vals = []
    for y in years:
        r = by_year.get(str(int(y)), {}).get("current_ratio", {})
        if r.get("value") is not None:
            cr_vals.append((int(y), r["value"]))
    if len(cr_vals) >= 2:
        prev_y, prev_v = cr_vals[-2]
        curr_y, curr_v = cr_vals[-1]
        decline = _pct_change(curr_v, prev_v)
        if decline is not None and decline <= -RISK_THRESHOLDS["current_ratio_decline_pct"]:
            signals.append(
                {
                    "rule_id": "CURRENT_RATIO_DECLINE",
                    "severity": "medium",
                    "title": "유동비율 하락",
                    "description": f"유동비율이 {prev_y}년 {prev_v}%에서 {curr_y}년 {curr_v}%로 하락했습니다.",
                    "evidence": [
                        {"source": "재무비율", "period": str(prev_y), "value": prev_v},
                        {"source": "재무비율", "period": str(curr_y), "value": curr_v},
                    ],
                    "review_question": "단기 유동성 관련 대응 방안을 확인해 주세요.",
                }
            )

    # REVENUE_UP_PROFIT_DOWN
    if len(df) >= 2:
        prev, curr = df.iloc[-2], df.iloc[-1]
        rev_chg = _pct_change(curr.get("revenue"), prev.get("revenue"))
        op_chg = _pct_change(curr.get("operating_income"), prev.get("operating_income"))
        cf_chg = _pct_change(curr.get("operating_cash_flow"), prev.get("operating_cash_flow"))
        if rev_chg is not None and rev_chg > 0:
            if (op_chg is not None and op_chg < 0) or (cf_chg is not None and cf_chg < 0):
                signals.append(
                    {
                        "rule_id": "REVENUE_UP_PROFIT_DOWN",
                        "severity": "medium",
                        "title": "매출 증가와 동시에 수익성/현금흐름 악화",
                        "description": "매출은 증가했으나 영업이익 또는 영업현금흐름이 전년 대비 악화되었습니다.",
                        "evidence": [
                            {"source": "재무제표", "period": str(int(curr["year"])), "metric": "revenue_change_pct", "value": round(rev_chg, 2)},
                            {"source": "재무제표", "period": str(int(curr["year"])), "metric": "operating_income_change_pct", "value": round(op_chg or 0, 2)},
                            {"source": "재무제표", "period": str(int(curr["year"])), "metric": "ocf_change_pct", "value": round(cf_chg or 0, 2)},
                        ],
                        "review_question": "매출 증가 대비 마진·현금전환율 변화 원인을 확인해 주세요.",
                    }
                )

    # SHORT_TERM_DEBT_SURGE
    if len(df) >= 2 and "short_term_borrowings" in df.columns:
        prev, curr = df.iloc[-2], df.iloc[-1]
        st_chg = _pct_change(curr.get("short_term_borrowings"), prev.get("short_term_borrowings"))
        if st_chg is not None and st_chg >= RISK_THRESHOLDS["short_term_debt_surge_pct"]:
            signals.append(
                {
                    "rule_id": "SHORT_TERM_DEBT_SURGE",
                    "severity": "high",
                    "title": "단기차입금 급증",
                    "description": f"단기차입금이 전년 대비 {st_chg:.1f}% 증가했습니다.",
                    "evidence": [
                        {"source": "재무제표", "period": str(int(prev["year"])), "value": prev.get("short_term_borrowings")},
                        {"source": "재무제표", "period": str(int(curr["year"])), "value": curr.get("short_term_borrowings")},
                    ],
                    "review_question": "단기차입금 증가 사유와 상환 재원을 확인해 주세요.",
                }
            )

    # RECEIVABLES_GROWTH
    if len(df) >= 2 and "accounts_receivable" in df.columns:
        prev, curr = df.iloc[-2], df.iloc[-1]
        rec_chg = _pct_change(curr.get("accounts_receivable"), prev.get("accounts_receivable"))
        rev_chg = _pct_change(curr.get("revenue"), prev.get("revenue"))
        if rec_chg is not None and rev_chg is not None:
            gap = rec_chg - rev_chg
            if gap >= RISK_THRESHOLDS["receivables_vs_revenue_gap_pp"]:
                signals.append(
                    {
                        "rule_id": "RECEIVABLES_GROWTH",
                        "severity": "medium",
                        "title": "매출채권 증가율이 매출 증가율보다 현저히 높음",
                        "description": f"매출채권 증가율({rec_chg:.1f}%)이 매출 증가율({rev_chg:.1f}%)을 크게 상회합니다.",
                        "evidence": [
                            {"source": "재무제표", "period": str(int(curr["year"])), "metric": "receivables_growth_pct", "value": round(rec_chg, 2)},
                            {"source": "재무제표", "period": str(int(curr["year"])), "metric": "revenue_growth_pct", "value": round(rev_chg, 2)},
                        ],
                        "review_question": "매출채권 회수 조건 및 대손 가능성을 확인해 주세요.",
                    }
                )

    # PLAN_REVENUE_OPTIMISTIC
    if plan_rev and len(df) >= 2:
        rev_series = df["revenue"].dropna()
        if len(rev_series) >= 2:
            cagr = ((rev_series.iloc[-1] / rev_series.iloc[0]) ** (1 / (len(rev_series) - 1)) - 1) * 100
            plan_growth = plan_rev.get("growth_pct")
            if plan_growth is not None and plan_growth - cagr >= RISK_THRESHOLDS["plan_revenue_optimism_pp"]:
                signals.append(
                    {
                        "rule_id": "PLAN_REVENUE_OPTIMISTIC",
                        "severity": "medium",
                        "title": "사업계획서 예상 매출 성장률이 실적 추세 대비 과도",
                        "description": f"사업계획 매출 성장률({plan_growth:.1f}%)이 최근 실적 CAGR({cagr:.1f}%)을 크게 상회합니다.",
                        "evidence": [
                            {"source": "사업계획서", "metric": "planned_revenue_growth_pct", "value": plan_growth},
                            {"source": "재무제표", "metric": "historical_revenue_cagr_pct", "value": round(cagr, 2)},
                        ],
                        "review_question": "매출 전망의 가정(수주, 가격, 물량)을 확인해 주세요.",
                    }
                )

    # PLAN_FINANCIAL_MISMATCH
    disclosed_rev = df.iloc[-1].get("revenue")
    plan_rev_amount = plan_rev.get("amount") if plan_rev else None
    if disclosed_rev and plan_rev_amount:
        diff_pct = abs(plan_rev_amount - disclosed_rev) / disclosed_rev * 100
        if diff_pct >= RISK_THRESHOLDS["plan_financial_mismatch_pct"]:
            signals.append(
                {
                    "rule_id": "PLAN_FINANCIAL_MISMATCH",
                    "severity": "high",
                    "title": "사업계획서 숫자와 공시 재무정보 불일치",
                    "description": f"사업계획서 매출({plan_rev_amount:,.0f})과 공시 매출({disclosed_rev:,.0f}) 차이가 {diff_pct:.1f}%입니다.",
                    "evidence": [
                        {"source": "사업계획서", "metric": "planned_revenue", "value": plan_rev_amount},
                        {"source": "재무제표", "period": str(int(df.iloc[-1]['year'])), "metric": "disclosed_revenue", "value": disclosed_rev},
                    ],
                    "review_question": "사업계획서 기준연도 및 매출 정의(연결/별도)를 확인해 주세요.",
                }
            )

    # MISSING_REPAYMENT_OR_PURPOSE
    missing = []
    for key, label in (
        ("fund_purpose", "자금 사용 목적"),
        ("repayment_plan", "상환 계획"),
    ):
        content = get_field_primary_content(doc, key).strip()
        if not content or content.startswith("문서에서 확인되지"):
            missing.append(label)
    if missing:
        signals.append(
            {
                "rule_id": "MISSING_REPAYMENT_OR_PURPOSE",
                "severity": "medium",
                "title": "상환재원 또는 자금 용도 미명시",
                "description": f"업로드 문서에서 다음 항목이 확인되지 않습니다: {', '.join(missing)}",
                "evidence": [{"source": "업로드 문서", "metric": "missing_fields", "value": missing}],
                "review_question": "자금 사용 목적과 상환 재원에 대한 추가 자료를 요청해 주세요.",
            }
        )

    return signals


def compare_analyses(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare two analysis records for the same company."""
    prev_rules = {s["rule_id"] for s in previous.get("risk_signals", [])}
    curr_rules = {s["rule_id"] for s in current.get("risk_signals", [])}

    prev_ratios = previous.get("ratios", {}).get("latest", {})
    curr_ratios = current.get("ratios", {}).get("latest", {})

    worsened = []
    improved = []
    for key in set(prev_ratios) | set(curr_ratios):
        pv = (prev_ratios.get(key) or {}).get("value")
        cv = (curr_ratios.get(key) or {}).get("value")
        if pv is None or cv is None:
            continue
        # Lower debt/current issues for debt_ratio; context-dependent — flag absolute change
        delta = cv - pv
        if abs(delta) >= 1.0:
            entry = {"ratio": key, "previous": pv, "current": cv, "delta": round(delta, 2)}
            if key in {"debt_ratio"} and delta > 0:
                worsened.append(entry)
            elif key in {"current_ratio", "operating_margin", "roe", "roa"} and delta < 0:
                worsened.append(entry)
            elif key in {"current_ratio", "operating_margin", "roe", "roa"} and delta > 0:
                improved.append(entry)
            elif key == "debt_ratio" and delta < 0:
                improved.append(entry)

    prev_memo = (previous.get("review_memo") or {}).get("summary", "")
    curr_memo = (current.get("review_memo") or {}).get("summary", "")

    return {
        "new_risk_signals": sorted(curr_rules - prev_rules),
        "resolved_risk_signals": sorted(prev_rules - curr_rules),
        "worsened_ratios": worsened,
        "improved_ratios": improved,
        "new_disclosures": current.get("new_disclosures", []),
        "memo_diff_hint": _memo_diff_hint(prev_memo, curr_memo),
    }


def _memo_diff_hint(prev: str, curr: str) -> str:
    if not prev:
        return "이전 분석 메모 없음 — 최초 분석"
    if prev.strip() == curr.strip():
        return "종합 검토 메모 요약 변경 없음"
    return "종합 검토 메모 요약이 변경되었습니다. 상세 비교는 검토 워크스페이스에서 확인하세요."


def _extract_numeric_from_text(text: str) -> dict[str, Any] | None:
    import re

    if not text:
        return None
    growth = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    year = re.search(r"(20\d{2})\s*년", text)
    result: dict[str, Any] = {}
    if growth:
        result["growth_pct"] = float(growth.group(1))
    if year:
        result["year"] = int(year.group(1))
    amount_match = re.search(
        r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(조|억|만|백만)\s*원?",
        text,
    )
    if amount_match:
        raw = amount_match.group(1).replace(",", "")
        val = float(raw)
        unit = amount_match.group(2)
        mult = {"조": 1_000_000_000_000, "억": 100_000_000, "백만": 1_000_000, "만": 10_000}
        result["amount"] = int(val * mult.get(unit, 1))
    return result or None


def compute_yoy_changes(financials: pd.DataFrame) -> list[dict[str, Any]]:
    """Compare latest two years for key metrics."""
    if financials.empty or len(financials) < 2:
        return []
    df = financials.sort_values("year")
    prev, curr = df.iloc[-2], df.iloc[-1]
    metrics = [
        ("revenue", "매출액"),
        ("operating_income", "영업이익"),
        ("net_income", "당기순이익"),
        ("operating_cash_flow", "영업현금흐름"),
    ]
    changes = []
    for col, label in metrics:
        chg = _pct_change(curr.get(col), prev.get(col))
        if chg is not None:
            changes.append({"metric": col, "label": label, "change_pct": round(chg, 1), "period": str(int(curr["year"]))})
    return changes


def compute_ratio_changes(ratios: dict[str, Any]) -> list[dict[str, Any]]:
    by_year = ratios.get("by_year", {})
    if len(by_year) < 2:
        return []
    years = sorted(by_year.keys())
    prev_y, curr_y = years[-2], years[-1]
    changes = []
    for key, label in (("debt_ratio", "부채비율"), ("current_ratio", "유동비율")):
        pv = (by_year[prev_y].get(key) or {}).get("value")
        cv = (by_year[curr_y].get(key) or {}).get("value")
        if pv is not None and cv is not None:
            changes.append({
                "metric": key,
                "label": label,
                "delta_pp": round(cv - pv, 1),
                "prev_year": prev_y,
                "curr_year": curr_y,
            })
    return changes


def run_cross_validation(
    financials: pd.DataFrame,
    document_fields: dict[str, Any],
    company: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Structured cross-validation between documents and DART data."""
    checks: list[dict[str, Any]] = []
    company = company or {}

    # Revenue plan vs actual
    rev_entries = get_field_entries(document_fields, "revenue_outlook")
    if rev_entries and not financials.empty:
        latest = financials.sort_values("year").iloc[-1]
        dart_year = str(int(latest["year"]))
        dart_rev = latest.get("revenue")
        for entry in rev_entries:
            parsed = _extract_numeric_from_text(entry.get("content", ""))
            if not parsed or parsed.get("amount") is None:
                checks.append({
                    "check_id": "REVENUE_PLAN_VS_ACTUAL",
                    "metric": "매출액",
                    "document_source": entry.get("source_file"),
                    "document_period": str(parsed.get("year")) if parsed and parsed.get("year") else None,
                    "document_value": None,
                    "dart_period": dart_year,
                    "dart_value": dart_rev,
                    "status": "NEEDS_REVIEW",
                    "reason": "문서에서 매출 수치를 안전하게 추출하지 못했습니다.",
                    "evidence": entry.get("evidence") or [],
                })
                continue
            doc_year = parsed.get("year")
            doc_val = parsed["amount"]
            if doc_year and int(doc_year) != int(dart_year):
                checks.append({
                    "check_id": "REVENUE_PLAN_VS_ACTUAL",
                    "metric": "매출액",
                    "document_source": entry.get("source_file"),
                    "document_period": str(doc_year),
                    "document_value": doc_val,
                    "dart_period": dart_year,
                    "dart_value": dart_rev,
                    "status": "NEEDS_REVIEW",
                    "reason": f"기준연도 확인 필요 (문서 {doc_year}년 vs 공시 {dart_year}년)",
                    "evidence": entry.get("evidence") or [],
                })
            elif dart_rev:
                diff = doc_val - dart_rev
                diff_pct = abs(diff) / dart_rev * 100
                status = "REVIEW_REQUIRED" if diff_pct >= RISK_THRESHOLDS["plan_financial_mismatch_pct"] else "CONFIRMED"
                checks.append({
                    "check_id": "REVENUE_PLAN_VS_ACTUAL",
                    "metric": "매출액",
                    "document_source": entry.get("source_file"),
                    "document_period": str(doc_year or dart_year),
                    "document_value": doc_val,
                    "dart_period": dart_year,
                    "dart_value": dart_rev,
                    "difference": diff,
                    "difference_pct": round(diff_pct, 2),
                    "status": status,
                    "reason": (
                        f"사업계획 매출이 공시 매출보다 {diff_pct:.1f}% {'높습니다' if diff > 0 else '낮습니다'}."
                        if status == "REVIEW_REQUIRED"
                        else "동일 기준연도 매출 수치가 유사합니다."
                    ),
                    "evidence": entry.get("evidence") or [],
                })

    # Document-to-document revenue mismatch
    if len(rev_entries) >= 2:
        parsed_vals = []
        for entry in rev_entries:
            p = _extract_numeric_from_text(entry.get("content", ""))
            if p and p.get("amount") is not None:
                parsed_vals.append((entry, p))
        for i in range(len(parsed_vals)):
            for j in range(i + 1, len(parsed_vals)):
                e1, p1 = parsed_vals[i]
                e2, p2 = parsed_vals[j]
                y1, y2 = p1.get("year"), p2.get("year")
                if y1 and y2 and y1 != y2:
                    continue
                v1, v2 = p1["amount"], p2["amount"]
                if v1 != v2:
                    checks.append({
                        "check_id": "DOC_REVENUE_MISMATCH",
                        "metric": "매출 전망",
                        "document_source": f"{e1.get('source_file')} vs {e2.get('source_file')}",
                        "document_value": v1,
                        "document_value_2": v2,
                        "difference": abs(v1 - v2),
                        "status": "CONFLICT",
                        "reason": "문서 간 매출 전망 수치가 다릅니다.",
                        "evidence": (e1.get("evidence") or []) + (e2.get("evidence") or []),
                    })

    # Text fields: fund purpose, repayment, customers, company name, business period
    text_checks = [
        ("fund_purpose", "자금 사용 목적"),
        ("repayment_plan", "상환 계획"),
        ("major_customers", "주요 거래처"),
        ("company_overview", "기업명"),
        ("business_purpose", "사업 기간"),
    ]
    for key, metric in text_checks:
        entries = get_field_entries(document_fields, key)
        if not entries:
            checks.append({
                "check_id": f"TEXT_{key.upper()}",
                "metric": metric,
                "status": "MISSING",
                "reason": f"문서에서 {metric}이(가) 확인되지 않습니다.",
                "evidence": [],
            })
        else:
            for entry in entries:
                status = "CONFIRMED" if entry.get("evidence") else "NEEDS_REVIEW"
                checks.append({
                    "check_id": f"TEXT_{key.upper()}",
                    "metric": metric,
                    "document_source": entry.get("source_file"),
                    "status": status,
                    "reason": f"{metric} 확인됨" if status == "CONFIRMED" else f"{metric}는 있으나 근거 위치가 불명확합니다.",
                    "content_excerpt": entry.get("content", "")[:200],
                    "evidence": entry.get("evidence") or [],
                })

    # Company name cross-check
    corp_name = company.get("corp_name", "")
    overview_entries = get_field_entries(document_fields, "company_overview")
    for entry in overview_entries:
        content = entry.get("content", "")
        if corp_name and corp_name.replace("(주)", "") not in content and corp_name not in content:
            checks.append({
                "check_id": "COMPANY_NAME_MISMATCH",
                "metric": "기업명",
                "document_source": entry.get("source_file"),
                "dart_value": corp_name,
                "document_excerpt": content[:100],
                "status": "NEEDS_REVIEW",
                "reason": "문서의 기업명과 DART 기업명이 일치하지 않을 수 있습니다.",
                "evidence": entry.get("evidence") or [],
            })

    return checks


def verify_claims(
    financials: pd.DataFrame,
    yoy_changes: list[dict[str, Any]],
    document_fields: dict[str, Any],
    cross_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verify memo claims against available evidence."""
    verifications: list[dict[str, Any]] = []

    for ch in yoy_changes:
        claim = f"{ch['label']}은(는) 전년 대비 {abs(ch['change_pct'])}% {'증가' if ch['change_pct'] > 0 else '감소'}"
        if financials.empty or len(financials) < 2:
            verifications.append({"claim": claim, "status": "unsupported", "evidence": []})
            continue
        df = financials.sort_values("year")
        prev, curr = df.iloc[-2], df.iloc[-1]
        metric = ch["metric"]
        verifications.append({
            "claim": claim,
            "status": "supported",
            "evidence": [
                {"source": "DART 재무제표", "period": str(int(prev["year"])), "metric": metric, "value": prev.get(metric)},
                {"source": "DART 재무제표", "period": str(int(curr["year"])), "metric": metric, "value": curr.get(metric)},
            ],
        })

    for entry in get_field_entries(document_fields, "revenue_outlook"):
        claim = f"문서({entry.get('source_file')}) 매출 전망: {entry.get('content', '')[:80]}"
        ev = entry.get("evidence") or []
        has_loc = any(ev_item.get("page") or ev_item.get("sheet") or ev_item.get("location") for ev_item in ev)
        if ev and has_loc:
            status = "supported"
        elif ev:
            status = "partial"
        else:
            status = "unsupported"
        verifications.append({"claim": claim, "status": status, "evidence": ev})

    for ck in cross_checks:
        if ck.get("status") in {"REVIEW_REQUIRED", "CONFLICT", "NEEDS_REVIEW"}:
            claim = ck.get("reason", "")
            ev = ck.get("evidence") or []
            status = "supported" if ev else "partial" if ck.get("dart_value") else "unsupported"
            verifications.append({"claim": claim, "status": status, "evidence": ev})

    return verifications
