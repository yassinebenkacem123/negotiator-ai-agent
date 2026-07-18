from typing import Dict, Optional
from pydantic import BaseModel


class Lead(BaseModel):
    """A discovered moving company — output of search_service, input to calls."""

    company_id: str
    name: str
    phone_number: Optional[str] = None
    working_hours: Dict[str, str] = {}  # e.g. {"mon": "08:00-18:00", ...}
    source_url: Optional[str] = None
    city: str
