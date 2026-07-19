"""Entry point: App initialization & routing.

Only responsibility: create the FastAPI app and mount routers. No business
logic here — see app/api/*.py for routes, app/services/*.py for logic.
"""

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api import calls, results, search, specs
from app.services.stream_handler import handle_media_stream

app = FastAPI(title="The Negotiator — Residential Moving Backend")

# Dev-friendly wildcard: the frontend runs on a different port during local
# testing. Tighten this to a specific origin before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(specs.router)
app.include_router(search.router)
app.include_router(calls.router)
app.include_router(results.router)


# ---------------------------------------------------------------------------
# Twilio WebSocket Media Stream Endpoint
# ---------------------------------------------------------------------------
# Twilio's <Stream> connects here. For each call, we run the full
# Whisper → GPT-4o → ElevenLabs TTS pipeline in real-time.
# ---------------------------------------------------------------------------

@app.websocket("/media-stream/{company_name:path}")
async def media_stream(websocket: WebSocket, company_name: str = "Provider"):
    """WebSocket endpoint for Twilio's <Stream> tag.

    Twilio sends base64 μ-law audio chunks; we transcribe, respond, and
    speak back via ElevenLabs TTS — all in real-time over this connection.
    """
    summary = await handle_media_stream(
        websocket=websocket,
        company_name=company_name,
        service_description="home improvement services",
    )
    # summary is logged server-side; in production, persist to DB


# ---------------------------------------------------------------------------
# TwiML Endpoint for Outbound Calls
# ---------------------------------------------------------------------------
# Twilio fetches this URL when placing an outbound call. The returned TwiML
# tells Twilio to open a <Stream> WebSocket to our /media-stream endpoint.
# The `wss_url` parameter is the publicly-accessible WebSocket origin
# (e.g., "wss://abc123.ngrok.io") so Twilio can reach your server.
# ---------------------------------------------------------------------------

@app.get("/twiml/{company_name:path}", response_class=PlainTextResponse)
async def twiml(
    company_name: str = "Provider",
    wss_url: str = Query(
        default="",
        description=(
            "Public WebSocket origin, e.g. 'wss://abc123.ngrok.io'. "
            "If empty, falls back to wss://localhost:8000 — which only works "
            "for local testing with wss:// (not ws://)."
        ),
    ),
):
    """Return TwiML that connects the call to our WebSocket media stream."""
    base = wss_url if wss_url else "wss://localhost:8000"
    ws_url = f"{base}/media-stream/{company_name}"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}" />
    </Connect>
</Response>"""


@app.get("/health")
def health():
    return {"status": "healthy"}
