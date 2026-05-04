"""
Data Diode — Unidirectional Data Flow Enforcement

The diode implements the core security invariant of the Aegis system:
  • Data MAY flow IN (write path) at any time.
  • Data MAY flow OUT (read path) ONLY with a valid multi-signature
    authorization token issued by Hermes.

This is the software analogue of a hardware optical data diode:
ingress is always open; egress requires authenticated authorization.

In STRICT mode a read without a valid Hermes token severs the
connection immediately and logs a security event.
"""
from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()


class DiodeMode(str, Enum):
    STRICT      = "strict"     # unauthorized reads → immediate disconnect
    PERMISSIVE  = "permissive" # unauthorized reads → log + 403


class DiodeViolation(Exception):
    """Raised when an unauthorized egress attempt is detected."""

    def __init__(self, reason: str, actor: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.actor  = actor


class DataDiode:
    """
    Software data diode.

    The diode tracks all ingress events (writes) and enforces that
    egress (reads) can only occur when an authorized multi-sig token
    is presented.
    """

    def __init__(self, mode: DiodeMode = DiodeMode.STRICT) -> None:
        self._mode           = mode
        self._ingress_count  = 0
        self._egress_denied  = 0
        self._egress_allowed = 0
        self._violations: list[dict] = []

    # ── Ingress (always permitted) ────────────────────────────────────────

    def record_ingress(self, source: str, data_hash: str) -> None:
        self._ingress_count += 1
        log.debug("diode.ingress", source=source, hash=data_hash)

    # ── Egress gating ─────────────────────────────────────────────────────

    def authorize_egress(
        self,
        actor: str,
        resource: str,
        hermes_token: Optional[str],
        token_validator,
    ) -> bool:
        """
        Returns True if egress is authorized, raises DiodeViolation in
        STRICT mode or returns False in PERMISSIVE mode.
        """
        if hermes_token and token_validator(hermes_token, actor, resource):
            self._egress_allowed += 1
            log.info("diode.egress.authorized", actor=actor, resource=resource)
            return True

        # Unauthorized egress attempt
        self._egress_denied += 1
        violation = {
            "actor":     actor,
            "resource":  resource,
            "timestamp": time.time(),
            "token_present": hermes_token is not None,
        }
        self._violations.append(violation)
        log.warning("diode.egress.denied", **violation)

        if self._mode == DiodeMode.STRICT:
            raise DiodeViolation(
                f"Unauthorized read of '{resource}' by '{actor}'",
                actor=actor,
            )
        return False

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "mode":             self._mode,
            "ingress_total":    self._ingress_count,
            "egress_allowed":   self._egress_allowed,
            "egress_denied":    self._egress_denied,
            "recent_violations": self._violations[-10:],
        }
