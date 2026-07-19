"""Injected adapters connecting P1 to the current P2/P3 in-memory seams."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.clients.eleven_client import ElevenLabsClient, ElevenLabsWebhookVerifier
from app.config import settings
from app.database import upsert_completed_call
from app.models.job_spec import JobSpec
from app.models.lead import Lead
from app.models.quote import Fee, Quote
from app.models.voice import P3QuoteInput, StoredCallArtifact
from app.store import call_artifacts, call_states, job_specs, leads, processed_webhook_events, quotes


class VoiceRepository(Protocol):
    def get_job_spec(self, job_spec_id: str) -> JobSpec | None: ...

    def get_company(self, job_spec_id: str, company_id: str) -> Lead | None: ...

    def get_artifact(self, call_id: str) -> StoredCallArtifact | None: ...

    def find_artifact_by_conversation(
        self, conversation_id: str
    ) -> StoredCallArtifact | None: ...

    def save_artifact(self, artifact: StoredCallArtifact) -> None: ...

    def claim_webhook_event(self, event_key: str) -> bool: ...

    def release_webhook_event(self, event_key: str) -> None: ...


class CompletedCallSink(Protocol):
    async def submit(self, job_spec_id: str, quote_input: P3QuoteInput) -> None: ...


class WebhookVerifier(Protocol):
    def verify(self, raw_body: bytes, signature: str | None) -> dict[str, Any]: ...


class InMemoryVoiceRepository:
    def get_job_spec(self, job_spec_id: str) -> JobSpec | None:
        return job_specs.get(job_spec_id)

    def get_company(self, job_spec_id: str, company_id: str) -> Lead | None:
        return next(
            (
                lead
                for lead in leads.get(job_spec_id, [])
                if lead.company_id == company_id
            ),
            None,
        )

    def get_artifact(self, call_id: str) -> StoredCallArtifact | None:
        return call_artifacts.get(call_id)

    def find_artifact_by_conversation(
        self, conversation_id: str
    ) -> StoredCallArtifact | None:
        return next(
            (
                artifact
                for artifact in call_artifacts.values()
                if artifact.conversation_id == conversation_id
            ),
            None,
        )

    def save_artifact(self, artifact: StoredCallArtifact) -> None:
        call_artifacts[artifact.call_id] = artifact

    def claim_webhook_event(self, event_key: str) -> bool:
        if event_key in processed_webhook_events:
            return False
        processed_webhook_events.add(event_key)
        return True

    def release_webhook_event(self, event_key: str) -> None:
        processed_webhook_events.discard(event_key)


class StoreCompletedCallSink:
    """P3 adapter for the current Quote model; replace when P3 adds a repository."""

    def __init__(self, repository: VoiceRepository) -> None:
        self._repository = repository

    async def submit(self, job_spec_id: str, quote_input: P3QuoteInput) -> None:
        company = self._repository.get_company(job_spec_id, quote_input.company_id)
        company_name = company.name if company else ""
        numeric_fees = [
            Fee(label=label, amount=float(amount))
            for label, amount in quote_input.fees.items()
            if isinstance(amount, (int, float)) and not isinstance(amount, bool)
        ]
        total = (
            quote_input.negotiated_price
            if quote_input.negotiation_successful
            and quote_input.negotiated_price is not None
            else quote_input.initial_price
        )
        quote = Quote(
            company_id=quote_input.company_id,
            company=company_name,
            call_id=quote_input.call_id,
            initial_price=quote_input.initial_price,
            negotiated_price=quote_input.negotiated_price,
            negotiation_successful=quote_input.negotiation_successful,
            total=total,
            fees=numeric_fees,
            differentiators=quote_input.differentiators,
            outcome=quote_input.outcome.value,
            transcript_url=quote_input.transcript_url,
            recording_url=quote_input.recording_url,
            red_flag=None,
        )
        existing = quotes.setdefault(job_spec_id, [])
        for index, stored in enumerate(existing):
            if stored.call_id == quote.call_id:
                existing[index] = quote
                break
        else:
            existing.append(quote)

        artifact = self._repository.get_artifact(quote_input.call_id)
        upsert_completed_call(
            job_spec_id=job_spec_id,
            quote_input=quote_input,
            company_name=company_name,
            company_phone=company.phone_number if company else None,
            artifact=artifact,
        )

        state = "completed" if quote.outcome == "quote" else quote.outcome
        call_states.setdefault(job_spec_id, {})[quote.company_id] = {
            **call_states.setdefault(job_spec_id, {}).get(quote.company_id, {}),
            "state": state,
            "outcome": quote.outcome,
            "call_id": quote.call_id,
            "transcript_url": quote.transcript_url,
            "recording_url": quote.recording_url,
        }

        from app.api.results import broadcast_report_update

        await broadcast_report_update(job_spec_id)


def get_voice_repository() -> VoiceRepository:
    return InMemoryVoiceRepository()


def get_completed_call_sink() -> CompletedCallSink:
    return StoreCompletedCallSink(get_voice_repository())


async def get_elevenlabs_client() -> AsyncIterator[ElevenLabsClient]:
    client = ElevenLabsClient(settings.elevenlabs_api_key)
    try:
        yield client
    finally:
        await client.aclose()


def get_webhook_verifier() -> WebhookVerifier:
    return ElevenLabsWebhookVerifier(
        api_key=settings.elevenlabs_api_key,
        secret=settings.elevenlabs_webhook_secret,
        app_env=settings.app_env,
    )
