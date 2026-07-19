"""Consistent safe HTTP mappings for ElevenLabs client failures."""

from fastapi import HTTPException

from app.clients.eleven_client import (
    ElevenLabsAuthenticationError,
    ElevenLabsConfigurationError,
    ElevenLabsConversationNotFoundError,
    ElevenLabsError,
    ElevenLabsMalformedResponseError,
    ElevenLabsTimeoutError,
)


def as_http_exception(exc: ElevenLabsError) -> HTTPException:
    if isinstance(exc, ElevenLabsConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ElevenLabsAuthenticationError):
        return HTTPException(status_code=502, detail="ElevenLabs authentication failed")
    if isinstance(exc, ElevenLabsConversationNotFoundError):
        return HTTPException(status_code=404, detail="conversation not found")
    if isinstance(exc, ElevenLabsTimeoutError):
        return HTTPException(status_code=504, detail="ElevenLabs request timed out")
    if isinstance(exc, ElevenLabsMalformedResponseError):
        return HTTPException(
            status_code=502, detail="ElevenLabs returned a malformed response"
        )
    return HTTPException(status_code=502, detail="ElevenLabs upstream request failed")
