"""WebSocket manager + Redis pub/sub relay for real-time progress."""

import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "ws:events"


class ConnectionManager:
    """Manages active WebSocket connections and relays Redis pub/sub messages."""

    def __init__(self):
        self.active: list[WebSocket] = []
        self._pubsub_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        """Send a JSON message to all connected clients."""
        data = json.dumps(message)
        stale = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                logger.warning("WebSocket send failed, removing stale connection", exc_info=True)
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    async def start_pubsub_relay(self):
        """Subscribe to Redis channel and relay messages to WebSocket clients."""
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(CHANNEL)
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        data = json.loads(msg["data"])
                        await self.broadcast(data)
                    except json.JSONDecodeError:
                        pass
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(CHANNEL)
            await r.aclose()

    async def start(self):
        """Start the pub/sub relay as a background task."""
        self._pubsub_task = asyncio.create_task(self.start_pubsub_relay())

    async def stop(self):
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass


manager = ConnectionManager()


async def publish_event(event_type: str, data: dict):
    """Publish an event to the Redis channel (called from Celery tasks or API)."""
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        payload = json.dumps({"type": event_type, **data})
        await r.publish(CHANNEL, payload)
    finally:
        await r.aclose()


def publish_event_sync(event_type: str, data: dict):
    """Synchronous version for use in Celery tasks."""
    import redis as sync_redis

    if not hasattr(publish_event_sync, "_pool"):
        publish_event_sync._pool = sync_redis.ConnectionPool.from_url(
            settings.redis_url, decode_responses=True
        )
    r = sync_redis.Redis(connection_pool=publish_event_sync._pool)
    try:
        payload = json.dumps({"type": event_type, **data})
        r.publish(CHANNEL, payload)
    except Exception:
        logger.warning("Failed to publish WebSocket event via Redis", exc_info=True)
    finally:
        r.close()
