"""Tests for Hermes-2 Sentinel and MultiSig."""
import sys
sys.path.insert(0, 'services/hermes')

from sentinel import HermesSentinel
from multisig import MultiSigAuthority
from kill_switch import KillSwitch, SystemState


def test_sentinel_allows_clean_request():
    s      = HermesSentinel()
    result = s.inspect({"path": "/write", "method": "POST", "client_ip": "10.0.0.1"})
    assert result["action"] == "allow"
    assert result["threat_score"] < 0.3


def test_sentinel_blocks_sql_injection():
    s      = HermesSentinel()
    result = s.inspect({
        "path": "/search?q=1' UNION SELECT * FROM users--",
        "method": "GET",
        "client_ip": "1.2.3.4",
    })
    assert result["action"] == "block"
    assert result["threat_score"] >= 0.7
    assert any(t["rule"] == "sql_injection" for t in result["triggered"])


def test_sentinel_detects_path_traversal():
    s      = HermesSentinel()
    result = s.inspect({"path": "/files/../../etc/passwd", "client_ip": "1.2.3.4"})
    assert result["threat_score"] >= 0.7


def test_multisig_full_flow():
    keys = {"s1": "key-s1", "s2": "key-s2"}
    ms   = MultiSigAuthority(threshold=2, signing_keys=keys, token_key="token-key")

    req  = ms.initiate("alice", "report/q4")
    assert not ms.is_approved(req.request_id)

    sig1 = ms.generate_sig(req.request_id, "s1")
    sig2 = ms.generate_sig(req.request_id, "s2")
    assert sig1 and sig2

    ms.sign(req.request_id, "s1", sig1)
    assert not ms.is_approved(req.request_id)  # only 1 of 2

    ms.sign(req.request_id, "s2", sig2)
    assert ms.is_approved(req.request_id)

    token = ms.issue_token(req.request_id)
    assert token is not None

    # Validate the issued token
    assert ms.validate_token(token, "alice", "report/q4")
    assert not ms.validate_token(token, "eve", "report/q4")


def test_multisig_wrong_signature_rejected():
    keys = {"s1": "key-s1"}
    ms   = MultiSigAuthority(threshold=1, signing_keys=keys, token_key="tk")
    req  = ms.initiate("bob", "db/records")
    ok   = ms.sign(req.request_id, "s1", "definitely-wrong-sig")
    assert not ok


def test_kill_switch_sign_verify():
    ks  = KillSwitch("super-secret")
    cmd = ks.sign_command("KILL", "all")
    result = ks.verify_command(cmd)
    assert result is not None
    assert result["command"] == "KILL"


def test_kill_switch_activate():
    ks  = KillSwitch("super-secret")
    cmd = ks.activate("security-team", "Breach detected")
    assert ks.state == SystemState.EMERGENCY
    result = ks.verify_command(cmd)
    assert result is not None
