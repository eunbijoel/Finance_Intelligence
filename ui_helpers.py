"""Display formatting, review summaries, and report generation."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from financial_analysis import compute_ratio_changes, compute_yoy_changes

FINANCIAL_LABELS = {
    "year": "연도",
    "revenue": "매출액",
    "operating_income": "영업이익",
    "net_income": "당기순이익",
    "operating_cash_flow": "영업현금흐름",
    "total_assets": "총자산",
    "total_liabilities": "총부채",
    "total_equity": "총자본",
    "current_assets": "유동자산",
    "current_liabilities": "유동부채",
    "short_term_borrowings": "단기차입금",
    "accounts_receivable": "매출채권",
}

RATIO_LABELS = {
    "debt_ratio": "부채비율",
    "current_ratio": "유동비율",
    "operating_margin": "영업이익률",
    "net_margin": "순이익률",
    "roa": "ROA",
    "roe": "ROE",
    "ocf_to_short_term_debt": "영업CF/단기차입",
}

DISCLOSURE_LABELS = {
    "report_nm": "공시명",
    "rcept_dt": "공시일",
    "flr_nm": "제출인",
    "rcept_no": "원문",
    "corp_cls": "시장구분",
}

DISCLOSURE_HIDE = {"corp_code", "corp_name", "stock_code", "rm"}

DISCLOSURE_CATEGORY_RULES = [
    ("정기보고", ["사업보고서", "반기보고서", "분기보고서", "감사보고서"]),
    ("실적·재무", ["실적", "매출", "영업이익", "잠정", "공정공시", "분기보고"]),
    ("자금조달", ["증자", "사채", "전환사채", "자금", "차입", "대출"]),
    ("주요계약", ["공급", "계약", "수주", "공급계약", "단일판매"]),
    ("지배구조", ["주주", "임원", "지배", "합병", "분할", "자기주식"]),
]


def format_krw_amount(value: Any) -> str:
    """Display-only KRW formatting."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "확인 불가"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000_000:
        return f"{sign}{v / 1_000_000_000_000:.1f}조 원"
    if v >= 100_000_000:
        return f"{sign}{v / 100_000_000:,.1f}억 원"
    if v >= 10_000:
        return f"{sign}{v / 10_000:,.0f}만 원"
    return f"{sign}{v:,.0f}원"


def format_financials_display(financials: pd.DataFrame) -> pd.DataFrame:
    if financials.empty:
        return pd.DataFrame()
    df = financials.sort_values("year").copy()
    display = pd.DataFrame()
    display["연도"] = df["year"].astype(int)
    for col, label in FINANCIAL_LABELS.items():
        if col == "year" or col not in df.columns:
            continue
        display[label] = df[col].apply(format_krw_amount)
    if len(df) >= 2:
        prev, curr = df.iloc[-2], df.iloc[-1]
        yoy = {}
        for col, label in FINANCIAL_LABELS.items():
            if col == "year" or col not in df.columns:
                continue
            pv, cv = prev.get(col), curr.get(col)
            if pv and cv and pv != 0:
                chg = (cv - pv) / abs(pv) * 100
                yoy[label] = f"{chg:+.1f}%"
            else:
                yoy[label] = "확인 불가"
        if yoy:
            display.loc[display.index[-1], "전년대비"] = "—"
            for label, val in yoy.items():
                if label in display.columns:
                    pass
            display["전년대비(최근연도)"] = pd.Series([""] * (len(display) - 1) + [", ".join(f"{k} {v}" for k, v in yoy.items())])
    return display


def format_ratios_table(ratios: dict[str, Any]) -> pd.DataFrame:
    by_year = ratios.get("by_year", {})
    if not by_year:
        return pd.DataFrame()
    years = sorted(by_year.keys())
    rows = []
    for key, label in RATIO_LABELS.items():
        row: dict[str, Any] = {"지표": label}
        vals = []
        for y in years:
            r = by_year[y].get(key, {})
            if r.get("value") is not None:
                val = f"{r['value']}{r.get('unit', '')}"
                row[y] = val
                vals.append(r["value"])
            else:
                row[y] = f"계산 불가"
        if len(vals) >= 2:
            row["최근 변화"] = f"{vals[-1] - vals[-2]:+.1f}%p" if "비율" in label or label.endswith("률") or label in {"ROA", "ROE"} else f"{vals[-1] - vals[-2]:+.1f}"
        else:
            row["최근 변화"] = "—"
        rows.append(row)
    return pd.DataFrame(rows)


def classify_disclosure(report_nm: str) -> str:
    name = report_nm or ""
    for category, keywords in DISCLOSURE_CATEGORY_RULES:
        if any(kw in name for kw in keywords):
            return category
    return "기타"


def format_disclosure_date(rcept_dt: str) -> str:
    if not rcept_dt or len(rcept_dt) != 8:
        return rcept_dt or "—"
    return f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"


