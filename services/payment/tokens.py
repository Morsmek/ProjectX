"""
Cryptographic Usage Token System

Every time a licensed module is initialized or processes a transaction,
it calls this service to generate a tamper-proof usage token.
Tokens are HMAC-SHA256 signed and contain:
  • module_id    — which Morten software product
  • tenant_id    — which customer installation
  • event_type   — "init" | "transaction" | "query"
  • issued_at    — Unix timestamp
  • nonce        — UUID4 (prevents replay)

Tokens are stored in the ledger for periodic billing aggregation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4


class UsageTokenFactory:
    def __init__(self, signing_key: str) -> None:
        self._key = signing_key.encode()

    def generate(
        self,
        module_id:  str,
        tenant_id:  str,
        event_type: str,
        metadata:   dict | None = None,
    ) -> dict:
        nonce  = str(uuid4())
        issued = time.time()
        payload = {
            "module_id":  module_id,
            "tenant_id":  tenant_id,
            "event_type": event_type,
            "issued_at":  issued,
            "nonce":      nonce,
            "metadata":   metadata or {},
        }
        canonical = json.dumps(payload, sort_keys=True)
        sig       = hmac.new(self._key, canonical.encode(), hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(
            f"{canonical}||{base64.b64encode(sig).decode()}".encode()
        ).decode()
        return {
            "token":      token,
            "module_id":  module_id,
            "tenant_id":  tenant_id,
            "event_type": event_type,
            "issued_at":  issued,
            "nonce":      nonce,
        }

    def verify(self, token: str) -> dict | None:
        try:
            raw = base64.urlsafe_b64decode(token).decode()
            canonical, sig_b64 = raw.rsplit("||", 1)
            expected = hmac.new(self._key, canonical.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, base64.b64decode(sig_b64)):
                return None
            payload = json.loads(canonical)
            if time.time() - payload["issued_at"] > 86400:
                return None  # token older than 24h
            return payload
        except Exception:
            return None
