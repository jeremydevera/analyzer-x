"""Two faults found by pressing Backtest v2 across two accounts, Sep 22, 2026.

The operator asked for Backtest v2 on 40 machines. Both runs started and both
measured with 1-minute candles — and this PC then believed only ONE of them
was a v2 run, and opened no live door for either.

* `live_ingest.ensure` raised `UnboundLocalError: cannot access local
  variable 'why'` the moment it had to REPLACE a door that serves the other
  store (the v1 door was open from the run before). `dispatch` swallows any
  failure there into `live_why`, so the press succeeded and 40 machines
  measured with the fast path silently shut.
* `cloud_sweep.remember` filed the store for `run["id"]` alone. One press now
  starts one run PER ACCOUNT, so run 35740445165 was filed as res='1m' and
  35740488141 — same press, same minutes — was filed as v1, which sends 531
  coins of v2 rows to the v1 collect for `land_rows` to refuse one by one.
"""
from __future__ import annotations

import json


def test_replacing_a_door_for_the_other_store_does_not_raise(monkeypatch, tmp_path):
    """The v1 door is open and a Backtest v2 press needs a v2 one.

    Driven through the REAL function with nothing stubbed but the process
    boundary — a source check would have passed on the broken file, because
    every line it needed was present and simply one level too far left.
    """
    from tradingagents import live_ingest as li

    # the guard that keeps a suite off the internet also keeps it out of this
    # branch, so it is lifted with every spawning call faked below
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(li, "current", lambda: {
        "url": "https://old.trycloudflare.com", "pid": 4242, "res": ""})
    monkeypatch.setattr(li, "_alive", lambda pid: True)
    stopped: list = []
    monkeypatch.setattr(li, "stop", lambda: stopped.append(True) or {})
    monkeypatch.setattr(li, "reachable", lambda url, timeout=20.0: "")
    monkeypatch.setattr(li, "cloudflared", lambda: str(tmp_path / "cf.exe"))
    spawned: list = []
    monkeypatch.setattr(li.subprocess, "Popen",
                        lambda *a, **k: spawned.append(a) or object())
    monkeypatch.setattr(li, "HOME", tmp_path)
    monkeypatch.setattr(li, "SERVE_LOG", tmp_path / "serve.log")

    got = li.ensure(res="1m", wait_s=0)

    assert isinstance(got, dict) and "why" in got
    assert "UnboundLocalError" not in str(got.get("why"))
    assert stopped, "the door for the other store must be stopped"
    assert spawned, "and a door for THIS store must be opened in its place"


def test_a_door_that_stopped_answering_still_says_so(monkeypatch, tmp_path):
    """The same branch's OTHER half: a door for THIS store that has gone
    quiet is replaced, and the reason is logged — moving the line must not
    delete the message it carries."""
    from tradingagents import live_ingest as li

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(li, "current", lambda: {
        "url": "https://old.trycloudflare.com", "pid": 4242, "res": "1m"})
    monkeypatch.setattr(li, "_alive", lambda pid: True)
    monkeypatch.setattr(li, "stop", lambda: {})
    monkeypatch.setattr(li, "reachable",
                        lambda url, timeout=20.0: "Non-existent domain")
    said: list = []
    monkeypatch.setattr(li, "log", lambda msg: said.append(str(msg)))
    monkeypatch.setattr(li, "cloudflared", lambda: "")
    monkeypatch.setattr(li, "fetch_cloudflared",
                        lambda: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(li, "HOME", tmp_path)

    got = li.ensure(res="1m", wait_s=0)

    assert any("Non-existent domain" in s for s in said), said
    assert "why" in got


def test_every_account_run_is_filed_with_its_own_store(monkeypatch, tmp_path):
    """"i want 40" made one press into two runs. Both are v2 or neither is."""
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "RUNFILE", tmp_path / "cloud_run.json")
    monkeypatch.setattr(cs, "RESFILE", tmp_path / "cloud_run_res.json")
    runs = [{"id": 35740445165, "repo": "a/analyzer-x", "res": "1m"},
            {"id": 35740488141, "repo": "b/analyzer-x", "res": "1m"}]

    cs.remember({**runs[0], "runs": runs, "why": "2 account(s) x 20 machines"})

    assert cs.run_res(35740445165) == "1m"
    assert cs.run_res(35740488141) == "1m", \
        "the second account's rows would be offered to the v1 collect"
    assert json.loads((tmp_path / "cloud_run.json").read_text())["runs"]


def test_a_single_run_press_is_unchanged(monkeypatch, tmp_path):
    """One remote, one run, no `runs` key — the shape every v1 press has."""
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "RUNFILE", tmp_path / "cloud_run.json")
    monkeypatch.setattr(cs, "RESFILE", tmp_path / "cloud_run_res.json")

    cs.remember({"id": 35723261621, "repo": "b/analyzer-x", "res": ""})

    assert cs.run_res(35723261621) == ""
    assert cs.run_res(999) == "", "an unknown run is v1, as it always was"
