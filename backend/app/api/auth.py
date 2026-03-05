"""Auth endpoints — login / logout / verify."""

import logging
import time

import redis as sync_redis
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import settings
from app.security import create_session, destroy_session, validate_session, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Rate limiting: max 10 login attempts per IP per 5 minutes
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 300  # seconds
_rate_limit_pool = sync_redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def _check_rate_limit(ip: str):
    """Raise 429 if IP has exceeded login rate limit."""
    r = sync_redis.Redis(connection_pool=_rate_limit_pool)
    key = f"login_rate:{ip}"
    try:
        attempts = r.incr(key)
        if attempts == 1:
            r.expire(key, _RATE_LIMIT_WINDOW)
        if attempts > _RATE_LIMIT_MAX:
            ttl = r.ttl(key)
            logger.warning(f"Login rate limit exceeded for IP {ip}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {ttl} seconds.",
            )
    finally:
        r.close()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    if not verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    token = await create_session()
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=72 * 3600,
    )
    return {"status": "ok"}


@router.post("/logout")
async def logout(response: Response, session_token: str | None = Cookie(default=None)):
    if session_token:
        await destroy_session(session_token)
    response.delete_cookie("session_token")
    return {"status": "ok"}


@router.get("/verify")
async def verify(session_token: str | None = Cookie(default=None)):
    if not session_token or not await validate_session(session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return {"status": "ok"}
