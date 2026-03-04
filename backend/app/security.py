"""Simple shared-password auth with session tokens stored in Redis."""

import secrets
from datetime import timedelta

import redis.asyncio as aioredis

from app.config import settings

_redis: aioredis.Redis | None = None

SESSION_PREFIX = "session:"


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def verify_password(password: str) -> bool:
    """Check if the provided password matches the dashboard password."""
    return secrets.compare_digest(password, settings.dashboard_password)


async def create_session() -> str:
    """Create a new session token and store in Redis."""
    token = secrets.token_urlsafe(32)
    r = await get_redis()
    await r.setex(
        f"{SESSION_PREFIX}{token}",
        timedelta(hours=settings.session_ttl_hours),
        "valid",
    )
    return token


async def validate_session(token: str) -> bool:
    """Check if a session token is valid."""
    if not token:
        return False
    r = await get_redis()
    val = await r.get(f"{SESSION_PREFIX}{token}")
    return val == "valid"


async def destroy_session(token: str) -> None:
    """Delete a session token."""
    r = await get_redis()
    await r.delete(f"{SESSION_PREFIX}{token}")
