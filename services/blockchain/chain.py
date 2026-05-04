"""
Project Aegis — Private PoA Blockchain Core

Implements a CLIQUE-style Proof-of-Authority chain:
  • Blocks are signed by a rotating set of validators (authorities).
  • Each transaction is content-addressed via SHA-256.
  • The chain is append-only; no block can be modified once finalized.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from uuid import uuid4


# ── Transaction ───────────────────────────────────────────────────────────────

@dataclass
class Transaction:
    tx_id:      str
    tx_type:    str          # "document" | "financial" | "audit" | "freeze"
    actor:      str
    payload:    dict
    timestamp:  float = field(default_factory=time.time)
    hash:       str   = field(init=False)

    def __post_init__(self) -> None:
        self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = json.dumps({
            "tx_id":    self.tx_id,
            "tx_type":  self.tx_type,
            "actor":    self.actor,
            "payload":  self.payload,
            "timestamp": self.timestamp,
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        tx = cls(
            tx_id=d["tx_id"],
            tx_type=d["tx_type"],
            actor=d["actor"],
            payload=d["payload"],
            timestamp=d["timestamp"],
        )
        tx.hash = d["hash"]
        return tx


# ── Block ─────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    index:         int
    transactions:  list[Transaction]
    previous_hash: str
    validator:     str          # authority address that sealed the block
    timestamp:     float = field(default_factory=time.time)
    nonce:         str   = field(default_factory=lambda: str(uuid4()))
    hash:          str   = field(init=False)
    signature:     str   = ""   # ECDSA signature by validator

    def __post_init__(self) -> None:
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        block_data = json.dumps({
            "index":         self.index,
            "transactions":  [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash,
            "validator":     self.validator,
            "timestamp":     self.timestamp,
            "nonce":         self.nonce,
        }, sort_keys=True)
        return hashlib.sha256(block_data.encode()).hexdigest()

    def finalize(self, validator_sign_fn) -> None:
        """Re-compute hash and attach validator signature."""
        self.hash = self.compute_hash()
        self.signature = validator_sign_fn(self.hash)

    def to_dict(self) -> dict:
        return {
            "index":         self.index,
            "transactions":  [t.to_dict() for t in self.transactions],
            "previous_hash": self.previous_hash,
            "validator":     self.validator,
            "timestamp":     self.timestamp,
            "nonce":         self.nonce,
            "hash":          self.hash,
            "signature":     self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        txs = [Transaction.from_dict(t) for t in d["transactions"]]
        blk = cls(
            index=d["index"],
            transactions=txs,
            previous_hash=d["previous_hash"],
            validator=d["validator"],
            timestamp=d["timestamp"],
            nonce=d["nonce"],
        )
        blk.hash = d["hash"]
        blk.signature = d.get("signature", "")
        return blk


# ── Blockchain ────────────────────────────────────────────────────────────────

class AegisChain:
    """In-process PoA chain with persistence hooks."""

    GENESIS_PREVIOUS = "0" * 64

    def __init__(self, chain_id: int = 1337) -> None:
        self.chain_id = chain_id
        self._chain: list[Block] = []
        self._pending: list[Transaction] = []
        self._frozen: bool = False
        self._freeze_reason: Optional[str] = None
        self._genesis()

    # ── Genesis ───────────────────────────────────────────────────────────

    def _genesis(self) -> None:
        genesis_tx = Transaction(
            tx_id="genesis",
            tx_type="audit",
            actor="system",
            payload={"message": "Project Aegis chain initialized"},
        )
        genesis = Block(
            index=0,
            transactions=[genesis_tx],
            previous_hash=self.GENESIS_PREVIOUS,
            validator="genesis",
        )
        self._chain.append(genesis)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def height(self) -> int:
        return len(self._chain)

    @property
    def latest_block(self) -> Block:
        return self._chain[-1]

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    # ── Transaction pool ──────────────────────────────────────────────────

    def submit_transaction(self, tx: Transaction) -> str:
        if self._frozen and tx.tx_type not in ("audit", "freeze"):
            raise ChainFrozenError(self._freeze_reason or "Chain is in hard-freeze state")
        self._pending.append(tx)
        return tx.hash

    # ── Block sealing (called by consensus layer) ─────────────────────────

    def seal_block(self, validator: str, sign_fn) -> Block:
        if not self._pending:
            raise ValueError("No pending transactions to seal")
        block = Block(
            index=self.height,
            transactions=list(self._pending),
            previous_hash=self.latest_block.hash,
            validator=validator,
        )
        block.finalize(sign_fn)
        self._chain.append(block)
        self._pending.clear()
        return block

    # ── Freeze / unfreeze ─────────────────────────────────────────────────

    def trigger_hard_freeze(self, reason: str, actor: str) -> None:
        self._frozen = True
        self._freeze_reason = reason
        freeze_tx = Transaction(
            tx_id=str(uuid4()),
            tx_type="freeze",
            actor=actor,
            payload={"reason": reason, "block_height": self.height},
        )
        self._pending.append(freeze_tx)

    def lift_freeze(self, actor: str, override_code: str) -> None:
        self._frozen = False
        self._freeze_reason = None
        lift_tx = Transaction(
            tx_id=str(uuid4()),
            tx_type="audit",
            actor=actor,
            payload={"action": "freeze_lifted", "override_code": override_code},
        )
        self._pending.append(lift_tx)

    # ── Validation ────────────────────────────────────────────────────────

    def validate_chain(self) -> tuple[bool, Optional[str]]:
        for i in range(1, len(self._chain)):
            current  = self._chain[i]
            previous = self._chain[i - 1]
            if current.previous_hash != previous.hash:
                return False, f"Hash mismatch at block {i}"
            if current.hash != current.compute_hash():
                return False, f"Block {i} hash is invalid (tampered)"
        return True, None

    # ── Query ─────────────────────────────────────────────────────────────

    def get_block(self, index: int) -> Optional[Block]:
        if 0 <= index < len(self._chain):
            return self._chain[index]
        return None

    def get_transaction(self, tx_hash: str) -> Optional[Transaction]:
        for block in self._chain:
            for tx in block.transactions:
                if tx.hash == tx_hash:
                    return tx
        return None

    def to_snapshot(self) -> list[dict]:
        return [b.to_dict() for b in self._chain]

    def load_snapshot(self, data: list[dict]) -> None:
        self._chain = [Block.from_dict(d) for d in data]

    def get_status(self) -> dict:
        return {
            "chain_id":       self.chain_id,
            "height":         self.height,
            "latest_hash":    self.latest_block.hash,
            "pending_txs":    len(self._pending),
            "frozen":         self._frozen,
            "freeze_reason":  self._freeze_reason,
        }


class ChainFrozenError(Exception):
    """Raised when a write is attempted on a frozen chain."""
