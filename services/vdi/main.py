"""
Project Aegis — VDI Management Service
Port 8087 | Internal network only
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from hypervisor import HypervisorManager, SessionState

log = structlog.get_logger()

REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379")
HERMES_URL   = os.environ.get("HERMES_URL", "http://hermes:8082")
SECRET_KEY   = os.environ["SECRET_KEY"]
SESSION_TTL  = int(os.environ.get("SESSION_TTL", "28800"))

_start_time  = time.time()

hypervisor:   HypervisorManager
redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global hypervisor, redis_client, http_client
    hypervisor   = HypervisorManager(ttl=SESSION_TTL)
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)
    asyncio.create_task(_sweep_loop())
    log.info("vdi.ready", ttl=SESSION_TTL)
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Aegis VDI", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(60)
        terminated = hypervisor.sweep_expired()
        for sid in terminated:
            log.info("vdi.session.swept", session_id=sid)
            await redis_client.xadd("aegis:events", {
                "event_type": "vdi.session.expired",
                "actor":      "vdi",
                "session_id": sid,
                "timestamp":  str(time.time()),
            })


class ProvisionRequest(BaseModel):
    user_id:      str
    tenant_id:    str
    auth_factors: int = 2


class TerminateRequest(BaseModel):
    session_id: str
    reason:     str = "user_logout"


@app.get("/health")
def health():
    return {"service": "vdi", "status": "ok",
            "active_sessions": hypervisor.active_count(),
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/session", dependencies=[Depends(_require_internal)])
async def provision_session(req: ProvisionRequest):
    try:
        session = hypervisor.provision(req.user_id, req.tenant_id, req.auth_factors)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await redis_client.xadd("aegis:events", {
        "event_type": "vdi.session.started",
        "actor":      req.user_id,
        "session_id": session.session_id,
        "timestamp":  str(time.time()),
    })
    return {
        "session_id":   session.session_id,
        "container_id": session.container_id,
        "expires_at":   session.expires_at,
        "state":        session.state,
    }


@app.delete("/session", dependencies=[Depends(_require_internal)])
async def terminate_session(req: TerminateRequest):
    session = hypervisor.terminate(req.session_id, req.reason)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await redis_client.xadd("aegis:events", {
        "event_type": "vdi.session.terminated",
        "actor":      session.user_id,
        "session_id": session.session_id,
        "reason":     req.reason,
        "timestamp":  str(time.time()),
    })
    return {"status": "terminated", "session_id": session.session_id}


@app.get("/session/{session_id}", dependencies=[Depends(_require_internal)])
def get_session(session_id: str):
    session = hypervisor.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id":   session.session_id,
        "user_id":      session.user_id,
        "state":        session.state,
        "expires_at":   session.expires_at,
    }


@app.get("/sessions", dependencies=[Depends(_require_internal)])
def list_sessions():
    return {"sessions": hypervisor.get_all_sessions()}
