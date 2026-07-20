"""Endpoints for Voice Orchestration (ElevenLabs/Twilio) — thin: loop leads,
delegate hours-check to telephony.py, delegate calling to telephony.py,
delegate conversation setup to voice_service.py. No calling/negotiation
logic lives in this file.
"""

from urllib.parse import quote
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import ValidationError

from app.api.results import broadcast_report_update
from app.api.voice_errors import as_http_exception
from app.clients.eleven_client import (
    ElevenLabsClient,
    ElevenLabsError,
    InvalidWebhookSignatureError,
)
from app.config import settings
from app.database import get_call, list_calls, upsert_completed_call, upsert_started_call
from app.models.lead import Lead
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
    P3CallOutcome,
    P3QuoteInput,
    PreparedOutboundCall,
    StartCallPreparationRequest,
    StoredCallArtifact,
    WebhookProcessingResult,
)
from app.services import extraction, telephony, voice_service
from app.services.webhook_service import InvalidWebhookPayloadError, WebhookProcessor
from app.store import call_states, job_specs, leads, quotes

router = APIRouter(prefix="/api/calls", tags=["calls"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quote_for(job_spec_id: str, company_id: str) -> Quote | None:
    for quote in quotes.get(job_spec_id, []):
        if quote.company_id == company_id:
            return quote
    return None


def _artifact_for(job_spec_id: str, company_id: str):
    from app.store import call_artifacts

    return next(
        (
            artifact
            for artifact in call_artifacts.values()
            if artifact.job_spec_id == job_spec_id and artifact.company_id == company_id
        ),
        None,
    )


def _set_call_state(job_spec_id: str, company_id: str, **updates) -> None:
    rows = call_states.get(job_spec_id, {})
    current = rows.get(company_id, {})
    current.update(updates)
    rows[company_id] = current
    call_states[job_spec_id] = rows


def _test_company() -> Lead:
    return Lead(
        company_id=settings.elevenlabs_test_company_id,
        name=settings.elevenlabs_test_company_name,
        phone_number=settings.elevenlabs_test_company_phone,
        working_hours={day: "24 hours" for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
        city="Test",
    )


def _prepare_test_call(job_spec_id: str, company: Lead) -> PreparedOutboundCall:
    spec = job_specs.get(job_spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")
    if not spec.confirmed_by_user:
        raise HTTPException(status_code=400, detail="job_spec not confirmed by user")
    try:
        return voice_service.prepare_outbound_call(
            spec,
            company,
            NegotiationContext(),
            settings.elevenlabs_caller_agent_id,
        )
    except voice_service.InvalidCompanyPhoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except voice_service.MissingCallerAgentIdError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except voice_service.InvalidJobSpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/start-test/{job_spec_id}")
def start_test_outbound_call(job_spec_id: str):
    """Start the fixed-number E2E test without invoking Tavily or discovery."""

    company = _test_company()
    prepared = _prepare_test_call(job_spec_id, company)
    leads[job_spec_id] = [company]
    register_url = (
        f"{settings.backend_public_url.rstrip('/')}/api/calls/elevenlabs-register/"
        f"{quote(job_spec_id, safe='')}/{quote(company.company_id, safe='')}"
    )
    try:
        call_sid = telephony.initiate_call(company, register_url)
    except Exception as exc:
        _set_call_state(
            job_spec_id,
            company.company_id,
            state="failed",
            outcome="no_answer",
            failure_message=str(exc),
        )
        raise HTTPException(status_code=502, detail="Twilio call initiation failed") from exc

    started_at = _now_iso()
    _set_call_state(
        job_spec_id,
        company.company_id,
        state="initiated",
        started_at=started_at,
        call_sid=call_sid,
        failure_message=None,
    )
    upsert_started_call(
        call_id=call_sid,
        job_spec_id=job_spec_id,
        company_id=company.company_id,
        company_name=company.name,
        company_phone=company.phone_number,
        started_at=started_at,
    )
    return {
        "job_spec_id": job_spec_id,
        "status": "calling",
        "call_sid": call_sid,
        "company": company.model_dump(),
        "prepared_call": prepared.model_dump(),
    }


@router.api_route(
    "/elevenlabs-register/{job_spec_id}/{company_id}",
    methods=["GET", "POST"],
    response_class=Response,
)
async def register_test_call_with_elevenlabs(
    job_spec_id: str,
    company_id: str,
    client: ElevenLabsClient = Depends(get_elevenlabs_client),
):
    """Return ElevenLabs TwiML to Twilio for the configured Caller Agent."""

    company = next(
        (item for item in leads.get(job_spec_id, []) if item.company_id == company_id),
        None,
    )
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    prepared = _prepare_test_call(job_spec_id, company)
    try:
        twiml = await client.register_twilio_call(
            agent_id=prepared.agent_id,
            from_number=settings.twilio_from_number,
            to_number=prepared.to_number,
            dynamic_variables=prepared.dynamic_variables.model_dump(),
        )
    except ElevenLabsError as exc:
        raise as_http_exception(exc) from exc
    return Response(content=twiml, media_type="application/xml")


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
    public_http_base = stream_webhook_base_url.rstrip("/")
    public_ws_base = public_http_base.replace("https://", "wss://", 1).replace(
        "http://", "ws://", 1
    )
    for lead in job_leads:
        if not telephony.is_within_working_hours(lead):
            _set_call_state(
                job_spec_id,
                lead.company_id,
                state="outside_hours_skipped",
                outcome="outside_hours_skipped",
                failure_message=None,
            )
            results.append(
                {"company_id": lead.company_id, "status": "outside_hours_skipped"}
            )
            continue

        wss_base = stream_webhook_base_url.replace("https://", "wss://")
        call_sid = telephony.initiate_call(
            lead,
            (
                f"{public_http_base}/api/calls/stream/{lead.company_id}"
                f"?wss_url={quote(public_ws_base, safe='')}"
            ),
        )
        _set_call_state(
            job_spec_id,
            lead.company_id,
            state="initiated",
            started_at=_now_iso(),
            call_sid=call_sid,
            failure_message=None,
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


@router.get("/stream/{company_id}", response_class=PlainTextResponse)
def stream_twiml(
    company_id: str,
    wss_url: str = Query(
        default="",
        description=(
            "Public WebSocket origin, e.g. 'wss://abc123.ngrok.io'. "
            "Pass the same base you use for stream_webhook_base_url, "
            "but with wss:// instead of https://."
        ),
    ),
    job_spec_id: str = Query(
        default="",
        description="ID of the job spec to associate with this call.",
    ),
):
    """TwiML endpoint — Twilio fetches this when placing an outbound call.

    Returns XML that tells Twilio to open a <Stream> WebSocket to our
    /media-stream endpoint so we can process audio in real-time.
    """
    base = wss_url if wss_url else "wss://localhost:8000"
    ws_url = f"{base}/media-stream/{company_id}?job_spec_id={job_spec_id}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""


def _find_quote(job_spec_id: str, company_id: str) -> Quote | None:
    for quote in quotes.get(job_spec_id, []):
        if quote.company_id == company_id:
            return quote
    return None


@router.get("/status/{job_spec_id}")
def get_call_statuses(job_spec_id: str):
    if job_spec_id not in job_specs:
        raise HTTPException(status_code=404, detail="job_spec not found")

    rows = call_states.get(job_spec_id, {})
    response = []
    for lead in leads.get(job_spec_id, []):
        state = rows.get(lead.company_id, {})
        quote = _quote_for(job_spec_id, lead.company_id)
        artifact = _artifact_for(job_spec_id, lead.company_id)
        response.append(
            {
                "company_id": lead.company_id,
                "company_name": lead.name,
                "phone_number": lead.phone_number,
                "state": (
                    "completed"
                    if quote
                    else state.get("state", "queued")
                ),
                "started_at": state.get("started_at"),
                "call_duration_seconds": (
                    artifact.metadata.get("call_duration_secs")
                    if artifact and isinstance(artifact.metadata, dict)
                    else None
                ),
                "outcome": quote.outcome if quote else state.get("outcome"),
                "failure_message": state.get("failure_message"),
                "call_id": quote.call_id if quote else (artifact.call_id if artifact else None),
                "call_sid": state.get("call_sid"),
                "transcript_url": quote.transcript_url if quote else None,
                "recording_url": quote.recording_url if quote else None,
            }
        )
    return {"job_spec_id": job_spec_id, "calls": response}


@router.get("")
def get_calls(
    job_spec_id: str | None = None,
    company_id: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
):
    return {
        "calls": list_calls(
            job_spec_id=job_spec_id,
            company_id=company_id,
            status=status,
            outcome=outcome,
        )
    }


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
    company = next(
        (item for item in leads.get(job_spec_id, []) if item.company_id == company_id),
        None,
    )
    quote = extraction.extract_quote(
        company_id, company_name, call_id, transcript, recording_url
    )
    stored_quotes = quotes.get(job_spec_id, [])
    stored_quotes.append(quote)
    quotes[job_spec_id] = stored_quotes
    upsert_completed_call(
        job_spec_id=job_spec_id,
        quote_input=P3QuoteInput(
            company_id=company_id,
            call_id=call_id,
            initial_price=quote.initial_price,
            negotiated_price=quote.negotiated_price,
            negotiation_successful=quote.negotiation_successful,
            fees={fee.label: fee.amount for fee in quote.fees},
            differentiators=quote.differentiators,
            outcome=P3CallOutcome(quote.outcome),
            transcript_url=quote.transcript_url,
            recording_url=quote.recording_url,
            red_flag=False,
        ),
        company_name=company_name,
        company_phone=company.phone_number if company else None,
    )
    _set_call_state(
        job_spec_id,
        company_id,
        state="completed",
        outcome=quote.outcome,
        call_id=call_id,
        recording_url=recording_url,
    )
    await broadcast_report_update(job_spec_id)
    return quote


@router.get("/{call_id}")
def get_call_detail(call_id: str):
    stored = get_call(call_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="call not found")
    return stored


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
