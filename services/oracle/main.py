"""
Project Aegis — Oracle Service (AI Project Manager / Smart Contract Auditor)
Port 8084 | Internal network only
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from auditor import OracleAuditor, Invoice, Milestone

log = structlog.get_logger()

REDIS_URL       = os.environ.get("REDIS_URL", "redis://localhost:6379")
BLOCKCHAIN_URL  = os.environ.get("BLOCKCHAIN_URL", "http://blockchain:8081")
HERMES_URL      = os.environ.get("HERMES_URL", "http://hermes:8082")
SECRET_KEY      = os.environ["SECRET_KEY"]

_start_time = time.time()

auditor:      OracleAuditor
redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global auditor, redis_client, http_client
    auditor      = OracleAuditor()
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)
    log.info("oracle.ready")
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Aegis Oracle", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectRequest(BaseModel):
    project_id: str
    name:       str
    budget:     float

class MilestoneRequest(BaseModel):
    project_id:        str
    name:              str
    value:             float
    required_progress: float = 1.0

class MilestoneProgressRequest(BaseModel):
    milestone_id: str
    progress:     float = Field(ge=0.0, le=1.0)

class InvoiceRequest(BaseModel):
    project_id:   str
    milestone_id: str
    amount:       float
    submitted_by: str

class OverrideRequest(BaseModel):
    project_id:    str
    override_code: str
    operator:      str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _chain_write(tx_type: str, actor: str, payload: dict) -> None:
    try:
        await http_client.post(
            f"{BLOCKCHAIN_URL}/tx",
            json={"tx_type": tx_type, "actor": actor, "payload": payload},
            headers={"X-Internal-Key": SECRET_KEY},
        )
    except Exception as e:
        log.warning("oracle.chain_write.failed", exc=str(e))


async def _trigger_chain_freeze(reason: str, actor: str) -> None:
    try:
        await http_client.post(
            f"{BLOCKCHAIN_URL}/freeze",
            json={"reason": reason, "actor": actor},
            headers={"X-Internal-Key": SECRET_KEY},
        )
    except Exception as e:
        log.warning("oracle.chain_freeze.failed", exc=str(e))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "oracle", "status": "ok",
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/project", dependencies=[Depends(_require_internal)])
async def create_project(req: ProjectRequest):
    auditor.register_project(req.project_id, req.name, req.budget)
    await _chain_write("audit", "oracle", {
        "action": "project_registered", "project_id": req.project_id, "budget": req.budget
    })
    return {"status": "ok", "project_id": req.project_id}


@app.post("/milestone", dependencies=[Depends(_require_internal)])
async def add_milestone(req: MilestoneRequest):
    ms = auditor.add_milestone(
        req.project_id, req.name, req.value, req.required_progress
    )
    await _chain_write("audit", "oracle", {
        "action": "milestone_added", "milestone_id": ms.milestone_id
    })
    return {"milestone_id": ms.milestone_id, "name": ms.name}


@app.post("/milestone/progress", dependencies=[Depends(_require_internal)])
async def update_progress(req: MilestoneProgressRequest):
    try:
        auditor.update_milestone_progress(req.milestone_id, req.progress)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await _chain_write("audit", "oracle", {
        "action": "milestone_progress", "milestone_id": req.milestone_id, "progress": req.progress
    })
    return {"status": "ok"}


@app.post("/invoice", dependencies=[Depends(_require_internal)])
async def submit_invoice(req: InvoiceRequest):
    invoice = Invoice(
        invoice_id=str(uuid4()),
        project_id=req.project_id,
        milestone_id=req.milestone_id,
        amount=req.amount,
        submitted_by=req.submitted_by,
    )
    result = auditor.submit_invoice(invoice)

    await _chain_write("financial", req.submitted_by, {
        "invoice_id": invoice.invoice_id,
        "amount":     req.amount,
        "status":     result["status"],
    })

    if result["status"] == "frozen":
        await _trigger_chain_freeze(
            reason=result.get("freeze_reason", "Oracle hard freeze"),
            actor="oracle",
        )
        await redis_client.xadd("aegis:security", {
            "event":  "oracle.hard_freeze",
            "project": req.project_id,
            "reason": result.get("freeze_reason", ""),
            "ts":     str(time.time()),
        })

    return result


@app.post("/override", dependencies=[Depends(_require_internal)])
async def manual_override(req: OverrideRequest):
    ok = auditor.manual_override(req.project_id, req.override_code, req.operator)
    if not ok:
        raise HTTPException(status_code=403, detail="Override denied")
    await http_client.post(
        f"{BLOCKCHAIN_URL}/freeze/lift",
        json={"actor": req.operator, "override_code": req.override_code},
        headers={"X-Internal-Key": SECRET_KEY},
    )
    return {"status": "unfrozen", "project_id": req.project_id}


@app.get("/project/{project_id}", dependencies=[Depends(_require_internal)])
def project_status(project_id: str):
    return auditor.get_project_status(project_id)


@app.get("/freeze/status", dependencies=[Depends(_require_internal)])
def freeze_status():
    frozen = [
        {"project_id": pid} for pid in auditor._frozen_projects
    ]
    return {"frozen_projects": frozen, "count": len(frozen)}


@app.get("/audit", dependencies=[Depends(_require_internal)])
def audit_log(limit: int = 50):
    return {"entries": auditor.get_audit_log(limit)}
