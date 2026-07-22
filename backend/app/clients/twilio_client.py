"""Thin wrapper around Twilio call initiation."""

from functools import lru_cache

from twilio.rest import Client

from app.config import settings


class TwilioConfigurationError(RuntimeError):
    pass


@lru_cache
def _get_client() -> Client:
    """Create the SDK client lazily so the app can boot before Twilio is used."""
    if not settings.twilio_account_sid:
        raise TwilioConfigurationError("TWILIO_ACCOUNT_SID is required")
    if not settings.twilio_auth_token:
        raise TwilioConfigurationError("TWILIO_AUTH_TOKEN is required")
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def place_call(to_number: str, stream_webhook_url: str) -> str:
    """Initiate an outbound call, return the Twilio call SID."""
    if not settings.twilio_from_number:
        raise TwilioConfigurationError("TWILIO_PHONE_NUMBER is required")
    if not to_number:
        raise TwilioConfigurationError("A destination phone number is required")

    call = _get_client().calls.create(
        to=to_number,
        from_=settings.twilio_from_number,
        url=stream_webhook_url,
    )
    return call.sid
