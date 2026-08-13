"""Tests for the Phase 28 security monitoring & threat detection subsystem."""

from security.collectors import (
    collect_firewall,
    collect_network,
    collect_processes,
    collect_resources,
    _is_temp_path,
)
from security.monitor import ThreatMonitor
from security.threats import (
    CLEAN_MESSAGE,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    ThreatAlert,
    sort_alerts,
    status_from_alerts,
    status_meta,
)


# -- ThreatAlert model ------------------------------------------------------

def test_alert_defaults_to_medium_with_timestamp():
    alert = ThreatAlert(detected="d", why="w", process="p")
    assert alert.severity == SEVERITY_MEDIUM
    assert alert.when
    assert alert.id


def test_status_high_beats_medium():
    alerts = [
        ThreatAlert(detected="a", why="w", process="p", severity=SEVERITY_MEDIUM),
        ThreatAlert(detected="b", why="w", process="p", severity=SEVERITY_HIGH),
    ]
    assert status_from_alerts(alerts) == "high_risk"


def test_status_medium_is_suspicious():
    alerts = [
        ThreatAlert(detected="a", why="w", process="p", severity=SEVERITY_LOW),
        ThreatAlert(detected="b", why="w", process="p", severity=SEVERITY_MEDIUM),
    ]
    assert status_from_alerts(alerts) == "suspicious"


def test_status_clean_is_normal():
    assert status_from_alerts([]) == "normal"
    alerts = [ThreatAlert(detected="a", why="w", process="p", severity=SEVERITY_LOW)]
    assert status_from_alerts(alerts) == "normal"


def test_normal_wording_is_honest():
    meta = status_meta("normal")
    assert meta["label"] == "🟢 NORMAL"
    assert meta["message"] == CLEAN_MESSAGE
    assert "cannot be hacked" not in meta["message"]
    assert "No obvious indicators of compromise were detected" in meta["message"]


def test_high_risk_meta_no_false_certainty():
    meta = status_meta("high_risk")
    assert meta["label"] == "🔴 HIGH RISK"
    assert "confirm" in meta["message"]


def test_sort_alerts_newest_high_first():
    alerts = [
        ThreatAlert(detected="low", why="w", process="p", severity=SEVERITY_LOW, when="2026-01-02"),
        ThreatAlert(detected="high", why="w", process="p", severity=SEVERITY_HIGH, when="2026-01-01"),
        ThreatAlert(detected="med", why="w", process="p", severity=SEVERITY_MEDIUM, when="2026-01-03"),
    ]
    ordered = sort_alerts(alerts)
    assert [a.detected for a in ordered] == ["high", "med", "low"]


def test_alert_round_trips_to_dict():
    alert = ThreatAlert(detected="d", why="w", process="p")
    data = alert.to_dict()
    assert data["severity"] == SEVERITY_MEDIUM


# -- collectors -------------------------------------------------------------

class _FakeProc:
    def __init__(self, info):
        self.info = info


class _FakePsutil:
    def __init__(self, procs=None, conns=None, cpu=10.0):
        self._procs = procs if procs is not None else []
        self._conns = conns if conns is not None else []
        self._cpu = cpu

    def process_iter(self, attrs):
        if self._procs is None:
            raise RuntimeError("boom")
        return list(self._procs)

    def net_connections(self, kind):
        return self._conns

    def cpu_percent(self, interval=None):
        return self._cpu


class _FakeConn:
    def __init__(self, port, status="ESTABLISHED"):
        self.raddr = type("R", (), {"ip": "1.2.3.4", "port": port})()
        self.status = status


def test_collect_processes_flags_known_malware(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(
        procs=[_FakeProc({"name": "xmrig.exe", "exe": "C:\\bad\\xmrig.exe", "pid": 5})],
    ))
    alerts = collect_processes()
    assert len(alerts) == 1
    assert alerts[0].severity == SEVERITY_HIGH


def test_collect_processes_flags_temp_path(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(
        procs=[_FakeProc({"name": "svc.exe", "exe": "C:\\Users\\x\\AppData\\Local\\Temp\\svc.exe", "pid": 6})],
    ))
    alerts = collect_processes()
    assert len(alerts) == 1
    assert alerts[0].severity == SEVERITY_MEDIUM


def test_collect_processes_survives_psutil_error(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(procs=None))
    assert collect_processes() == []


