"""Auth endpoints — login / logout / verify."""

from fastapi import APIRouter, Cookie, HTTPException, Response, status
from pydantic import BaseModel

from app.security import create_session, destroy_session, validate_session, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response):
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
