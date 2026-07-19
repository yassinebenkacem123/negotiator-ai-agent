from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.database import connect, initialize_database, upsert_completed_call
from app.main import app
from app.models.voice import P3CallOutcome, P3QuoteInput, StoredCallArtifact, TranscriptTurn


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_sqlite_table_creation(tmp_path: Path) -> None:
    previous = settings.database_url
    settings.database_url = sqlite_url(tmp_path / "negotiator.db")
    try:
        initialize_database()
        with connect() as db:
            row = db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'calls'"
            ).fetchone()
        assert row is not None
    finally:
        settings.database_url = previous


def test_completed_call_upsert_is_idempotent(tmp_path: Path) -> None:
    previous = settings.database_url
    settings.database_url = sqlite_url(tmp_path / "negotiator.db")
    quote = P3QuoteInput(
        company_id="company_123",
        call_id="call_123",
        initial_price=2000,
        negotiated_price=1850,
        negotiation_successful=True,
        fees={"fuel": 50},
        differentiators=["insured"],
        outcome=P3CallOutcome.QUOTE,
        transcript_url="http://test/transcript",
        recording_url="http://test/recording",
    )
    artifact = StoredCallArtifact(
        call_id="call_123",
        conversation_id="conv_123",
        transcript=[TranscriptTurn(role="agent", message="Hello")],
        metadata={"call_duration_secs": 12},
        has_recording=True,
    )
    try:
        first = upsert_completed_call(
            job_spec_id="spec_123",
            quote_input=quote,
            company_name="Fast Move Logistics",
            company_phone="+12025550123",
            artifact=artifact,
        )
        quote.negotiated_price = 1800
        second = upsert_completed_call(
            job_spec_id="spec_123",
            quote_input=quote,
            company_name="Fast Move Logistics",
            artifact=artifact,
        )
        with connect() as db:
            count = db.execute("SELECT COUNT(*) AS count FROM calls").fetchone()["count"]
        assert count == 1
        assert first["conversation_id"] == "conv_123"
        assert second["negotiated_price"] == 1800
        assert second["transcript"][0]["message"] == "Hello"
        assert second["company_phone"] == "+12025550123"
    finally:
        settings.database_url = previous


def test_completed_call_upsert_matches_existing_conversation_id(tmp_path: Path) -> None:
    previous = settings.database_url
    settings.database_url = sqlite_url(tmp_path / "negotiator.db")
    first = P3QuoteInput(
        company_id="company_123",
        call_id="temporary_call_id",
        initial_price=2000,
        negotiated_price=1850,
        negotiation_successful=True,
        fees={},
        differentiators=[],
        outcome=P3CallOutcome.QUOTE,
    )
    second = P3QuoteInput(
        company_id="company_123",
        call_id="canonical_call_id",
        initial_price=2000,
        negotiated_price=1750,
        negotiation_successful=True,
        fees={},
        differentiators=[],
        outcome=P3CallOutcome.QUOTE,
    )
    artifact = StoredCallArtifact(
        call_id="canonical_call_id",
        conversation_id="conv_123",
        transcript=[TranscriptTurn(role="agent", message="Updated transcript")],
    )
    try:
        upsert_completed_call(
            job_spec_id="spec_123",
            quote_input=first,
            company_name="Fast Move Logistics",
            artifact=artifact,
        )
        stored = upsert_completed_call(
            job_spec_id="spec_123",
            quote_input=second,
            company_name="Fast Move Logistics",
            artifact=artifact,
        )
        with connect() as db:
            count = db.execute("SELECT COUNT(*) AS count FROM calls").fetchone()["count"]
        assert count == 1
        assert stored["call_id"] == "canonical_call_id"
        assert stored["conversation_id"] == "conv_123"
        assert stored["negotiated_price"] == 1750
    finally:
        settings.database_url = previous


def test_calls_api_and_report_read_persisted_calls(tmp_path: Path) -> None:
    previous = settings.database_url
    settings.database_url = sqlite_url(tmp_path / "negotiator.db")
    quote = P3QuoteInput(
        company_id="company_123",
        call_id="call_123",
        initial_price=2000,
        negotiated_price=1850,
        negotiation_successful=True,
        fees={"fuel": 50},
        differentiators=["insured"],
        outcome=P3CallOutcome.QUOTE,
        transcript_url="http://test/transcript",
        recording_url="http://test/recording",
    )
    try:
        upsert_completed_call(
            job_spec_id="spec_123",
            quote_input=quote,
            company_name="Fast Move Logistics",
            artifact=StoredCallArtifact(
                call_id="call_123",
                conversation_id="conv_123",
                transcript=[TranscriptTurn(role="user", message="Can I get a quote?")],
            ),
        )
        with TestClient(app) as client:
            calls = client.get("/api/calls", params={"job_spec_id": "spec_123"})
            detail = client.get("/api/calls/call_123")
            report = client.get("/api/results/spec_123")
        assert calls.status_code == 200
        assert calls.json()["calls"][0]["company_name"] == "Fast Move Logistics"
        assert detail.status_code == 200
        assert detail.json()["transcript"][0]["message"] == "Can I get a quote?"
        assert report.status_code == 200
        ranked = report.json()["ranked_companies"][0]
        assert ranked["company_id"] == "company_123"
        assert ranked["final_price"] == 1850
    finally:
        settings.database_url = previous
