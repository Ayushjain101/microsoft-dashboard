"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, mailboxes, monitor, settings as settings_api, tenants, totp, ws
from app.api.v2 import workflows as v2_workflows, tenants as v2_tenants, mailboxes as v2_mailboxes, monitoring as v2_monitoring, ws as v2_ws
from app.api.v2 import totp as v2_totp, settings as v2_settings
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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Cookie"],
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

# API v2 routers
app.include_router(v2_workflows.router)
app.include_router(v2_tenants.router)
app.include_router(v2_mailboxes.router)
app.include_router(v2_monitoring.router)
app.include_router(v2_ws.router)
app.include_router(v2_totp.router)
app.include_router(v2_settings.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/health")
async def health_detailed():
    """Health check that verifies DB and Redis connectivity."""
    import redis.asyncio as aioredis
    from app.database import engine

    checks = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"

    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:100]}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}
