"""API v2 — Enhanced WebSocket with topic subscriptions."""

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.security import validate_session
from app.websocket import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket-v2"])


@router.websocket("/ws/v2/live")
async def websocket_v2(
    ws: WebSocket,
    token: str | None = Query(None),
    subscribe: str | None = Query(None),
):
    """Enhanced WebSocket with topic-based subscriptions.

    Query params:
        token: Session token for auth
        subscribe: Comma-separated topics (e.g., 'tenant:uuid,job:uuid')
    """
    # Auth check
    session_token = token or ws.cookies.get("session")
    if not session_token or not await validate_session(session_token):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(ws)

    # Parse subscriptions
    topics: set[str] = set()
    if subscribe:
        topics = {t.strip() for t in subscribe.split(",") if t.strip()}

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "subscribe" and msg.get("topic"):
                    topics.add(msg["topic"])
                elif msg.get("action") == "unsubscribe" and msg.get("topic"):
                    topics.discard(msg["topic"])
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
