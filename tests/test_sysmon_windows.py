"""The system tiles must read on Windows too.

`os.getloadavg()` does not exist there, so `/api/system` answered HTTP 500 on
every page load of the operator's PC (4-6 console errors a page, tiles blank)
from the first hour it ran. A load average is a unix idea; Windows has a CPU
BUSY PERCENTAGE, which is the same question asked differently — so the tile
gets a real number and says which kind it is, rather than the route failing.
"""
from tradingagents import portable, sysmon


def _fresh():
    sysmon._CACHE.update(at=0.0, value=None)


def test_snapshot_answers_on_this_machine():
    _fresh()
    got = sysmon.snapshot(force=True)
    assert got["cores"] >= 1
    for k in ("load1", "load5", "load15", "load_per_core"):
        assert isinstance(got[k], (int, float)), k
        assert got[k] >= 0
    assert got["load_kind"] in ("loadavg", "cpu-percent")


def test_windows_reports_cpu_percent_and_unix_reports_loadavg(monkeypatch):
    _fresh()
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "cpu_busy_percent", lambda: 42.0)
    got = sysmon.snapshot(force=True)
    assert got["load_kind"] == "cpu-percent"
    # 42% busy over N cores is 0.42 of the machine
    assert got["load_per_core"] == 0.42
    assert got["load1"] == round(0.42 * got["cores"], 2)

    _fresh()
    monkeypatch.setattr(portable, "WINDOWS", False)
    monkeypatch.setattr(portable, "load_average", lambda: (1.5, 1.0, 0.5))
    got = sysmon.snapshot(force=True)
    assert got["load_kind"] == "loadavg"
    assert (got["load1"], got["load5"], got["load15"]) == (1.5, 1.0, 0.5)


def test_an_unreadable_load_is_zero_not_a_crash(monkeypatch):
    """A dead counter must not take the whole page's tiles down."""
    _fresh()
    monkeypatch.setattr(portable, "WINDOWS", True)
    monkeypatch.setattr(portable, "cpu_busy_percent",
                        lambda: (_ for _ in ()).throw(OSError("no counter")))
    got = sysmon.snapshot(force=True)
    assert got["load1"] == 0.0 and got["cores"] >= 1


def test_no_module_calls_getloadavg_directly():
    """It is a unix-only call; portable.load_average is the one place."""
    import pathlib

    hits = []
    for f in pathlib.Path("tradingagents").rglob("*.py"):
        if f.name == "portable.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]        # a comment may NAME the call
            if "os.getloadavg(" in code:
                hits.append(f"{f}:{i}")
    assert hits == [], hits
