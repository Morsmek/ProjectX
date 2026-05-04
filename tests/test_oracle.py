"""Tests for the Oracle smart contract auditor."""
import sys
sys.path.insert(0, 'services/oracle')

import pytest
from auditor import OracleAuditor, Invoice


def _setup():
    oracle = OracleAuditor()
    oracle.register_project("proj-1", "Office Renovation", 100_000.0)
    ms = oracle.add_milestone("proj-1", "Phase 1 — Foundation", value=30_000.0, required_progress=0.5)
    return oracle, ms


def test_invoice_approved_when_valid():
    oracle, ms = _setup()
    oracle.update_milestone_progress(ms.milestone_id, 0.8)  # above required 0.5
    inv = Invoice(
        invoice_id="inv-1",
        project_id="proj-1",
        milestone_id=ms.milestone_id,
        amount=25_000.0,
        submitted_by="contractor-a",
    )
    result = oracle.submit_invoice(inv)
    assert result["status"] == "approved"


def test_invoice_frozen_milestone_incomplete():
    oracle, ms = _setup()
    oracle.update_milestone_progress(ms.milestone_id, 0.1)  # below required 0.5
    inv = Invoice(
        invoice_id="inv-2",
        project_id="proj-1",
        milestone_id=ms.milestone_id,
        amount=25_000.0,
        submitted_by="contractor-a",
    )
    result = oracle.submit_invoice(inv)
    assert result["status"] == "frozen"
    assert oracle.is_project_frozen("proj-1")


def test_invoice_frozen_amount_exceeds_milestone():
    oracle, ms = _setup()
    oracle.update_milestone_progress(ms.milestone_id, 1.0)
    inv = Invoice(
        invoice_id="inv-3",
        project_id="proj-1",
        milestone_id=ms.milestone_id,
        amount=40_000.0,   # > 30_000 * 1.1 tolerance
        submitted_by="contractor-a",
    )
    result = oracle.submit_invoice(inv)
    assert result["status"] == "frozen"


def test_manual_override_unfreezes():
    oracle, ms = _setup()
    oracle.update_milestone_progress(ms.milestone_id, 0.0)
    inv = Invoice("inv-4", "proj-1", ms.milestone_id, 5_000.0, "user")
    oracle.submit_invoice(inv)
    assert oracle.is_project_frozen("proj-1")

    ok = oracle.manual_override("proj-1", "OVERRIDE-999", "cfo")
    assert ok
    assert not oracle.is_project_frozen("proj-1")


def test_budget_cap_enforced():
    oracle = OracleAuditor()
    oracle.register_project("proj-2", "Small Project", 10_000.0)
    ms = oracle.add_milestone("proj-2", "M1", value=10_000.0, required_progress=0.0)

    inv = Invoice("inv-5", "proj-2", ms.milestone_id, 11_000.0, "user")
    result = oracle.submit_invoice(inv)
    assert result["status"] == "frozen"
