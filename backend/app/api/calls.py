"""Endpoints for Voice Orchestration (ElevenLabs/Twilio) — thin: loop leads,
delegate hours-check to telephony.py, delegate calling to telephony.py,
delegate conversation setup to voice_service.py. No calling/negotiation
logic lives in this file.
"""

from fastapi import APIRouter, HTTPException

from app.api.results import broadcast_report_update
from app.models.quote import Quote
from app.services import extraction, telephony, voice_service
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
        raise HTTPException(status_code=400, detail="job_spec not confirmed by user yet")

    known_competing_prices = [
        q.negotiated_price or q.initial_price
        for q in quotes.get(job_spec_id, [])
        if (q.negotiated_price or q.initial_price)
    ]

    results = []
    for lead in job_leads:
        if not telephony.is_within_working_hours(lead):
            results.append({"company_id": lead.company_id, "status": "outside_hours_skipped"})
            continue

        voice_service.build_caller_context(spec, known_competing_prices)
        call_sid = telephony.initiate_call(lead, f"{stream_webhook_base_url}/api/calls/stream/{lead.company_id}")
        results.append({"company_id": lead.company_id, "status": "calling", "call_sid": call_sid})

    return {"job_spec_id": job_spec_id, "results": results}


@router.post("/completed/{job_spec_id}/{company_id}", response_model=Quote)
async def call_completed(job_spec_id: str, company_id: str, call_id: str, transcript: str, recording_url: str | None = None):
    """Webhook target once a call ends: extract the structured quote, store it,
    and push a fresh ranked report to any connected frontend clients."""
    quote = extraction.extract_quote(company_id, call_id, transcript, recording_url)
    quotes.setdefault(job_spec_id, []).append(quote)
    await broadcast_report_update(job_spec_id)
    return quote
