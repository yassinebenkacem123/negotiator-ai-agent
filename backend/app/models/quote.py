from typing import List, Optional
from pydantic import BaseModel


class Fee(BaseModel):
    label: str
    amount: float


class Quote(BaseModel):
    """Output of a single negotiation call — written by extraction.py, read by ranking.py.

    Field shapes (fees as array, red_flag as string|null, company name, total)
    match frontend/src/lib/api.ts exactly — that contract was set by the
    already-built frontend, not the other way around.
    """

    company_id: str
    company: str = ""
    call_id: str
    initial_price: Optional[float] = None
    negotiated_price: Optional[float] = None
    negotiation_successful: bool = False
    total: Optional[float] = None  # negotiated_price if successful else initial_price
    fees: List[Fee] = []
    differentiators: List[str] = []
    outcome: str  # "quote" | "callback_scheduled" | "declined" | "no_answer" | "outside_hours_skipped"
    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None
    red_flag: Optional[str] = None  # explanation string when flagged, null otherwise


class RankedCompany(BaseModel):
    company_id: str
    company: str
    total: float
    final_price: float
    fees: List[Fee] = []
    differentiators: List[str] = []
    red_flag: Optional[str] = None
    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None
    rank: int
    recommended: bool = False


class Report(BaseModel):
    job_spec_id: str
    ranked_companies: List[RankedCompany]
    summary: str
