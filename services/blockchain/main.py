"""
Project Aegis — Blockchain Service
Port 8081 | Internal network only
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from chain import AegisChain, Transaction, ChainFrozenError
from consensus import ValidatorSet, BlockSigner, ConsensusEngine

log = structlog.get_logger()

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY           = os.environ["SECRET_KEY"]
NODE_KEY             = os.environ.get("BLOCKCHAIN_NODE_KEY", "dev-node-key-change-me")
VALIDATOR_KEYS_RAW   = os.environ.get("BLOCKCHAIN_VALIDATOR_KEYS", NODE_KEY)
CHAIN_ID             = int(os.environ.get("CHAIN_ID", "1337"))
BLOCK_TIME           = int(os.environ.get("BLOCK_TIME", "5"))
REDIS_URL            = os.environ.get("REDIS_URL", "redis://localhost:6379")

_start_time = time.time()

# ── Globals ───────────────────────────────────────────────────────────────────

chain:    AegisChain
engine:   ConsensusEngine
redis_client: aioredis.Redis

# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global chain, engine, redis_client

    validator_keys = [k.strip() for k in VALIDATOR_KEYS_RAW.split(",") if k.strip()]
    signer   = BlockSigner(NODE_KEY)
    vs       = ValidatorSet(validator_keys, block_time=BLOCK_TIME)
    engine   = ConsensusEngine(vs, signer, signer.address)
    chain    = AegisChain(chain_id=CHAIN_ID)

    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

    # Subscribe to incoming transaction events
    asyncio.create_task(_consume_tx_queue())
    # Block sealing loop
    asyncio.create_task(_sealing_loop())

    log.info("blockchain.ready", chain_id=CHAIN_ID, height=chain.height)
    yield

    await redis_client.aclose()


app = FastAPI(title="Aegis Blockchain", version="1.0.0", lifespan=lifespan)

# ── Auth ──────────────────────────────────────────────────────────────────────

def _require_internal(x_internal_key: str = Header(...)):
    if x_internal_key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

# ── Schemas ───────────────────────────────────────────────────────────────────

class SubmitTxRequest(BaseModel):
    tx_type: str
    actor:   str
    payload: dict = Field(default_factory=dict)

class FreezeRequest(BaseModel):
    reason: str
    actor:  str

class LiftFreezeRequest(BaseModel):
    actor:         str
    override_code: str

# ── Background tasks ──────────────────────────────────────────────────────────

async def _consume_tx_queue() -> None:
    """Pull transactions published to the Redis 'aegis:tx' stream."""
    while True:
        try:
            items = await redis_client.xread({"aegis:tx": "$"}, block=1000, count=50)
            for _, messages in (items or []):
                for _msg_id, data in messages:
                    try:
                        tx = Transaction(
                            tx_id=data.get("tx_id", str(uuid4())),
                            tx_type=data.get("tx_type", "document"),
                            actor=data.get("actor", "unknown"),
                            payload=json.loads(data.get("payload", "{}")),
                            timestamp=float(data.get("timestamp", time.time())),
                        )
                        chain.submit_transaction(tx)
                    except ChainFrozenError as e:
                        log.warning("tx.rejected.frozen", reason=str(e))
                    except Exception as exc:
                        log.error("tx.consume.error", exc=str(exc))
        except Exception as exc:
            log.error("tx.queue.error", exc=str(exc))
            await asyncio.sleep(2)


async def _sealing_loop() -> None:
    """Periodically seal pending transactions into a new block."""
    while True:
        await asyncio.sleep(BLOCK_TIME)
        try:
            if chain._pending:
                next_idx = chain.height
                if engine.should_propose(next_idx):
                    block = chain.seal_block(
                        validator=engine._address,
                        sign_fn=engine.sign_block,
                    )
                    engine.record_seal()
                    await redis_client.xadd("aegis:blocks", {
                        "index":     str(block.index),
                        "hash":      block.hash,
                        "validator": block.validator,
                        "tx_count":  str(len(block.transactions)),
                        "timestamp": str(block.timestamp),
                    })
                    log.info("block.sealed", index=block.index, txs=len(block.transactions))
        except Exception as exc:
            log.error("sealing.error", exc=str(exc))

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"service": "blockchain", "status": "ok", "height": chain.height,
            "uptime": round(time.time() - _start_time, 1)}


@app.get("/status")
def status(_=Depends(_require_internal)):
    valid, err = chain.validate_chain()
    s = chain.get_status()
    s["chain_valid"] = valid
    s["validation_error"] = err
    s["consensus"] = engine.get_info()
    return s


@app.post("/tx", dependencies=[Depends(_require_internal)])
def submit_tx(req: SubmitTxRequest):
    tx = Transaction(
        tx_id=str(uuid4()),
        tx_type=req.tx_type,
        actor=req.actor,
        payload=req.payload,
    )
    try:
        tx_hash = chain.submit_transaction(tx)
        return {"tx_hash": tx_hash, "status": "pending"}
    except ChainFrozenError as e:
        raise HTTPException(status_code=423, detail=str(e))


@app.get("/block/{index}", dependencies=[Depends(_require_internal)])
def get_block(index: int):
    block = chain.get_block(index)
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    return block.to_dict()


@app.get("/tx/{tx_hash}", dependencies=[Depends(_require_internal)])
def get_tx(tx_hash: str):
    tx = chain.get_transaction(tx_hash)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx.to_dict()


@app.get("/chain", dependencies=[Depends(_require_internal)])
def get_chain(limit: int = 20, offset: int = 0):
    snapshot = chain.to_snapshot()
    total = len(snapshot)
    return {
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "blocks": snapshot[offset: offset + limit],
    }


@app.post("/freeze", dependencies=[Depends(_require_internal)])
def freeze(req: FreezeRequest):
    chain.trigger_hard_freeze(req.reason, req.actor)
    log.warning("chain.frozen", reason=req.reason, actor=req.actor)
    return {"status": "frozen", "reason": req.reason}


@app.post("/freeze/lift", dependencies=[Depends(_require_internal)])
def lift_freeze(req: LiftFreezeRequest):
    chain.lift_freeze(req.actor, req.override_code)
    log.info("chain.unfrozen", actor=req.actor)
    return {"status": "active"}


@app.get("/validate", dependencies=[Depends(_require_internal)])
def validate():
    valid, err = chain.validate_chain()
    return {"valid": valid, "error": err, "height": chain.height}
