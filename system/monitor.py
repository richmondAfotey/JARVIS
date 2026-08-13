"""
System monitor (Phase 9) - collects real system metrics with psutil.

Everything the UI needs is packed into a single `SystemSnapshot`, so the
UI never has to know about psutil. If psutil is missing or a sensor is
unavailable (e.g. no battery on a desktop), the value is reported as
`None` instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from utils.logger import get_logger

log = get_logger(__name__)

try:  # pragma: no cover - import guard for environments without psutil
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _gb(bytes_value: float) -> str:
    """Format a byte count as GB with one decimal."""
    return f"{bytes_value / (1024 ** 3):.1f}"


def _mbps(bytes_per_sec: float) -> str:
    """Format a transfer rate (bytes/s) as KB/s or MB/s."""
    if bytes_per_sec >= 1024 ** 2:
        return f"{bytes_per_sec / (1024 ** 2):.1f} MB/s"
    return f"{bytes_per_sec / 1024:.1f} KB/s"


def format_uptime(seconds: float) -> str:
    """Format a duration in seconds as 'Xh Ym' or 'Xd Yh'."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@dataclass
class SystemSnapshot:
    """A point-in-time sample of system metrics.

    Values are ready-to-display strings. `None` means "not available"
    (no battery, no psutil, sensor error...).
    """

    cpu_percent: float | None = None
    cpu_text: str = "--"
    ram_percent: float | None = None
    ram_text: str = "--"
    disk_free: str = "--"
    battery_percent: float | None = None
    battery_text: str = "--"
    network: str = "--"
    uptime: str = "--"

    @property
    def has_psutil(self) -> bool:
        return psutil is not None


def collect() -> SystemSnapshot:
    """Gather current system metrics into a snapshot.

    Never raises: every sensor is guarded so the UI keeps updating even
    if one measurement fails.
    """
    snapshot = SystemSnapshot()
    if psutil is None:
        return snapshot

    try:
        snapshot.cpu_percent = psutil.cpu_percent(interval=None)
        snapshot.cpu_text = f"{snapshot.cpu_percent:.0f}"
    except Exception as exc:  # noqa: BLE001 - sensors must never crash the UI
        log.warning("CPU sensor failed: %s", exc)

    try:
        vm = psutil.virtual_memory()
        snapshot.ram_percent = vm.percent
        snapshot.ram_text = (
            f"{vm.percent:.0f}  {_gb(vm.used)}/{_gb(vm.total)} GB"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Memory sensor failed: %s", exc)

    try:
        usage = psutil.disk_usage(psutil.disk_partitions()[0].mountpoint)
        snapshot.disk_free = f"{_gb(usage.free)} GB"
    except Exception as exc:  # noqa: BLE001
        log.warning("Disk sensor failed: %s", exc)

    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            snapshot.battery_percent = battery.percent
            charging = "charging" if battery.power_plugged else "discharging"
            snapshot.battery_text = f"{battery.percent:.0f}%  {charging}"
        else:
            snapshot.battery_text = "AC"
    except Exception as exc:  # noqa: BLE001
        log.warning("Battery sensor failed: %s", exc)

    try:
        counters = psutil.net_io_counters()
        total = counters.bytes_sent + counters.bytes_recv
        snapshot.network = _sample_net_rate(total)
    except Exception as exc:  # noqa: BLE001
        log.warning("Network sensor failed: %s", exc)

    try:
        booted = psutil.boot_time()
        snapshot.uptime = format_uptime(datetime.now().timestamp() - booted)
    except Exception as exc:  # noqa: BLE001
        log.warning("Uptime sensor failed: %s", exc)

    return snapshot


_previous: tuple[float, float] | None = None


def _sample_net_rate(total_bytes: float) -> str:
    """Return the transfer rate since the last call (bytes/s)."""
    global _previous
    now = datetime.now().timestamp()
    if _previous is None:
        _previous = (now, total_bytes)
        return "0.0 KB/s"
    last_time, last_bytes = _previous
    dt = max(now - last_time, 0.001)
    rate = abs(total_bytes - last_bytes) / dt
    _previous = (now, total_bytes)
    return _mbps(rate)
