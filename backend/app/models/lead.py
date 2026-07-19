from typing import Dict, Optional
from pydantic import BaseModel


class Lead(BaseModel):
    """A discovered moving company — output of search_service, input to calls.

    All fields beyond company_id/name/city are optional and best-effort —
    extraction quality varies per source page. Owned by P2 (search/discovery);
    kept intentionally open to extension (e.g. rating, review_count) rather
    than locked down, since P2's real implementation isn't merged yet.
    """

    company_id: str
    name: str
    phone_number: Optional[str] = None
    address: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    working_hours: Dict[str, str] = {}  # e.g. {"mon": "08:00-18:00", ...}
    source_url: Optional[str] = None
    city: str
