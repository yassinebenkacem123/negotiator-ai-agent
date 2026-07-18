"""SRP: Connectivity.

Manages the Twilio stream and bridges the phone line audio to voice_service.
Does not care what is being said — only that the audio stream stays open and
that calls are only ever placed inside a lead's working hours.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.clients import twilio_client
from app.config import settings
from app.models.lead import Lead


def is_within_working_hours(lead: Lead, now: datetime | None = None) -> bool:
    """Gate: only allow a call if `now` falls inside the lead's listed hours.

    If a lead has no working_hours on file, default to NOT calling — silence
    on this field should never be interpreted as "always open."
    """
    if not settings.respect_working_hours:
        return True
    if not lead.working_hours:
        return False

    tz = ZoneInfo(settings.default_timezone)
    now = now or datetime.now(tz)
    day_key = now.strftime("%a").lower()[:3]
    hours = lead.working_hours.get(day_key)
    if not hours:
        return False

    start_str, end_str = hours.split("-")
    start = now.replace(hour=int(start_str.split(":")[0]), minute=int(start_str.split(":")[1]), second=0)
    end = now.replace(hour=int(end_str.split(":")[0]), minute=int(end_str.split(":")[1]), second=0)
    return start <= now <= end


def initiate_call(lead: Lead, stream_webhook_url: str) -> str:
    """Place the outbound call via Twilio. Caller (api/calls.py) must have
    already checked is_within_working_hours before calling this."""
    return twilio_client.place_call(lead.phone_number, stream_webhook_url)
