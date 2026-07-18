"""Endpoints for Ranking & Reports — thin: call ranking_service, return/broadcast.
No scoring/red-flag math here (see services/ranking.py)."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
            await websocket.receive_text()  # keep-alive; frontend doesn't need to send anything meaningful
    except WebSocketDisconnect:
        _connections[job_spec_id].remove(websocket)


async def broadcast_report_update(job_spec_id: str):
    """Call this (e.g. from api/calls.py after call_completed) to push a fresh
    report to any connected frontend clients."""
    report = ranking.rank_quotes(job_spec_id, quotes.get(job_spec_id, []))
    for ws in _connections.get(job_spec_id, []):
        await ws.send_json(report.model_dump())
