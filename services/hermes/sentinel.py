"""
Hermes-2 Guardian — Threat Detection Sentinel

Scores every packet/request flowing through the gateway.
Uses a rule-based engine augmented with an exponential moving average
of request rates to detect anomalous patterns.

Actions:
  allow   — pass through
  warn    — log + alert SDBA, pass through
  block   — sever connection immediately
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Optional

import structlog

log = structlog.get_logger()


# ── Threat Rules ──────────────────────────────────────────────────────────────

class Rule:
    def __init__(self, name: str, score: float, description: str) -> None:
        self.name        = name
        self.score       = score
        self.description = description

    def matches(self, request: dict) -> bool:
        raise NotImplementedError


class PathRule(Rule):
    def __init__(self, name: str, score: float, description: str, pattern: str) -> None:
        super().__init__(name, score, description)
        self._re = re.compile(pattern, re.IGNORECASE)

    def matches(self, request: dict) -> bool:
        return bool(self._re.search(request.get("path", "")))


class MethodRule(Rule):
    def __init__(self, name: str, score: float, description: str, allowed: list[str]) -> None:
        super().__init__(name, score, description)
        self._allowed = allowed

    def matches(self, request: dict) -> bool:
        return request.get("method", "").upper() not in self._allowed


DEFAULT_RULES: list[Rule] = [
    PathRule("sql_injection",    0.9, "SQL injection pattern in path",
             r"(union\s+select|drop\s+table|--\s*$|;\s*drop|xp_cmdshell)"),
    PathRule("path_traversal",   0.85, "Directory traversal attempt",
             r"(\.\./|\.\.\\|%2e%2e)"),
    PathRule("secret_probe",     0.8,  "Probing for secrets/config",
             r"/(\.env|\.git|config|secrets?|credentials?|passwd|shadow)"),
    PathRule("admin_bypass",     0.7,  "Admin endpoint probing",
             r"/admin|/root|/superuser"),
    PathRule("bulk_export",      0.6,  "Bulk data export pattern",
             r"/(export|dump|backup|extract)"),
]

# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-IP exponential moving average rate tracker."""

    def __init__(self, window: int = 60, threshold: float = 100.0) -> None:
        self._window    = window
        self._threshold = threshold
        self._ts: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))

    def record(self, ip: str) -> float:
        now = time.time()
        dq  = self._ts[ip]
        dq.append(now)
        cutoff = now - self._window
        while dq and dq[0] < cutoff:
            dq.popleft()
        rate = len(dq) / self._window
        return rate

    def score(self, ip: str) -> float:
        rate = self.record(ip)
        if rate <= self._threshold:
            return 0.0
        excess = (rate - self._threshold) / self._threshold
        return min(excess * 0.4, 0.95)


# ── Sentinel ──────────────────────────────────────────────────────────────────

class HermesSentinel:
    """
    Core threat scoring engine.

    Combines rule-based scoring with IP rate-limit scoring.
    Final score ∈ [0.0, 1.0]:
      < 0.3  → allow
      0.3–0.7 → warn
      ≥ 0.7  → block
    """

    def __init__(self, rules: list[Rule] = DEFAULT_RULES) -> None:
        self._rules       = rules
        self._rate_limiter = RateLimiter()
        self._blocked_ips: set[str] = set()
        self._inspection_count = 0

    def inspect(self, request: dict) -> dict:
        self._inspection_count += 1
        ip   = request.get("client_ip", "unknown")
        path = request.get("path", "")

        if ip in self._blocked_ips:
            return self._verdict(1.0, "block", [{"rule": "ip_blocked", "score": 1.0}])

        triggered: list[dict] = []
        rule_score = 0.0
        for rule in self._rules:
            if rule.matches(request):
                triggered.append({"rule": rule.name, "score": rule.score, "desc": rule.description})
                rule_score = max(rule_score, rule.score)

        rate_score = self._rate_limiter.score(ip)
        total_score = min(rule_score + rate_score * 0.3, 1.0)

        if total_score >= 0.7:
            self._blocked_ips.add(ip)
            action = "block"
        elif total_score >= 0.3:
            action = "warn"
        else:
            action = "allow"

        result = self._verdict(total_score, action, triggered)
        log.debug("hermes.inspect", path=path, score=total_score, action=action)
        return result

    def unblock_ip(self, ip: str) -> None:
        self._blocked_ips.discard(ip)

    def stats(self) -> dict:
        return {
            "inspections":  self._inspection_count,
            "blocked_ips":  len(self._blocked_ips),
            "rule_count":   len(self._rules),
        }

    @staticmethod
    def _verdict(score: float, action: str, triggered: list[dict]) -> dict:
        return {
            "threat_score": round(score, 4),
            "action":       action,
            "triggered":    triggered,
        }
