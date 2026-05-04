"""
Project Aegis — Payment Gateway Service
Port 8085 | Internal network only
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from tokens import UsageTokenFactory
from ledger import UsageLedger

log = structlog.get_logger()

REDIS_URL         = os.environ.get("REDIS_URL", "redis://localhost:6379")
BLOCKCHAIN_URL    = os.environ.get("BLOCKCHAIN_URL", "http://blockchain:8081")
TOKEN_SIGNING_KEY = os.environ.get("TOKEN_SIGNING_KEY", "payment-dev-key-change-me")
SECRET_KEY        = os.environ["SECRET_KEY"]

_start_time = time.time()

factory:      UsageTokenFactory
ledger:       UsageLedger
redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global factory, ledger, redis_client, http_client
    factory      = UsageTokenFactory(TOKEN_SIGNING_KEY)
    ledger       = UsageLedger()
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)
    log.info("payment.ready")
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Aegis Payment", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


class TokenRequest(BaseModel):
    module_id:  str
    tenant_id:  str
    event_type: str
    metadata:   dict = {}

class VerifyRequest(BaseModel):
    token: str

class StatementRequest(BaseModel):
    tenant_id:    str
    period_start: float
    period_end:   float


@app.get("/health")
def health():
    return {"service": "payment", "status": "ok",
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/token/generate", dependencies=[Depends(_require_internal)])
async def generate_token(req: TokenRequest):
    token_data = factory.generate(req.module_id, req.tenant_id, req.event_type, req.metadata)

    # Record in ledger
    try:
        rec = ledger.record(req.module_id, req.tenant_id, req.event_type, token_data["nonce"])
    except ValueError:
        raise HTTPException(status_code=409, detail="Duplicate token — replay detected")

    # Write usage event to blockchain
    try:
        await http_client.post(
            f"{BLOCKCHAIN_URL}/tx",
            json={
                "tx_type": "audit",
                "actor":   req.tenant_id,
                "payload": {
                    "module_id":  req.module_id,
                    "event_type": req.event_type,
                    "nonce":      token_data["nonce"],
                    "unit_price": rec.unit_price,
                },
            },
            headers={"X-Internal-Key": SECRET_KEY},
        )
    except Exception:
        pass  # blockchain unavailability doesn't block token issuance

    return token_data


@app.post("/token/verify", dependencies=[Depends(_require_internal)])
def verify_token(req: VerifyRequest):
    payload = factory.verify(req.token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return {"valid": True, "payload": payload}


@app.post("/statement", dependencies=[Depends(_require_internal)])
def get_statement(req: StatementRequest):
    stmt = ledger.generate_statement(req.tenant_id, req.period_start, req.period_end)
    return {
        "tenant_id":    stmt.tenant_id,
        "period_start": stmt.period_start,
        "period_end":   stmt.period_end,
        "line_items":   stmt.line_items,
        "total":        stmt.total,
    }


@app.get("/summary/{tenant_id}", dependencies=[Depends(_require_internal)])
def tenant_summary(tenant_id: str):
    return ledger.tenant_summary(tenant_id)
