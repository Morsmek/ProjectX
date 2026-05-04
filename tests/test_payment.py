"""Tests for the cryptographic token payment system."""
import sys
sys.path.insert(0, 'services/payment')

import pytest
from tokens import UsageTokenFactory
from ledger import UsageLedger


def test_token_generate_and_verify():
    factory = UsageTokenFactory("test-signing-key")
    tok     = factory.generate("munnin-note", "tenant-abc", "transaction")
    assert tok["token"]
    assert tok["module_id"] == "munnin-note"

    payload = factory.verify(tok["token"])
    assert payload is not None
    assert payload["tenant_id"] == "tenant-abc"
    assert payload["event_type"] == "transaction"


def test_token_tamper_detected():
    factory = UsageTokenFactory("test-signing-key")
    tok     = factory.generate("plinxx", "t1", "init")
    token   = tok["token"]

    # Corrupt the token
    corrupted = token[:-4] + "XXXX"
    assert factory.verify(corrupted) is None


def test_replay_prevention():
    ledger = UsageLedger()
    ledger.record("munnin-note", "t1", "query", "nonce-abc")
    with pytest.raises(ValueError, match="replay"):
        ledger.record("munnin-note", "t1", "query", "nonce-abc")


def test_billing_statement():
    import time
    ledger = UsageLedger()
    start  = time.time()
    for i in range(5):
        ledger.record("plinxx", "tenant-1", "transaction", f"nonce-{i}")
    for i in range(3):
        ledger.record("munnin-note", "tenant-1", "query", f"nonce-m-{i}")
    end = time.time() + 1

    stmt = ledger.generate_statement("tenant-1", start - 1, end)
    assert stmt.total > 0
    assert len(stmt.line_items) == 2

    # plinxx transactions: 5 × 0.05 = 0.25
    plinxx_item = next(i for i in stmt.line_items if i["module_id"] == "plinxx")
    assert plinxx_item["count"] == 5
    assert abs(plinxx_item["amount"] - 0.25) < 0.001


def test_different_signing_keys_incompatible():
    f1 = UsageTokenFactory("key-alpha")
    f2 = UsageTokenFactory("key-beta")
    tok = f1.generate("m", "t", "init")
    assert f2.verify(tok["token"]) is None
