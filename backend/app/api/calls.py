"""Endpoints for Voice Orchestration (ElevenLabs/Twilio) — thin: loop leads,
delegate hours-check to telephony.py, delegate calling to telephony.py,
delegate conversation setup to voice_service.py. No calling/negotiation
logic lives in this file.
"""

from pydantic import ValidationError
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.results import broadcast_report_update
from app.api.voice_errors import as_http_exception
from app.clients.eleven_client import (
    ElevenLabsClient,
    ElevenLabsError,
    InvalidWebhookSignatureError,
)
from app.config import settings
from app.dependencies.voice import (
    CompletedCallSink,
    VoiceRepository,
    WebhookVerifier,
    get_completed_call_sink,
    get_elevenlabs_client,
    get_voice_repository,
    get_webhook_verifier,
)
from app.models.quote import Quote
from app.models.voice import (
    ElevenLabsConversationResult,
    NegotiationContext,
    PostCallWebhookPayload,
    PreparedOutboundCall,
    StartCallPreparationRequest,
    StoredCallArtifact,
    WebhookProcessingResult,
)
from app.services import extraction, telephony, voice_service
from app.services.webhook_service import InvalidWebhookPayloadError, WebhookProcessor
from app.store import job_specs, leads, quotes

router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.post("/start-negotiating/{job_spec_id}")
def start_negotiating(job_spec_id: str, stream_webhook_base_url: str):
    """Loop through this job's leads, skip anyone outside working hours,
    place a call for everyone else. Real orchestration would queue/retry the
    skipped ones later rather than dropping them (see P2's scheduler)."""
    spec = job_specs.get(job_spec_id)
    job_leads = leads.get(job_spec_id, [])
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")
    if not spec.confirmed_by_user:
        raise HTTPException(
            status_code=400, detail="job_spec not confirmed by user yet"
        )

    results = []
    for lead in job_leads:
        if not telephony.is_within_working_hours(lead):
            results.append(
                {"company_id": lead.company_id, "status": "outside_hours_skipped"}
            )
            continue

        call_sid = telephony.initiate_call(
            lead, f"{stream_webhook_base_url}/api/calls/stream/{lead.company_id}"
        )
        results.append(
            {"company_id": lead.company_id, "status": "calling", "call_sid": call_sid}
        )

    return {"job_spec_id": job_spec_id, "results": results}


def _lead_name(job_spec_id: str, company_id: str) -> str:
    for lead in leads.get(job_spec_id, []):
        if lead.company_id == company_id:
            return lead.name
    return "Unknown Mover"


def _find_quote(job_spec_id: str, company_id: str) -> Quote | None:
    for quote in quotes.get(job_spec_id, []):
        if quote.company_id == company_id:
            return quote
    return None


@router.post("/completed/{job_spec_id}/{company_id}", response_model=Quote)
async def call_completed(
    job_spec_id: str,
    company_id: str,
    call_id: str | None = None,
    transcript: str | None = None,
    recording_url: str | None = None,
):
    """Dual-purpose by design, matching how the frontend already calls this path:
    - With `transcript` provided: telephony webhook target once a real call ends —
      extract the structured quote, store it, push a fresh report over the websocket.
    - Without `transcript`: read-only fetch of the already-stored quote for this
      company (what frontend/src/lib/api.ts's getCompletedCall expects — a POST
      with no body that returns the existing result, not a new extraction).
    """
    if transcript is None:
        existing = _find_quote(job_spec_id, company_id)
        if not existing:
            raise HTTPException(
                status_code=404, detail="no completed call found for this company yet"
            )
        return existing

    if call_id is None:
        raise HTTPException(
            status_code=400, detail="call_id is required when submitting a transcript"
        )

    company_name = _lead_name(job_spec_id, company_id)
    quote = extraction.extract_quote(
        company_id, company_name, call_id, transcript, recording_url
    )
    quotes.setdefault(job_spec_id, []).append(quote)
    await broadcast_report_update(job_spec_id)
    return quote


@router.post("/prepare", response_model=PreparedOutboundCall)
async def prepare_call(
    request: StartCallPreparationRequest,
    repository: VoiceRepository = Depends(get_voice_repository),
) -> PreparedOutboundCall:
    """Prepare P1's payload for P2 without initiating a phone call."""

    spec = repository.get_job_spec(request.job_spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="job_spec not found")
    if not spec.confirmed_by_user:
        raise HTTPException(status_code=400, detail="job_spec not confirmed by user")
    company = repository.get_company(request.job_spec_id, request.company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")

    context = NegotiationContext(
        negotiation_mode=request.negotiation_mode,
        competing_quote=request.competing_quote,
        competing_company_name=request.competing_company_name,
    )
    try:
        return voice_service.prepare_outbound_call(
            spec,
            company,
            context,
            settings.elevenlabs_caller_agent_id,
        )
    except voice_service.InvalidCompanyPhoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except voice_service.MissingCallerAgentIdError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except voice_service.InvalidJobSpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/conversations/{conversation_id}", response_model=ElevenLabsConversationResult
)
async def get_conversation_result(
    conversation_id: str,
    client: ElevenLabsClient = Depends(get_elevenlabs_client),
    repository: VoiceRepository = Depends(get_voice_repository),
) -> ElevenLabsConversationResult:
    try:
        payload = await client.get_conversation(conversation_id)
    except ElevenLabsError as exc:
        raise as_http_exception(exc) from exc

    try:
        result = voice_service.normalize_conversation_result(
            payload,
            backend_public_url=settings.backend_public_url,
        )
    except voice_service.InvalidJobSpecError as exc:
        raise HTTPException(
            status_code=502, detail="ElevenLabs returned a malformed response"
        ) from exc

    if result.recording_url:
        existing = repository.find_artifact_by_conversation(conversation_id)
        call_id = existing.call_id if existing else conversation_id
        result.recording_url = f"{settings.backend_public_url.rstrip('/')}/api/results/calls/{call_id}/recording"
        repository.save_artifact(
            StoredCallArtifact(
                call_id=call_id,
                conversation_id=conversation_id,
                job_spec_id=existing.job_spec_id if existing else None,
                company_id=existing.company_id if existing else None,
                status=result.status,
                transcript=result.transcript,
                metadata=result.metadata,
                has_recording=True,
            )
        )
    return result


@router.post(
    "/webhooks/elevenlabs/post-call",
    response_model=WebhookProcessingResult,
)
async def elevenlabs_post_call_webhook(
    request: Request,
    verifier: WebhookVerifier = Depends(get_webhook_verifier),
    repository: VoiceRepository = Depends(get_voice_repository),
    completed_call_sink: CompletedCallSink = Depends(get_completed_call_sink),
) -> WebhookProcessingResult:
    raw_body = await request.body()
    signature = request.headers.get("elevenlabs-signature")
    try:
        event = verifier.verify(raw_body, signature)
    except InvalidWebhookSignatureError as exc:
        raise HTTPException(
            status_code=401, detail="invalid webhook signature"
        ) from exc
    except ElevenLabsError as exc:
        raise as_http_exception(exc) from exc

    try:
        payload = PostCallWebhookPayload.model_validate(event)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid webhook payload") from exc

    processor = WebhookProcessor(
        repository=repository,
        completed_call_sink=completed_call_sink,
        backend_public_url=settings.backend_public_url,
    )
    try:
        return await processor.process(payload)
    except InvalidWebhookPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
