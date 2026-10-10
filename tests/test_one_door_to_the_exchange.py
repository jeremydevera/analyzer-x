"""One door to the exchange (spec D2, Oct 10, 2026).

Every caller imports `tradingagents.dataflows.exchange as fx`, and the door
hands each attribute to the venue's adapter AT CALL TIME — so moving the app
from MEXC to Gate is one setting, and a test that monkeypatches
`mexc_futures` still reaches the code it drives.

The AST scan is the guard that keeps it one door: a module that imports
`mexc_futures` directly would keep talking to MEXC after the switch, and
nothing on any screen would say so.
"""
import ast
from pathlib import Path

import pytest

from tradingagents.dataflows import exchange, gate_futures, mexc_futures

ROOT = Path(__file__).resolve().parents[1]
# the only places allowed to name an adapter: the door, the adapters' own
# credentials helpers, and the cutover that reads MEXC's last prices
ALLOWED = {
    "tradingagents/dataflows/exchange.py",
    "tradingagents/dataflows/mexc_futures.py",
    "tradingagents/dataflows/gate_futures.py",
    "tradingagents/dataflows/mexc_credentials.py",
    "tradingagents/venue.py",
    "tradingagents/venue_switch.py",
    # MexcProtocol signs MEXC's own socket login with MEXC's one signer
    "tradingagents/live_price.py",
}


def test_the_door_hands_each_call_to_the_venue_at_call_time(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert exchange.adapter() is mexc_futures

    def fake(*a, **k):
        return "patched"
    monkeypatch.setattr(mexc_futures, "klines", fake)
    assert exchange.klines("BTC_USDT", "Min60", 5) == "patched"
    monkeypatch.setenv("TA_VENUE", "gate")
    assert exchange.adapter() is gate_futures
    assert exchange.klines is gate_futures.klines


def test_a_patch_through_the_door_lands_on_the_adapter_and_leaves_nothing():
    """The replay shard's tests failed after the sweep shard's: a patch on the
    door left the real function pinned IN the door, and later patches of
    mexc_futures were bypassed (Oct 10, 2026)."""
    real = mexc_futures.klines
    mp = pytest.MonkeyPatch()
    mp.setenv("TA_VENUE", "mexc")
    mp.setattr(exchange, "klines", lambda *a, **k: "fake")
    assert mexc_futures.klines(1, 2, 3) == "fake"
    mp.undo()
    assert mexc_futures.klines is real
    assert "klines" not in vars(exchange), "nothing pinned in the door"


def test_a_name_neither_adapter_has_is_an_attribute_error(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    with pytest.raises(AttributeError, match="Gate"):
        exchange.no_such_thing  # noqa: B018


def test_both_adapters_answer_every_name_the_app_reads():
    """Every attribute the app reads through the door exists on BOTH sides,
    so switching the setting can never meet a missing function at a signal."""
    names = set()
    for path in _app_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in ("fx", "_fx")
                    and _imports_the_door(tree)):
                names.add(node.attr)
    names -= {"key_of", "clean_spec", "export_dir", "run", "FILTER_KEYS"}
    missing = {n: [m.__name__.rsplit(".", 1)[-1] for m in (mexc_futures, gate_futures)
                   if not hasattr(m, n)] for n in sorted(names)}
    missing = {n: m for n, m in missing.items() if m}
    assert not missing, f"names an adapter does not answer: {missing}"


def _app_files():
    for base in ("tradingagents", ".github/scripts", "scripts"):
        for p in (ROOT / base).rglob("*.py"):
            if "__pycache__" not in p.parts:
                yield p
    yield ROOT / "start.py"


def _imports_the_door(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tradingagents.dataflows":
            if any(a.name == "exchange" for a in node.names):
                return True
    return False


def test_no_app_module_reaches_mexc_except_through_the_door():
    bad = []
    for path in _app_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [a.name for a in node.names]
                if node.module.endswith("mexc_futures") or (
                        node.module == "tradingagents.dataflows"
                        and "mexc_futures" in names):
                    bad.append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.Import):
                if any(a.name.endswith("mexc_futures") for a in node.names):
                    bad.append(f"{rel}:{node.lineno}")
    assert not bad, f"imports MEXC directly, bypassing the door: {bad}"


def test_no_app_module_builds_a_mexc_address_itself():
    """`fx._get_public(f"{fx.BASE}/api/v1/contract/detail")` asked MEXC for
    its coin list from five places; under Gate it would ask Gate for a MEXC
    path. They ask `fx.trading_symbols()` now."""
    bad = []
    for path in _app_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or rel == "tradingagents/live_price.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("api/v1/contract", "fx.BASE", "fx._get_public",
                       "fx._klines_page", "contract.mexc.com\", 443"):
            if needle in text:
                bad.append(f"{rel}: {needle}")
    assert not bad, bad
