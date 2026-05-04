"""
Smart Contract Engine

Defines the rules that the Oracle validates against.
Each contract is a set of conditions; violation triggers a Hard Freeze.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4


class ContractStatus(str, Enum):
    ACTIVE    = "active"
    VIOLATED  = "violated"
    COMPLETED = "completed"
    FROZEN    = "frozen"


@dataclass
class ContractCondition:
    name:       str
    description: str
    check: Callable[..., bool]     # returns True if condition is met (not violated)


@dataclass
class SmartContract:
    contract_id: str
    project_id:  str
    name:        str
    conditions:  list[ContractCondition]
    status:      ContractStatus = ContractStatus.ACTIVE
    created_at:  float = field(default_factory=time.time)
    violations:  list[dict] = field(default_factory=list)

    def evaluate(self, context: dict) -> list[dict]:
        """Run all conditions against context; return list of violations."""
        found = []
        for cond in self.conditions:
            try:
                passed = cond.check(context)
            except Exception as e:
                passed = False
                found.append({"condition": cond.name, "error": str(e)})
                continue
            if not passed:
                found.append({"condition": cond.name, "description": cond.description})
        if found:
            self.violations.extend(found)
            self.status = ContractStatus.VIOLATED
        return found


# ── Built-in contract factories ───────────────────────────────────────────────

def invoice_milestone_contract(
    project_id: str,
    invoice_id: str,
    milestone_id: str,
    invoice_amount: float,
    milestone_value: float,
    tolerance: float = 0.10,
) -> SmartContract:
    """
    Validates that an invoice amount does not exceed the milestone value
    by more than the allowed tolerance.
    """
    def check_amount(ctx: dict) -> bool:
        inv = ctx.get("invoice_amount", invoice_amount)
        ms  = ctx.get("milestone_value", milestone_value)
        return inv <= ms * (1 + tolerance)

    def check_milestone_complete(ctx: dict) -> bool:
        return ctx.get("milestone_progress", 0.0) >= ctx.get("milestone_required", 1.0)

    return SmartContract(
        contract_id=str(uuid4()),
        project_id=project_id,
        name=f"Invoice {invoice_id} ↔ Milestone {milestone_id}",
        conditions=[
            ContractCondition(
                name="amount_within_tolerance",
                description=f"Invoice must not exceed milestone value by >{tolerance*100:.0f}%",
                check=check_amount,
            ),
            ContractCondition(
                name="milestone_sufficiently_complete",
                description="Milestone must reach required progress before invoice is payable",
                check=check_milestone_complete,
            ),
        ],
    )


def budget_cap_contract(project_id: str, cap: float) -> SmartContract:
    def check_budget(ctx: dict) -> bool:
        return ctx.get("total_invoiced", 0.0) <= cap

    return SmartContract(
        contract_id=str(uuid4()),
        project_id=project_id,
        name="Project Budget Cap",
        conditions=[
            ContractCondition(
                name="within_budget",
                description=f"Total invoiced must not exceed {cap:,.2f}",
                check=check_budget,
            ),
        ],
    )
