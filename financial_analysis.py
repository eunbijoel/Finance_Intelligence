"""Financial ratio calculation and rule-based risk detection."""

from __future__ import annotations

from typing import Any

import pandas as pd

from config import RISK_THRESHOLDS


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

    # CF_NEGATIVE_2Y
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
    plan_rev = _extract_numeric_from_text(doc.get("revenue_outlook", {}).get("content", ""))
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
        content = (doc.get(key) or {}).get("content", "").strip()
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
    amount = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:억|조|원)?", text)
    result: dict[str, Any] = {}
    if growth:
        result["growth_pct"] = float(growth.group(1))
    if amount:
        raw = amount.group(1).replace(",", "")
        val = float(raw)
        if "조" in text:
            val *= 1_000_000_000_000
        elif "억" in text:
            val *= 100_000_000
        result["amount"] = val
    return result or None
