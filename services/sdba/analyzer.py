"""
SDBA — Security Database Behavior Analytics

Builds per-actor behavioral baselines and scores each event for anomaly.

Technique: Z-score deviation from rolling mean + heuristic rule set.
A score ≥ THRESHOLD triggers an alert and optionally a Hermes state
transition.

SDBA also implements "Targeted Information Discovery" — scanning
internal project flows for emerging risks or synergies.
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

WINDOW = 3600           # 1-hour rolling baseline window
MIN_SAMPLES = 10        # minimum observations before baseline is trusted


@dataclass
class ActorProfile:
    actor:          str
    event_counts:   dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=500)))
    last_seen:      float = 0.0
    total_events:   int   = 0
    risk_score:     float = 0.0


class BehaviorAnalyzer:
    """
    Per-actor behavioral baseline tracker.

    Maintains a rolling window of event counts per event type.
    Anomaly score is computed as the normalized excess above μ + 2σ.
    """

    def __init__(self, threshold: float = 0.75) -> None:
        self._threshold = threshold
        self._profiles: dict[str, ActorProfile] = {}
        self._alert_history: list[dict] = []

    # ── Event ingestion ───────────────────────────────────────────────────

    def record_event(self, actor: str, event_type: str, metadata: dict) -> dict:
        profile = self._get_or_create(actor)
        now     = time.time()
        profile.event_counts[event_type].append(now)
        profile.last_seen  = now
        profile.total_events += 1

        score = self._score(profile, event_type)
        profile.risk_score = max(profile.risk_score * 0.95, score)

        result: dict = {
            "actor":      actor,
            "event_type": event_type,
            "score":      round(score, 4),
            "threshold":  self._threshold,
            "alert":      score >= self._threshold,
        }

        if result["alert"]:
            self._record_alert(result, metadata)

        log.debug("sdba.event", **result)
        return result

    # ── Targeted discovery ────────────────────────────────────────────────

    def discover_patterns(self) -> list[dict]:
        """
        Cross-actor pattern analysis — looks for correlated anomalies
        that might indicate coordinated activity.
        """
        findings: list[dict] = []
        now  = time.time()
        high_risk = [p for p in self._profiles.values() if p.risk_score > 0.5]

        if len(high_risk) >= 2:
            actors = [p.actor for p in high_risk]
            findings.append({
                "type":    "coordinated_risk",
                "actors":  actors,
                "detail":  f"{len(actors)} actors simultaneously elevated",
                "score":   max(p.risk_score for p in high_risk),
            })

        # Detect "quiet then burst" exfiltration pattern
        for actor, profile in self._profiles.items():
            for etype, timestamps in profile.event_counts.items():
                if not timestamps:
                    continue
                recent = [t for t in timestamps if now - t < 300]
                older  = [t for t in timestamps if 300 <= now - t < 3600]
                if older and len(recent) > len(older) * 5:
                    findings.append({
                        "type":   "burst_after_quiet",
                        "actor":  actor,
                        "event":  etype,
                        "detail": f"Burst rate {len(recent)/5:.1f} vs baseline {len(older)/60:.1f}/min",
                        "score":  0.8,
                    })

        return findings

    # ── Query ─────────────────────────────────────────────────────────────

    def get_actor_profile(self, actor: str) -> Optional[dict]:
        p = self._profiles.get(actor)
        if not p:
            return None
        return {
            "actor":       p.actor,
            "risk_score":  round(p.risk_score, 4),
            "total_events": p.total_events,
            "last_seen":   p.last_seen,
            "event_types": list(p.event_counts.keys()),
        }

    def get_alerts(self, limit: int = 50) -> list[dict]:
        return self._alert_history[-limit:]

    def global_stats(self) -> dict:
        return {
            "actors_tracked": len(self._profiles),
            "total_alerts":   len(self._alert_history),
            "high_risk_actors": [
                p.actor for p in self._profiles.values() if p.risk_score > 0.5
            ],
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_or_create(self, actor: str) -> ActorProfile:
        if actor not in self._profiles:
            self._profiles[actor] = ActorProfile(actor=actor)
        return self._profiles[actor]

    def _score(self, profile: ActorProfile, event_type: str) -> float:
        now = time.time()
        dq  = profile.event_counts[event_type]

        # Recent (last 5 min) vs historical rate
        recent_count = sum(1 for t in dq if now - t < 300)
        hist_count   = sum(1 for t in dq if 300 <= now - t < WINDOW)
        hist_minutes = (WINDOW - 300) / 60

        if hist_count < MIN_SAMPLES:
            return 0.0  # not enough baseline

        baseline_rate = hist_count / hist_minutes
        current_rate  = recent_count / 5.0  # per minute

        if baseline_rate == 0:
            return 0.5 if current_rate > 0 else 0.0

        deviation = (current_rate - baseline_rate) / baseline_rate
        score = min(max(deviation / 5.0, 0.0), 1.0)
        return score

    def _record_alert(self, result: dict, metadata: dict) -> None:
        alert = {**result, "metadata": metadata, "timestamp": time.time()}
        self._alert_history.append(alert)
        if len(self._alert_history) > 1000:
            self._alert_history = self._alert_history[-500:]
