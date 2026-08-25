"""Run the whole sweep, unattended, wherever it can run.

The operator, after three days of watching it break:

    "do backtest on your own using github actions ... i want accurate data and
     make sure to resume if it hits rate limit. give me update on percentage
     every 1 min, if i've been disconnected to wifi then continue the backtest
     local ... you already have the candles so you can work on this locally if
     there is no internet, make sure to store the backtest in database"

So this is a supervisor with one job: keep measuring, from whichever machine is
available, and never lose ground.

    GitHub reachable      -> dispatch shards for the coins nobody has measured
    rate limited          -> stop asking, wait for the reset, keep working
    no internet at all    -> measure locally from the candles already on disk
    either way            -> every finished pair lands in SQLite

WHY IT WATCHES GIT, NOT THE API
    Shards publish their own progress to the `sweep-progress` branch. Reading
    it with `git fetch` costs no API quota, which matters because polling the
    REST API burned 5,000 requests in an hour on 2026-08-25 and blinded every
    tool at once. The API is used only to dispatch, and once per cycle at most.

WHY LOCAL WORK NEEDS NO NETWORK
    4,946 candle files are already on disk. `run_pair` only calls the venue to
    TOP UP candles; with `days` already covered it measures from the cache. So
    a dropped connection changes where the work happens, not whether it does.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home() / ".tradingagents"
STATE = HOME / "orchestrator.json"
LOG = HOME / "orchestrator.log"
STOP = HOME / "orchestrator.STOP"

TICK = 60.0                 # the operator asked for a percentage every minute
CLOUD_SHARDS = 20
CLOUD_MAX_CONCURRENT = 1    # one cloud run at a time; shards are the parallelism


def log(msg: str) -> None:
    from tradingagents.positions_view import fmt_when

    line = f"{fmt_when(time.time())} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:      # noqa: SIM115
            fh.write(line + "\n")
    except OSError:
        pass


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def online() -> bool:
    """Is the venue reachable? The sweep needs MEXC, not github.com."""
    try:
        import socket

        socket.create_connection(("contract.mexc.com", 443), timeout=6).close()
        return True
    except OSError:
        return False


def gh_budget() -> tuple[int, float]:
    """(requests left, seconds until reset). (0, 0) if gh cannot answer."""
    try:
        out = subprocess.run(["gh", "api", "rate_limit", "--jq",
                              ".resources.core"], capture_output=True,
                             text=True, timeout=30)
        if out.returncode:
            return 0, 0.0
        d = json.loads(out.stdout)
        return int(d.get("remaining") or 0), max(
            0.0, float(d.get("reset") or 0) - time.time())
    except Exception:
        return 0, 0.0


# ----------------------------------------------------------------- the work
def pairs_wanted(coins, tfs) -> list:
    return [(c, tf) for c in coins for tf in tfs]


def measured(pairs) -> set:
    """Pairs already finished, read from their watermark — a tail read each."""
    from tradingagents import market_sweep as msw

    done = set()
    for sym, tf in pairs:
        if msw.pair_watermark(sym.replace("_USDT", ""), tf) > 0:
            done.add((sym, tf))
    return done


def store_pair(coin: str, tf: str) -> int:
    """Fold one finished pair into SQLite. Returns rows indexed."""
    from tradingagents import market_sweep as msw, rows_index as ri

    f = msw.ROWDIR / f"{coin}-{tf}.json"
    if not f.exists():
        return 0
    return ri.index_pair(f)


def local_round(pairs_left, *, workers: int = 0) -> int:
    """Measure locally, in parallel, from the candles already on disk."""
    from tradingagents import backtest_report as br

    coins = sorted({c for c, _ in pairs_left})
    tfs = sorted({tf for _, tf in pairs_left})
    got = br.grid_from_store(coins, tfs, base_margin=5.0, days=365,
                             workers=workers, fresh=False,
                             progress=lambda *a, **k: None)
    return len(got.get("rows") or [])


# ------------------------------------------------------------------- cycle
def run(coins, tfs, *, prefer_cloud: bool = True) -> None:
    from tradingagents import cloud_sweep as cs, rows_index as ri

    want = pairs_wanted(coins, tfs)
    total = len(want)
    ri.ensure()
    cloud_run: dict | None = None
    started = time.time()
    log(f"start: {total:,} pairs ({len(coins)} coins x {len(tfs)} timeframes)")

    while not STOP.exists():
        done = measured(want)
        left = [p for p in want if p not in done]
        pct = 100.0 * len(done) / total if total else 0.0

        # everything finished has to be IN THE DATABASE, not just on disk
        indexed = 0
        for sym, tf in list(done)[:40]:          # a slice per tick keeps it cheap
            indexed += store_pair(sym.replace("_USDT", ""), tf)

        net = online()
        budget, reset_in = gh_budget() if net else (0, 0.0)
        where = "waiting"

        if not left:
            _write(STATE, {"pct": 100.0, "done": len(done), "total": total,
                           "where": "finished", "running": False,
                           "elapsed_min": round((time.time() - started) / 60, 1)})
            log(f"FINISHED {len(done):,}/{total:,} pairs")
            return

        if not net:
            where = "this Mac (no internet — measuring from stored candles)"
            log(f"{pct:5.1f}%  {len(done):,}/{total:,}  offline, measuring "
                f"{min(len(left), 40)} pairs locally")
            local_round(left[:40])
        elif prefer_cloud and budget > 200:
            if cloud_run is None:
                unmeasured_coins = sorted({c for c, _ in left})
                run_ = cs.dispatch(shards=CLOUD_SHARDS,
                                   coins=len(unmeasured_coins),
                                   timeframes=",".join(tfs))
                cs.remember(run_)
                cloud_run = run_
                log(f"dispatched GitHub run {run_.get('id')} for "
                    f"{len(unmeasured_coins)} coins")
            where = f"GitHub Actions (run {cloud_run.get('id')})"
        else:
            where = ("this Mac (GitHub rate limited, "
                     f"{reset_in / 60:.0f} min to reset)")
            log(f"{pct:5.1f}%  rate limited — {budget} requests left, working "
                f"locally for {reset_in / 60:.0f} min")
            local_round(left[:40])

        _write(STATE, {"pct": round(pct, 2), "done": len(done), "total": total,
                       "left": len(left), "where": where, "running": True,
                       "indexed_rows": indexed,
                       "gh_requests_left": budget,
                       "elapsed_min": round((time.time() - started) / 60, 1)})
        log(f"{pct:5.1f}%  {len(done):,}/{total:,} pairs  ·  {where}")
        time.sleep(TICK)

    log("stopped by request")


def main() -> int:
    with contextlib.suppress(OSError, AttributeError):
        os.nice(5)                       # never outrank the operator's clicks
    STOP.unlink(missing_ok=True)
    spec = json.loads((HOME / "orchestrator.spec.json").read_text())
    run(spec["coins"], spec["tfs"],
        prefer_cloud=bool(spec.get("prefer_cloud", True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
