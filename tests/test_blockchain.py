"""Tests for the PoA Blockchain core."""
import sys
sys.path.insert(0, 'services/blockchain')

import pytest
from chain import AegisChain, Transaction, ChainFrozenError
from consensus import ValidatorSet, BlockSigner


def _make_chain():
    return AegisChain(chain_id=1337)


def _signer(key="test-key"):
    return BlockSigner(key)


def test_genesis_block():
    chain = _make_chain()
    assert chain.height == 1
    genesis = chain.get_block(0)
    assert genesis is not None
    assert genesis.index == 0
    assert genesis.previous_hash == "0" * 64


def test_submit_and_seal():
    chain  = _make_chain()
    signer = _signer()
    tx = Transaction(tx_id="tx1", tx_type="document", actor="alice", payload={"doc": "hello"})
    chain.submit_transaction(tx)
    assert len(chain._pending) == 1

    block = chain.seal_block(validator=signer.address, sign_fn=signer.sign)
    assert chain.height == 2
    assert len(block.transactions) == 1
    assert len(chain._pending) == 0


def test_chain_integrity():
    chain  = _make_chain()
    signer = _signer()
    for i in range(5):
        tx = Transaction(tx_id=f"tx{i}", tx_type="document", actor="bob", payload={"i": i})
        chain.submit_transaction(tx)
        chain.seal_block(signer.address, signer.sign)

    valid, err = chain.validate_chain()
    assert valid, err


def test_chain_tampering_detected():
    chain  = _make_chain()
    signer = _signer()
    tx = Transaction(tx_id="tx1", tx_type="financial", actor="eve", payload={"amount": 1000})
    chain.submit_transaction(tx)
    chain.seal_block(signer.address, signer.sign)

    # Tamper with block
    chain._chain[1].transactions[0].payload["amount"] = 9999999

    valid, err = chain.validate_chain()
    assert not valid


def test_hard_freeze():
    chain  = _make_chain()
    signer = _signer()

    chain.trigger_hard_freeze("Test freeze", "auditor")
    assert chain.is_frozen

    tx = Transaction(tx_id="tx_blocked", tx_type="document", actor="user", payload={})
    with pytest.raises(ChainFrozenError):
        chain.submit_transaction(tx)

    # Audit writes still allowed during freeze
    chain.lift_freeze("admin", "OVERRIDE-123")
    assert not chain.is_frozen


def test_transaction_lookup():
    chain  = _make_chain()
    signer = _signer()
    tx = Transaction(tx_id="find-me", tx_type="audit", actor="sys", payload={"x": 1})
    chain.submit_transaction(tx)
    chain.seal_block(signer.address, signer.sign)

    found = chain.get_transaction(tx.hash)
    assert found is not None
    assert found.tx_id == "find-me"


def test_validator_set_rotation():
    keys = ["v1", "v2", "v3"]
    vs   = ValidatorSet(keys, block_time=5)
    assert vs.in_turn_validator(0) == "v1"
    assert vs.in_turn_validator(1) == "v2"
    assert vs.in_turn_validator(3) == "v1"
    assert vs.is_authorized("v2")
    assert not vs.is_authorized("evil")
