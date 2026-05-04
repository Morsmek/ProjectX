"""
PoA Consensus — CLIQUE-style round-robin validator rotation.

Validators take turns proposing blocks. If the in-turn validator misses its
slot (configurable BLOCK_TIME), the next validator in the rotation steps in.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional


class ValidatorSet:
    """Ordered set of authority addresses."""

    def __init__(self, validator_keys: list[str], block_time: int = 5) -> None:
        if not validator_keys:
            raise ValueError("At least one validator key required")
        self._keys: list[str] = validator_keys
        self.block_time = block_time
        self._slot_start: float = time.time()

    @property
    def count(self) -> int:
        return len(self._keys)

    def in_turn_validator(self, block_index: int) -> str:
        return self._keys[block_index % self.count]

    def is_authorized(self, address: str) -> bool:
        return address in self._keys

    def add_validator(self, address: str) -> None:
        if address not in self._keys:
            self._keys.append(address)

    def remove_validator(self, address: str) -> None:
        self._keys = [k for k in self._keys if k != address]

    def all_validators(self) -> list[str]:
        return list(self._keys)


class BlockSigner:
    """HMAC-SHA256 block signer (production would use ECDSA secp256k1)."""

    def __init__(self, private_key: str) -> None:
        self._key = private_key.encode()

    def sign(self, block_hash: str) -> str:
        sig = hmac.new(self._key, block_hash.encode(), hashlib.sha256).digest()
        return base64.b64encode(sig).decode()

    def verify(self, block_hash: str, signature: str, public_key: str) -> bool:
        expected = hmac.new(public_key.encode(), block_hash.encode(), hashlib.sha256).digest()
        try:
            provided = base64.b64decode(signature)
            return hmac.compare_digest(expected, provided)
        except Exception:
            return False

    @property
    def address(self) -> str:
        return hashlib.sha256(self._key).hexdigest()[:40]


class ConsensusEngine:
    """Coordinates block proposals and sealing."""

    def __init__(
        self,
        validator_set: ValidatorSet,
        signer: BlockSigner,
        node_address: str,
    ) -> None:
        self._vs      = validator_set
        self._signer  = signer
        self._address = node_address
        self._last_sealed: float = time.time()

    @property
    def is_in_turn(self, block_index: int) -> bool:
        return self._vs.in_turn_validator(block_index) == self._address

    def should_propose(self, next_block_index: int) -> bool:
        elapsed = time.time() - self._last_sealed
        in_turn = self._vs.in_turn_validator(next_block_index) == self._address
        # Allow out-of-turn proposal after 1.5× block time if in-turn validator missed
        if in_turn:
            return elapsed >= self._vs.block_time
        return elapsed >= self._vs.block_time * 1.5

    def sign_block(self, block_hash: str) -> str:
        return self._signer.sign(block_hash)

    def verify_block(self, block_hash: str, signature: str, validator: str) -> bool:
        return self._signer.verify(block_hash, signature, validator)

    def record_seal(self) -> None:
        self._last_sealed = time.time()

    def get_info(self) -> dict:
        return {
            "node_address":   self._address,
            "validators":     self._vs.all_validators(),
            "block_time":     self._vs.block_time,
        }
