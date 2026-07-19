from typing import Optional
from pydantic import BaseModel


class JobSpec(BaseModel):
    job_spec_id: str = ""  # frontend's CreateSpecInput omits this entirely; server generates it
    origin_address: str
    origin_floor: int = 0  # 0 = ground floor
    origin_has_elevator: bool = False
    origin_lat: Optional[float] = None  # from map pin selection (frontend)
    origin_lng: Optional[float] = None
    destination_address: str
    destination_floor: int = 0
    destination_has_elevator: bool = False
    destination_lat: Optional[float] = None
    destination_lng: Optional[float] = None
    distance_miles: Optional[float] = None  # server-computed from lat/lng, never trust a client-sent value
    move_date: str
    date_flexible: bool = True
    num_trips: int
    num_bags: int
    notes: Optional[str] = None
    source: str  # "voice_interview" | "document_upload"
    confirmed_by_user: bool = False
    intake_transcript: Optional[str] = None  # set when source == "voice_interview", shown to user for review
