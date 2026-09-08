"""Append-only audit log service (no update/delete APIs)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_audit(
    *,
    action: str,
    actor_id: str | None = None,
    actor_role: str | None = None,
    case_id: str | None = None,
    analysis_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> str:
    audit_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (
                audit_id, case_id, analysis_id, actor_id, actor_role, action,
                entity_type, entity_id, before_json, after_json, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                case_id,
                analysis_id,
                actor_id,
                actor_role,
                action,
                entity_type,
                entity_id,
                json.dumps(before or {}, ensure_ascii=False) if before is not None else None,
                json.dumps(after or {}, ensure_ascii=False) if after is not None else None,
                reason,
                _now_iso(),
            ),
        )
    return audit_id


def list_audit_logs(case_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    q = "SELECT * FROM audit_logs"
    params: list[Any] = []
    if case_id:
        q += " WHERE case_id = ?"
        params.append(case_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "audit_id": r["audit_id"],
                "case_id": r["case_id"],
                "analysis_id": r["analysis_id"],
                "actor_id": r["actor_id"],
                "actor_role": r["actor_role"],
                "action": r["action"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "before": json.loads(r["before_json"] or "{}") if r["before_json"] else None,
                "after": json.loads(r["after_json"] or "{}") if r["after_json"] else None,
                "reason": r["reason"],
                "created_at": r["created_at"],
            }
        )
    return out
