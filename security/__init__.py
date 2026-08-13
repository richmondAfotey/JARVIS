"""Security monitoring and threat detection subsystem (Phase 28).

Modules:
    * threats.py    - the ThreatAlert model, severity levels and honest
                      status wording.
    * collectors.py - defensive indicator collectors for processes, CPU/
                      RAM, network, startup apps, firewall, logons, files.
    * monitor.py    - ThreatMonitor: periodic scan loop + alert buffer.
"""

from security.monitor import ThreatMonitor
from security.threats import (
    CLEAN_MESSAGE,
    STATUS_HIGH_RISK,
    STATUS_NORMAL,
    STATUS_SUSPICIOUS,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ThreatAlert,
    sort_alerts,
    status_from_alerts,
    status_meta,
)

__all__ = [
    "ThreatMonitor",
    "ThreatAlert",
    "CLEAN_MESSAGE",
    "STATUS_HIGH_RISK",
    "STATUS_NORMAL",
    "STATUS_SUSPICIOUS",
    "SEVERITY_HIGH",
    "SEVERITY_LOW",
    "SEVERITY_MEDIUM",
    "sort_alerts",
    "status_from_alerts",
    "status_meta",
]