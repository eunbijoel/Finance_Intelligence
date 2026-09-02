"""Document parsing for business plan review."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

FIELD_PATTERNS: dict[str, list[str]] = {
    "company_overview": ["기업 개요", "회사 개요", "기업소개", "Company Overview"],
    "business_purpose": ["사업 목적", "사업의 목적", "프로젝트 목적"],
    "fund_purpose": ["자금 사용 목적", "자금운용", "조달 자금 용도", "Use of Proceeds"],
    "revenue_outlook": ["매출 전망", "매출계획", "매출 목표", "Revenue Forecast"],
    "cost_outlook": ["비용 전망", "비용계획", "비용 추정"],
    "repayment_plan": ["상환 계획", "상환방안", "상환 재원", "Repayment"],
    "major_customers": ["주요 거래처", "주요 고객", "매출처"],
    "core_capabilities": ["핵심 기술", "사업 역량", "경쟁력", "Core Competency"],
    "risk_factors": ["위험요인", "리스크", "Risk Factors"],
}


def parse_uploaded_file(filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(filename, content)
    if ext == ".docx":
        return _parse_docx(filename, content)
    if ext == ".xlsx":
        return _parse_xlsx(filename, content)
    if ext == ".csv":
        return _parse_csv(filename, content)
    if ext == ".txt":
        return _parse_txt(filename, content)
    return {"filename": filename, "error": f"지원하지 않는 형식: {ext}", "sections": [], "fields": {}}


def extract_business_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """Map parsed sections to structured business plan fields with evidence."""
    fields: dict[str, Any] = {}
    missing: list[str] = []

    for field_key, labels in FIELD_PATTERNS.items():
        match = _find_field(parsed, labels)
        if match:
            fields[field_key] = match
        else:
            missing.append(field_key)
            fields[field_key] = {
                "content": "문서에서 확인되지 않음",
                "evidence": [],
            }

    fields["unverified_items"] = {
        "content": ", ".join(missing) if missing else "없음",
        "evidence": [],
    }
    return fields


def _find_field(parsed: dict[str, Any], labels: list[str]) -> dict[str, Any] | None:
    text_blocks = parsed.get("sections") or []
    full_text = parsed.get("full_text", "")

    for block in text_blocks:
        title = block.get("title", "")
        for label in labels:
            if label.lower() in title.lower() or label.lower() in block.get("text", "").lower()[:80]:
                return {
                    "content": block.get("text", "").strip()[:2000],
                    "evidence": [
                        {
                            "source_file": parsed.get("filename"),
                            "page": block.get("page"),
                            "sheet": block.get("sheet"),
                            "location": block.get("location", "위치 확인 불가"),
                            "excerpt": block.get("text", "")[:300],
                        }
                    ],
                }

    for label in labels:
        pattern = rf"({re.escape(label)}[^\n]{{0,40}}\n)([\s\S]{{20,800}}?)(?=\n[A-Za-z가-힣]{{2,15}}[\s:：]|\Z)"
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            return {
                "content": m.group(0).strip()[:2000],
                "evidence": [
                    {
                        "source_file": parsed.get("filename"),
                        "page": None,
                        "sheet": None,
                        "location": "위치 확인 불가",
                        "excerpt": m.group(0)[:300],
                    }
                ],
            }
    return None


def _parse_pdf(filename: str, content: bytes) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    sections = []
    pages_text = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages_text.append(text)
        for label in _all_labels():
            if label in text:
                idx = text.find(label)
                excerpt = text[idx : idx + 600]
                sections.append(
                    {
                        "title": label,
                        "text": excerpt,
                        "page": i,
                        "sheet": None,
                        "location": f"page {i}",
                    }
                )
    return {
        "filename": filename,
        "sections": sections,
        "full_text": "\n".join(pages_text),
    }


def _parse_docx(filename: str, content: bytes) -> dict[str, Any]:
    from docx import Document

    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)
    sections = []
    for label in _all_labels():
        if label in full_text:
            idx = full_text.find(label)
            sections.append(
                {
                    "title": label,
                    "text": full_text[idx : idx + 600],
                    "page": None,
                    "sheet": None,
                    "location": "위치 확인 불가",
                }
            )
    return {"filename": filename, "sections": sections, "full_text": full_text}


def _parse_xlsx(filename: str, content: bytes) -> dict[str, Any]:
    xls = pd.ExcelFile(io.BytesIO(content))
    sections = []
    full_parts = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=None)
        text = df.astype(str).to_string(index=False)
        full_parts.append(f"[{sheet}]\n{text}")
        for r in range(min(len(df), 50)):
            for c in range(min(len(df.columns), 20)):
                cell = str(df.iat[r, c])
                for label in _all_labels():
                    if label in cell:
                        excerpt_rows = df.iloc[r : r + 5, c : c + 3].astype(str).to_string(index=False)
                        sections.append(
                            {
                                "title": label,
                                "text": excerpt_rows,
                                "page": None,
                                "sheet": sheet,
                                "location": f"row {r+1}, col {c+1}",
                            }
                        )
    return {
        "filename": filename,
        "sections": sections,
        "full_text": "\n\n".join(full_parts),
    }


def _parse_csv(filename: str, content: bytes) -> dict[str, Any]:
    df = pd.read_csv(io.BytesIO(content))
    text = df.astype(str).to_string(index=False)
    sections = []
    for label in _all_labels():
        if label in text:
            sections.append(
                {
                    "title": label,
                    "text": text[:800],
                    "page": None,
                    "sheet": None,
                    "location": "위치 확인 불가",
                }
            )
    return {"filename": filename, "sections": sections, "full_text": text}


def _parse_txt(filename: str, content: bytes) -> dict[str, Any]:
    text = content.decode("utf-8", errors="replace")
    sections = []
    for label in _all_labels():
        if label in text:
            idx = text.find(label)
            sections.append(
                {
                    "title": label,
                    "text": text[idx : idx + 600],
                    "page": None,
                    "sheet": None,
                    "location": "위치 확인 불가",
                }
            )
    return {"filename": filename, "sections": sections, "full_text": text}


def _all_labels() -> list[str]:
    labels: list[str] = []
    for group in FIELD_PATTERNS.values():
        labels.extend(group)
    return labels
