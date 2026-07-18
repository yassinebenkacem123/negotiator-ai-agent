"""Thin wrapper around ElevenLabs Conversational AI — connection/auth only.

Only responsibility: know the agent IDs and API key, open/manage the
conversational session. It does NOT decide what the agent says — that is
services/voice_service.py's job (conversation design / prompt injection).
"""

from functools import lru_cache

from elevenlabs.client import ElevenLabs

from app.config import settings


@lru_cache
def get_client() -> ElevenLabs:
    """Created lazily on first use, not at import time — so the app can boot
    even before this key is configured; it only fails when actually called."""
    return ElevenLabs(api_key=settings.elevenlabs_api_key)


def estimator_agent_id() -> str:
    return settings.elevenlabs_agent_id_estimator


def caller_agent_id() -> str:
    return settings.elevenlabs_agent_id_caller
