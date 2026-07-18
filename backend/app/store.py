"""Minimal in-memory store — placeholder until a real DB is wired in.
Not part of your original tree; added because api/ routes need somewhere to
persist job specs, leads, and quotes between requests during the hackathon.
Swap for Postgres/SQLAlchemy models/ later without touching service logic.
"""

from app.models.job_spec import JobSpec
from app.models.lead import Lead
from app.models.quote import Quote

job_specs: dict[str, JobSpec] = {}
leads: dict[str, list[Lead]] = {}  # job_spec_id -> leads
quotes: dict[str, list[Quote]] = {}  # job_spec_id -> quotes
