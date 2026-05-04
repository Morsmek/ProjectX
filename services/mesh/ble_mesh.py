"""
BLE Mesh Network Simulation

Models a Bluetooth Low Energy mesh topology for emergency communications
when primary Ethernet/Wi-Fi infrastructure is unavailable.

In production, this layer interfaces with hardware BLE adapters.
In simulation, nodes communicate via a shared Redis pub/sub channel
that represents the radio frequency band.

Message routing uses a flood-fill approach with TTL-limited retransmission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4

import structlog

log = structlog.get_logger()


class MessageType(str, Enum):
    EMERGENCY    = "emergency"
    KILL_SWITCH  = "kill_switch"
    STATUS_PING  = "status_ping"
    STATUS_PONG  = "status_pong"
    DATA_RELAY   = "data_relay"
    HEARTBEAT    = "heartbeat"


@dataclass
class MeshMessage:
    msg_id:       str
    msg_type:     MessageType
    origin:       str
    payload:      dict
    ttl:          int   = 5        # hops remaining
    timestamp:    float = field(default_factory=time.time)
    signature:    str   = ""
    relay_path:   list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "msg_id":     self.msg_id,
            "msg_type":   self.msg_type,
            "origin":     self.origin,
            "payload":    self.payload,
            "ttl":        self.ttl,
            "timestamp":  self.timestamp,
            "signature":  self.signature,
            "relay_path": self.relay_path,
        })

    @classmethod
    def from_json(cls, raw: str) -> "MeshMessage":
        d = json.loads(raw)
        return cls(**d)

    def hop(self, node_id: str) -> "MeshMessage":
        return MeshMessage(
            msg_id=self.msg_id,
            msg_type=self.msg_type,
            origin=self.origin,
            payload=self.payload,
            ttl=self.ttl - 1,
            timestamp=self.timestamp,
            signature=self.signature,
            relay_path=self.relay_path + [node_id],
        )


@dataclass
class MeshNode:
    node_id:    str
    is_online:  bool  = True
    last_seen:  float = field(default_factory=time.time)
    rssi:       int   = -70  # simulated signal strength (dBm)


class BLEMesh:
    """
    Software BLE mesh node.

    Each Aegis hardware box runs one mesh node.  When primary network
    fails the Blackout Protocol activates this layer as the sole
    communication channel.
    """

    CHANNEL = "aegis:ble-mesh"

    def __init__(self, node_id: str, signing_key: str) -> None:
        self._node_id    = node_id
        self._key        = signing_key
        self._peers: dict[str, MeshNode] = {}
        self._seen_msgs: set[str] = set()       # dedup by msg_id
        self._inbox: list[MeshMessage] = []
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self) -> None:
        self._active = True
        log.warning("ble_mesh.activated", node_id=self._node_id)

    def deactivate(self) -> None:
        self._active = False

    def create_message(self, msg_type: MessageType, payload: dict, ttl: int = 5) -> MeshMessage:
        msg = MeshMessage(
            msg_id=str(uuid4()),
            msg_type=msg_type,
            origin=self._node_id,
            payload=payload,
            ttl=ttl,
        )
        msg.signature = self._sign(msg.msg_id, msg.origin, msg.payload)
        return msg

    def receive(self, msg: MeshMessage) -> Optional[MeshMessage]:
        """
        Process an incoming mesh message.
        Returns the message if it should be relayed, None otherwise.
        """
        if msg.msg_id in self._seen_msgs:
            return None  # already processed
        if not self._verify(msg):
            log.warning("ble_mesh.invalid_sig", msg_id=msg.msg_id)
            return None

        self._seen_msgs.add(msg.msg_id)

        # Update peer table
        self._peers[msg.origin] = MeshNode(
            node_id=msg.origin, last_seen=time.time()
        )

        self._inbox.append(msg)
        log.debug("ble_mesh.received", msg_id=msg.msg_id, type=msg.msg_type,
                  origin=msg.origin, ttl=msg.ttl)

        # Relay only if TTL > 1 (i.e. there are hops remaining after this one)
        # and the message did not originate from this node
        if msg.ttl > 1 and msg.origin != self._node_id:
            return msg.hop(self._node_id)
        return None

    def get_inbox(self, msg_type: Optional[MessageType] = None) -> list[MeshMessage]:
        if msg_type:
            return [m for m in self._inbox if m.msg_type == msg_type]
        return list(self._inbox)

    def get_peers(self) -> list[dict]:
        now = time.time()
        return [
            {
                "node_id":  p.node_id,
                "online":   now - p.last_seen < 60,
                "last_seen": p.last_seen,
            }
            for p in self._peers.values()
        ]

    def _sign(self, msg_id: str, origin: str, payload: dict) -> str:
        data = f"{msg_id}|{origin}|{json.dumps(payload, sort_keys=True)}"
        import base64
        sig = hmac.new(self._key.encode(), data.encode(), hashlib.sha256).digest()
        import base64
        return base64.b64encode(sig).decode()

    def _verify(self, msg: MeshMessage) -> bool:
        expected = self._sign(msg.msg_id, msg.origin, msg.payload)
        import base64, hmac as _hmac
        try:
            return _hmac.compare_digest(
                base64.b64decode(msg.signature),
                base64.b64decode(expected)
            )
        except Exception:
            return False
