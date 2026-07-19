"""Async ElevenLabs REST client and official webhook-signature adapter."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class ElevenLabsError(Exception):
    """Base class for safe, typed ElevenLabs failures."""


class ElevenLabsConfigurationError(ElevenLabsError):
    pass


class ElevenLabsAuthenticationError(ElevenLabsError):
    pass


class ElevenLabsConversationNotFoundError(ElevenLabsError):
    pass


class ElevenLabsTimeoutError(ElevenLabsError):
    pass


class ElevenLabsMalformedResponseError(ElevenLabsError):
    pass


class ElevenLabsUpstreamError(ElevenLabsError):
    pass


class InvalidWebhookSignatureError(ElevenLabsError):
    pass


class ElevenLabsClient:
    """Small async client for the official conversation REST resources."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.elevenlabs.io",
        timeout_seconds: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ElevenLabsConfigurationError("ELEVENLABS_API_KEY is required")
        return {"xi-api-key": self._api_key, "Accept": "application/json"}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ElevenLabsAuthenticationError("ElevenLabs authentication failed")
        if response.status_code == 404:
            raise ElevenLabsConversationNotFoundError(
                "ElevenLabs conversation not found"
            )
        if response.status_code >= 400:
            raise ElevenLabsUpstreamError(
                f"ElevenLabs request failed with status {response.status_code}"
            )

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"/v1/convai/conversations/{conversation_id}",
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise ElevenLabsTimeoutError("ElevenLabs request timed out") from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsUpstreamError("ElevenLabs request failed") from exc

        self._raise_for_status(response)
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ElevenLabsMalformedResponseError(
                "ElevenLabs returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("conversation_id"), str
        ):
            raise ElevenLabsMalformedResponseError(
                "ElevenLabs returned an invalid conversation payload"
            )
        return payload

    async def register_twilio_call(
        self,
        *,
        agent_id: str,
        from_number: str,
        to_number: str,
        dynamic_variables: dict[str, str],
    ) -> str:
        """Register an existing outbound Twilio call with an ElevenLabs agent."""

        if not agent_id:
            raise ElevenLabsConfigurationError(
                "ELEVENLABS_CALLER_AGENT_ID is required"
            )
        if not from_number:
            raise ElevenLabsConfigurationError("TWILIO_FROM_NUMBER is required")
        try:
            response = await self._client.post(
                "/v1/convai/twilio/register-call",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={
                    "agent_id": agent_id,
                    "from_number": from_number,
                    "to_number": to_number,
                    "direction": "outbound",
                    "conversation_initiation_client_data": {
                        "dynamic_variables": dynamic_variables,
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise ElevenLabsTimeoutError("ElevenLabs request timed out") from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsUpstreamError("ElevenLabs request failed") from exc
        self._raise_for_status(response)
        if not response.text.strip():
            raise ElevenLabsMalformedResponseError(
                "ElevenLabs returned empty TwiML"
            )
        return response.text

    async def get_conversation_audio(
        self, conversation_id: str
    ) -> AsyncIterator[bytes]:
        """Yield MP3 bytes without buffering the full recording in memory."""

        try:
            async with self._client.stream(
                "GET",
                f"/v1/convai/conversations/{conversation_id}/audio",
                headers=self._headers(),
            ) as response:
                self._raise_for_status(response)
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.TimeoutException as exc:
            raise ElevenLabsTimeoutError("ElevenLabs audio request timed out") from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsUpstreamError("ElevenLabs audio request failed") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class ElevenLabsWebhookVerifier:
    """Verify HMAC webhooks through ElevenLabs' official Python SDK helper."""

    def __init__(self, *, api_key: str, secret: str, app_env: str) -> None:
        self._api_key = api_key
        self._secret = secret
        self._app_env = app_env.lower()

    def verify(self, raw_body: bytes, signature: str | None) -> dict[str, Any]:
        if not self._secret:
            if self._app_env in {"production", "prod", "staging"}:
                raise ElevenLabsConfigurationError(
                    "ELEVENLABS_WEBHOOK_SECRET is required outside development"
                )
            return self._parse_development_payload(raw_body)
        if not signature:
            raise InvalidWebhookSignatureError("Missing ElevenLabs webhook signature")

        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs.errors import BadRequestError
        except ImportError as exc:
            raise ElevenLabsConfigurationError(
                "The ElevenLabs SDK is required for webhook verification"
            ) from exc

        try:
            client = ElevenLabs(api_key=self._api_key or None)
            event = client.webhooks.construct_event(
                rawBody=raw_body.decode("utf-8"),
                sig_header=signature,
                secret=self._secret,
            )
        except (BadRequestError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise InvalidWebhookSignatureError(
                "Invalid ElevenLabs webhook signature"
            ) from exc
        if not isinstance(event, dict):
            raise InvalidWebhookSignatureError("Invalid ElevenLabs webhook payload")
        return event

    @staticmethod
    def _parse_development_payload(raw_body: bytes) -> dict[str, Any]:
        try:
            event = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidWebhookSignatureError(
                "Invalid ElevenLabs webhook payload"
            ) from exc
        if not isinstance(event, dict):
            raise InvalidWebhookSignatureError("Invalid ElevenLabs webhook payload")
        return event
