"""
Project Aegis — SDBA (Security Database Behavior Analytics)
Port 8083 | Internal network only
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from analyzer import BehaviorAnalyzer

log = structlog.get_logger()

REDIS_URL        = os.environ.get("REDIS_URL", "redis://localhost:6379")
HERMES_URL       = os.environ.get("HERMES_URL", "http://hermes:8082")
SECRET_KEY       = os.environ["SECRET_KEY"]
ANOMALY_THRESHOLD = float(os.environ.get("ANOMALY_THRESHOLD", "0.75"))

_start_time = time.time()

analyzer:     BehaviorAnalyzer
redis_client: aioredis.Redis
http_client:  httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    global analyzer, redis_client, http_client

    analyzer     = BehaviorAnalyzer(threshold=ANOMALY_THRESHOLD)
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    http_client  = httpx.AsyncClient(timeout=5.0)

    asyncio.create_task(_consume_event_stream())
    asyncio.create_task(_consume_security_stream())
    asyncio.create_task(_discovery_loop())

    log.info("sdba.ready", threshold=ANOMALY_THRESHOLD)
    yield

    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(title="Aegis SDBA", version="1.0.0", lifespan=lifespan)


def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Background consumers ──────────────────────────────────────────────────────

async def _consume_event_stream() -> None:
    cursor = "$"
    while True:
        try:
            items = await redis_client.xread({"aegis:events": cursor}, block=1000, count=100)
            for _, messages in (items or []):
                for msg_id, data in messages:
                    cursor = msg_id
                    actor      = data.get("actor", "system")
                    event_type = data.get("event_type", "unknown")
                    result = analyzer.record_event(actor, event_type, dict(data))
                    if result["alert"]:
                        await _escalate_alert(result)
        except Exception as exc:
            log.error("sdba.event.consumer.error", exc=str(exc))
            await asyncio.sleep(2)


async def _consume_security_stream() -> None:
    cursor = "$"
    while True:
        try:
            items = await redis_client.xread({"aegis:security": cursor}, block=1000, count=100)
            for _, messages in (items or []):
                for msg_id, data in messages:
                    cursor     = msg_id
                    actor      = data.get("actor", "system")
                    event_type = data.get("event", "security.unknown")
                    score_val  = float(data.get("score", "1.0"))
                    result = analyzer.record_event(actor, event_type, dict(data))
                    result["score"] = max(result["score"], score_val)
                    if result["score"] >= ANOMALY_THRESHOLD:
                        await _escalate_alert(result)
        except Exception as exc:
            log.error("sdba.security.consumer.error", exc=str(exc))
            await asyncio.sleep(2)


async def _discovery_loop() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            findings = analyzer.discover_patterns()
            for finding in findings:
                log.warning("sdba.discovery", **finding)
                if finding.get("score", 0) >= 0.7:
                    await redis_client.xadd("aegis:security", {
                        "event":  "sdba.pattern_discovered",
                        "type":   finding["type"],
                        "detail": finding.get("detail", ""),
                        "score":  str(finding.get("score", 0)),
                        "ts":     str(time.time()),
                    })
        except Exception as exc:
            log.error("sdba.discovery.error", exc=str(exc))


async def _escalate_alert(result: dict) -> None:
    score = result.get("score", 0)
    if score >= 0.9:
        try:
            await http_client.post(
                f"{HERMES_URL}/transition",
                json={"state": "lockdown", "actor": "sdba", "reason": f"High anomaly: {result}"},
                headers={"X-Internal-Key": SECRET_KEY},
            )
        except Exception:
            pass
    await redis_client.xadd("aegis:alerts", {
        "actor":      result.get("actor", ""),
        "event_type": result.get("event_type", ""),
        "score":      str(score),
        "ts":         str(time.time()),
    })


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "sdba", "status": "ok",
            "uptime": round(time.time() - _start_time, 1)}


@app.get("/alerts", dependencies=[Depends(_require_internal)])
def get_alerts(limit: int = 50):
    return {"alerts": analyzer.get_alerts(limit)}


@app.get("/actor/{actor}", dependencies=[Depends(_require_internal)])
def actor_profile(actor: str):
    profile = analyzer.get_actor_profile(actor)
    if not profile:
        raise HTTPException(status_code=404, detail="Actor not tracked")
    return profile


@app.get("/stats", dependencies=[Depends(_require_internal)])
def stats():
    return analyzer.global_stats()


@app.get("/discover", dependencies=[Depends(_require_internal)])
def discover():
    return {"findings": analyzer.discover_patterns()}


class ManualEventRequest(BaseModel):
    actor:      str
    event_type: str
    metadata:   dict = {}


@app.post("/event", dependencies=[Depends(_require_internal)])
def record_event(req: ManualEventRequest):
    result = analyzer.record_event(req.actor, req.event_type, req.metadata)
    return result
