"""Neon Postgres persistence with a SQLite backend retained for tests."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.quote import Fee, Quote
from app.models.voice import P3QuoteInput, StoredCallArtifact

_initialized_database_urls: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_url(database_url: str | None = None) -> str:
    url = database_url or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def _is_postgres(database_url: str | None = None) -> bool:
    return _database_url(database_url).startswith(("postgresql://", "postgres://"))


def _path_from_url(database_url: str | None = None) -> Path:
    url = _database_url(database_url)
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("DATABASE_URL must use postgresql://, postgres://, or sqlite:///")
    raw_path = url[len(prefix) :]
    path = Path(raw_path)
    return path if path.is_absolute() else Path.cwd() / path


def connect():
    if _is_postgres():
        from psycopg import connect as postgres_connect
        from psycopg.rows import dict_row

        return postgres_connect(
            _database_url(),
            row_factory=dict_row,
            connect_timeout=10,
        )

    path = _path_from_url()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _sql(statement: str) -> str:
    """Translate the project's DB-API placeholders for Psycopg."""

    return statement.replace("?", "%s") if _is_postgres() else statement


def _execute(db, statement: str, values: tuple | list = ()):
    return db.execute(_sql(statement), values)


def initialize_database() -> None:
    database_url = _database_url()
    if database_url in _initialized_database_urls:
        return
    with connect() as db:
        id_definition = "BIGSERIAL PRIMARY KEY" if _is_postgres() else "INTEGER PRIMARY KEY AUTOINCREMENT"
        _execute(
            db,
            f"""
            CREATE TABLE IF NOT EXISTS calls (
                id {id_definition},
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
        if _is_postgres():
            _execute(db, "ALTER TABLE calls ADD COLUMN IF NOT EXISTS company_phone TEXT")
        else:
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(calls)").fetchall()
            }
            if "company_phone" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN company_phone TEXT")
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_calls_job_spec_id ON calls(job_spec_id)")
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_calls_company_id ON calls(company_id)")
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status)")
        _execute(db, "CREATE INDEX IF NOT EXISTS idx_calls_completed_at ON calls(completed_at)")
        _execute(
            db,
            """
            CREATE TABLE IF NOT EXISTS app_state (
                namespace TEXT NOT NULL,
                state_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (namespace, state_key)
            )
            """,
        )
        _execute(
            db,
            """
            CREATE TABLE IF NOT EXISTS processed_webhook_events (
                event_key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """,
        )
    _initialized_database_urls.add(database_url)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def _loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _row_to_dict(row: Mapping[str, Any]) -> dict[str, Any]:
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


def _quote_from_row(row: Mapping[str, Any]) -> Quote:
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
        existing = _execute(
            db,
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
            _execute(
                db,
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
            _execute(
                db,
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
        row = _execute(
            db,
            "SELECT * FROM calls WHERE call_id = ?",
            (quote_input.call_id,),
        ).fetchone()
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
        _execute(
            db,
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
        row = _execute(
            db,
            "SELECT * FROM calls WHERE call_id = ?",
            (call_id,),
        ).fetchone()
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
        rows = _execute(
            db,
            f"SELECT * FROM calls {where} ORDER BY completed_at DESC, updated_at DESC",
            values,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_call(call_id: str) -> dict[str, Any] | None:
    initialize_database()
    with connect() as db:
        row = _execute(
            db,
            "SELECT * FROM calls WHERE call_id = ? OR conversation_id = ?",
            (call_id, call_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_quotes(job_spec_id: str) -> list[Quote]:
    initialize_database()
    with connect() as db:
        rows = _execute(
            db,
            "SELECT * FROM calls WHERE job_spec_id = ? AND initial_price IS NOT NULL",
            (job_spec_id,),
        ).fetchall()
    return [_quote_from_row(row) for row in rows]


def get_state(namespace: str, key: str) -> Any | None:
    initialize_database()
    with connect() as db:
        row = _execute(
            db,
            "SELECT value_json FROM app_state WHERE namespace = ? AND state_key = ?",
            (namespace, key),
        ).fetchone()
    return _loads(row["value_json"], None) if row else None


def set_state(namespace: str, key: str, value: Any) -> None:
    initialize_database()
    with connect() as db:
        _execute(
            db,
            """
            INSERT INTO app_state (namespace, state_key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, state_key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (namespace, key, _json(value), _now()),
        )


def delete_state(namespace: str, key: str) -> None:
    initialize_database()
    with connect() as db:
        _execute(
            db,
            "DELETE FROM app_state WHERE namespace = ? AND state_key = ?",
            (namespace, key),
        )


def list_state(namespace: str) -> dict[str, Any]:
    initialize_database()
    with connect() as db:
        rows = _execute(
            db,
            "SELECT state_key, value_json FROM app_state WHERE namespace = ?",
            (namespace,),
        ).fetchall()
    return {row["state_key"]: _loads(row["value_json"], None) for row in rows}


def claim_webhook_event(event_key: str) -> bool:
    initialize_database()
    with connect() as db:
        if _is_postgres():
            row = _execute(
                db,
                """
                INSERT INTO processed_webhook_events (event_key, created_at)
                VALUES (?, ?)
                ON CONFLICT(event_key) DO NOTHING
                RETURNING event_key
                """,
                (event_key, _now()),
            ).fetchone()
            return row is not None
        cursor = _execute(
            db,
            "INSERT OR IGNORE INTO processed_webhook_events (event_key, created_at) VALUES (?, ?)",
            (event_key, _now()),
        )
        return cursor.rowcount == 1


def webhook_event_exists(event_key: str) -> bool:
    initialize_database()
    with connect() as db:
        row = _execute(
            db,
            "SELECT event_key FROM processed_webhook_events WHERE event_key = ?",
            (event_key,),
        ).fetchone()
    return row is not None


def release_webhook_event(event_key: str) -> None:
    initialize_database()
    with connect() as db:
        _execute(
            db,
            "DELETE FROM processed_webhook_events WHERE event_key = ?",
            (event_key,),
        )


def list_webhook_events() -> list[str]:
    initialize_database()
    with connect() as db:
        rows = _execute(
            db,
            "SELECT event_key FROM processed_webhook_events ORDER BY created_at",
        ).fetchall()
    return [row["event_key"] for row in rows]


def check_database_connection() -> str:
    """Execute a real query and return the active database backend name."""

    initialize_database()
    with connect() as db:
        row = _execute(db, "SELECT 1 AS ok").fetchone()
    if not row or row["ok"] != 1:
        raise RuntimeError("Database health check returned an unexpected result")
    return "postgresql" if _is_postgres() else "sqlite"
