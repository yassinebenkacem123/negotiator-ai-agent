"""Endpoints for Lead Sourcing (Tavily) — thin: call search_service, store, return.
No scraping/regex/query logic here (see services/search_service.py)."""

from fastapi import APIRouter, HTTPException

from app.services import search_service
from app.store import job_specs, leads

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/find-movers/{job_spec_id}")
def find_movers(job_spec_id: str):
    """No city parameter needed — the only location input is the job spec's
    origin_address, already collected during intake. City is detected from it."""
    spec = job_specs.get(job_spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="job_spec not found")

    found = search_service.find_movers_near(spec.origin_address)
    leads[job_spec_id] = found
    return {"job_spec_id": job_spec_id, "leads": found}


@router.get("/leads/{job_spec_id}")
def get_leads(job_spec_id: str):
    return leads.get(job_spec_id, [])
