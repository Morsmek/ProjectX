"""
Project Aegis — Hermes-2 Guardian Service
Port 8082 | Internal network only

Hermes is the AI security sentinel of the Aegis system:
  1. Inspects every incoming request for threats (sentinel.py)
  2. Manages multi-signature read authorization (multisig.py)
  3. Holds the kill-switch for emergency system transitions (kill_switch.py)
  4. Publishes security events to SDBA via Redis
"""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from sentinel import HermesSentinel
from multisig import MultiSigAuthority
from kill_switch import KillSwitch, SystemState

log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

REDIS_URL         = os.environ.get("REDIS_URL", "redis://localhost:6379")
SECRET_KEY        = os.environ["SECRET_KEY"]
SIGNING_KEY       = os.environ.get("HERMES_SIGNING_KEY", "hermes-dev-key-change-me")
KILL_KEY          = os.environ.get("KILL_SWITCH_KEY", "kill-dev-key-change-me")
THRESHOLD         = int(os.environ.get("MULTISIG_THRESHOLD", "2"))

_start_time = time.time()

# ── Globals ───────────────────────────────────────────────────────────────────

sentinel:    HermesSentinel
multisig:    MultiSigAuthority
kill_switch: KillSwitch
redis_client: aioredis.Redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sentinel, multisig, kill_switch, redis_client

    sentinel     = HermesSentinel()
    kill_switch  = KillSwitch(KILL_KEY)

    # Two built-in signatories; production keys loaded from secret store
    signing_keys = {
        "hermes-primary":   SIGNING_KEY,
        "hermes-secondary": SIGNING_KEY[::-1],
    }
    multisig = MultiSigAuthority(
        threshold=THRESHOLD,
        signing_keys=signing_keys,
        token_key=SIGNING_KEY,
    )

    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    log.info("hermes.ready", threshold=THRESHOLD)
    yield
    await redis_client.aclose()


app = FastAPI(title="Aegis Hermes Guardian", version="1.0.0", lifespan=lifespan)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Schemas ───────────────────────────────────────────────────────────────────

class InspectRequest(BaseModel):
    path:       str
    method:     str = "GET"
    client_ip:  str = "0.0.0.0"
    actor:      str = "unknown"
    timestamp:  float = Field(default_factory=time.time)

class AuthInitRequest(BaseModel):
    actor:    str
    resource: str

class SignRequest(BaseModel):
    request_id:   str
    signatory_id: str
    signature:    str

class KillSwitchRequest(BaseModel):
    actor:  str
    reason: str

class TransitionRequest(BaseModel):
    state:  str
    actor:  str
    reason: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "hermes", "status": "ok",
            "system_state": kill_switch.state,
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/inspect", dependencies=[Depends(_require_internal)])
async def inspect(req: InspectRequest):
    verdict = sentinel.inspect(req.model_dump())
    if verdict["action"] == "block":
        await redis_client.xadd("aegis:security", {
            "event":    "hermes.block",
            "actor":    req.actor,
            "path":     req.path,
            "score":    str(verdict["threat_score"]),
            "rules":    json.dumps(verdict["triggered"]),
            "ts":       str(time.time()),
        })
    return verdict


@app.post("/auth/initiate", dependencies=[Depends(_require_internal)])
def auth_initiate(req: AuthInitRequest):
    pending = multisig.initiate(req.actor, req.resource)
    signatories = list(multisig._keys.keys())
    return {
        "request_id":  pending.request_id,
        "nonce":       pending.nonce,
        "expires_at":  pending.expires_at,
        "required":    pending.threshold,
        "signatories": signatories,
    }


@app.post("/auth/sign", dependencies=[Depends(_require_internal)])
def auth_sign(req: SignRequest):
    ok = multisig.sign(req.request_id, req.signatory_id, req.signature)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid signature or expired request")
    approved = multisig.is_approved(req.request_id)
    token    = multisig.issue_token(req.request_id) if approved else None
    return {"signed": True, "approved": approved, "token": token}


@app.get("/auth/sig/{request_id}/{signatory_id}", dependencies=[Depends(_require_internal)])
def get_expected_sig(request_id: str, signatory_id: str):
    """Debug endpoint: returns the correct sig for a signatory."""
    sig = multisig.generate_sig(request_id, signatory_id)
    if sig is None:
        raise HTTPException(status_code=404, detail="Request or signatory not found")
    return {"signature": sig}


@app.post("/kill", dependencies=[Depends(_require_internal)])
async def activate_kill(req: KillSwitchRequest):
    signed_cmd = kill_switch.activate(req.actor, req.reason)
    await redis_client.publish("aegis:kill", signed_cmd)
    await redis_client.xadd("aegis:security", {
        "event":   "kill_switch.activated",
        "actor":   req.actor,
        "reason":  req.reason,
        "ts":      str(time.time()),
    })
    log.critical("kill_switch.activated", actor=req.actor, reason=req.reason)
    return {"status": "KILL_ACTIVATED", "command": signed_cmd}


@app.post("/transition", dependencies=[Depends(_require_internal)])
def transition(req: TransitionRequest):
    try:
        new_state = SystemState(req.state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown state: {req.state}")
    kill_switch.transition(new_state, req.actor, req.reason)
    return {"status": "ok", "state": new_state}


@app.get("/status", dependencies=[Depends(_require_internal)])
def status():
    return {
        "system_state": kill_switch.get_status(),
        "sentinel":     sentinel.stats(),
    }


@app.post("/unblock/{ip}", dependencies=[Depends(_require_internal)])
def unblock_ip(ip: str):
    sentinel.unblock_ip(ip)
    return {"unblocked": ip}
