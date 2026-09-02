"""OpenDART API client with mock/sample fallback."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pandas as pd
import requests

from config import DART_API_KEY, USE_DART_MOCK

DART_BASE = "https://opendart.fss.or.kr/api"

# Sample company profile (Samsung Electronics — public identifiers, illustrative financials)
SAMPLE_COMPANY = {
    "corp_code": "00126380",
    "corp_name": "삼성전자(주)",
    "stock_code": "005930",
    "corp_cls": "Y",
    "industry": "반도체·전자부품 제조업",
    "modify_date": "20250101",
}

SAMPLE_FINANCIALS = [
    {
        "year": 2022,
        "revenue": 302_231_000_000_000,
        "operating_income": 43_376_000_000_000,
        "net_income": 55_654_000_000_000,
        "total_assets": 448_424_000_000_000,
        "total_liabilities": 93_679_000_000_000,
        "total_equity": 354_745_000_000_000,
        "operating_cash_flow": 62_069_000_000_000,
        "current_assets": 218_470_000_000_000,
        "current_liabilities": 78_344_000_000_000,
        "short_term_borrowings": 8_000_000_000_000,
        "accounts_receivable": 36_000_000_000_000,
    },
    {
        "year": 2023,
        "revenue": 258_935_000_000_000,
        "operating_income": 6_567_000_000_000,
        "net_income": 15_487_000_000_000,
        "total_assets": 455_906_000_000_000,
        "total_liabilities": 92_228_000_000_000,
        "total_equity": 363_678_000_000_000,
        "operating_cash_flow": 41_082_000_000_000,
        "current_assets": 195_937_000_000_000,
        "current_liabilities": 75_719_000_000_000,
        "short_term_borrowings": 10_500_000_000_000,
        "accounts_receivable": 38_500_000_000_000,
    },
    {
        "year": 2024,
        "revenue": 300_870_000_000_000,
        "operating_income": 32_726_000_000_000,
        "net_income": 34_451_000_000_000,
        "total_assets": 514_531_000_000_000,
        "total_liabilities": 112_340_000_000_000,
        "total_equity": 402_191_000_000_000,
        "operating_cash_flow": 51_947_000_000_000,
        "current_assets": 227_062_000_000_000,
        "current_liabilities": 93_326_000_000_000,
        "short_term_borrowings": 15_200_000_000_000,
        "accounts_receivable": 45_000_000_000_000,
    },
]

SAMPLE_DISCLOSURES = [
    {
        "rcept_no": "20250315000001",
        "report_nm": "사업보고서 (2024.12)",
        "rcept_dt": "20250315",
        "flr_nm": "삼성전자",
    },
    {
        "rcept_no": "20250201000002",
        "report_nm": "분기보고서 (2024.09)",
        "rcept_dt": "20250201",
        "flr_nm": "삼성전자",
    },
    {
        "rcept_no": "20241115000003",
        "report_nm": "주요사항보고서(자기주식취득)",
        "rcept_dt": "20241115",
        "flr_nm": "삼성전자",
    },
]


class DartClient:
    def __init__(self, api_key: str | None = None, use_mock: bool | None = None) -> None:
        self.api_key = (api_key or DART_API_KEY).strip()
        self.use_mock = USE_DART_MOCK if use_mock is None else use_mock
        self._corp_index: list[dict[str, str]] | None = None

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.use_mock:
            return {"status": "000", "message": "mock"}
        params = {**params, "crtfc_key": self.api_key}
        resp = requests.get(f"{DART_BASE}/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _load_corp_index(self) -> list[dict[str, str]]:
        if self._corp_index is not None:
            return self._corp_index
        if self.use_mock:
            self._corp_index = [SAMPLE_COMPANY]
            return self._corp_index
        # corpCode.xml returns a ZIP archive, not JSON
        resp = requests.get(
            f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": self.api_key},
            timeout=120,
        )
        resp.raise_for_status()
        if resp.headers.get("Content-Type", "").startswith("application/json"):
            err = resp.json()
            self._corp_index = []
            return self._corp_index
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            xml_name = [n for n in zf.namelist() if n.endswith(".xml")][0]
            xml_text = zf.read(xml_name).decode("utf-8")
        import re

        corps = []
        for block in re.findall(r"<list>(.*?)</list>", xml_text, re.DOTALL):
            item = {}
            for tag in ("corp_code", "corp_name", "stock_code", "modify_date"):
                m = re.search(rf"<{tag}>(.*?)</{tag}>", block)
                if m:
                    item[tag] = m.group(1).strip()
            if item:
                corps.append(item)
        self._corp_index = corps
        return corps

    def search_company(self, query: str) -> dict[str, Any] | None:
        query = (query or "").strip()
        if not query:
            return None
        if self.use_mock:
            q = query.lower()
            if q in {"005930", "삼성", "삼성전자", "samsung"}:
                return {**SAMPLE_COMPANY, "source": "mock"}
            return None
        corps = self._load_corp_index()
        if not corps:
            return None
        stock_query = query.zfill(6) if query.isdigit() else query
        # exact stock code
        for c in corps:
            code = (c.get("stock_code") or "").strip()
            if code and code == stock_query:
                return {**c, "source": "dart"}
        # name contains
        for c in corps:
            if query in c.get("corp_name", ""):
                return {**c, "source": "dart"}
        return None

    def get_financials(self, corp_code: str, years: int = 3) -> pd.DataFrame:
        if self.use_mock:
            rows = SAMPLE_FINANCIALS[-years:]
            return pd.DataFrame(rows)
        # Simplified: fetch single consolidated statements for recent years
        frames = []
        from datetime import datetime

        current_year = datetime.now().year
        for year in range(current_year - years, current_year):
            for reprt_code in ("11011",):  # annual only for MVP
                data = self._get(
                    "fnlttSinglAcntAll.json",
                    {
                        "corp_code": corp_code,
                        "bsns_year": str(year),
                        "reprt_code": reprt_code,
                        "fs_div": "CFS",
                    },
                )
                if data.get("status") != "000":
                    continue
                rows = data.get("list") or []
                parsed = _parse_dart_accounts(rows, year)
                if parsed:
                    frames.append(parsed)
                break
        if not frames:
            return pd.DataFrame()
        return pd.DataFrame(frames).sort_values("year")

    def get_recent_disclosures(self, corp_code: str, count: int = 5) -> list[dict[str, Any]]:
        if self.use_mock:
            return SAMPLE_DISCLOSURES[:count]
        end_de = "20251231"
        begin_de = "20240101"
        data = self._get(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": begin_de,
                "end_de": end_de,
                "page_count": count,
            },
        )
        if data.get("status") != "000":
            return []
        return data.get("list") or []


def _parse_dart_accounts(rows: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    mapping = {
        "매출액": "revenue",
        "영업이익": "operating_income",
        "당기순이익": "net_income",
        "자산총계": "total_assets",
        "부채총계": "total_liabilities",
        "자본총계": "total_equity",
        "영업활동현금흐름": "operating_cash_flow",
        "유동자산": "current_assets",
        "유동부채": "current_liabilities",
        "단기차입금": "short_term_borrowings",
        "매출채권": "accounts_receivable",
    }
    result: dict[str, Any] = {"year": year}
    for row in rows:
        name = (row.get("account_nm") or "").replace(" ", "")
        for key, field in mapping.items():
            if key in name and field not in result:
                try:
                    result[field] = int(str(row.get("thstrm_amount", "0")).replace(",", ""))
                except ValueError:
                    pass
    if "revenue" not in result and "total_assets" not in result:
        return None
    return result
