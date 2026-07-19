from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clients.eleven_client import (
    ElevenLabsAuthenticationError,
    ElevenLabsConversationNotFoundError,
    ElevenLabsMalformedResponseError,
    ElevenLabsTimeoutError,
)
from app.config import settings
from app.dependencies.voice import get_elevenlabs_client
from app.main import app
from app.services import telephony
from app.database import get_call
from app.store import call_states, job_specs, leads
from app.models.voice import ConversationStatus, StoredCallArtifact, TranscriptTurn
from tests.conftest import FakeRepository, make_company, make_spec


def test_health_contract(api_client: TestClient) -> None:
    assert api_client.get("/health").json() == {"status": "healthy"}


def test_cors_allows_local_frontend_origin(api_client: TestClient) -> None:
    response = api_client.options(
        "/api/specs",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,ngrok-skip-browser-warning",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "ngrok-skip-browser-warning" in response.headers["access-control-allow-headers"].lower()


def test_cors_rejects_unknown_origin(api_client: TestClient) -> None:
    response = api_client.options(
        "/api/specs",
        headers={
            "Origin": "https://not-the-frontend.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_prepare_succeeds_for_confirmed_spec(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "spec_123", "company_id": "company_123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "agent_xxx"
    assert payload["to_number"] == "+12025550123"
    assert payload["dynamic_variables"]["company_name"] == "Fast Move Logistics"
    assert payload["dynamic_variables"]["move_date"] == "August 8, 2026"


def test_prepare_rejects_unconfirmed_spec(
    api_client: TestClient,
    repository: FakeRepository,
) -> None:
    repository.spec = make_spec(confirmed_by_user=False)
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "spec_123", "company_id": "company_123"},
    )
    assert response.status_code == 400


def test_start_negotiating_passes_public_wss_url_to_twilio(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = make_spec(job_spec_id="spec_public_url")
    company = make_company(company_id="company_public_url")
    job_specs[spec.job_spec_id] = spec
    leads[spec.job_spec_id] = [company]
    captured_urls: list[str] = []

    monkeypatch.setattr(telephony, "is_within_working_hours", lambda lead: True)

    def fake_initiate_call(lead, stream_webhook_url: str) -> str:
        captured_urls.append(stream_webhook_url)
        return "CA123"

    monkeypatch.setattr(telephony, "initiate_call", fake_initiate_call)

    try:
        response = api_client.post(
            f"/api/calls/start-negotiating/{spec.job_spec_id}",
            params={"stream_webhook_base_url": "https://5a0b.ngrok-free.app/"},
        )
    finally:
        job_specs.pop(spec.job_spec_id, None)
        leads.pop(spec.job_spec_id, None)

    assert response.status_code == 200
    assert captured_urls == [
        "https://5a0b.ngrok-free.app/api/calls/stream/company_public_url"
        "?wss_url=wss%3A%2F%2F5a0b.ngrok-free.app"
    ]


def test_start_test_call_skips_discovery_and_persists_initiated_call(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec(job_spec_id="spec_test_outbound")
    job_specs[spec.job_spec_id] = spec
    previous_database = settings.database_url
    settings.database_url = f"sqlite:///{(tmp_path / 'calls.db').as_posix()}"
    captured: dict[str, str] = {}

    def fake_initiate_call(lead, stream_webhook_url: str) -> str:
        captured["phone"] = lead.phone_number
        captured["url"] = stream_webhook_url
        return "CA_TEST_123"

    monkeypatch.setattr(telephony, "initiate_call", fake_initiate_call)
    try:
        response = api_client.post(f"/api/calls/start-test/{spec.job_spec_id}")
        stored = get_call("CA_TEST_123")
    finally:
        settings.database_url = previous_database
        job_specs.pop(spec.job_spec_id, None)
        leads.pop(spec.job_spec_id, None)
        call_states.pop(spec.job_spec_id, None)

    assert response.status_code == 200
    payload = response.json()
    assert captured["phone"] == "+212610833077"
    assert captured["url"].endswith(
        "/api/calls/elevenlabs-register/spec_test_outbound/test_moving_company"
    )
    assert payload["prepared_call"]["dynamic_variables"]["origin_address"] == spec.origin_address
    assert stored is not None
    assert stored["status"] == "initiated"
    assert stored["company_name"] == "Test Moving Company"
    assert stored["company_phone"] == "+212610833077"


def test_start_test_call_rejects_unconfirmed_spec(
    api_client: TestClient,
) -> None:
    spec = make_spec(job_spec_id="spec_unconfirmed_test", confirmed_by_user=False)
    job_specs[spec.job_spec_id] = spec
    try:
        response = api_client.post(f"/api/calls/start-test/{spec.job_spec_id}")
    finally:
        job_specs.pop(spec.job_spec_id, None)
    assert response.status_code == 400


def test_call_statuses_return_backend_states(api_client: TestClient) -> None:
    spec = make_spec(job_spec_id="spec_status")
    company = make_company(company_id="company_status")
    job_specs[spec.job_spec_id] = spec
    leads[spec.job_spec_id] = [company]
    call_states[spec.job_spec_id] = {
        company.company_id: {
            "state": "initiated",
            "started_at": "2026-07-19T00:00:00+00:00",
            "call_sid": "CA123",
        }
    }
    try:
        response = api_client.get(f"/api/calls/status/{spec.job_spec_id}")
    finally:
        job_specs.pop(spec.job_spec_id, None)
        leads.pop(spec.job_spec_id, None)
        call_states.pop(spec.job_spec_id, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["calls"][0]["company_name"] == company.name
    assert payload["calls"][0]["phone_number"] == company.phone_number
    assert payload["calls"][0]["state"] == "initiated"
    assert payload["calls"][0]["call_sid"] == "CA123"


def test_prepare_missing_spec_returns_404(
    api_client: TestClient,
    repository: FakeRepository,
) -> None:
    repository.spec = None
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "missing", "company_id": "company_123"},
    )
    assert response.status_code == 404


def test_prepare_missing_company_returns_404(
    api_client: TestClient,
    repository: FakeRepository,
) -> None:
    repository.company = None
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "spec_123", "company_id": "missing"},
    )
    assert response.status_code == 404


