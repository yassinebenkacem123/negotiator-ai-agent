import httpx
import pytest
import json

from app.clients.eleven_client import (
    ElevenLabsAuthenticationError,
    ElevenLabsClient,
    ElevenLabsConfigurationError,
    ElevenLabsConversationNotFoundError,
    ElevenLabsMalformedResponseError,
    ElevenLabsTimeoutError,
    ElevenLabsUpstreamError,
    ElevenLabsWebhookVerifier,
    InvalidWebhookSignatureError,
)


def make_client(handler, api_key: str = "test-key") -> ElevenLabsClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        transport=transport, base_url="https://api.elevenlabs.io"
    )
    return ElevenLabsClient(api_key, http_client=http_client)


@pytest.mark.asyncio
async def test_get_conversation_sends_api_key_and_returns_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["xi-api-key"] == "test-key"
        assert request.url.path == "/v1/convai/conversations/conv_123"
        return httpx.Response(
            200, json={"conversation_id": "conv_123", "status": "done"}
        )

    client = make_client(handler)
    assert (await client.get_conversation("conv_123"))["status"] == "done"


@pytest.mark.asyncio
async def test_register_twilio_call_sends_agent_and_dynamic_variables() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/convai/twilio/register-call"
        payload = json.loads(request.content)
        assert payload["agent_id"] == "agent_123"
        assert payload["from_number"] == "+14145550100"
        assert payload["to_number"] == "+212610833077"
        assert payload["direction"] == "outbound"
        assert payload["conversation_initiation_client_data"]["dynamic_variables"]["job_spec_id"] == "spec_123"
        return httpx.Response(200, text="<Response><Connect /></Response>")

    client = make_client(handler)
    twiml = await client.register_twilio_call(
        agent_id="agent_123",
        from_number="+14145550100",
        to_number="+212610833077",
        dynamic_variables={"job_spec_id": "spec_123"},
    )
    assert twiml.startswith("<Response>")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_authentication_errors_are_typed(status: int) -> None:
    client = make_client(lambda request: httpx.Response(status))
    with pytest.raises(ElevenLabsAuthenticationError):
        await client.get_conversation("conv_123")


@pytest.mark.asyncio
async def test_not_found_is_typed() -> None:
    client = make_client(lambda request: httpx.Response(404))
    with pytest.raises(ElevenLabsConversationNotFoundError):
        await client.get_conversation("missing")


@pytest.mark.asyncio
async def test_timeout_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(ElevenLabsTimeoutError):
        await client.get_conversation("conv_123")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"status": "done"}),
        httpx.Response(200, json=[]),
    ],
)
async def test_malformed_responses_are_typed(response: httpx.Response) -> None:
    client = make_client(lambda request: response)
    with pytest.raises(ElevenLabsMalformedResponseError):
        await client.get_conversation("conv_123")


@pytest.mark.asyncio
async def test_general_upstream_failure_is_typed() -> None:
    client = make_client(lambda request: httpx.Response(500))
    with pytest.raises(ElevenLabsUpstreamError):
        await client.get_conversation("conv_123")


@pytest.mark.asyncio
async def test_missing_api_key_fails_clearly() -> None:
    client = make_client(lambda request: httpx.Response(200), api_key="")
    with pytest.raises(ElevenLabsConfigurationError):
        await client.get_conversation("conv_123")


@pytest.mark.asyncio
async def test_audio_is_streamed_in_chunks() -> None:
    client = make_client(lambda request: httpx.Response(200, content=b"mp3-bytes"))
    chunks = [chunk async for chunk in client.get_conversation_audio("conv_123")]
    assert b"".join(chunks) == b"mp3-bytes"


def test_official_webhook_verifier_rejects_invalid_signature() -> None:
    verifier = ElevenLabsWebhookVerifier(
        api_key="test-key",
        secret="test-secret",
        app_env="production",
    )
    with pytest.raises(InvalidWebhookSignatureError):
        verifier.verify(b'{"type":"post_call_transcription"}', "invalid")


def test_production_webhooks_require_a_secret() -> None:
    verifier = ElevenLabsWebhookVerifier(
        api_key="test-key", secret="", app_env="production"
    )
    with pytest.raises(ElevenLabsConfigurationError):
        verifier.verify(b"{}", None)


def test_unsigned_development_webhook_is_parsed_defensively() -> None:
    verifier = ElevenLabsWebhookVerifier(api_key="", secret="", app_env="development")
    assert verifier.verify(b'{"type":"post_call_audio"}', None) == {
        "type": "post_call_audio"
    }
