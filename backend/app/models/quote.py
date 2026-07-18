from typing import Dict, List, Optional
from pydantic import BaseModel


class Quote(BaseModel):
    """Output of a single negotiation call — written by extraction.py, read by ranking.py."""

    company_id: str
    call_id: str
    initial_price: Optional[float] = None
    negotiated_price: Optional[float] = None
    negotiation_successful: bool = False
    fees: Dict[str, float] = {}
    differentiators: List[str] = []
    outcome: str  # "quote" | "callback_scheduled" | "declined" | "no_answer" | "outside_hours_skipped"
    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None
    red_flag: bool = False


class RankedCompany(BaseModel):
    company_id: str
    final_price: float
    rank: int
    differentiators: List[str] = []
    red_flag: bool = False


class Report(BaseModel):
    job_spec_id: str
    ranked_companies: List[RankedCompany]
    summary: str
