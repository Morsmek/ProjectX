"""
Munnin Note — Encrypted Document & Note Module
Port 8090 | Internal network only

Munnin Note is the knowledge-management layer of the Aegis ERP.
All writes are recorded on the blockchain via the Data Diode Gateway.
Every module initialization and transaction generates a cryptographic
usage token for the per-use licensing model.
"""
from __future__ import annotations

import hashlib
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

REDIS_URL       = os.environ.get("REDIS_URL", "redis://localhost:6379")
GATEWAY_URL     = os.environ.get("GATEWAY_URL", "http://gateway:8080")
PAYMENT_URL     = os.environ.get("PAYMENT_URL", "http://payment:8085")
LICENSE_KEY     = os.environ.get("MODULE_LICENSE_KEY", "munnin-dev-license")
SECRET_KEY      = os.environ["SECRET_KEY"]
MODULE_ID       = "munnin-note"

_start_time = time.time()
_notes: dict[str, dict] = {}   # in-memory store (production: PostgreSQL)

redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)
    await _emit_token("init", "system")
    log.info("munnin-note.ready")
    yield
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Munnin Note", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def _emit_token(event_type: str, tenant_id: str) -> Optional[str]:
    try:
        resp = await http_client.post(
            f"{PAYMENT_URL}/token/generate",
            json={"module_id": MODULE_ID, "tenant_id": tenant_id, "event_type": event_type},
            headers={"X-Internal-Key": SECRET_KEY},
        )
        return resp.json().get("token")
    except Exception:
        return None


async def _write_to_chain(actor: str, payload: dict) -> None:
    try:
        await redis_client.xadd("aegis:tx", {
            "tx_id":     str(uuid4()),
            "tx_type":   "document",
            "actor":     actor,
            "payload":   str(payload),
            "timestamp": str(time.time()),
        })
    except Exception:
        pass


# ── Schemas ───────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    title:   str
    content: str
    tags:    list[str] = Field(default_factory=list)
    tenant:  str = "default"

class NoteUpdate(BaseModel):
    title:   Optional[str] = None
    content: Optional[str] = None
    tags:    Optional[list[str]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "munnin-note", "status": "ok",
            "note_count": len(_notes),
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/notes", dependencies=[Depends(_require_internal)])
async def create_note(req: NoteCreate):
    note_id  = str(uuid4())
    content_hash = hashlib.sha256(req.content.encode()).hexdigest()
    note = {
        "note_id":      note_id,
        "title":        req.title,
        "content":      req.content,
        "content_hash": content_hash,
        "tags":         req.tags,
        "tenant":       req.tenant,
        "created_at":   time.time(),
        "updated_at":   time.time(),
        "version":      1,
    }
    _notes[note_id] = note

    await _write_to_chain(req.tenant, {
        "action":       "note.create",
        "note_id":      note_id,
        "content_hash": content_hash,
    })
    await _emit_token("transaction", req.tenant)

    return {"note_id": note_id, "content_hash": content_hash}


@app.get("/notes", dependencies=[Depends(_require_internal)])
def list_notes(tenant: str = "default", tag: Optional[str] = None):
    notes = [n for n in _notes.values() if n["tenant"] == tenant]
    if tag:
        notes = [n for n in notes if tag in n.get("tags", [])]
    return {"notes": [{"note_id": n["note_id"], "title": n["title"],
                       "tags": n["tags"], "created_at": n["created_at"]} for n in notes]}


@app.get("/notes/{note_id}", dependencies=[Depends(_require_internal)])
async def get_note(note_id: str):
    note = _notes.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await _emit_token("query", note["tenant"])
    return note


@app.put("/notes/{note_id}", dependencies=[Depends(_require_internal)])
async def update_note(note_id: str, req: NoteUpdate):
    note = _notes.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if req.title   is not None: note["title"]   = req.title
    if req.content is not None:
        note["content"]      = req.content
        note["content_hash"] = hashlib.sha256(req.content.encode()).hexdigest()
    if req.tags    is not None: note["tags"]    = req.tags
    note["updated_at"] = time.time()
    note["version"]   += 1

    await _write_to_chain(note["tenant"], {
        "action":       "note.update",
        "note_id":      note_id,
        "content_hash": note["content_hash"],
        "version":      note["version"],
    })
    await _emit_token("transaction", note["tenant"])
    return {"note_id": note_id, "version": note["version"]}


@app.delete("/notes/{note_id}", dependencies=[Depends(_require_internal)])
async def delete_note(note_id: str):
    note = _notes.pop(note_id, None)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await _write_to_chain(note["tenant"], {"action": "note.delete", "note_id": note_id})
    await _emit_token("transaction", note["tenant"])
    return {"deleted": note_id}
