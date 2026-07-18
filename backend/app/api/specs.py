"""Endpoints for Job Spec & Doc Intake — thin: validate request, call store, return.
No business logic here (see models/job_spec.py for shape, store.py for persistence)."""

import uuid

from fastapi import APIRouter, HTTPException

from app.models.job_spec import JobSpec
from app.services import geo
from app.store import job_specs

router = APIRouter(prefix="/api/specs", tags=["specs"])


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
    return spec
