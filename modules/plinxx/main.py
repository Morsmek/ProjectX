"""
Plinxx — Project Management & Workflow Module
Port 8091 | Internal network only

Plinxx is the project execution layer of the Aegis ERP.
It manages tasks, milestones, timelines, and reports.
Every project event is anchored to the blockchain and
cross-validated by the Oracle smart contract engine.
"""
from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field

log = structlog.get_logger()

REDIS_URL    = os.environ.get("REDIS_URL", "redis://localhost:6379")
GATEWAY_URL  = os.environ.get("GATEWAY_URL", "http://gateway:8080")
ORACLE_URL   = os.environ.get("ORACLE_URL", "http://oracle:8084")
PAYMENT_URL  = os.environ.get("PAYMENT_URL", "http://payment:8085")
LICENSE_KEY  = os.environ.get("MODULE_LICENSE_KEY", "plinxx-dev-license")
SECRET_KEY   = os.environ["SECRET_KEY"]
MODULE_ID    = "plinxx"

_start_time = time.time()
_projects: dict[str, dict] = {}
_tasks:    dict[str, dict] = {}

redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)
    await _emit_token("init", "system")
    log.info("plinxx.ready")
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Plinxx", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _emit_token(event_type: str, tenant_id: str) -> None:
    try:
        await http_client.post(
            f"{PAYMENT_URL}/token/generate",
            json={"module_id": MODULE_ID, "tenant_id": tenant_id, "event_type": event_type},
            headers={"X-Internal-Key": SECRET_KEY},
        )
    except Exception:
        pass


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name:        str
    description: str = ""
    budget:      float
    tenant:      str = "default"
    owner:       str

class TaskCreate(BaseModel):
    project_id:  str
    title:       str
    description: str = ""
    assignee:    str = ""
    due_date:    Optional[float] = None
    priority:    str = "medium"  # low | medium | high | critical

class TaskUpdate(BaseModel):
    title:       Optional[str]   = None
    description: Optional[str]   = None
    assignee:    Optional[str]   = None
    status:      Optional[str]   = None  # todo | in_progress | review | done
    progress:    Optional[float] = Field(None, ge=0.0, le=1.0)
    due_date:    Optional[float] = None

class MilestoneCreate(BaseModel):
    project_id: str
    name:       str
    value:      float
    due_date:   Optional[float] = None

class InvoiceSubmit(BaseModel):
    project_id:   str
    milestone_id: str
    amount:       float
    submitted_by: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "plinxx", "status": "ok",
            "projects": len(_projects),
            "tasks":    len(_tasks),
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/projects", dependencies=[Depends(_require_internal)])
async def create_project(req: ProjectCreate):
    project_id = str(uuid4())
    project = {
        "project_id":  project_id,
        "name":        req.name,
        "description": req.description,
        "budget":      req.budget,
        "tenant":      req.tenant,
        "owner":       req.owner,
        "status":      "active",
        "created_at":  time.time(),
        "milestones":  [],
    }
    _projects[project_id] = project

    # Register with Oracle
    try:
        await http_client.post(
            f"{ORACLE_URL}/project",
            json={"project_id": project_id, "name": req.name, "budget": req.budget},
            headers={"X-Internal-Key": SECRET_KEY},
        )
    except Exception:
        pass

    await redis_client.xadd("aegis:tx", {
        "tx_id":     str(uuid4()),
        "tx_type":   "document",
        "actor":     req.owner,
        "payload":   str({"action": "project.create", "project_id": project_id}),
        "timestamp": str(time.time()),
    })
    await _emit_token("transaction", req.tenant)
    return {"project_id": project_id, "name": req.name}


@app.get("/projects", dependencies=[Depends(_require_internal)])
def list_projects(tenant: str = "default"):
    return {"projects": [
        {"project_id": p["project_id"], "name": p["name"],
         "status": p["status"], "budget": p["budget"]}
        for p in _projects.values() if p["tenant"] == tenant
    ]}


@app.get("/projects/{project_id}", dependencies=[Depends(_require_internal)])
async def get_project(project_id: str):
    proj = _projects.get(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    # Get Oracle status
    try:
        resp = await http_client.get(
            f"{ORACLE_URL}/project/{project_id}",
            headers={"X-Internal-Key": SECRET_KEY},
        )
        oracle_status = resp.json()
    except Exception:
        oracle_status = {}
    await _emit_token("query", proj["tenant"])
    return {**proj, "oracle": oracle_status}


@app.post("/tasks", dependencies=[Depends(_require_internal)])
async def create_task(req: TaskCreate):
    proj = _projects.get(req.project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    task_id = str(uuid4())
    task = {
        "task_id":     task_id,
        "project_id":  req.project_id,
        "title":       req.title,
        "description": req.description,
        "assignee":    req.assignee,
        "due_date":    req.due_date,
        "priority":    req.priority,
        "status":      "todo",
        "progress":    0.0,
        "created_at":  time.time(),
        "updated_at":  time.time(),
    }
    _tasks[task_id] = task
    await _emit_token("transaction", proj["tenant"])
    return {"task_id": task_id}


@app.put("/tasks/{task_id}", dependencies=[Depends(_require_internal)])
async def update_task(task_id: str, req: TaskUpdate):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, val in req.model_dump(exclude_none=True).items():
        task[field] = val
    task["updated_at"] = time.time()

    proj = _projects.get(task["project_id"], {})
    await _emit_token("transaction", proj.get("tenant", "default"))
    return {"task_id": task_id, "status": task["status"]}


@app.get("/tasks", dependencies=[Depends(_require_internal)])
def list_tasks(project_id: str, status: Optional[str] = None):
    tasks = [t for t in _tasks.values() if t["project_id"] == project_id]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return {"tasks": tasks}


@app.post("/milestones", dependencies=[Depends(_require_internal)])
async def create_milestone(req: MilestoneCreate):
    proj = _projects.get(req.project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        resp = await http_client.post(
            f"{ORACLE_URL}/milestone",
            json={
                "project_id": req.project_id,
                "name":       req.name,
                "value":      req.value,
            },
            headers={"X-Internal-Key": SECRET_KEY},
        )
        milestone_id = resp.json().get("milestone_id", str(uuid4()))
    except Exception:
        milestone_id = str(uuid4())

    proj["milestones"].append({
        "milestone_id": milestone_id,
        "name":         req.name,
        "value":        req.value,
        "due_date":     req.due_date,
    })
    await _emit_token("transaction", proj["tenant"])
    return {"milestone_id": milestone_id, "name": req.name}


@app.post("/invoices", dependencies=[Depends(_require_internal)])
async def submit_invoice(req: InvoiceSubmit):
    proj = _projects.get(req.project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        resp = await http_client.post(
            f"{ORACLE_URL}/invoice",
            json={
                "project_id":   req.project_id,
                "milestone_id": req.milestone_id,
                "amount":       req.amount,
                "submitted_by": req.submitted_by,
            },
            headers={"X-Internal-Key": SECRET_KEY},
        )
        result = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle unreachable: {e}")

    await _emit_token("transaction", proj["tenant"])
    return result
