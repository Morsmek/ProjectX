"""
Hermes Kill Switch

Broadcasts an emergency KILL command across all registered Aegis nodes.
On receipt, each node drops all active sessions, freezes writes, and
transitions to BLE-mesh-only mode.

The command is signed with KILL_SWITCH_KEY to prevent spoofing.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()


class SystemState(str, Enum):
    NOMINAL   = "nominal"
    ELEVATED  = "elevated"    # increased monitoring
    LOCKDOWN  = "lockdown"    # read-only, extra auth
    BLACKOUT  = "blackout"    # network severed, mesh only
    EMERGENCY = "emergency"   # kill switch activated


class KillSwitch:
    def __init__(self, signing_key: str) -> None:
        self._key   = signing_key
        self._state = SystemState.NOMINAL
        self._history: list[dict] = []

    @property
    def state(self) -> SystemState:
        return self._state

    def sign_command(self, command: str, target: str = "*") -> str:
        payload = f"{command}|{target}|{time.time()}"
        sig = hmac.new(self._key.encode(), payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(f"{payload}|{base64.b64encode(sig).decode()}".encode()).decode()

    def verify_command(self, signed: str) -> Optional[dict]:
        try:
            raw    = base64.urlsafe_b64decode(signed).decode()
            parts  = raw.rsplit("|", 1)
            payload, sig_b64 = parts
            p_parts = payload.split("|")
            command, target, ts = p_parts[0], p_parts[1], float(p_parts[2])
            if time.time() - ts > 120:
                return None  # expired
            expected = hmac.new(self._key.encode(), payload.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(base64.b64decode(sig_b64), expected):
                return None
            return {"command": command, "target": target, "timestamp": ts}
        except Exception:
            return None

    def transition(self, new_state: SystemState, actor: str, reason: str = "") -> None:
        old = self._state
        self._state = new_state
        entry = {
            "from":      old,
            "to":        new_state,
            "actor":     actor,
            "reason":    reason,
            "timestamp": time.time(),
        }
        self._history.append(entry)
        log.warning("kill_switch.transition", **entry)

    def activate(self, actor: str, reason: str) -> str:
        self.transition(SystemState.EMERGENCY, actor, reason)
        return self.sign_command("KILL", target="all")

    def get_status(self) -> dict:
        return {
            "state":   self._state,
            "history": self._history[-20:],
        }
