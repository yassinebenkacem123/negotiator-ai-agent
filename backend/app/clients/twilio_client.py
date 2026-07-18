"""Thin wrapper around Twilio — call initiation only, no conversation logic.

Only responsibility: place an outbound call and bridge the stream to a target
webhook URL. telephony.py owns the higher-level "when/who to call" decisions.
"""

from functools import lru_cache

from twilio.rest import Client

from app.config import settings


@lru_cache
def _get_client() -> Client:
    """Created lazily on first use, not at import time — so the app can boot
    even before this key is configured; it only fails when actually called."""
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def place_call(to_number: str, stream_webhook_url: str) -> str:
    """Initiate an outbound call, return the Twilio call SID."""
    call = _get_client().calls.create(
        to=to_number,
        from_=settings.twilio_from_number,
        url=stream_webhook_url,
    )
    return call.sid
