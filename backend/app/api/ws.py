"""WebSocket endpoint."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.security import validate_session
from app.websocket import manager

router = APIRouter()


@router.websocket("/ws/live")
async def websocket_endpoint(ws: WebSocket):
    # Check auth from query param or cookie
    token = ws.query_params.get("token") or ws.cookies.get("session_token")
    if not token or not await validate_session(token):
        await ws.accept()
        await ws.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