def format_disclosures_display(disclosures: list[dict[str, Any]]) -> pd.DataFrame:
    if not disclosures:
        return pd.DataFrame()
    rows = []
    for d in disclosures:
        row = {}
        for src, label in DISCLOSURE_LABELS.items():
            if src in DISCLOSURE_HIDE:
                continue
            val = d.get(src, "")
            if src == "rcept_dt":
                val = format_disclosure_date(str(val))
            elif src == "rcept_no" and val:
                val = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={val}"
            row[label] = val
        row["분류"] = classify_disclosure(d.get("report_nm", ""))
        rows.append(row)
    return pd.DataFrame(rows)


def build_what_changed(
    financials: pd.DataFrame,
    ratios: dict[str, Any],
    comparison: dict[str, Any] | None,
    disclosures: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    for ch in compute_yoy_changes(financials):
        direction = "증가" if ch["change_pct"] > 0 else "감소"
        lines.append(f"{ch['label']}은(는) 전년 대비 {abs(ch['change_pct'])}% {direction}")
    for ch in compute_ratio_changes(ratios):
        lines.append(f"{ch['label']}은(는) {ch['delta_pp']:+.1f}%p 변화 ({ch['prev_year']}→{ch['curr_year']})")
    if comparison:
        for rid in comparison.get("new_risk_signals", []):
            lines.append(f"신규 위험 신호: {rid}")
        for rid in comparison.get("resolved_risk_signals", []):
            lines.append(f"해소된 위험 신호: {rid}")
        for nd in comparison.get("new_disclosures", []):
            lines.append(f"신규 공시: {nd.get('report_nm', '—')}")
    if disclosures and not comparison:
        lines.append(f"최근 공시 {len(disclosures)}건 확인")
    return lines


def generate_markdown_report(
    company: dict[str, Any],
    analysis_date: str,
    documents: list[str],
    financials: pd.DataFrame,
    ratios: dict[str, Any],
    risk_signals: list[dict[str, Any]],
    cross_checks: list[dict[str, Any]],
    review_memo: dict[str, Any],
    evidence: list[dict[str, Any]],
    what_changed: list[str] | None = None,
) -> str:
    name = company.get("corp_name", "기업")
    sections = (review_memo or {}).get("sections", {})
    lines = [
        f"# {name} 기업검토 보고서",
        "",
        f"**분석 기준일:** {analysis_date}",
        "",
        "## 1. 기업 개요",
        sections.get("1_company_overview", "—"),
        "",
        "## 2. 사용 자료",
        "\n".join(f"- {d}" for d in documents) if documents else "- DART 공시·재무정보",
        "",
        "## 3. 주요 재무 변화",
    ]
    for item in what_changed or build_what_changed(financials, ratios, None, []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## 4. 긍정 요인",
    ])
    pos = sections.get("4_positive_factors", [])
    if isinstance(pos, list):
        lines.extend(f"- {p}" for p in pos)
    else:
        lines.append(str(pos))
    lines.extend(["", "## 5. 위험 신호"])
    if risk_signals:
        for sig in risk_signals:
            lines.append(f"- [{sig.get('severity')}] {sig.get('title')}: {sig.get('description')}")
    else:
        lines.append("- 탐지된 위험 신호 없음")
    lines.extend(["", "## 6. 문서 교차검증"])
    if cross_checks:
        for ck in cross_checks:
            lines.append(f"- [{ck.get('status')}] {ck.get('metric')}: {ck.get('reason', '')}")
    else:
        lines.append("- 교차검증 결과 없음")
    lines.extend([
        "",
        "## 7. 추가 확인사항",
    ])
    follow = sections.get("7_follow_up", [])
    if isinstance(follow, list):
        lines.extend(f"- {f}" for f in follow)
    lines.extend([
        "",
        "## 8. 요청할 추가자료",
    ])
    add_docs = sections.get("8_additional_documents", [])
    if isinstance(add_docs, list):
        lines.extend(f"- {d}" for d in add_docs)
    lines.extend([
        "",
        "## 9. 종합 검토 메모",
        sections.get("10_summary_draft", review_memo.get("summary", "—")),
        "",
        "## 10. 근거 목록",
        f"- 근거 항목 {len(evidence)}건 (상세는 시스템 참조)",
        "",
        "## 11. 면책문구",
        "본 보고서는 대출 승인·거절, 신용등급, 한도 산정, 투자 추천을 의미하지 않으며 심사역 검토 보조용 초안입니다.",
    ])
    return "\n".join(lines)


def report_filename(company: dict[str, Any], analysis_date: str | None = None) -> str:
    name = (company.get("corp_name") or "기업").replace("(주)", "").replace(" ", "")
    d = (analysis_date or date.today().isoformat()).replace("-", "")
    return f"{name}_기업검토_{d}.md"