def test_prepare_fails_clearly_when_caller_agent_id_is_missing(
    api_client: TestClient,
) -> None:
    settings.elevenlabs_caller_agent_id = ""
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "spec_123", "company_id": "company_123"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "ELEVENLABS_CALLER_AGENT_ID is required"


@pytest.mark.parametrize(
    "phone", [None, "202-555-0123", "+0123456789", "+1 202 555 0123"]
)
def test_prepare_rejects_missing_or_invalid_phone(
    api_client: TestClient,
    repository: FakeRepository,
    phone: str | None,
) -> None:
    repository.company = make_company(phone_number=phone)
    response = api_client.post(
        "/api/calls/prepare",
        json={"job_spec_id": "spec_123", "company_id": "company_123"},
    )
    assert response.status_code == 422


class ConversationClient:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def get_conversation(self, conversation_id: str):
        if self.error:
            raise self.error
        return self.payload

    async def get_conversation_audio(
        self, conversation_id: str
    ) -> AsyncIterator[bytes]:
        yield b"audio"

    async def register_twilio_call(self, **kwargs) -> str:
        self.register_payload = kwargs
        return "<Response><Connect /></Response>"


def override_conversation_client(client: ConversationClient) -> None:
    app.dependency_overrides[get_elevenlabs_client] = lambda: client


def test_conversation_endpoint_returns_normalized_result(
    api_client: TestClient,
) -> None:
    override_conversation_client(
        ConversationClient(
            {
                "conversation_id": "conv_123",
                "status": "done",
                "has_audio": True,
                "metadata": {"call_duration_secs": 42, "cost_fiat": 9.99},
                "transcript": [
                    {"role": "agent", "message": "Hello", "time_in_call_secs": 0}
                ],
                "analysis": {
                    "transcript_summary": "A quote was collected.",
                    "data_collection_results": {
                        "initial_price": {"value": "$2,000"},
                        "call_outcome": {"value": "quote"},
                    },
                },
            }
        )
    )
    response = api_client.get("/api/calls/conversations/conv_123")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["call_duration_seconds"] == 42
    assert "cost_fiat" not in payload["metadata"]
    assert payload["collected_data"]["initial_price"] == 2000
    assert payload["recording_url"].endswith("/api/results/calls/conv_123/recording")


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ElevenLabsAuthenticationError(), 502),
        (ElevenLabsConversationNotFoundError(), 404),
        (ElevenLabsTimeoutError(), 504),
        (ElevenLabsMalformedResponseError(), 502),
    ],
)
def test_conversation_errors_map_safely(
    api_client: TestClient,
    error: Exception,
    status: int,
) -> None:
    override_conversation_client(ConversationClient(error=error))
    response = api_client.get("/api/calls/conversations/conv_123")
    assert response.status_code == status
    assert "api_key" not in response.text.lower()


def test_transcript_endpoint_returns_404_when_missing(api_client: TestClient) -> None:
    assert api_client.get("/api/results/calls/missing/transcript").status_code == 404


def test_recording_endpoint_returns_404_when_missing(api_client: TestClient) -> None:
    assert api_client.get("/api/results/calls/missing/recording").status_code == 404


def test_transcript_and_recording_handoffs(
    api_client: TestClient,
    repository: FakeRepository,
) -> None:
    repository.save_artifact(
        StoredCallArtifact(
            call_id="call_123",
            conversation_id="conv_123",
            status=ConversationStatus.COMPLETED,
            transcript=[TranscriptTurn(role="agent", message="Hello")],
            has_recording=True,
        )
    )
    override_conversation_client(
        ConversationClient(
            {"conversation_id": "conv_123", "status": "done", "has_audio": True}
        )
    )
    transcript = api_client.get("/api/results/calls/call_123/transcript")
    recording = api_client.get("/api/results/calls/call_123/recording")
    assert transcript.status_code == 200
    assert transcript.json()["transcript"][0]["message"] == "Hello"
    assert recording.status_code == 200
    assert recording.headers["content-type"].startswith("audio/mpeg")
    assert recording.content == b"audio"
