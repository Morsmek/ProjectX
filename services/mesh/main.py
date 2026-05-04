"""
Project Aegis — BLE Mesh / Blackout Protocol Service
Port 8086 | Internal network only
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from ble_mesh import BLEMesh, MessageType, MeshMessage
from blackout import BlackoutProtocol, NetworkMode

log = structlog.get_logger()

REDIS_URL     = os.environ.get("REDIS_URL", "redis://localhost:6379")
SECRET_KEY    = os.environ["SECRET_KEY"]
NODE_ID       = os.environ.get("MESH_NODE_ID", "node-0")
KILL_KEY      = os.environ.get("KILL_SWITCH_KEY", "kill-dev-key-change-me")

_start_time = time.time()

mesh:         BLEMesh
blackout:     BlackoutProtocol
redis_client: aioredis.Redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mesh, blackout, redis_client
    mesh         = BLEMesh(NODE_ID, KILL_KEY)
    blackout     = BlackoutProtocol()
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    asyncio.create_task(_listen_ble_channel())
    asyncio.create_task(_heartbeat_loop())
    asyncio.create_task(_listen_kill_channel())

    log.info("mesh.ready", node_id=NODE_ID)
    yield
    await redis_client.aclose()


app = FastAPI(title="Aegis Mesh", version="1.0.0", lifespan=lifespan)


def _require_kill(x_kill_switch_key: str = Header(...)):
    if x_kill_switch_key != KILL_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Background tasks ──────────────────────────────────────────────────────────

async def _listen_ble_channel() -> None:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(BLEMesh.CHANNEL)
    async for raw_msg in pubsub.listen():
        if raw_msg["type"] != "message":
            continue
        try:
            msg = MeshMessage.from_json(raw_msg["data"])
            relay = mesh.receive(msg)
            if relay:
                await redis_client.publish(BLEMesh.CHANNEL, relay.to_json())
        except Exception as exc:
            log.error("mesh.receive.error", exc=str(exc))


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(30)
        if mesh.is_active:
            hb = mesh.create_message(
                MessageType.HEARTBEAT,
                {"node_id": NODE_ID, "ts": time.time()},
                ttl=2,
            )
            await redis_client.publish(BLEMesh.CHANNEL, hb.to_json())


async def _listen_kill_channel() -> None:
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("aegis:kill")
    async for raw_msg in pubsub.listen():
        if raw_msg["type"] != "message":
            continue
        try:
            blackout.activate("Kill command received", actor="hermes")
            mesh.activate()
            kill_msg = mesh.create_message(
                MessageType.KILL_SWITCH,
                {"command": "KILL", "origin": NODE_ID},
                ttl=10,
            )
            await redis_client.publish(BLEMesh.CHANNEL, kill_msg.to_json())
        except Exception as exc:
            log.error("mesh.kill.error", exc=str(exc))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "mesh", "status": "ok", "node_id": NODE_ID,
            "mesh_active": mesh.is_active,
            "network_mode": blackout.mode,
            "uptime": round(time.time() - _start_time, 1)}


@app.post("/blackout/activate")
async def activate_blackout(x_kill_switch_key: str = Header(...)):
    if x_kill_switch_key != KILL_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    blackout.activate("Manual activation", actor="operator")
    mesh.activate()
    msg = mesh.create_message(MessageType.EMERGENCY, {"type": "blackout", "node": NODE_ID})
    await redis_client.publish(BLEMesh.CHANNEL, msg.to_json())
    return blackout.get_status()


@app.post("/blackout/deactivate", dependencies=[Depends(_require_internal)])
def deactivate_blackout():
    queued = blackout.deactivate("operator")
    mesh.deactivate()
    return {"status": "primary", "replayed_writes": len(queued)}


@app.get("/status", dependencies=[Depends(_require_internal)])
def status():
    return {
        "blackout": blackout.get_status(),
        "peers":    mesh.get_peers(),
        "inbox_count": len(mesh.get_inbox()),
    }


class BroadcastRequest(BaseModel):
    msg_type: str = "emergency"
    payload:  dict


@app.post("/broadcast", dependencies=[Depends(_require_internal)])
async def broadcast(req: BroadcastRequest):
    try:
        msg_type = MessageType(req.msg_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown message type: {req.msg_type}")
    msg = mesh.create_message(msg_type, req.payload)
    await redis_client.publish(BLEMesh.CHANNEL, msg.to_json())
    return {"msg_id": msg.msg_id, "published": True}


@app.get("/inbox", dependencies=[Depends(_require_internal)])
def inbox(msg_type: str = None):
    mt = MessageType(msg_type) if msg_type else None
    return {"messages": [m.to_json() for m in mesh.get_inbox(mt)]}
