"""FastAPI dependencies — DB session and auth check."""

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import validate_session


async def get_session(db: AsyncSession = Depends(get_db)):
    """Yield a DB session."""
    yield db


async def check_auth(session_token: str | None = Cookie(default=None)):
    """Verify the session cookie. Raises 401 if invalid."""
    if not session_token or not await validate_session(session_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return session_token
