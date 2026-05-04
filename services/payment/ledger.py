"""
Usage Ledger — records and aggregates per-use billing events.

Per-use model: each cryptographic token represents one billable unit.
The ledger aggregates counts and amounts for periodic invoice generation.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# Pricing per event type per module (example rates)
MODULE_RATES: dict[str, dict[str, float]] = {
    "munnin-note": {
        "init":        0.05,
        "transaction": 0.02,
        "query":       0.01,
    },
    "plinxx": {
        "init":        0.10,
        "transaction": 0.05,
        "query":       0.02,
    },
}

DEFAULT_RATE = 0.01


@dataclass
class UsageRecord:
    record_id:   str
    module_id:   str
    tenant_id:   str
    event_type:  str
    token_nonce: str
    unit_price:  float
    timestamp:   float = field(default_factory=time.time)


@dataclass
class BillingStatement:
    tenant_id:  str
    period_start: float
    period_end:   float
    line_items: list[dict] = field(default_factory=list)
    total:      float = 0.0


class UsageLedger:
    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._nonces:  set[str]          = set()

    def record(
        self,
        module_id:   str,
        tenant_id:   str,
        event_type:  str,
        token_nonce: str,
    ) -> UsageRecord:
        if token_nonce in self._nonces:
            raise ValueError("Duplicate token nonce — replay detected")
        self._nonces.add(token_nonce)

        rate = MODULE_RATES.get(module_id, {}).get(event_type, DEFAULT_RATE)
        rec  = UsageRecord(
            record_id=token_nonce,
            module_id=module_id,
            tenant_id=tenant_id,
            event_type=event_type,
            token_nonce=token_nonce,
            unit_price=rate,
        )
        self._records.append(rec)
        return rec

    def generate_statement(
        self,
        tenant_id:    str,
        period_start: float,
        period_end:   float,
    ) -> BillingStatement:
        relevant = [
            r for r in self._records
            if r.tenant_id == tenant_id
            and period_start <= r.timestamp <= period_end
        ]

        by_module: dict[str, dict[str, list[UsageRecord]]] = defaultdict(lambda: defaultdict(list))
        for r in relevant:
            by_module[r.module_id][r.event_type].append(r)

        stmt  = BillingStatement(tenant_id=tenant_id, period_start=period_start, period_end=period_end)
        total = 0.0
        for module_id, events in by_module.items():
            for event_type, recs in events.items():
                count  = len(recs)
                amount = sum(r.unit_price for r in recs)
                stmt.line_items.append({
                    "module_id":  module_id,
                    "event_type": event_type,
                    "count":      count,
                    "unit_price": recs[0].unit_price,
                    "amount":     round(amount, 4),
                })
                total += amount
        stmt.total = round(total, 4)
        return stmt

    def tenant_summary(self, tenant_id: str) -> dict:
        recs = [r for r in self._records if r.tenant_id == tenant_id]
        return {
            "tenant_id":    tenant_id,
            "total_events": len(recs),
            "total_spend":  round(sum(r.unit_price for r in recs), 4),
            "modules_used": list({r.module_id for r in recs}),
        }
