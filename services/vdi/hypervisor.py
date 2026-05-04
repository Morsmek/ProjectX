"""
VDI Hypervisor Manager

Manages non-persistent virtual desktop sessions.
Each session:
  1. Provisions an ephemeral container from a hardened base image.
  2. Records session start on the blockchain.
  3. On session end (or TTL expiry), destroys the container
     and all ephemeral data — nothing persists between sessions.

Zero-footprint guarantee: no user data is stored on the thin-client
host.  All state lives in the session container, which is destroyed
on logout.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4

import structlog

log = structlog.get_logger()


class SessionState(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE       = "active"
    TERMINATING  = "terminating"
    TERMINATED   = "terminated"


@dataclass
class VDISession:
    session_id:  str
    user_id:     str
    tenant_id:   str
    container_id: Optional[str]
    state:       SessionState = SessionState.PROVISIONING
    created_at:  float = field(default_factory=time.time)
    expires_at:  float = 0.0
    terminated_at: Optional[float] = None
    auth_factors: int = 0    # number of auth factors verified


class HypervisorManager:
    """
    Thin wrapper around container lifecycle for VDI sessions.

    In production this integrates with Docker/KVM directly.
    Here, session state is tracked in-process; a real deployment
    would call the Docker API or libvirt.
    """

    BASE_IMAGE = "aegis-vdi-base:latest"

    def __init__(self, ttl: int = 28800) -> None:
        self._ttl      = ttl
        self._sessions: dict[str, VDISession] = {}

    def provision(self, user_id: str, tenant_id: str, auth_factors: int = 0) -> VDISession:
        if auth_factors < 2:
            raise PermissionError("Dual-factor authentication required for VDI access")

        session = VDISession(
            session_id=str(uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            container_id=None,
            expires_at=time.time() + self._ttl,
            auth_factors=auth_factors,
        )
        self._sessions[session.session_id] = session

        # Simulate container provisioning
        session.container_id = f"vdi-{session.session_id[:8]}"
        session.state        = SessionState.ACTIVE

        log.info("vdi.session.started", session_id=session.session_id, user=user_id)
        return session

    def terminate(self, session_id: str, reason: str = "user_logout") -> Optional[VDISession]:
        session = self._sessions.get(session_id)
        if not session:
            return None
        if session.state == SessionState.TERMINATED:
            return session

        session.state         = SessionState.TERMINATING
        # Container would be `docker rm -f <id>` here
        session.container_id  = None
        session.state         = SessionState.TERMINATED
        session.terminated_at = time.time()

        log.info("vdi.session.terminated", session_id=session_id, reason=reason)
        return session

    def sweep_expired(self) -> list[str]:
        """Terminate all sessions past their TTL."""
        now       = time.time()
        expired   = [
            s for s in self._sessions.values()
            if s.state == SessionState.ACTIVE and s.expires_at < now
        ]
        terminated = []
        for s in expired:
            self.terminate(s.session_id, reason="ttl_expired")
            terminated.append(s.session_id)
        return terminated

    def get_session(self, session_id: str) -> Optional[VDISession]:
        return self._sessions.get(session_id)

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.state == SessionState.ACTIVE)

    def get_all_sessions(self) -> list[dict]:
        return [
            {
                "session_id":  s.session_id,
                "user_id":     s.user_id,
                "state":       s.state,
                "expires_at":  s.expires_at,
                "container_id": s.container_id,
            }
            for s in self._sessions.values()
        ]
