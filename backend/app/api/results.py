"""Endpoints for Ranking & Reports — thin: call ranking_service, return/broadcast.
No scoring/red-flag math here (see services/ranking.py)."""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.api.voice_errors import as_http_exception
from app.clients.eleven_client import ElevenLabsClient, ElevenLabsError
from app.dependencies.voice import (
    VoiceRepository,
    get_elevenlabs_client,
    get_voice_repository,
)
from app.models.quote import Report
from app.services import ranking
from app.store import quotes

router = APIRouter(prefix="/api/results", tags=["results"])

_connections: dict[str, list[WebSocket]] = {}


@router.get("/{job_spec_id}", response_model=Report)
def get_report(job_spec_id: str):
    return ranking.rank_quotes(job_spec_id, quotes.get(job_spec_id, []))


@router.websocket("/ws/{job_spec_id}")
async def report_updates(websocket: WebSocket, job_spec_id: str):
    """Frontend (P4/Lovable) connects here for live report updates as calls complete."""
    await websocket.accept()
    _connections.setdefault(job_spec_id, []).append(websocket)
    try:
        while True:
            await (
                websocket.receive_text()
            )  # keep-alive; frontend doesn't need to send anything meaningful
    except WebSocketDisconnect:
        _connections[job_spec_id].remove(websocket)


async def broadcast_report_update(job_spec_id: str):
    """Call this (e.g. from api/calls.py after call_completed) to push a fresh
    report to any connected frontend clients."""
    report = ranking.rank_quotes(job_spec_id, quotes.get(job_spec_id, []))
    for ws in _connections.get(job_spec_id, []):
        await ws.send_json(report.model_dump())


@router.get("/calls/{call_id}/transcript")
def get_call_transcript(
    call_id: str,
    repository: VoiceRepository = Depends(get_voice_repository),
):
    artifact = repository.get_artifact(call_id)
    if artifact is None or not artifact.transcript:
        raise HTTPException(status_code=404, detail="transcript not found")
    return {
        "call_id": artifact.call_id,
        "conversation_id": artifact.conversation_id,
        "transcript": [turn.model_dump() for turn in artifact.transcript],
    }


@router.get("/calls/{call_id}/recording")
async def get_call_recording(
    call_id: str,
    repository: VoiceRepository = Depends(get_voice_repository),
    client: ElevenLabsClient = Depends(get_elevenlabs_client),
) -> StreamingResponse:
    artifact = repository.get_artifact(call_id)
    if artifact is None or not artifact.has_recording:
        raise HTTPException(status_code=404, detail="recording not found")
    try:
        payload = await client.get_conversation(artifact.conversation_id)
    except ElevenLabsError as exc:
        raise as_http_exception(exc) from exc
    if payload.get("has_audio") is not True:
        raise HTTPException(status_code=404, detail="recording not found")
    return StreamingResponse(
        client.get_conversation_audio(artifact.conversation_id),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'inline; filename="{call_id}.mp3"'},
    )
