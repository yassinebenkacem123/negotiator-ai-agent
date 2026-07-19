from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies.voice import (
    get_completed_call_sink,
    get_voice_repository,
    get_webhook_verifier,
)
from app.main import app
from app.models.job_spec import JobSpec
from app.models.lead import Lead
from app.models.voice import P3QuoteInput, StoredCallArtifact


def make_spec(**overrides: Any) -> JobSpec:
    data: dict[str, Any] = {
        "job_spec_id": "spec_123",
        "origin_address": "1425 Elm Street, Brooklyn, NY 11201",
        "origin_floor": 4,
        "origin_has_elevator": False,
        "origin_lat": 40.1,
        "origin_lng": -73.1,
        "destination_address": "88 Beacon Hill Rd, Boston, MA 02108",
        "destination_floor": 2,
        "destination_has_elevator": True,
        "destination_lat": 42.1,
        "destination_lng": -71.1,
        "distance_miles": 214.7,
        "move_date": "2026-08-08",
        "date_flexible": True,
        "num_trips": 2,
        "num_bags": 18,
        "notes": "Street parking requires a permit.",
        "source": "voice_interview",
        "confirmed_by_user": True,
    }
    data.update(overrides)
    return JobSpec(**data)


def make_company(**overrides: Any) -> Lead:
    data: dict[str, Any] = {
        "company_id": "company_123",
        "name": "Fast Move Logistics",
        "phone_number": "+12025550123",
        "working_hours": {},
        "city": "Brooklyn",
    }
    data.update(overrides)
    return Lead(**data)


class FakeRepository:
    def __init__(
        self,
        spec: JobSpec | None = None,
        company: Lead | None = None,
    ) -> None:
        self.spec = spec
        self.company = company
        self.artifacts: dict[str, StoredCallArtifact] = {}
        self.events: set[str] = set()

    def get_job_spec(self, job_spec_id: str) -> JobSpec | None:
        return self.spec if self.spec and self.spec.job_spec_id == job_spec_id else None

    def get_company(self, job_spec_id: str, company_id: str) -> Lead | None:
        return (
            self.company
            if self.company and self.company.company_id == company_id
            else None
        )

    def get_artifact(self, call_id: str) -> StoredCallArtifact | None:
        return self.artifacts.get(call_id)

    def find_artifact_by_conversation(
        self, conversation_id: str
    ) -> StoredCallArtifact | None:
        return next(
            (
                item
                for item in self.artifacts.values()
                if item.conversation_id == conversation_id
            ),
            None,
        )

    def save_artifact(self, artifact: StoredCallArtifact) -> None:
        self.artifacts[artifact.call_id] = artifact

    def claim_webhook_event(self, event_key: str) -> bool:
        if event_key in self.events:
            return False
        self.events.add(event_key)
        return True

    def release_webhook_event(self, event_key: str) -> None:
        self.events.discard(event_key)


class FakeSink:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, P3QuoteInput]] = []

    async def submit(self, job_spec_id: str, quote_input: P3QuoteInput) -> None:
        self.submissions.append((job_spec_id, quote_input))


class JsonVerifier:
    def verify(self, raw_body: bytes, signature: str | None) -> dict[str, Any]:
        import json

        return json.loads(raw_body)


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository(make_spec(), make_company())


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


@pytest.fixture
def api_client(repository: FakeRepository, sink: FakeSink) -> Iterator[TestClient]:
    previous_agent_id = settings.elevenlabs_caller_agent_id
    previous_url = settings.backend_public_url
    settings.elevenlabs_caller_agent_id = "agent_xxx"
    settings.backend_public_url = "http://testserver"
    app.dependency_overrides[get_voice_repository] = lambda: repository
    app.dependency_overrides[get_completed_call_sink] = lambda: sink
    app.dependency_overrides[get_webhook_verifier] = JsonVerifier
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    settings.elevenlabs_caller_agent_id = previous_agent_id
    settings.backend_public_url = previous_url
