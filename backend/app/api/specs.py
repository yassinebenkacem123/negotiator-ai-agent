"""Endpoints for Job Spec & Doc Intake — thin: validate request, call store, return.
No business logic here (see models/job_spec.py for shape, store.py for persistence)."""

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.models.job_spec import JobSpec
from app.services import document_intake, geo, voice_intake
from app.store import job_specs

router = APIRouter(prefix="/api/specs", tags=["specs"])


class VoiceTranscriptInput(BaseModel):
    transcript: str


@router.post("", response_model=JobSpec)
def create_spec(spec: JobSpec):
    if not spec.job_spec_id:
        spec.job_spec_id = str(uuid.uuid4())

    # Distance is always server-computed from lat/lng when both points are
    # present — never trust a distance_miles value sent by the client.
    if None not in (spec.origin_lat, spec.origin_lng, spec.destination_lat, spec.destination_lng):
        spec.distance_miles = geo.haversine_distance_miles(
            spec.origin_lat, spec.origin_lng, spec.destination_lat, spec.destination_lng
        )
    else:
        spec.distance_miles = None

    job_specs[spec.job_spec_id] = spec
    return spec


@router.post("/from-document", response_model=JobSpec)
async def create_spec_from_document(file: UploadFile = File(...)):
    """Second required intake path: a photo of an existing quote, inventory
    list, etc. Produces the same JobSpec shape as the voice interview and
    the manual form — fields not visible in the image are left blank/zeroed
    rather than guessed, so the user must review and correct via the normal
    confirm flow before any calls are made (same as every other intake path)."""
    image_bytes = await file.read()
    fields = document_intake.extract_job_spec_fields(image_bytes, file.content_type or "image/jpeg")

    spec = JobSpec(
        job_spec_id=str(uuid.uuid4()),
        origin_address=fields.get("origin_address") or "",
        destination_address=fields.get("destination_address") or "",
        move_date=fields.get("move_date") or "",
        num_trips=fields.get("num_trips") or 1,
        num_bags=fields.get("num_bags") or 0,
        notes=fields.get("notes"),
        source="document_upload",
        confirmed_by_user=False,
    )
    job_specs[spec.job_spec_id] = spec
    return spec


@router.post("/from-voice", response_model=JobSpec)
async def create_spec_from_voice(payload: VoiceTranscriptInput):
    """Required voice interview intake path: an Estimator-agent transcript in,
    the same JobSpec shape out as every other intake path. The transcript is
    stored (intake_transcript) so the frontend can show it for the user to
    verify before confirming -- same review requirement as every other path."""
    fields = voice_intake.extract_job_spec_fields(payload.transcript)

    spec = JobSpec(
        job_spec_id=str(uuid.uuid4()),
        origin_address=fields.get("origin_address") or "",
        origin_floor=fields.get("origin_floor") or 0,
        origin_has_elevator=bool(fields.get("origin_has_elevator") or False),
        destination_address=fields.get("destination_address") or "",
        destination_floor=fields.get("destination_floor") or 0,
        destination_has_elevator=bool(fields.get("destination_has_elevator") or False),
        move_date=fields.get("move_date") or "",
        date_flexible=fields.get("date_flexible") if fields.get("date_flexible") is not None else True,
        num_trips=fields.get("num_trips") or 1,
        num_bags=fields.get("num_bags") or 0,
        notes=fields.get("notes"),
        source="voice_interview",
        intake_transcript=payload.transcript,
        confirmed_by_user=False,
    )
    job_specs[spec.job_spec_id] = spec
    return spec


@router.post("/{job_spec_id}/enrich-from-document", response_model=JobSpec)
async def enrich_spec_from_document(job_spec_id: str, file: UploadFile = File(...)):
    """Optional step after voice intake: attach a document (existing quote,
    inventory list) to fill gaps the interview missed. Never overwrites a
    field the user already has a real value for -- only fills what's empty,
    and appends (rather than replaces) notes so nothing said on the call is lost."""
    spec = job_specs.get(job_spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")

    document_bytes = await file.read()
    fields = document_intake.extract_job_spec_fields(document_bytes, file.content_type or "image/jpeg")

    if not spec.origin_address and fields.get("origin_address"):
        spec.origin_address = fields["origin_address"]
    if not spec.destination_address and fields.get("destination_address"):
        spec.destination_address = fields["destination_address"]
    if not spec.move_date and fields.get("move_date"):
        spec.move_date = fields["move_date"]
    if not spec.num_trips and fields.get("num_trips"):
        spec.num_trips = fields["num_trips"]
    if not spec.num_bags and fields.get("num_bags"):
        spec.num_bags = fields["num_bags"]
    if fields.get("notes"):
        spec.notes = f"{spec.notes}\n{fields['notes']}" if spec.notes else fields["notes"]

    job_specs[job_spec_id] = spec
    return spec


@router.put("/{job_spec_id}", response_model=JobSpec)
def update_spec(job_spec_id: str, spec: JobSpec):
    """Lets the user correct fields after any intake path (voice transcription
    errors, a document that misread an address, etc.) before confirming.
    job_spec_id in the path always wins over whatever's in the body."""
    if job_spec_id not in job_specs:
        raise HTTPException(status_code=404, detail="job_spec not found")
    spec.job_spec_id = job_spec_id

    if None not in (spec.origin_lat, spec.origin_lng, spec.destination_lat, spec.destination_lng):
        spec.distance_miles = geo.haversine_distance_miles(
            spec.origin_lat, spec.origin_lng, spec.destination_lat, spec.destination_lng
        )
    else:
        spec.distance_miles = None

    job_specs[job_spec_id] = spec
    return spec


@router.get("/{job_spec_id}", response_model=JobSpec)
def get_spec(job_spec_id: str):
    spec = job_specs.get(job_spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")
    return spec


@router.post("/{job_spec_id}/confirm", response_model=JobSpec)
def confirm_spec(job_spec_id: str):
    spec = job_specs.get(job_spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")
    spec.confirmed_by_user = True
    job_specs[job_spec_id] = spec
    return spec
