"""SQLite persistence for completed calls.

The rest of the app still owns business logic; this module only stores and
retrieves completed call/quote records so they survive process restarts.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.quote import Fee, Quote
from app.models.voice import P3QuoteInput, StoredCallArtifact


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_from_url(database_url: str | None = None) -> Path:
    url = database_url or settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("Only sqlite:/// DATABASE_URL values are supported")
    raw_path = url[len(prefix) :]
    path = Path(raw_path)
    return path if path.is_absolute() else Path.cwd() / path


def connect() -> sqlite3.Connection:
    path = _path_from_url()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT UNIQUE,
                conversation_id TEXT UNIQUE,
                job_spec_id TEXT,
                company_id TEXT,
                company_name TEXT,
                company_phone TEXT,
                status TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_seconds REAL,
                transcript_json TEXT,
                transcript_url TEXT,
                recording_url TEXT,
                initial_price REAL,
                negotiated_price REAL,
                negotiation_successful INTEGER NOT NULL DEFAULT 0,
                fees_json TEXT,
                differentiators_json TEXT,
                outcome TEXT,
                red_flag INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(calls)").fetchall()
        }
        if "company_phone" not in columns:
            db.execute("ALTER TABLE calls ADD COLUMN company_phone TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS idx_calls_job_spec_id ON calls(job_spec_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_calls_company_id ON calls(company_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_calls_completed_at ON calls(completed_at)")


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["negotiation_successful"] = bool(payload["negotiation_successful"])
    payload["red_flag"] = bool(payload["red_flag"])
    payload["transcript"] = _loads(payload.pop("transcript_json", None), [])
    payload["fees"] = _loads(payload.pop("fees_json", None), {})
    payload["differentiators"] = _loads(payload.pop("differentiators_json", None), [])
    return payload


def _quote_total(row: dict[str, Any]) -> float | None:
    if row["negotiation_successful"] and row["negotiated_price"] is not None:
        return row["negotiated_price"]
    return row["initial_price"]


def _quote_from_row(row: sqlite3.Row) -> Quote:
    payload = _row_to_dict(row)
    fees = [
        Fee(label=label, amount=float(amount))
        for label, amount in payload["fees"].items()
        if isinstance(amount, (int, float)) and not isinstance(amount, bool)
    ]
    return Quote(
        company_id=payload["company_id"] or "",
        company=payload["company_name"] or "",
        call_id=payload["call_id"] or payload["conversation_id"] or "",
        initial_price=payload["initial_price"],
        negotiated_price=payload["negotiated_price"],
        negotiation_successful=payload["negotiation_successful"],
        total=_quote_total(payload),
        fees=fees,
        differentiators=payload["differentiators"],
        outcome=payload["outcome"] or "declined",
        transcript_url=payload["transcript_url"],
        recording_url=payload["recording_url"],
        red_flag=None,
    )


def upsert_completed_call(
    *,
    job_spec_id: str,
    quote_input: P3QuoteInput,
    company_name: str,
    company_phone: str | None = None,
    artifact: StoredCallArtifact | None = None,
) -> dict[str, Any]:
    initialize_database()
    now = _now()
    conversation_id = artifact.conversation_id if artifact else quote_input.call_id
    metadata = artifact.metadata if artifact else {}
    duration = metadata.get("call_duration_secs") if isinstance(metadata, dict) else None
    started_at = metadata.get("start_time_unix_secs") if isinstance(metadata, dict) else None
    if isinstance(started_at, (int, float)):
        started_at = datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat()
    transcript = [turn.model_dump() for turn in artifact.transcript] if artifact else []

    with connect() as db:
        existing = db.execute(
            "SELECT id, created_at FROM calls WHERE call_id = ? OR conversation_id = ?",
            (quote_input.call_id, conversation_id),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        values = (
            quote_input.call_id,
            conversation_id,
            job_spec_id,
            quote_input.company_id,
            company_name,
            company_phone,
            "completed",
            started_at,
            now,
            duration,
            _json(transcript),
            quote_input.transcript_url,
            quote_input.recording_url,
            quote_input.initial_price,
            quote_input.negotiated_price,
            int(quote_input.negotiation_successful),
            _json(quote_input.fees),
            _json(quote_input.differentiators),
            quote_input.outcome.value,
            int(quote_input.red_flag),
            created_at,
            now,
        )
        if existing:
            db.execute(
                """
                UPDATE calls SET
                    call_id = ?,
                    conversation_id = ?,
                    job_spec_id = ?,
                    company_id = ?,
                    company_name = ?,
                    company_phone = COALESCE(?, company_phone),
                    status = ?,
                    started_at = COALESCE(?, started_at),
                    completed_at = ?,
                    duration_seconds = COALESCE(?, duration_seconds),
                    transcript_json = ?,
                    transcript_url = ?,
                    recording_url = ?,
                    initial_price = ?,
                    negotiated_price = ?,
                    negotiation_successful = ?,
                    fees_json = ?,
                    differentiators_json = ?,
                    outcome = ?,
                    red_flag = ?,
                    created_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (*values, existing["id"]),
            )
        else:
            db.execute(
                """
                INSERT INTO calls (
                    call_id, conversation_id, job_spec_id, company_id, company_name,
                    company_phone, status, started_at, completed_at, duration_seconds, transcript_json,
                    transcript_url, recording_url, initial_price, negotiated_price,
                    negotiation_successful, fees_json, differentiators_json, outcome,
                    red_flag, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        row = db.execute("SELECT * FROM calls WHERE call_id = ?", (quote_input.call_id,)).fetchone()
    return _row_to_dict(row)


def upsert_started_call(
    *,
    call_id: str,
    job_spec_id: str,
    company_id: str,
    company_name: str,
    company_phone: str,
    started_at: str,
) -> dict[str, Any]:
    """Persist an initiated call so the calls page updates before completion."""

    initialize_database()
    now = _now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO calls (
                call_id, conversation_id, job_spec_id, company_id, company_name,
                company_phone, status, started_at, completed_at, duration_seconds,
                transcript_json, transcript_url, recording_url, initial_price,
                negotiated_price, negotiation_successful, fees_json,
                differentiators_json, outcome, red_flag, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL,
                      NULL, 0, ?, ?, NULL, 0, ?, ?)
            ON CONFLICT(call_id) DO UPDATE SET
                job_spec_id = excluded.job_spec_id,
                company_id = excluded.company_id,
                company_name = excluded.company_name,
                company_phone = excluded.company_phone,
                status = excluded.status,
                started_at = excluded.started_at,
                updated_at = excluded.updated_at
            """,
            (
                call_id,
                call_id,
                job_spec_id,
                company_id,
                company_name,
                company_phone,
                "initiated",
                started_at,
                _json([]),
                _json({}),
                _json([]),
                now,
                now,
            ),
        )
        row = db.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    return _row_to_dict(row)


def list_calls(
    *,
    job_spec_id: str | None = None,
    company_id: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
) -> list[dict[str, Any]]:
    initialize_database()
    clauses: list[str] = []
    values: list[Any] = []
    for field, value in (
        ("job_spec_id", job_spec_id),
        ("company_id", company_id),
        ("status", status),
        ("outcome", outcome),
    ):
        if value:
            clauses.append(f"{field} = ?")
            values.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM calls {where} ORDER BY completed_at DESC, updated_at DESC",
            values,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_call(call_id: str) -> dict[str, Any] | None:
    initialize_database()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM calls WHERE call_id = ? OR conversation_id = ?",
            (call_id, call_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_quotes(job_spec_id: str) -> list[Quote]:
    initialize_database()
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM calls WHERE job_spec_id = ? AND initial_price IS NOT NULL",
            (job_spec_id,),
        ).fetchall()
    return [_quote_from_row(row) for row in rows]
