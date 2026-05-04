"""Tests for the BLE mesh and Blackout protocol."""
import sys
sys.path.insert(0, 'services/mesh')

import json
from ble_mesh import BLEMesh, MessageType, MeshMessage
from blackout import BlackoutProtocol, NetworkMode


def _make_node(node_id="node-test"):
    return BLEMesh(node_id, signing_key="mesh-test-key")


def test_create_and_receive_message():
    sender   = _make_node("sender")
    receiver = _make_node("receiver")

    msg = sender.create_message(MessageType.EMERGENCY, {"alert": "test"})
    relay = receiver.receive(msg)

    assert relay is not None
    assert relay.ttl == msg.ttl - 1
    # relay_path records the node that forwarded (receiver), not origin
    assert "receiver" in relay.relay_path


def test_duplicate_message_ignored():
    sender   = _make_node("sender")
    receiver = _make_node("receiver")
    msg = sender.create_message(MessageType.HEARTBEAT, {}, ttl=3)

    r1 = receiver.receive(msg)
    r2 = receiver.receive(msg)   # duplicate
    assert r1 is not None        # first receipt → relay
    assert r2 is None            # duplicate → dropped


def test_own_message_not_relayed():
    node = _make_node("self-node")
    msg  = node.create_message(MessageType.HEARTBEAT, {}, ttl=5)
    # Node receives its own broadcast back — should not relay
    relay = node.receive(msg)
    assert relay is None


def test_ttl_exhaustion():
    sender   = _make_node("s")
    receiver = _make_node("r")
    # TTL=1: after receive, remaining TTL=0 → no further relay
    msg = sender.create_message(MessageType.DATA_RELAY, {"data": "x"}, ttl=1)
    relay = receiver.receive(msg)
    assert relay is None


def test_invalid_signature_rejected():
    node = _make_node()
    msg  = MeshMessage(
        msg_id="fake-id",
        msg_type=MessageType.KILL_SWITCH,
        origin="attacker",
        payload={"command": "KILL"},
        ttl=5,
        timestamp=0,
        signature="invalidsig==",
    )
    result = node.receive(msg)
    assert result is None


def test_blackout_activate_deactivate():
    bp = BlackoutProtocol()
    assert bp.mode == NetworkMode.PRIMARY

    bp.activate("Primary severed", "system")
    assert bp.is_blackout

    bp.queue_write({"tx": "pending"})
    queued = bp.deactivate("operator")
    assert len(queued) == 1
    assert bp.mode == NetworkMode.PRIMARY


def test_blackout_status():
    bp = BlackoutProtocol()
    bp.activate("test", "system")
    s = bp.get_status()
    assert s["mode"] == NetworkMode.BLACKOUT
    assert s["reason"] == "test"
