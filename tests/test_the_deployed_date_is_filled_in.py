"""The DEPLOYED column was blank on 113 of the operator's 120 rows.

Operator, `Sep 17, 2026`: *"fill up the deployed date column now i want the
value when i did added this strategy"*.

Measured on their machine before this change:

    rows on the strategies grid            120
    rows the deploy log could date           7   (Sep 04, 2026 1:33am)
    rows the deploy log had NEVER seen     113

`deployments.jsonl` is written by the SAVE path. The 113 were the 280 row ids
they pasted on `Sep 16, 2026`, deployed by writing the settings file directly,
so no save ever happened and no line was ever logged. A log cannot date an
event it never saw.

Their own settings backups can. Each carries the moment it was taken in its
filename (`auto_trade.json.before-delist-1789494891`), and the pair count runs
35 at `Sep 16, 1:42am` → 133 at `1:54am` → 120 at `2:14am`. So those 113 were
added inside a twelve-minute window.

**A WINDOW IS NOT A FACT.** The upper bound alone would print `Sep 16, 2026
1:54am` on 113 rows as if somebody had recorded it. Both ends travel to the
screen, which prints "about" and names both in its tooltip — the same rule
that CLAUDE.md calls label-must-match-data, and the same shape as "an empty
page may never speak for the store".
"""
from __future__ import annotations

import json
import time

import pytest

from tradingagents import local_history as lh

KEY = "willr14_30m_sl2tp05"


def _snap(dirpath, name, pairs, when=None):
    """One settings backup, named the way the app names them."""
    f = dirpath / (f"auto_trade.json.{name}" if when is None
                   else f"auto_trade.json.{name}-{when}")
    f.write_text(json.dumps({"strategy_coins": pairs}), encoding="utf-8")
    return f


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, "SETTINGS_SNAPSHOTS", tmp_path)
    monkeypatch.setattr(lh, "DEPLOY_LOG", tmp_path / "deployments.jsonl")
    monkeypatch.setattr(lh, "_SNAP_CACHE", {"stamp": None, "value": {}})
    # the operator's own shape: a small config, then a big one twelve minutes on
    _snap(tmp_path, "before-127", {KEY: ["DVNSTOCK_USDT"]}, 1789494163)
    _snap(tmp_path, "before-delist",
          {KEY: ["DVNSTOCK_USDT", "VUG_USDT", "FASTSTOCK_USDT"]}, 1789494891)
    return tmp_path


# ------------------------------------------------- 1. the fallback itself
def test_a_pair_is_dated_by_the_first_backup_that_holds_it(home):
    got = lh.first_seen_in_settings()
    assert got[f"{KEY}|DVNSTOCK_USDT"][0] == 1789494163, "the earlier copy"
    assert got[f"{KEY}|VUG_USDT"][0] == 1789494891, "the copy it appears in"


def test_the_OTHER_end_of_the_window_comes_back_too(home):
    """The whole point. 1789494891 alone would read as a recorded fact; the
    truth is 'somewhere after 1789494163'."""
    at_, from_ = lh.first_seen_in_settings()[f"{KEY}|VUG_USDT"]
    assert from_ == 1789494163, "the screen cannot say 'about' without this"
    assert from_ < at_


def test_the_oldest_backup_has_no_lower_bound(home):
    """A pair present in the very first copy could have been added any time
    before it, and that is reported as no lower bound rather than a guess."""
    assert lh.first_seen_in_settings()[f"{KEY}|DVNSTOCK_USDT"][1] == 0


def test_a_backup_with_no_time_in_its_name_uses_its_file_time(home):
    f = _snap(home, "bak", {KEY: ["KKRSTOCK_USDT"]})
    then = 1789400000
    import os
    os.utime(f, (then, then))
    lh._SNAP_CACHE["stamp"] = None
    assert lh.first_seen_in_settings()[f"{KEY}|KKRSTOCK_USDT"][0] == then


def test_unreadable_backups_are_skipped_not_fatal(home):
    (home / "auto_trade.json.broken-1789494000").write_text("{ not json",
                                                            encoding="utf-8")
    lh._SNAP_CACHE["stamp"] = None
    got = lh.first_seen_in_settings()
    assert f"{KEY}|VUG_USDT" in got, "one bad backup emptied the whole column"


def test_the_lock_and_want_files_are_not_settings(home):
    (home / "auto_trade.lock").write_text("", encoding="utf-8")
    (home / "auto_trade.WANT").write_text("", encoding="utf-8")
    lh._SNAP_CACHE["stamp"] = None
    assert f"{KEY}|VUG_USDT" in lh.first_seen_in_settings()


# ------------------------------------------- 2. the log still wins outright
def test_a_logged_deploy_beats_a_backup_and_is_marked_exact(home):
    lh.record_deployment({"changed_at": 1789000000, "strategy_key": KEY,
                          "symbol": "VUG_USDT", "action": "deployed"})
    got = lh.deployed_at()[f"{KEY}|VUG_USDT"]
    assert got["at"] == 1789000000, "a real recorded second was overruled"
    assert got["from"] is None, (
        "a logged deploy is EXACT — a window here would make the screen say "
        "'about' about something it actually witnessed")


def test_a_pair_only_the_backups_know_carries_its_window(home):
    got = lh.deployed_at()[f"{KEY}|FASTSTOCK_USDT"]
    assert got["at"] == 1789494891
    assert got["from"] == 1789494163, "the window was thrown away"


def test_every_deployed_pair_gets_an_answer(home):
    """The operator's actual ask: no blanks. 120 of 120."""
    got = lh.deployed_at()
    for coin in ("DVNSTOCK_USDT", "VUG_USDT", "FASTSTOCK_USDT"):
        assert got.get(f"{KEY}|{coin}", {}).get("at"), coin


# --------------------------------------------------- 3. the screen says which
def test_the_column_prints_about_when_it_is_a_window():
    p = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert "r.deployed_at_from" in p, "the screen cannot tell the two apart"
    assert "about {fmtWhen(r.deployed_at)}" in p, (
        "a window is being printed as a plain date — that is a bound wearing "
        "a fact's clothes")
    assert "added between ${fmtWhen(r.deployed_at_from)} and " in p, \
        "the tooltip must name BOTH ends"
    assert "fmtWhen" in p and "toLocale" not in p, "CLAUDE.md date format"


def test_the_route_sends_both_ends():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api.trade_strategies)
    assert "_lh.deployed_at()" in src, "still reading the log alone"
    assert '"deployed_at_from"' in src


# ------------------------------------------------------------ 4. it is cached
def test_reading_it_twice_does_not_reopen_every_backup(home, monkeypatch):
    """The grid polls every five seconds and this opens every settings copy."""
    lh.first_seen_in_settings()
    hits = {"n": 0}
    real = lh.Path.read_text

    def counted(self, *a, **k):
        hits["n"] += 1
        return real(self, *a, **k)

    monkeypatch.setattr(lh.Path, "read_text", counted)
    lh.first_seen_in_settings()
    assert hits["n"] == 0, f"re-read {hits['n']} file(s) with nothing changed"


def test_a_new_backup_busts_the_cache(home):
    lh.first_seen_in_settings()
    _snap(home, "before-new", {KEY: ["ROLSTOCK_USDT"]}, int(time.time()))
    assert f"{KEY}|ROLSTOCK_USDT" in lh.first_seen_in_settings(), \
        "a row deployed since the last read would stay blank for ever"
