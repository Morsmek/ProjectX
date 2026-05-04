"""
Blackout Protocol

Activated when:
  1. Primary network (Ethernet/Wi-Fi) is severed, OR
  2. Hermes issues a KILL command

On activation:
  • BLE mesh becomes the sole communication channel
  • All pending blockchain writes are queued locally
  • Only kill-switch and emergency messages are transmitted
  • Restoration is possible only via signed re-join command
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional


class NetworkMode(str, Enum):
    PRIMARY   = "primary"    # Ethernet/Wi-Fi operational
    DEGRADED  = "degraded"   # Partial connectivity
    BLACKOUT  = "blackout"   # BLE mesh only


class BlackoutProtocol:
    def __init__(self) -> None:
        self._mode:     NetworkMode = NetworkMode.PRIMARY
        self._activated_at: Optional[float] = None
        self._reason:   Optional[str] = None
        self._queue:    list[dict] = []  # writes held during blackout
        self._events:   list[dict] = []

    @property
    def mode(self) -> NetworkMode:
        return self._mode

    @property
    def is_blackout(self) -> bool:
        return self._mode == NetworkMode.BLACKOUT

    def activate(self, reason: str, actor: str = "system") -> None:
        self._mode         = NetworkMode.BLACKOUT
        self._activated_at = time.time()
        self._reason       = reason
        self._log_event("blackout.activated", actor, reason)

    def deactivate(self, actor: str) -> list[dict]:
        """Returns queued writes for replay on primary network restoration."""
        self._mode = NetworkMode.PRIMARY
        queued     = list(self._queue)
        self._queue.clear()
        self._log_event("blackout.deactivated", actor)
        return queued

    def queue_write(self, payload: dict) -> None:
        self._queue.append({"payload": payload, "queued_at": time.time()})

    def set_degraded(self, reason: str) -> None:
        self._mode   = NetworkMode.DEGRADED
        self._reason = reason
        self._log_event("network.degraded", "system", reason)

    def get_status(self) -> dict:
        return {
            "mode":          self._mode,
            "activated_at":  self._activated_at,
            "reason":        self._reason,
            "queued_writes": len(self._queue),
            "recent_events": self._events[-10:],
        }

    def _log_event(self, event: str, actor: str, detail: str = "") -> None:
        self._events.append({
            "event":     event,
            "actor":     actor,
            "detail":    detail,
            "timestamp": time.time(),
        })