def test_is_temp_path():
    assert _is_temp_path(r"C:\Users\x\AppData\Local\Temp\a.exe") is True
    assert _is_temp_path(r"C:\Program Files\a.exe") is False
    assert _is_temp_path(r"C:\Users\x\AppData\Local\Programs\a.exe") is False
    assert _is_temp_path("") is False


def test_collect_network_flags_suspicious_port(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(
        conns=[_FakeConn(4444), _FakeConn(80)],
    ))
    alerts = collect_network()
    ports = {a.detected for a in alerts}
    assert any("4444" in p for p in ports)


def test_collect_resources_flags_high_cpu(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(cpu=97))
    alerts = collect_resources()
    assert len(alerts) == 1
    assert alerts[0].severity == SEVERITY_MEDIUM


def test_collect_resources_normal(monkeypatch):
    monkeypatch.setattr("security.collectors.psutil", _FakePsutil(cpu=20))
    assert collect_resources() == []


def test_collect_firewall_flags_off(monkeypatch):
    class _Result:
        returncode = 0
        stdout = (
            "Domain Profile Settings:\nState                                 OFF\n\n"
            "Private Profile Settings:\nState                                 ON\n"
        )

    def fake_run(*args, **kwargs):
        return _Result()

    monkeypatch.setattr("security.collectors.subprocess.run", fake_run)
    alerts = collect_firewall()
    assert len(alerts) == 1
    assert alerts[0].severity == SEVERITY_HIGH
    assert "Domain" in alerts[0].detected


def test_collect_firewall_no_alert_when_on(monkeypatch):
    class _Result:
        returncode = 0
        stdout = (
            "Domain Profile Settings:\nState                                 ON\n"
            "Private Profile Settings:\nState                                 ON\n"
        )

    monkeypatch.setattr("security.collectors.subprocess.run", lambda *a, **k: _Result())
    assert collect_firewall() == []


def test_collect_firewall_survives_no_netsh(monkeypatch):
    def boom(*a, **k):
        raise OSError("no netsh")

    monkeypatch.setattr("security.collectors.subprocess.run", boom)
    assert collect_firewall() == []


# -- ThreatMonitor ----------------------------------------------------------

def test_monitor_scan_runs_and_persists(tmp_path):
    from memory.database import Database

    db = Database(tmp_path / "sec.db")

    def fake_runner():
        return [
            ThreatAlert(detected="x", why="y", process="p", severity=SEVERITY_HIGH, source="tests"),
        ]

    monitor = ThreatMonitor(database=db, runner=fake_runner, interval_seconds=60)
    results = monitor.scan_now()
    assert len(results) == 1
    assert monitor.status() == "high_risk"
    assert len(monitor.alerts()) == 1
    data = monitor.dashboard_data()
    assert data["label"] == "🔴 HIGH RISK"
    assert data["counts"]["high"] == 1
    rows = db.recent_security_events()
    assert any(r["category"] == "threat" for r in rows)


def test_monitor_scan_now_triggers_callback():
    seen = {}
    monitor = ThreatMonitor(on_update=lambda status, alerts: seen.update(
        {"status": status, "count": len(alerts)}
    ), runner=lambda: [ThreatAlert(detected="a", why="b", process="c")])
    monitor.scan_now()
    assert seen["status"] == "suspicious"
    assert seen["count"] == 1


def test_monitor_start_stop_lifecycle():
    monitor = ThreatMonitor(runner=lambda: [])
    monitor.start()
    assert monitor._thread is not None
    monitor.stop()
    assert monitor._thread is None or not monitor._thread.is_alive()
    assert monitor.last_scan() is not None


def test_monitor_persists_only_medium_high(tmp_path):
    from memory.database import Database

    db = Database(tmp_path / "sec.db2")

    def fake_runner():
        return [ThreatAlert(detected="l", why="w", process="p", severity=SEVERITY_LOW, source="tests")]

    monitor = ThreatMonitor(database=db, runner=fake_runner)
    monitor.scan_now()
    rows = db.recent_security_events()
    assert not any(r["category"] == "threat" for r in rows)


# -- honest wording helper --------------------------------------------------

def test_clean_message_never_overclaims():
    assert "cannot be hacked" not in CLEAN_MESSAGE
    assert "No obvious indicators" in CLEAN_MESSAGE