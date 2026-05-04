"""Tests for the Data Diode."""
import sys
sys.path.insert(0, 'services/gateway')

import pytest
from diode import DataDiode, DiodeMode, DiodeViolation


def _always_valid(token, actor, resource):
    return True

def _always_invalid(token, actor, resource):
    return False


def test_ingress_always_allowed():
    diode = DataDiode(mode=DiodeMode.STRICT)
    diode.record_ingress("terminal-1", "abc123")
    assert diode.stats()["ingress_total"] == 1


def test_authorized_egress():
    diode = DataDiode(mode=DiodeMode.STRICT)
    ok = diode.authorize_egress("alice", "doc/123", "valid-token", _always_valid)
    assert ok
    assert diode.stats()["egress_allowed"] == 1


def test_strict_unauthorized_egress_raises():
    diode = DataDiode(mode=DiodeMode.STRICT)
    with pytest.raises(DiodeViolation) as exc_info:
        diode.authorize_egress("eve", "secret/data", None, _always_invalid)
    assert "eve" in exc_info.value.reason or exc_info.value.actor == "eve"
    assert diode.stats()["egress_denied"] == 1


def test_permissive_unauthorized_egress_returns_false():
    diode = DataDiode(mode=DiodeMode.PERMISSIVE)
    result = diode.authorize_egress("bob", "report", "bad-token", _always_invalid)
    assert result is False
    assert diode.stats()["egress_denied"] == 1


def test_violation_logged():
    diode = DataDiode(mode=DiodeMode.PERMISSIVE)
    diode.authorize_egress("attacker", "db/dump", None, _always_invalid)
    stats = diode.stats()
    assert len(stats["recent_violations"]) == 1
    assert stats["recent_violations"][0]["actor"] == "attacker"
