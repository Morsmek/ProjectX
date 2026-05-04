"""
Project Aegis — Data Sink Gateway
Port 8080 | Exposed to DMZ network

This service is the sole entry/exit point for the Aegis system:
  • Ingress:  unrestricted write path → queued to blockchain
  • Egress:   requires a valid Hermes multi-sig authorization token
  • Hermes is consulted on every incoming request for threat scoring
"""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from diode import DataDiode, DiodeMode, DiodeViolation
from auth import get_current_user, validate_hermes_token, create_access_token

log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_URL       = os.environ.get("REDIS_URL", "redis://localhost:6379")
HERMES_URL      = os.environ.get("HERMES_URL", "http://hermes:8082")
BLOCKCHAIN_URL  = os.environ.get("BLOCKCHAIN_URL", "http://blockchain:8081")
SECRET_KEY      = os.environ["SECRET_KEY"]
DIODE_MODE_STR  = os.environ.get("DIODE_MODE", "strict")

_start_time = time.time()

# ── Globals ───────────────────────────────────────────────────────────────────

diode:        DataDiode
redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global diode, redis_client, http_client

    mode         = DiodeMode.STRICT if DIODE_MODE_STR == "strict" else DiodeMode.PERMISSIVE
    diode        = DataDiode(mode=mode)
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)

    log.info("gateway.ready", mode=mode)
    yield

    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Aegis Gateway", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Hermes consultation ────────────────────────────────────────────────────────

async def _consult_hermes(request_meta: dict) -> dict:
    try:
        resp = await http_client.post(
            f"{HERMES_URL}/inspect",
            json=request_meta,
            headers={"X-Internal-Key": SECRET_KEY},
        )
        return resp.json()
    except Exception:
        return {"threat_score": 0.0, "action": "allow"}


# ── Middleware: Hermes inspection on every request ────────────────────────────

@app.middleware("http")
async def hermes_inspection_middleware(request: Request, call_next):
    meta = {
        "path":       request.url.path,
        "method":     request.method,
        "client_ip":  request.client.host if request.client else "unknown",
        "timestamp":  time.time(),
    }
    verdict = await _consult_hermes(meta)

    if verdict.get("action") == "block":
        log.warning("gateway.blocked", path=meta["path"], score=verdict.get("threat_score"))
        return JSONResponse(
            status_code=403,
            content={"detail": "Connection severed by Hermes Guardian"},
        )
    return await call_next(request)


# ── Schemas ───────────────────────────────────────────────────────────────────

class WriteRequest(BaseModel):
    tx_type:  str = "document"
    actor:    str
    payload:  dict = Field(default_factory=dict)

class AuthRequest(BaseModel):
    username: str
    password: str
    tenant:   str = "default"

class ReadRequest(BaseModel):
    resource:      str
    hermes_token:  str

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "gateway", "status": "ok",
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/auth/token")
async def get_token(req: AuthRequest):
    """
    Minimal credential exchange (production: integrate with LDAP/SSO).
    Returns a JWT for use on subsequent API calls.
    """
    # Placeholder — real implementation hashes against user DB
    token = create_access_token(req.username, req.tenant, ["user"])
    return {"access_token": token, "token_type": "bearer"}


@app.post("/write")
async def write(req: WriteRequest, user: dict = Depends(get_current_user)):
    """
    INGRESS path — always permitted through the diode.
    Enqueues the transaction to the blockchain service via Redis stream.
    """
    tx_id = str(uuid4())
    diode.record_ingress(user["sub"], req.tx_type)

    await redis_client.xadd("aegis:tx", {
        "tx_id":     tx_id,
        "tx_type":   req.tx_type,
        "actor":     user["sub"],
        "payload":   json.dumps(req.payload),
        "timestamp": str(time.time()),
    })

    # Also publish to SDBA event bus
    await redis_client.xadd("aegis:events", {
        "event_type": "data.write",
        "actor":      user["sub"],
        "tx_type":    req.tx_type,
        "timestamp":  str(time.time()),
    })

    log.info("gateway.write", tx_id=tx_id, actor=user["sub"], tx_type=req.tx_type)
    return {"tx_id": tx_id, "status": "accepted"}


@app.post("/read")
async def read(req: ReadRequest, user: dict = Depends(get_current_user)):
    """
    EGRESS path — gated by the data diode.
    Requires a valid Hermes multi-sig authorization token.
    """
    try:
        authorized = diode.authorize_egress(
            actor=user["sub"],
            resource=req.resource,
            hermes_token=req.hermes_token,
            token_validator=validate_hermes_token,
        )
    except DiodeViolation as e:
        # Publish security alert to SDBA
        await redis_client.xadd("aegis:security", {
            "event":  "diode.violation",
            "actor":  user["sub"],
            "detail": e.reason,
            "ts":     str(time.time()),
        })
        raise HTTPException(status_code=403, detail="Access denied — connection severed")

    if not authorized:
        raise HTTPException(status_code=403, detail="Access denied")

    # Forward authorized read to blockchain
    resp = await http_client.get(
        f"{BLOCKCHAIN_URL}/tx/{req.resource}",
        headers={"X-Internal-Key": SECRET_KEY},
    )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resp.json()


@app.get("/chain/status")
async def chain_status(user: dict = Depends(get_current_user)):
    resp = await http_client.get(
        f"{BLOCKCHAIN_URL}/status",
        headers={"X-Internal-Key": SECRET_KEY},
    )
    return resp.json()


@app.get("/chain/blocks")
async def list_blocks(
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    resp = await http_client.get(
        f"{BLOCKCHAIN_URL}/chain",
        params={"limit": limit, "offset": offset},
        headers={"X-Internal-Key": SECRET_KEY},
    )
    return resp.json()


@app.get("/diode/stats")
async def diode_stats(user: dict = Depends(get_current_user)):
    if "admin" not in user.get("roles", []):
        raise HTTPException(status_code=403, detail="Admin role required")
    return diode.stats()
