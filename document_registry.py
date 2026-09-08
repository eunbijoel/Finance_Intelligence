"""Document registry: SHA-256 hashing, storage, and manifests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR
from database import get_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def uploads_dir() -> Path:
    path = DATA_DIR / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_duplicate(case_id: str, sha256: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE case_id = ? AND sha256 = ? LIMIT 1",
            (case_id, sha256),
        ).fetchone()
    return dict(row) if row else None


def register_document(
    *,
    case_id: str,
    filename: str,
    content: bytes,
    uploaded_by: str | None,
    analysis_id: str | None = None,
    page_count: int | None = None,
    sheet_names: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Save document bytes and register metadata.

    Returns (document_record, is_duplicate).
    """
    sha = compute_sha256(content)
    dup = find_duplicate(case_id, sha)
    if dup:
        return dict(dup), True

    document_id = str(uuid.uuid4())
    ext = Path(filename).suffix.lower()
    storage = uploads_dir() / case_id
    storage.mkdir(parents=True, exist_ok=True)
    storage_path = storage / f"{document_id}{ext}"
    storage_path.write_bytes(content)

    with get_connection() as conn:
        # version = count of same filename + 1
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM documents WHERE case_id = ? AND filename = ?",
            (case_id, filename),
        ).fetchone()
        source_version = int(row["c"] or 0) + 1
        conn.execute(
            """
            INSERT INTO documents (
                document_id, case_id, filename, file_type, file_size, sha256,
                uploaded_by, uploaded_at, analysis_id, source_version,
                storage_path, page_count, sheet_names_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                case_id,
                filename,
                ext.lstrip(".") or None,
                len(content),
                sha,
                uploaded_by,
                _now_iso(),
                analysis_id,
                source_version,
                str(storage_path),
                page_count,
                json.dumps(sheet_names or [], ensure_ascii=False),
            ),
        )
    doc = get_document(document_id)
    return doc or {}, False


def get_document(document_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sheet_names"] = json.loads(d.pop("sheet_names_json") or "[]")
    return d


def list_documents(case_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE case_id = ? ORDER BY uploaded_at DESC",
            (case_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sheet_names"] = json.loads(d.pop("sheet_names_json") or "[]")
        out.append(d)
    return out


def build_manifest(case_id: str) -> list[dict[str, Any]]:
    docs = list_documents(case_id)
    return [
        {
            "document_id": d["document_id"],
            "filename": d["filename"],
            "sha256": d["sha256"],
            "file_size": d["file_size"],
            "source_version": d["source_version"],
            "uploaded_at": d["uploaded_at"],
        }
        for d in docs
    ]
