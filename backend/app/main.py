"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, mailboxes, monitor, settings as settings_api, tenants, totp, ws
from app.config import settings
from app.websocket import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: begin WebSocket pub/sub relay
    await manager.start()
    yield
    # Shutdown
    await manager.stop()


app = FastAPI(title="Microsoft Tenant Tool", version="1.0.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(mailboxes.router)
app.include_router(mailboxes.jobs_router)
app.include_router(monitor.router)
app.include_router(settings_api.router)
app.include_router(totp.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
