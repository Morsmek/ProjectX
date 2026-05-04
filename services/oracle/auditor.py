"""
Oracle Auditor

Cross-references invoices against project milestones.
Detects discrepancies and triggers Hard Freeze via blockchain service.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import structlog

from contracts import SmartContract, ContractStatus, invoice_milestone_contract, budget_cap_contract

log = structlog.get_logger()


@dataclass
class Milestone:
    milestone_id: str
    project_id:   str
    name:         str
    value:        float          # monetary value associated
    required_progress: float     # 0.0–1.0
    actual_progress:   float = 0.0
    completed:         bool  = False


@dataclass
class Invoice:
    invoice_id:    str
    project_id:    str
    milestone_id:  str
    amount:        float
    submitted_by:  str
    timestamp:     float = field(default_factory=time.time)
    approved:      bool  = False
    freeze_reason: Optional[str] = None


class OracleAuditor:
    """
    The Oracle validates every invoice submission against its
    corresponding project milestone.  If the checks fail, a Hard Freeze
    is triggered on the blockchain until a manual override clears it.
    """

    def __init__(self) -> None:
        self._projects:   dict[str, dict]                       = {}
        self._milestones: dict[str, Milestone]                  = {}
        self._invoices:   dict[str, Invoice]                    = {}
        self._contracts:  dict[str, SmartContract]              = {}
        self._frozen_projects: set[str]                         = set()
        self._audit_log:  list[dict]                            = []

    # ── Project management ────────────────────────────────────────────────

    def register_project(self, project_id: str, name: str, budget: float) -> None:
        self._projects[project_id] = {
            "project_id": project_id,
            "name":       name,
            "budget":     budget,
            "created_at": time.time(),
        }
        cap_contract = budget_cap_contract(project_id, budget)
        self._contracts[cap_contract.contract_id] = cap_contract
        log.info("oracle.project.registered", project_id=project_id, budget=budget)

    def add_milestone(
        self,
        project_id: str,
        name: str,
        value: float,
        required_progress: float = 1.0,
    ) -> Milestone:
        ms = Milestone(
            milestone_id=str(uuid4()),
            project_id=project_id,
            name=name,
            value=value,
            required_progress=required_progress,
        )
        self._milestones[ms.milestone_id] = ms
        return ms

    def update_milestone_progress(self, milestone_id: str, progress: float) -> None:
        ms = self._milestones.get(milestone_id)
        if not ms:
            raise KeyError(f"Milestone {milestone_id} not found")
        ms.actual_progress = min(progress, 1.0)
        ms.completed       = ms.actual_progress >= ms.required_progress
        log.info("oracle.milestone.updated", milestone_id=milestone_id, progress=progress)

    # ── Invoice submission ────────────────────────────────────────────────

    def submit_invoice(self, invoice: Invoice) -> dict:
        """
        Validate invoice against milestone and budget contracts.
        Returns audit result; sets freeze if violations found.
        """
        ms = self._milestones.get(invoice.milestone_id)
        if not ms:
            return self._reject(invoice, "Milestone not found")
        if ms.project_id != invoice.project_id:
            return self._reject(invoice, "Milestone/project mismatch")

        total_invoiced = sum(
            i.amount for i in self._invoices.values()
            if i.project_id == invoice.project_id and i.approved
        ) + invoice.amount

        context = {
            "invoice_amount":        invoice.amount,
            "milestone_value":       ms.value,
            "milestone_progress":    ms.actual_progress,
            "milestone_required":    ms.required_progress,
            "total_invoiced":        total_invoiced,
        }

        # Create and evaluate an invoice-specific contract
        inv_contract = invoice_milestone_contract(
            project_id=invoice.project_id,
            invoice_id=invoice.invoice_id,
            milestone_id=invoice.milestone_id,
            invoice_amount=invoice.amount,
            milestone_value=ms.value,
        )

        # Evaluate budget cap contracts for project
        violations: list[dict] = inv_contract.evaluate(context)
        for c in self._contracts.values():
            if c.project_id == invoice.project_id and c.status == ContractStatus.ACTIVE:
                violations.extend(c.evaluate(context))

        self._invoices[invoice.invoice_id] = invoice

        if violations:
            invoice.freeze_reason = "; ".join(v["condition"] for v in violations)
            self._frozen_projects.add(invoice.project_id)
            self._log_audit(invoice, violations, "FROZEN")
            log.warning("oracle.freeze.triggered", invoice_id=invoice.invoice_id,
                        violations=violations)
            return {
                "status":     "frozen",
                "invoice_id": invoice.invoice_id,
                "violations": violations,
                "freeze_reason": invoice.freeze_reason,
            }

        invoice.approved = True
        self._log_audit(invoice, [], "APPROVED")
        log.info("oracle.invoice.approved", invoice_id=invoice.invoice_id)
        return {
            "status":     "approved",
            "invoice_id": invoice.invoice_id,
            "violations": [],
        }

    def manual_override(self, project_id: str, override_code: str, operator: str) -> bool:
        self._frozen_projects.discard(project_id)
        self._log_audit(None, [], "MANUAL_OVERRIDE",
                        extra={"project_id": project_id, "operator": operator})
        log.info("oracle.freeze.lifted", project_id=project_id, operator=operator)
        return True

    def is_project_frozen(self, project_id: str) -> bool:
        return project_id in self._frozen_projects

    # ── Queries ───────────────────────────────────────────────────────────

    def get_project_status(self, project_id: str) -> dict:
        proj = self._projects.get(project_id)
        if not proj:
            return {"error": "not found"}
        milestones = [
            {"milestone_id": m.milestone_id, "name": m.name,
             "progress": m.actual_progress, "completed": m.completed}
            for m in self._milestones.values() if m.project_id == project_id
        ]
        invoices = [
            {"invoice_id": i.invoice_id, "amount": i.amount,
             "approved": i.approved, "freeze_reason": i.freeze_reason}
            for i in self._invoices.values() if i.project_id == project_id
        ]
        return {
            **proj,
            "frozen":      self.is_project_frozen(project_id),
            "milestones":  milestones,
            "invoices":    invoices,
        }

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        return self._audit_log[-limit:]

    # ── Internal ──────────────────────────────────────────────────────────

    def _reject(self, invoice: Invoice, reason: str) -> dict:
        invoice.freeze_reason = reason
        self._invoices[invoice.invoice_id] = invoice
        return {"status": "rejected", "invoice_id": invoice.invoice_id, "reason": reason}

    def _log_audit(self, invoice: Optional[Invoice], violations: list, outcome: str,
                   extra: dict = {}) -> None:
        entry = {
            "timestamp": time.time(),
            "outcome":   outcome,
            "violations": violations,
            **extra,
        }
        if invoice:
            entry["invoice_id"]  = invoice.invoice_id
            entry["project_id"]  = invoice.project_id
            entry["amount"]      = invoice.amount
        self._audit_log.append(entry)
        if len(self._audit_log) > 2000:
            self._audit_log = self._audit_log[-1000:]
