"""Tests for the Phase 9 system monitor."""

import sys
from datetime import datetime

import pytest

import system.monitor as monitor


class _FakeVM:
    percent = 63.0
    used = 8 * 1024 ** 3
    total = 16 * 1024 ** 3


class _FakeBattery:
    percent = 82.0
    power_plugged = True


class _FakeNetIO:
    bytes_sent = 5_000_000
    bytes_recv = 7_000_000


def _install_fake_psutil(monkeypatch, *, battery=True, net_rate=0.0):
    """Monkeypatch psutil into the monitor module with fixed values."""

    class FakePartition:
        mountpoint = "C:\\"

    class FakeUsage:
        free = 120 * 1024 ** 3

    class FakePsutil:
        @staticmethod
        def cpu_percent(interval=None):
            return 34.5

        @staticmethod
        def virtual_memory():
            return _FakeVM()

        @staticmethod
        def disk_partitions():
            return [FakePartition()]

        @staticmethod
        def disk_usage(mountpoint):
            return FakeUsage()

        @staticmethod
        def sensors_battery():
            return _FakeBattery() if battery else None

        @staticmethod
        def net_io_counters():
            return _FakeNetIO()

        @staticmethod
        def boot_time():
            return datetime.now().timestamp() - (26 * 3600 + 10 * 60)

    monkeypatch.setattr(monitor, "psutil", FakePsutil)
    monkeypatch.setattr(monitor, "_previous", (0.0, 12_000_000))
    # First call computes the rate from _previous to net totals.
    monkeypatch.setattr(monitor, "_sample_net_rate", lambda total: "3.0 MB/s")


def test_format_uptime():
    assert monitor.format_uptime(26 * 3600 + 10 * 60) == "1d 2h"
    assert monitor.format_uptime(3600 + 30 * 60) == "1h 30m"
    assert monitor.format_uptime(5 * 60) == "5m"


def test_collect_with_psutil(monkeypatch):
    _install_fake_psutil(monkeypatch)
    snapshot = monitor.collect()
    assert snapshot.has_psutil is True
    assert snapshot.cpu_percent == 34.5
    assert snapshot.cpu_text == "34"
    assert snapshot.ram_percent == 63.0
    assert "8.0/16.0" in snapshot.ram_text
    assert snapshot.disk_free == "120.0 GB"
    assert snapshot.battery_percent == 82.0
    assert "charging" in snapshot.battery_text
    assert snapshot.network == "3.0 MB/s"
    assert snapshot.uptime == "1d 2h"


def test_collect_no_battery(monkeypatch):
    _install_fake_psutil(monkeypatch, battery=False)
    snapshot = monitor.collect()
    assert snapshot.battery_percent is None
    assert snapshot.battery_text == "AC"


def test_collect_without_psutil(monkeypatch):
    monkeypatch.setattr(monitor, "psutil", None)
    snapshot = monitor.collect()
    assert snapshot.has_psutil is False
    assert snapshot.cpu_text == "--"
    assert snapshot.ram_text == "--"
    assert snapshot.uptime == "--"


def test_collect_survives_sensor_errors(monkeypatch):
    class Broken:
        @staticmethod
        def cpu_percent(interval=None):
            raise OSError("boom")

        @staticmethod
        def virtual_memory():
            raise OSError("boom")

        @staticmethod
        def disk_partitions():
            raise OSError("boom")

        @staticmethod
        def sensors_battery():
            raise OSError("boom")

        @staticmethod
        def net_io_counters():
            raise OSError("boom")

        @staticmethod
        def boot_time():
            raise OSError("boom")

    monkeypatch.setattr(monitor, "psutil", Broken)
    snapshot = monitor.collect()
    assert snapshot.cpu_text == "--"
    assert snapshot.uptime == "--"
