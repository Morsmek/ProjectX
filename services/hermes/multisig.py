"""
Multi-Signature Read Authorization

A read authorization token is valid only when THRESHOLD different
signatories have independently signed the (actor, resource, nonce) tuple.

Each signatory holds a distinct ECDSA-equivalent key (HMAC-SHA256 used
here for portability; production deployments should use secp256k1).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

import structlog

log = structlog.get_logger()


@dataclass
class SignatureRequest:
    request_id: str
    actor:      str
    resource:   str
    nonce:      str
    created_at: float
    signatures: dict[str, str]   # signatory_id → signature
    threshold:  int
    expires_at: float


class MultiSigAuthority:
    """
    Manages pending authorization requests and accumulates signatures.
    When threshold is reached, issues a short-lived JWT-like token.
    """

    def __init__(
        self,
        threshold: int,
        signing_keys: dict[str, str],  # signatory_id → HMAC key
        token_key: str,
        ttl: int = 300,
    ) -> None:
        self._threshold    = threshold
        self._keys         = signing_keys
        self._token_key    = token_key
        self._pending: dict[str, SignatureRequest] = {}
        self._ttl          = ttl

    # ── Public API ────────────────────────────────────────────────────────

    def initiate(self, actor: str, resource: str) -> SignatureRequest:
        req = SignatureRequest(
            request_id=str(uuid4()),
            actor=actor,
            resource=resource,
            nonce=str(uuid4()),
            created_at=time.time(),
            signatures={},
            threshold=self._threshold,
            expires_at=time.time() + self._ttl,
        )
        self._pending[req.request_id] = req
        log.info("multisig.initiated", request_id=req.request_id, actor=actor)
        return req

    def sign(self, request_id: str, signatory_id: str, provided_sig: str) -> bool:
        req = self._pending.get(request_id)
        if not req or time.time() > req.expires_at:
            return False
        if signatory_id not in self._keys:
            return False
        expected = self._compute_sig(req, signatory_id)
        if not hmac.compare_digest(expected, provided_sig):
            log.warning("multisig.bad_signature", signatory=signatory_id)
            return False
        req.signatures[signatory_id] = provided_sig
        log.info("multisig.signed", request_id=request_id, signatory=signatory_id,
                 collected=len(req.signatures), needed=self._threshold)
        return True

    def is_approved(self, request_id: str) -> bool:
        req = self._pending.get(request_id)
        if not req or time.time() > req.expires_at:
            return False
        return len(req.signatures) >= self._threshold

    def issue_token(self, request_id: str) -> Optional[str]:
        if not self.is_approved(request_id):
            return None
        req = self._pending.pop(request_id)
        payload = f"{req.actor}|{req.resource}|{req.nonce}|{time.time() + 600}"
        sig = hmac.new(self._token_key.encode(), payload.encode(), hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(
            f"{payload}|{base64.b64encode(sig).decode()}".encode()
        ).decode()
        log.info("multisig.token_issued", actor=req.actor, resource=req.resource)
        return token

    def validate_token(self, token: str, actor: str, resource: str) -> bool:
        try:
            raw = base64.urlsafe_b64decode(token).decode()
            parts = raw.rsplit("|", 1)
            if len(parts) != 2:
                return False
            payload, sig_b64 = parts
            p_actor, p_resource, _nonce, exp_str = payload.split("|", 3)
            if p_actor != actor or p_resource != resource:
                return False
            if float(exp_str) < time.time():
                return False
            expected = hmac.new(self._token_key.encode(), payload.encode(), hashlib.sha256).digest()
            return hmac.compare_digest(base64.b64decode(sig_b64), expected)
        except Exception:
            return False

    def generate_sig(self, request_id: str, signatory_id: str) -> Optional[str]:
        """Helper: generate the correct signature for a signatory (for testing)."""
        req = self._pending.get(request_id)
        if not req or signatory_id not in self._keys:
            return None
        return self._compute_sig(req, signatory_id)

    # ── Internal ──────────────────────────────────────────────────────────

    def _compute_sig(self, req: SignatureRequest, signatory_id: str) -> str:
        key  = self._keys[signatory_id]
        data = f"{req.request_id}|{req.actor}|{req.resource}|{req.nonce}"
        raw  = hmac.new(key.encode(), data.encode(), hashlib.sha256).digest()
        return base64.b64encode(raw).decode()
