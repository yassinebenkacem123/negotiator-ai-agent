from collections.abc import AsyncIterator

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
from app.models.voice import ConversationStatus, StoredCallArtifact, TranscriptTurn
from tests.conftest import FakeRepository, make_company, make_spec


def test_health_contract(api_client: TestClient) -> None:
    assert api_client.get("/health").json() == {"status": "healthy"}


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
