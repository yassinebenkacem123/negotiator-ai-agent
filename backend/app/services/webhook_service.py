"""Idempotent post-call webhook orchestration and P3 handoff."""

from typing import Any

from app.dependencies.voice import CompletedCallSink, VoiceRepository
from app.models.voice import (
    CallOutcome,
    ConversationStatus,
    ElevenLabsCollectedData,
    PostCallWebhookPayload,
    StoredCallArtifact,
    WebhookEventType,
    WebhookProcessingResult,
)
from app.services.voice_service import (
    extract_dynamic_identifiers,
    map_to_p3_quote_input,
    normalize_conversation_result,
)


class InvalidWebhookPayloadError(Exception):
    pass


class WebhookProcessor:
    def __init__(
        self,
        *,
        repository: VoiceRepository,
        completed_call_sink: CompletedCallSink,
        backend_public_url: str,
    ) -> None:
        self._repository = repository
        self._completed_call_sink = completed_call_sink
        self._backend_public_url = backend_public_url.rstrip("/")

    async def process(self, payload: PostCallWebhookPayload) -> WebhookProcessingResult:
        conversation_id = payload.data.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            raise InvalidWebhookPayloadError(
                "webhook payload is missing conversation_id"
            )
        event_key = f"{payload.type.value}:{conversation_id}"
        if not self._repository.claim_webhook_event(event_key):
            return WebhookProcessingResult(
                status="duplicate",
                event_type=payload.type,
                conversation_id=conversation_id,
            )

        try:
            if payload.type == WebhookEventType.POST_CALL_TRANSCRIPTION:
                await self._process_transcription(payload.data)
            elif payload.type == WebhookEventType.POST_CALL_AUDIO:
                self._process_audio(payload.data)
            elif payload.type == WebhookEventType.CALL_INITIATION_FAILURE:
                await self._process_failure(payload.data)
        except Exception:
            self._repository.release_webhook_event(event_key)
            raise

        return WebhookProcessingResult(
            status="processed",
            event_type=payload.type,
            conversation_id=conversation_id,
        )

    async def _process_transcription(self, data: dict[str, Any]) -> None:
        normalized = normalize_conversation_result(
            data,
            backend_public_url=self._backend_public_url,
        )
        job_spec_id, company_id = extract_dynamic_identifiers(data)
        existing = self._repository.find_artifact_by_conversation(
            normalized.conversation_id
        )
        call_id = _extract_call_id(data) or (
            existing.call_id if existing else normalized.conversation_id
        )
        has_recording = data.get("has_audio") is True or bool(
            existing and existing.has_recording
        )
        artifact = StoredCallArtifact(
            call_id=call_id,
            conversation_id=normalized.conversation_id,
            job_spec_id=job_spec_id or (existing.job_spec_id if existing else None),
            company_id=company_id or (existing.company_id if existing else None),
            status=normalized.status,
            transcript=normalized.transcript,
            metadata=normalized.metadata,
            has_recording=has_recording,
        )
        self._repository.save_artifact(artifact)

        if artifact.job_spec_id and artifact.company_id:
            transcript_url = (
                f"{self._backend_public_url}/api/results/calls/{call_id}/transcript"
                if artifact.transcript
                else None
            )
            recording_url = (
                f"{self._backend_public_url}/api/results/calls/{call_id}/recording"
                if artifact.has_recording
                else None
            )
            quote_input = map_to_p3_quote_input(
                company_id=artifact.company_id,
                call_id=call_id,
                collected_data=normalized.collected_data,
                transcript_url=transcript_url,
                recording_url=recording_url,
            )
            await self._completed_call_sink.submit(artifact.job_spec_id, quote_input)

    def _process_audio(self, data: dict[str, Any]) -> None:
        conversation_id = str(data["conversation_id"])
        existing = self._repository.find_artifact_by_conversation(conversation_id)
        artifact = StoredCallArtifact(
            call_id=existing.call_id if existing else conversation_id,
            conversation_id=conversation_id,
            job_spec_id=existing.job_spec_id if existing else None,
            company_id=existing.company_id if existing else None,
            status=existing.status if existing else ConversationStatus.COMPLETED,
            transcript=existing.transcript if existing else [],
            metadata=existing.metadata if existing else {},
            has_recording=True,
        )
        # full_audio is deliberately not persisted; the recording endpoint proxies
        # the provider resource instead of storing large base64 blobs in process.
        self._repository.save_artifact(artifact)

    async def _process_failure(self, data: dict[str, Any]) -> None:
        conversation_id = str(data["conversation_id"])
        job_spec_id, company_id = extract_dynamic_identifiers(data)
        call_id = _extract_call_id(data) or conversation_id
        artifact = StoredCallArtifact(
            call_id=call_id,
            conversation_id=conversation_id,
            job_spec_id=job_spec_id,
            company_id=company_id,
            status=ConversationStatus.FAILED,
            metadata={"failure_reason": data.get("failure_reason", "unknown")},
        )
        self._repository.save_artifact(artifact)
        if job_spec_id and company_id:
            collected = ElevenLabsCollectedData(call_outcome=CallOutcome.NO_ANSWER)
            quote_input = map_to_p3_quote_input(
                company_id=company_id,
                call_id=call_id,
                collected_data=collected,
            )
            await self._completed_call_sink.submit(job_spec_id, quote_input)


def _extract_call_id(data: dict[str, Any]) -> str | None:
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    direct = metadata.get("call_sid") or metadata.get("call_id")
    if isinstance(direct, str) and direct:
        return direct
    phone_call = metadata.get("phone_call")
    if isinstance(phone_call, dict):
        value = phone_call.get("call_sid") or phone_call.get("call_id")
        if isinstance(value, str) and value:
            return value
    body = metadata.get("body")
    if isinstance(body, dict):
        value = body.get("CallSid") or body.get("call_sid")
        if isinstance(value, str) and value:
            return value
    return None
