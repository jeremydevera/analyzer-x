"""The machine's own load, beside the job bars.

The rule that matters: a temperature that cannot be read is REPORTED AS
UNAVAILABLE, never inferred from load. A plausible invented number on a
trading terminal is the same class of fault as a mislabelled total.
"""
from tradingagents import sysmon


def test_a_temperature_is_never_invented(monkeypatch):
    monkeypatch.setattr(sysmon.subprocess, "run",
                        lambda *a, **kw: type("R", (), {"stdout": ""})())
    got = sysmon._thermal()
    assert got["available"] is False
    assert "root" in got["why"]
    assert "celsius" not in str(got).lower() and got.get("temp") is None


def test_throttling_is_read_from_the_speed_limit(monkeypatch):
    monkeypatch.setattr(sysmon.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"stdout": "CPU_Speed_Limit \t= 70"})())
    got = sysmon._thermal()
    assert got["available"] is True and got["speed_limit"] == 70
    assert got["throttled"] is True and got["pressure"] == "throttling"


def test_a_full_speed_machine_is_not_called_throttled(monkeypatch):
    monkeypatch.setattr(sysmon.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"stdout": "CPU_Speed_Limit \t= 100"})())
    got = sysmon._thermal()
    assert got["throttled"] is False and got["pressure"] == "nominal"


def test_busy_is_derived_from_idle_not_guessed(monkeypatch):
    monkeypatch.setattr(sysmon.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"stdout": "CPU usage: 61.20% user, 12.30% sys, 26.50% idle"})())
    got = sysmon._top_sample()
    assert got["busy"] == 73.5 and got["idle"] == 26.5


def test_a_top_that_fails_returns_nothing_rather_than_zeros(monkeypatch):
    """Zeros would read as an idle machine mid-sweep."""
    def boom(*a, **kw):
        raise OSError("no top")
    monkeypatch.setattr(sysmon.subprocess, "run", boom)
    assert sysmon._top_sample() == {}


def test_load_per_core_is_load_over_cores(monkeypatch):
    # through the portable seam: Windows has no getloadavg at all, and
    # patching os.getloadavg there tested a call that is never made
    from tradingagents import portable

    monkeypatch.setattr(portable, "WINDOWS", False)
    monkeypatch.setattr(portable, "load_average", lambda: (16.0, 8.0, 4.0))
    monkeypatch.setattr(sysmon, "cpu_count", lambda: 8)
    monkeypatch.setattr(sysmon, "_top_sample", lambda: {"busy": 99.0})
    monkeypatch.setattr(sysmon, "_thermal", lambda: {"available": False})
    got = sysmon.snapshot(force=True)
    assert got["load_per_core"] == 2.0 and got["cores"] == 8


def test_the_snapshot_is_cached_so_polling_does_not_spawn_top(monkeypatch):
    calls = []
    monkeypatch.setattr(sysmon, "_top_sample", lambda: calls.append(1) or {})
    monkeypatch.setattr(sysmon, "_thermal", lambda: {"available": False})
    sysmon.snapshot(force=True)
    sysmon.snapshot()
    sysmon.snapshot()
    assert len(calls) == 1, "a UI polling every 2s must not run `top` every 2s"
