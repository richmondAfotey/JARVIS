"""
Security monitoring and threat detection (Phase 28).

The `ThreatMonitor` periodically inspects observable indicators of
suspicious activity and raises `ThreatAlert`s. Every alert carries:

    * detected   - what was observed
    * why        - why it is suspicious
    * process    - which process / application is involved
    * when       - when it occurred
    * severity   - low / medium / high
    * recommended- a recommended action

Honesty contract (from the design brief):
    * We never claim the computer is definitely safe. A clean scan reports
      "No obvious indicators of compromise were detected."
    * This module ONLY detects and reports. It never deletes files, kills
      processes, disables security software, edits firewall rules, changes
      passwords, disconnects networks or alters system settings. Acting on
      a high-risk alert is left to the user, who is asked to confirm any
      remediation before it happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

#: Severity of a detected indicator, used to rank the overall status.
SEVERITY_LOW = "low"
SEVERITY_MEDIUM = "medium"
SEVERITY_HIGH = "high"

#: Overall posture labels, matching the security dashboard spec.
STATUS_NORMAL = "normal"
STATUS_SUSPICIOUS = "suspicious"
STATUS_HIGH_RISK = "high_risk"

#: Wording we are allowed to use. We never promise absolute safety.
CLEAN_MESSAGE = "No obvious indicators of compromise were detected."

#: Order used when sorting alerts by severity (highest first).
_SEV_ORDER = {SEVERITY_LOW: 0, SEVERITY_MEDIUM: 1, SEVERITY_HIGH: 2}


@dataclass
class ThreatAlert:
    """A single observable indicator that may need attention."""

    detected: str  # what was detected
    why: str  # why it is suspicious
    process: str  # which process / application is involved
    severity: str = SEVERITY_MEDIUM  # low / medium / high
    recommended: str = ""  # recommended action for the user
    source: str = ""  # which collector produced this alert
    when: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
    )
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "detected": self.detected,
            "why": self.why,
            "process": self.process,
            "severity": self.severity,
            "recommended": self.recommended,
            "source": self.source,
            "when": self.when,
        }

    @property
    def severity_rank(self) -> int:
        return _SEV_ORDER.get(self.severity, 0)


def status_from_alerts(alerts: list[ThreatAlert]) -> str:
    """Overall posture: HIGH_RISK > SUSPICIOUS > NORMAL."""
    worst = max((a.severity_rank for a in alerts), default=_SEV_ORDER[SEVERITY_LOW])
    if worst >= _SEV_ORDER[SEVERITY_HIGH]:
        return STATUS_HIGH_RISK
    if worst >= _SEV_ORDER[SEVERITY_MEDIUM]:
        return STATUS_SUSPICIOUS
    return STATUS_NORMAL


STATUS_META = {
    STATUS_NORMAL: {
        "label": "🟢 NORMAL",
        "color": "#22c55e",
        "message": CLEAN_MESSAGE,
    },
    STATUS_SUSPICIOUS: {
        "label": "🟡 SUSPICIOUS",
        "color": "#fbbf24",
        "message": "Suspicious indicators were detected. Review the alerts "
        "below and investigate before taking further action.",
    },
    STATUS_HIGH_RISK: {
        "label": "🔴 HIGH RISK",
        "color": "#ef4444",
        "message": "High-risk indicators were detected. Treat them seriously, "
        "review each alert, and confirm any remediation step explicitly "
        "before applying it.",
    },
}


def status_meta(status: str) -> dict:
    """Display metadata (label, colour, honest message) for a posture."""
    return STATUS_META.get(status, STATUS_META[STATUS_NORMAL])


def sort_alerts(alerts: list[ThreatAlert]) -> list[ThreatAlert]:
    """Newest and most severe first."""
    return sorted(alerts, key=lambda a: (a.severity_rank, a.when), reverse=True)