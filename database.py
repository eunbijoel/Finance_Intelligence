"""SQLite persistence for analysis decision memory."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from config import DATA_DIR, DB_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                analysis_date TEXT NOT NULL,
                documents_json TEXT,
                ratios_json TEXT,
                risk_signals_json TEXT,
                review_memo_json TEXT,
                evidence_json TEXT,
                user_edits TEXT,
                approved INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analyses_company
                ON analyses(company_id, created_at DESC);
            """
        )


def save_analysis(record: dict[str, Any]) -> str:
    analysis_id = record.get("analysis_id") or str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO analyses (
                analysis_id, company_id, company_name, analysis_date,
                documents_json, ratios_json, risk_signals_json,
                review_memo_json, evidence_json, user_edits, approved, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                record["company_id"],
                record["company_name"],
                record.get("analysis_date", _now_iso()[:10]),
                json.dumps(record.get("documents", []), ensure_ascii=False),
                json.dumps(record.get("ratios", {}), ensure_ascii=False),
                json.dumps(record.get("risk_signals", []), ensure_ascii=False),
                json.dumps(record.get("review_memo", {}), ensure_ascii=False),
                json.dumps(record.get("evidence", []), ensure_ascii=False),
                record.get("user_edits", ""),
                1 if record.get("approved") else 0,
                record.get("created_at", _now_iso()),
            ),
        )
    return analysis_id


def list_analyses(company_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    query = "SELECT * FROM analyses"
    params: tuple[Any, ...] = ()
    if company_id:
        query += " WHERE company_id = ?"
        params = (company_id,)
    query += " ORDER BY created_at DESC LIMIT ?"
    params = (*params, limit)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_analysis(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_latest_analysis(company_id: str) -> dict[str, Any] | None:
    rows = list_analyses(company_id=company_id, limit=1)
    return rows[0] if rows else None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "analysis_id": row["analysis_id"],
        "company_id": row["company_id"],
        "company_name": row["company_name"],
        "analysis_date": row["analysis_date"],
        "documents": json.loads(row["documents_json"] or "[]"),
        "ratios": json.loads(row["ratios_json"] or "{}"),
        "risk_signals": json.loads(row["risk_signals_json"] or "[]"),
        "review_memo": json.loads(row["review_memo_json"] or "{}"),
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "user_edits": row["user_edits"] or "",
        "approved": bool(row["approved"]),
        "created_at": row["created_at"],
    }
