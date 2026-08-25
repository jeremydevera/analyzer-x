"""Cloud shards and the local sweep must be the SAME measurement.

The operator asked whether handing a running sweep to GitHub Actions was safe
and would keep the backtest accurate. It was not: the shard tested one
threshold of three and discarded every losing row, so folding its output into
the store produced a pair whose grid could not be reasoned about. These tests
pin the parity.
"""

import pytest


# --------------------------------------------------- cloud / local parity
# The operator: "i want it to be accurate". A coin measured in the cloud and
# the same coin measured on the Mac have to be the SAME measurement, or folding
# one into the other produces a store nobody can reason about.
def _shard_src():
    import pathlib
    return pathlib.Path(".github/scripts/sweep_shard.py").read_text()


def test_one_definition_of_round_trip_cost():
    """The two had their own, and they disagreed by 1.63x on APEX: slippage is
    measured against MID, so half the spread is already inside it and adding
    spread/2 charges the top of the book twice. It is printed as COST/TP and it
    decides which combinations the liquidity gate withholds."""
    import inspect

    from tradingagents import backtest_report as br, market_sweep as msw

    assert br.round_trip_cost(0.0004, {"slippage": 0.000689,
                                       "spread": 0.001379}) == pytest.approx(
        2 * (0.0004 + 0.000689))
    # the spread must NOT appear in it
    with_spread = br.round_trip_cost(0.0004, {"slippage": 0.000689,
                                              "spread": 0.5})
    assert with_spread == pytest.approx(2 * (0.0004 + 0.000689))

    # and nobody computes it privately any more
    local = inspect.getsource(msw)
    assert 'spread") or 0) / 2' not in local, "market_sweep still adds spread/2"
    assert local.count("br.round_trip_cost(fee, book)") == 2
    assert "br.round_trip_cost(fee, book)" in _shard_src(), \
        "the shard must share the definition, not mirror it"


def test_the_cloud_tests_every_threshold_like_the_mac():
    """It took THRESHOLDS[tf][1] — one of three — so the cloud grid was a third
    as wide for every momentum and fade rule."""
    src = _shard_src()
    assert "br.THRESHOLDS[tf][1]" not in src, "still capped to the middle value"
    assert "ths = br.THRESHOLDS[tf] if sig in br.THRESH_SIGNALS else [None]" in src
    assert "for th in ths:" in src, "and it must loop over them"


def test_the_cloud_writes_losers_too():
    """It dropped `profit <= 0 or trades < 100`, so a merged pair held only its
    profitable slice: the combination count was unanswerable, win/loss across
    the grid meaningless, and a "profitable only" filter a no-op."""
    src = _shard_src()
    assert 'r["profit"] <= 0' not in src, "still discarding losing rows"
    assert "MIN_TRADES" not in src, "the trade floor is gone with it"
    assert 'if not r["trades"]:' in src, "a row with no trade is still not a row"
    # the log must not advertise a cap that no longer exists
    assert "profitable slice of the grid" not in src
    assert "PARITY" in src


def test_a_merged_cloud_pair_is_never_resumed_from(monkeypatch, tmp_path):
    """The merge records a watermark so the pair counts as measured — but the
    cloud sends no per-combination state, so resuming from that bar would start
    every combination with no ladder or running total behind it."""
    import inspect

    from tradingagents import market_sweep as msw

    src = inspect.getsource(msw.run_pair)
    assert 'states.get("__cloud__")' in src, "run_pair must notice the mark"
    i = src.index('states.get("__cloud__")')
    assert "states = {}" in src[i:i + 200], "and drop the resume point"


def test_the_merge_records_freshness_and_ownership(monkeypatch):
    from tradingagents import cloud_sweep as cs, market_sweep as msw

    saved_rows, saved_states = [], {}
    monkeypatch.setattr(msw, "pair_watermark", lambda c, tf: 0)
    monkeypatch.setattr(msw, "save_pair_rows",
                        lambda c, tf, rs: saved_rows.append((c, tf, len(rs))))
    monkeypatch.setattr(msw, "save_states",
                        lambda c, tf, st: saved_states.update({(c, tf): st}))
    cs.merge_into_store([
        {"coin": "NEW", "tf": "1h", "profit": 1.0, "last_ms": 1787450400000},
        {"coin": "NEW", "tf": "1h", "profit": -2.0, "last_ms": 1787450400000}])
    assert saved_rows == [("NEW", "1h", 2)], "losers must be stored too"
    st = saved_states[("NEW", "1h")]
    assert st["__last_ms__"] == 1787450400000
    assert st["__cloud__"] is True


def test_availability_is_judged_by_the_call_we_need(monkeypatch):
    """`gh auth status` exits non-zero when ANY configured account is
    unhealthy. The operator's keyring token was invalid all day while
    `gh workflow list` answered fine through another credential — so the
    hand-off button vanished and the panel reported "gh is not logged in"
    about a CLI that was demonstrably logged in."""
    import inspect

    from tradingagents import cloud_sweep as cs

    src = inspect.getsource(cs.available)
    assert '"auth", "status"' not in src, "no auth pre-flight"
    assert '"workflow", "list"' in src, "ask for what we actually need"

    calls = []
    monkeypatch.setattr(cs, "repo_slug", lambda cwd=None: "me/repo")
    monkeypatch.setattr(cs, "_gh",
                        lambda *a, **k: calls.append(a) or
                        '[{"name": "Market sweep (15m / 30m)", "state": "active"}]')
    ok, why = cs.available()
    assert ok is True and why == "me/repo"
    assert not any("auth" in c for c in calls), calls


def test_a_real_auth_failure_still_says_what_to_run(monkeypatch):
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "repo_slug", lambda cwd=None: "me/repo")

    def boom(*a, **k):
        raise cs.CloudError("HTTP 401: Bad credentials (login required)")

    monkeypatch.setattr(cs, "_gh", boom)
    ok, why = cs.available()
    assert ok is False
    assert "gh auth refresh" in why
