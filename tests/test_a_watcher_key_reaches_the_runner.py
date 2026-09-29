"""A key the watcher registers is traded by a runner that was already running.

auto_trader builds STRATEGY_SPECS once, at import. The runner imports it once
and runs for days. A key registered after that would be armed in the settings
and traded by nobody, with nothing on screen saying so (Review Focus 4)."""
import pytest

from tradingagents import auto_trader as at, runtime_specs as rs

KEY = "bb20_15m_sl07tp09"
SPEC = {"interval": "Min15", "bar_seconds": 900, "tp": 0.009, "sl": 0.007}


@pytest.fixture(autouse=True)
def _own_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "PATH", tmp_path / "runtime_specs.json")
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    monkeypatch.setattr(at, "_RUNTIME_SEEN", {"mtime": None})
    yield
    at.STRATEGY_SPECS.pop(KEY, None)
    at.STRATEGY_ORDER = tuple(k for k in at.STRATEGY_ORDER if k != KEY)


def test_the_runner_path_sees_a_key_registered_after_import():
    assert KEY not in at.STRATEGY_SPECS
    rs.register(KEY, SPEC)
    at.load_settings()                      # what run_cycle calls every round
    assert at.STRATEGY_SPECS[KEY] == SPEC
    assert KEY in at.STRATEGY_ORDER


def test_run_cycle_reads_the_settings_every_round():
    import inspect

    body = inspect.getsource(at.run_cycle)
    assert "load_settings(" in body, "the merge rides on this call"


def test_a_committed_key_can_never_be_redefined():
    committed = next(iter(at._OPERATORS_V2_SEP24))
    with pytest.raises(ValueError):
        rs.register(committed, {**at.STRATEGY_SPECS[committed], "tp": 0.5})
    assert rs.register(committed, dict(at.STRATEGY_SPECS[committed])) == "same"


def test_the_merge_is_cached_on_the_files_mtime():
    rs.register(KEY, SPEC)
    assert at.merge_runtime_specs() == 1
    assert at.merge_runtime_specs() == 0, "every settings read must not re-read it"


def test_a_corrupt_registry_changes_nothing_and_does_not_raise(tmp_path):
    rs.PATH.write_text("not json")
    before = dict(at.STRATEGY_SPECS)
    assert at.merge_runtime_specs() == 0
    assert at.STRATEGY_SPECS == before


def test_two_threads_merging_at_once_add_the_key_once():
    """The API loads settings from request threads AND the watcher thread."""
    import threading

    rs.register(KEY, SPEC)
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        at.merge_runtime_specs()

    ts = [threading.Thread(target=go) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert at.STRATEGY_ORDER.count(KEY) == 1


def test_the_merge_takes_a_lock():
    import inspect

    assert "_RUNTIME_LOCK" in inspect.getsource(at.merge_runtime_specs)
