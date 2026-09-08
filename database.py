"""SQLite persistence: analyses, cases, users, documents, comments, audit logs."""

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


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _table_columns(conn, table)
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


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

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_cases (
                case_id TEXT PRIMARY KEY,
                case_number TEXT NOT NULL UNIQUE,
                company_id TEXT,
                company_name TEXT NOT NULL,
                stock_code TEXT,
                application_amount REAL,
                fund_purpose TEXT,
                loan_product TEXT,
                application_date TEXT,
                due_date TEXT,
                priority TEXT DEFAULT 'NORMAL',
                status TEXT NOT NULL,
                maker_id TEXT,
                checker_id TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                current_analysis_id TEXT,
                version INTEGER DEFAULT 1,
                closed_at TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_cases_status ON review_cases(status);
            CREATE INDEX IF NOT EXISTS idx_cases_maker ON review_cases(maker_id);
            CREATE INDEX IF NOT EXISTS idx_cases_checker ON review_cases(checker_id);

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                case_id TEXT,
                filename TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER,
                sha256 TEXT NOT NULL,
                uploaded_by TEXT,
                uploaded_at TEXT NOT NULL,
                analysis_id TEXT,
                source_version INTEGER DEFAULT 1,
                storage_path TEXT,
                page_count INTEGER,
                sheet_names_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_docs_case ON documents(case_id);
            CREATE INDEX IF NOT EXISTS idx_docs_hash ON documents(case_id, sha256);

            CREATE TABLE IF NOT EXISTS review_comments (
                comment_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                analysis_id TEXT,
                author_id TEXT,
                author_role TEXT,
                comment_type TEXT,
                original_text TEXT,
                revised_text TEXT,
                comment TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_case ON review_comments(case_id);

            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id TEXT PRIMARY KEY,
                case_id TEXT,
                analysis_id TEXT,
                actor_id TEXT,
                actor_role TEXT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                before_json TEXT,
                after_json TEXT,
                reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_logs(case_id, created_at DESC);
            """
        )
        _ensure_columns(
            conn,
            "analyses",
            {
                "case_id": "TEXT",
                "analysis_version": "INTEGER DEFAULT 1",
                "created_by": "TEXT",
                "model_provider": "TEXT",
                "model_name": "TEXT",
                "prompt_version": "TEXT",
                "rule_version": "TEXT",
                "workflow_version": "TEXT",
                "input_snapshot_json": "TEXT",
                "document_manifest_json": "TEXT",
                "ai_memo_original": "TEXT",
                "maker_memo_revised": "TEXT",
                "prompt_hash": "TEXT",
            },
        )
        _seed_users(conn)


def _seed_users(conn: sqlite3.Connection) -> None:
    seeds = [
        ("maker01", "김심사", "MAKER"),
        ("maker02", "이담당", "MAKER"),
        ("checker01", "박책임", "CHECKER"),
        ("admin01", "관리자", "ADMIN"),
    ]
    now = _now_iso()
    for user_id, name, role in seeds:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (user_id, display_name, role, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (user_id, name, role, now),
        )


def list_users(active_only: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM users"
    if active_only:
        q += " WHERE active = 1"
    q += " ORDER BY role, user_id"
    with get_connection() as conn:
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def get_user(user_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def save_analysis(record: dict[str, Any]) -> str:
    analysis_id = record.get("analysis_id") or str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO analyses (
                analysis_id, company_id, company_name, analysis_date,
                documents_json, ratios_json, risk_signals_json,
                review_memo_json, evidence_json, user_edits, approved, created_at,
                case_id, analysis_version, created_by, model_provider, model_name,
                prompt_version, rule_version, workflow_version,
                input_snapshot_json, document_manifest_json,
                ai_memo_original, maker_memo_revised, prompt_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                record.get("case_id"),
                record.get("analysis_version", 1),
                record.get("created_by"),
                record.get("model_provider"),
                record.get("model_name"),
                record.get("prompt_version"),
                record.get("rule_version"),
                record.get("workflow_version"),
                json.dumps(record.get("input_snapshot") or {}, ensure_ascii=False),
                json.dumps(record.get("document_manifest") or [], ensure_ascii=False),
                record.get("ai_memo_original"),
                record.get("maker_memo_revised"),
                record.get("prompt_hash"),
            ),
        )
    return analysis_id


def list_analyses(
    company_id: str | None = None,
    case_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM analyses WHERE 1=1"
    params: list[Any] = []
    if company_id:
        query += " AND company_id = ?"
        params.append(company_id)
    if case_id:
        query += " AND case_id = ?"
        params.append(case_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
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


def get_latest_analysis_for_case(case_id: str) -> dict[str, Any] | None:
    rows = list_analyses(case_id=case_id, limit=1)
    return rows[0] if rows else None


def next_analysis_version(case_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(analysis_version), 0) AS m FROM analyses WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    return int(row["m"] or 0) + 1


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    result = {
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
    for opt in (
        "case_id",
        "analysis_version",
        "created_by",
        "model_provider",
        "model_name",
        "prompt_version",
        "rule_version",
        "workflow_version",
        "ai_memo_original",
        "maker_memo_revised",
        "prompt_hash",
    ):
        if opt in keys:
            result[opt] = row[opt]
    if "input_snapshot_json" in keys:
        result["input_snapshot"] = json.loads(row["input_snapshot_json"] or "{}")
    if "document_manifest_json" in keys:
        result["document_manifest"] = json.loads(row["document_manifest_json"] or "[]")
    return result
