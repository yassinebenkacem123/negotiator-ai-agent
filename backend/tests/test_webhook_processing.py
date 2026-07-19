import json

from fastapi.testclient import TestClient

from app.clients.eleven_client import InvalidWebhookSignatureError
from app.dependencies.voice import get_webhook_verifier
from app.main import app
from app.models.voice import P3CallOutcome
from tests.conftest import FakeRepository, FakeSink


def transcription_event() -> dict:
    return {
        "type": "post_call_transcription",
        "event_timestamp": 100,
        "data": {
            "conversation_id": "conv_123",
            "status": "done",
            "has_audio": True,
            "transcript": [{"role": "agent", "message": "Hello"}],
            "metadata": {"call_sid": "CA123", "call_duration_secs": 12},
            "conversation_initiation_client_data": {
                "dynamic_variables": {
                    "job_spec_id": "spec_123",
                    "company_id": "company_123",
                }
            },
            "analysis": {
                "data_collection_results": {
                    "initial_price": {"value": "$2,000"},
                    "negotiated_price": {"value": "$1,850"},
                    "additional_fees": {"value": {"fuel": "$50"}},
                    "call_outcome": {"value": "quote"},
                }
            },
        },
    }


def test_transcription_webhook_is_normalized_and_handed_to_p3(
    api_client: TestClient,
    repository: FakeRepository,
    sink: FakeSink,
) -> None:
    response = api_client.post(
        "/api/calls/webhooks/elevenlabs/post-call",
        content=json.dumps(transcription_event()),
        headers={"elevenlabs-signature": "test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    artifact = repository.get_artifact("CA123")
    assert artifact is not None
    assert artifact.has_recording is True
    assert artifact.transcript[0].message == "Hello"
    assert len(sink.submissions) == 1
    job_spec_id, handoff = sink.submissions[0]
    assert job_spec_id == "spec_123"
    assert handoff.company_id == "company_123"
    assert handoff.negotiation_successful is True
    assert handoff.red_flag is False
    assert handoff.transcript_url.endswith("/api/results/calls/CA123/transcript")


def test_duplicate_webhook_is_idempotent(
    api_client: TestClient,
    sink: FakeSink,
) -> None:
    body = json.dumps(transcription_event())
    first = api_client.post("/api/calls/webhooks/elevenlabs/post-call", content=body)
    second = api_client.post("/api/calls/webhooks/elevenlabs/post-call", content=body)
    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"
    assert len(sink.submissions) == 1


def test_audio_webhook_stores_reference_not_base64(
    api_client: TestClient,
    repository: FakeRepository,
) -> None:
    response = api_client.post(
        "/api/calls/webhooks/elevenlabs/post-call",
        json={
            "type": "post_call_audio",
            "data": {
                "conversation_id": "conv_audio",
                "full_audio": "very-large-base64",
            },
        },
    )
    assert response.status_code == 200
    artifact = repository.get_artifact("conv_audio")
    assert artifact is not None
    assert artifact.has_recording is True
    assert "full_audio" not in artifact.model_dump_json()


def test_call_initiation_failure_maps_to_no_answer(
    api_client: TestClient,
    sink: FakeSink,
) -> None:
    response = api_client.post(
        "/api/calls/webhooks/elevenlabs/post-call",
        json={
            "type": "call_initiation_failure",
            "data": {
                "conversation_id": "conv_failed",
                "failure_reason": "no-answer",
                "conversation_initiation_client_data": {
                    "dynamic_variables": {
                        "job_spec_id": "spec_123",
                        "company_id": "company_123",
                    }
                },
            },
        },
    )
    assert response.status_code == 200
    assert sink.submissions[0][1].outcome == P3CallOutcome.NO_ANSWER


class RejectingVerifier:
    def verify(self, raw_body: bytes, signature: str | None):
        raise InvalidWebhookSignatureError()


def test_invalid_webhook_signature_is_rejected(api_client: TestClient) -> None:
    app.dependency_overrides[get_webhook_verifier] = RejectingVerifier
    response = api_client.post(
        "/api/calls/webhooks/elevenlabs/post-call",
        json={"type": "post_call_audio", "data": {"conversation_id": "conv_123"}},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid webhook signature"}
