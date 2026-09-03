"""Where can this work actually RUN right now — this PC, GitHub, or both.

Operator, 2026-09-03: *"i want you to detect if there is a free both in github
and machine"*, after asking why I had not used GitHub at all — *"why did you not
use github since its free?"*. The honest answer was that nothing looked: the
UPDATE button always ran on this PC, and GitHub sat idle through a 4,124-pair
run that took most of a day.

The split is BY TIMEFRAME, because that is the only axis the cloud shard can be
pointed at (`.github/workflows/sweep.yml` takes a `timeframes` input; its coins
are sliced by index inside the shard). Splitting by timeframe also means the two
halves can never measure the same combination, so nothing is written twice and
no merge has to choose a winner.

Heavier timeframes go to the cloud, because 20 runners beat this machine's
cores: 15m is 35,040 bars a year against 1d's 365, and the fleet should get the
work that hurts.
"""
from __future__ import annotations

import os

# What the sweep workflow's runners cost us: nothing on a public repository, and
# this one is public. Twenty is the shard count `cloud_sweep.dispatch` defaults
# to and the number the workflow's matrix builds.
CLOUD_RUNNERS = 20

# Bars per year per timeframe — the weight of one pair on one frame. Used only
# to decide WHO gets which frame, never to measure anything.
BARS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 365,
}

ALL_TFS = ("15m", "30m", "1h", "4h", "1d")


def local_workers() -> int:
    """How many pairs this PC measures at once. The sweep's own pool size."""
    try:
        from tradingagents import market_sweep as msw

        n = getattr(msw, "WORKERS", None)
        if callable(n):
            n = n()
        if n:
            return max(1, int(n))
    except Exception:                                          # noqa: BLE001
        pass
    return max(1, (os.cpu_count() or 4))


def local_free(ignore=()) -> tuple[bool, str]:
    """Is this machine free to take a sweep?

    Busy means a backtest or an update is already running. They write the same
    row files, so two of them is not twice the speed — it is two processes
    fighting over one pair lock.

    `ignore` names the job asking the question. Without it, `_run_btupdate`
    calls this from INSIDE the update job — whose pid file and progress file
    both say "running" — decides this PC is busy, and sends every timeframe to
    GitHub while the machine it is running on sits idle.
    """
    from tradingagents import db_jobs as dj

    for kind, name in (("backtest", "a backtest"), ("btupdate", "an update")):
        if kind in ignore:
            continue
        try:
            st = dj.status(kind)
        except Exception as exc:                               # noqa: BLE001
            # unknown is not busy: a job kind this build does not have must
            # never be the reason the machine measures nothing
            print(f"[capacity] cannot read the {kind} job "
                  f"({type(exc).__name__}: {exc}) — treating it as idle",
                  flush=True)
            continue
        if st.get("running"):
            done, total = st.get("done") or 0, st.get("total") or 0
            where = f" ({done:,}/{total:,})" if total else ""
            return False, f"{name} is already running on this PC{where}"
    return True, "free"


def cloud_free() -> tuple[bool, str]:
    """Is GitHub free to take a sweep?

    Busy means a sweep run of ours is queued or in progress. GitHub would
    happily start a second one, and both would measure the same contracts.
    """
    from tradingagents import cloud_sweep as cs

    ok, why = cs.available()
    if not ok:
        return False, why
    try:
        runs = cs._runs(why, limit=5)
    except Exception as exc:                                   # noqa: BLE001
        return False, f"cannot list runs: {type(exc).__name__}: {exc}"
    for r in runs:
        if r.get("status") in ("queued", "in_progress", "requested", "waiting"):
            return False, (f"run {r['databaseId']} is already "
                           f"{str(r.get('status')).replace('_', ' ')}")
    return True, "free"


def split(tfs, *, to_local: bool, to_cloud: bool,
          runners: int = CLOUD_RUNNERS, workers: int | None = None) -> dict:
    """Hand each timeframe to one side, in proportion to how fast each is.

    Pure, so it can be tested without a machine or a network. The cloud always
    gets at least the heaviest frame when it is free — the whole point of this
    module is that GitHub sat idle for a day — and then keeps taking frames
    while it is under its share of the bars. This PC gets the rest, which may
    be nothing when there is only one frame to do.
    """
    tfs = [t for t in tfs if t]
    if not tfs:
        return {"local": [], "cloud": [], "why": "no timeframe was asked for"}
    if not to_local and not to_cloud:
        return {"local": [], "cloud": [], "why": "nothing is free"}
    if not to_cloud:
        return {"local": list(tfs), "cloud": [],
                "why": "GitHub is busy — all of it on this PC"}
    if not to_local:
        return {"local": [], "cloud": list(tfs),
                "why": "this PC is busy — all of it on GitHub"}

    workers = workers or local_workers()
    order = sorted(tfs, key=lambda t: -BARS_PER_YEAR.get(t, 1))
    weight = {t: BARS_PER_YEAR.get(t, 1) for t in order}
    total = sum(weight.values()) or 1
    want = runners / float(runners + workers)          # the cloud's fair share

    cloud, got = [], 0
    for t in order:
        if not cloud or got / total < want:
            cloud.append(t)
            got += weight[t]
    local = [t for t in order if t not in cloud]
    share = f"{100 * got / total:.0f}% of the bars"
    why = (f"both free — GitHub takes {', '.join(cloud)} ({share}) on "
           f"{runners} runners")
    why += (f", this PC takes {', '.join(local)} on {workers} worker(s)"
            if local else
            f"; nothing left for this PC — one timeframe cannot be split")
    return {"local": local, "cloud": cloud, "why": why}


def plan(tfs=ALL_TFS, ignore=()) -> dict:
    """Look at both sides, then say who runs what. Never starts anything.

    `ignore` is passed through to `local_free` — the job asking must not count
    itself as the thing making this PC busy.
    """
    lf, lwhy = local_free(ignore)
    cf, cwhy = cloud_free()
    out = split(tfs, to_local=lf, to_cloud=cf)
    out.update({"local_free": lf, "local_why": lwhy,
                "cloud_free": cf, "cloud_why": cwhy,
                "workers": local_workers(), "runners": CLOUD_RUNNERS,
                "timeframes": list(tfs)})
    if not lf and not cf:
        out["why"] = f"nothing is free — this PC: {lwhy}; GitHub: {cwhy}"
    return out
