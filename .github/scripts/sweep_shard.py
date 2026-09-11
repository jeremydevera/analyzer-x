"""One shard of the market sweep, for a GitHub runner.

Public data only — candles, funding, order book, contract detail. No API key is
read and none is needed, which is why this can run on someone else's machine.

WORK IS CLAIMED, NOT SLICED. The shards used to take a fixed slice each
(`syms[SHARD::SHARDS]`) and exit when it was done; on run 34004227228
(Sep 06, 2026) four machines sat idle 12-21 minutes while the slowest was at
30 of 52 coins, because the slices are equal in COUNT but not in WORK — a 15m
coin with three years of history costs many times a young 4h coin. The
operator: *"did not i mentioned if the machine is 100% take a new job"*.

Each shard now claims ONE COIN at a time from a shared board on the
sweep-progress branch (progress.ClaimBoard — an atomic create per coin, so no
coin can be measured twice) and keeps claiming until the board is empty. The
run ends when the WORK ends, not when the unluckiest slice does. Without a
token (local runs, tests) it falls back to the old static slice.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import (
    backtest_report as br,  # noqa: E402
    fast_grid as fg,  # noqa: E402
    resume_state as rs,  # noqa: E402
)
from tradingagents.dataflows import mexc_futures as fx  # noqa: E402
from tradingagents.market_sweep import CONTEXT_BARS, combo_key  # noqa: E402
from tradingagents.positions_view import fmt_when  # noqa: E402

SHARD = int(os.environ.get("SHARD", "0"))
SHARDS = max(1, int(os.environ.get("SHARDS", "1")))
PER_SHARD = int(os.environ.get("COINS", "0"))
TFS = [t.strip() for t in os.environ.get("TFS", "15m,30m").split(",") if t.strip()]
MIN_DAYS = int(os.environ.get("MIN_DAYS", "0"))
# The history window, in days -- the same knob the Backtest screen sends the
# local job ("Previous 2 months" = 60). Default a year, as before.
DAYS = int(os.environ.get("DAYS", "365"))
# How many times ONE pair is redone before the shard gives up on it. The
# local sweep's rule (market_sweep.PAIR_RETRIES), and the operator's words on
# 2026-08-25: "if the backtest failed for certain coin make sure to stop the
# process for that specific coin and retry it". Never the whole shard.
PAIR_RETRIES = 2
# The operator's stake, sent by the dispatch. It was hardcoded at 5.0 while
# the local job took `base` from the Backtest screen, so after the move to
# GitHub (Sep 05, 2026) every dollar figure would have been measured at a
# stake nobody chose. Same default as before when the input is absent.
BASE_MARGIN = float(os.environ.get("BASE_MARGIN") or 5.0)
GATE_BLOCK = 0.50
# UPDATE OR FULL. Operator, 2026-09-09: "if the last backtest was sep1 and i
# click update it should run on github to update the gap which is sept 2
# onwards". "update" continues every pair that has a SAVED POSITION from an
# earlier run over its new bars only; a pair without one is measured in full
# (and says so). "full" measures the whole window from scratch — the BACKTEST
# button — and both modes save every pair's position for the next run.
MODE = (os.environ.get("MODE") or "full").strip().lower()
# WHICH COINS this run was asked for, by name. Empty = the whole market, which
# is what every dispatch meant by accident until Sep 10, 2026: only the COUNT
# travelled, so picking BTC on the Backtest screen sent "1 coin" and the twenty
# machines claimed the first coin at each of their own starting points —
# 0G, ALPINE, AVAAI… — while BTC sat unmeasured at position 190 of 1,065.
COIN_LIST = [c.strip().upper() for c in os.environ.get("COIN_LIST", "").split(",")
             if c.strip()]
# The runs whose `state-*` artifacts hold the latest saved positions, oldest
# first (the newest wins a pair). Set by the dispatch from this PC's record.
STATE_RUNS = [x.strip() for x in os.environ.get("STATE_RUNS", "").split(",")
              if x.strip()]
# market_sweep's fingerprint for a state measured with every threshold; a
# saved position with another fingerprint is measured in full, never continued
VERSION = f"signals{len(br.SIGNALS)}-th3"

# WHERE TO POST EACH FINISHED PAIR, right now. The operator, Sep 09, 2026:
# "why not immediately put the results in my pc" — a finished pair used to sit
# in an artifact until the whole machine stopped, and run 34307921614's rows
# were still landing fifteen hours after it finished. The url is a one-run
# Cloudflare address their PC opened before the dispatch; the token is a
# repository secret (masked in the log). Empty = artifacts only, exactly as
# before. The artifact is written EITHER WAY: the post is speed, never the
# record.
INGEST_URL = (os.environ.get("INGEST_URL") or "").strip().rstrip("/")
INGEST_TOKEN = (os.environ.get("INGEST_TOKEN") or "").strip()
INGEST_TRIES = 2
INGEST_TIMEOUT_S = 90

OUT = os.path.join("out", f"rows-{SHARD}.jsonl")
STATE_OUT = os.path.join("out", "state")
os.makedirs("out", exist_ok=True)
os.makedirs(STATE_OUT, exist_ok=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import ClaimBoard, Reporter  # noqa: E402

report = Reporter()
board = ClaimBoard()

# Stop CLAIMING here, even though the hard stop is later: the last claimed coin
# still has to finish and upload before GitHub kills the runner at six hours.
CLAIM_CUTOFF_S = 4.8 * 3600

# A retried pair is not re-attempted inside this many seconds of its failure.
# The old design queued every pair up front, so a retry landed minutes later,
# behind the whole slice; claiming one coin at a time can bring it back around
# in SECONDS — straight into the same venue blip, burning both redos on one
# outage. The pair prefers to WAIT BEHIND other work (the queue rotates), and
# only sleeps when there is nothing else left to do.
RETRY_COOLDOWN_S = 30.0


def log(msg):
    print(f"[shard {SHARD}] {msg}", flush=True)


def post_pair(coin, tf, lines) -> bool:
    """Send one finished pair's lines to the operator's PC. Best effort.

    Never raises and never stops the sweep: a PC that is asleep, a tunnel that
    dropped or a slow post costs immediacy only, because these very lines are
    also in this machine's artifact. Called AFTER the artifact write, so the
    record exists before the copy leaves.
    """
    if not (INGEST_URL and INGEST_TOKEN and lines):
        return False
    import gzip
    import hashlib
    import hmac
    import urllib.error
    import urllib.request

    body = gzip.compress("".join(lines).encode("utf-8"))
    # SIGNED, not carried: the secret itself never goes on the wire, so a post
    # that reached the wrong host (a recycled tunnel hostname) teaches it
    # nothing it can reuse. The path is signed with the body — the receiver
    # computes the same thing (live_ingest.sign).
    sig = hmac.new(INGEST_TOKEN.encode(), b"/rows" + body,
                   hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"{INGEST_URL}/rows", data=body, method="POST",
        # NOT Content-Encoding: a proxy may unzip that on the way and the
        # receiver would get bytes it cannot read. This is a gzip PAYLOAD.
        headers={"Content-Type": "application/octet-stream",
                 "X-Ingest-Sig": sig,
                 "X-Run-Id": os.environ.get("GITHUB_RUN_ID", "")})
    for attempt in range(1, INGEST_TRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=INGEST_TIMEOUT_S) as r:
                if r.status == 200:
                    _bump("posted")
                    return True
                why = f"HTTP {r.status}"
        except urllib.error.HTTPError as exc:
            why = f"HTTP {exc.code}"
            if exc.code in (401, 404, 413):
                # the door is shut, the wrong shape, or the body too big:
                # trying again cannot help, and 5,000 more posts would only
                # slow the sweep down
                globals()["INGEST_URL"] = ""
                log(f"live posting OFF for this machine ({why}) — every row "
                    f"still goes to the artifact")
                _bump("post_failed")
                return False
        except Exception as exc:                                # noqa: BLE001
            why = f"{type(exc).__name__}: {str(exc)[:60]}"
        if attempt >= INGEST_TRIES:
            log(f"{coin} {tf}: could not post to the PC ({why}) — it is in "
                f"the artifact, the collect will land it")
            _bump("post_failed")
            return False
        time.sleep(2.0 * attempt)
    return False


def eligible():
    """The WHOLE market's contracts, sorted — the same list on every shard.

    No slice here any more: the claim board decides who measures what, one
    coin at a time. The MIN_DAYS age screen moved to `old_enough`, checked per
    CLAIMED coin — screening the whole list per shard would be ~1,000 Day1
    fetches times twenty machines for coins most shards will never touch."""
    raw = fx._get_public(f"{fx.BASE}/api/v1/contract/detail").get("data") or []
    syms = sorted(x["symbol"] for x in raw
                  if str(x.get("symbol", "")).endswith("_USDT")
                  and int(x.get("state", 1)) == 0)
    if COIN_LIST:
        # THE COINS THE OPERATOR PICKED. The board is exactly these, so a
        # one-coin ask measures that one coin and nothing else.
        want = [c if c.endswith("_USDT") else f"{c}_USDT" for c in COIN_LIST]
        live = set(syms)
        board = sorted({s for s in want if s in live})
        missing = sorted({s for s in want if s not in live})
        if missing:
            # NAMED, never counted away (rule 20): a coin the operator asked
            # for and did not get has to be readable in the run's own log
            shown = ", ".join(m.replace("_USDT", "") for m in missing[:10])
            log(f"asked for {len(missing)} coin(s) the venue is not trading "
                f"right now — not measured: {shown}"
                + (f" … and {len(missing) - 10} more" if len(missing) > 10 else ""))
        log(f"{len(board)} coin(s) named by the dispatch — measuring exactly "
            f"those, not the whole market")
        return board
    log(f"{len(syms)} contracts on the board")
    return syms


def old_enough(sym):
    """The MIN_DAYS screen, for ONE claimed coin.

    A coin whose age check RAISES is kept, not dropped. It used to be dropped,
    so one timeout deleted a contract from the sweep with nothing but a log
    line to say so — the row's own `days` column is the honest place to report
    a short history, not silent removal from the search."""
    if MIN_DAYS <= 0:
        return True
    try:
        d = fx.klines(sym, "Day1", 500)
        return (d["Date"].iloc[-1] - d["Date"].iloc[0]).days >= MIN_DAYS
    except Exception as exc:
        log(f"{sym}: age check failed ({str(exc)[:50]}), keeping it anyway")
        return True


def coin_stream(coins, t0):
    """Yield the coins THIS shard measures: one claim at a time off the board.

    The walk starts at this shard's own region of the sorted list, so at the
    start the twenty shards claim in twenty different places and almost never
    race; a shard that finishes its region walks on into the next one — which
    is exactly the moment the old design went idle.

    Without a token (local runs, tests) it yields the old static slice, and
    ONLY then: a shard whose board breaks MID-RUN stops rather than guessing,
    because measuring a coin someone else owns writes the same rows twice and
    the collector appends duplicates.
    """
    if not board.enabled:
        mine = coins[SHARD::SHARDS]
        log(f"no claim board (no token) — static slice of {len(mine)}")
        yield from (mine[:PER_SHARD] if PER_SHARD else mine)
        return
    start = (SHARD * len(coins)) // SHARDS
    order = coins[start:] + coins[:start]
    # spread the first burst: twenty first-claims in the same second is
    # twenty commits racing one branch ref
    time.sleep((SHARD % SHARDS) * 0.7)
    seen_taken: set = set()
    claimed = 0
    dead = 0
    for sym in order:
        if PER_SHARD and claimed >= PER_SHARD:
            log(f"COINS cap reached ({PER_SHARD}) — stopping")
            return
        if time.time() - t0 > CLAIM_CUTOFF_S:
            log("claim cutoff reached — finishing what is queued, "
                "claiming nothing new so the artifact survives the 6h kill")
            return
        if sym in seen_taken:
            continue
        # refresh the board over git (free) so a taken coin costs no API call;
        # the PUT's own 422 is still the real lock for the race window
        seen_taken |= board.taken()
        if sym in seen_taken:
            continue
        got = board.claim(sym)
        if got is None:
            # Unreachable is not the same as contended. One dead answer skips
            # ONE coin (someone else probably has it anyway); three in a row is
            # a network that is actually down, and then the shard stops with
            # what it measured rather than risking a double-measured coin.
            dead += 1
            if dead >= 3:
                log("the claim board is unreachable (3 coins in a row) — "
                    "stopping with what is measured rather than risking a "
                    "double-measured coin")
                return
            log(f"claim of {sym} got no answer — skipping it, not stopping")
            continue
        dead = 0
        if not got:
            seen_taken.add(sym)
            continue
        claimed += 1
        yield sym


class PairFailed(Exception):
    """The venue failed this pair part-way. Nothing of it was written."""


# A rule may read up to 200 bars back (every confluence setup does, through
# its 200-bar average). Hand it fewer and it abstains -- silently, at the
# START of the window, where the abstention looks like "no trade" instead of
# "cannot tell". market_sweep uses the same number for the same reason.
WARMUP_BARS = 300


def window(df):
    """`(df, warm)` -- the measured window with WARMUP_BARS of history in
    front of it, and how many leading bars are warm-up only.

    Sep 11, 2026: this used to cut to DAYS+30 CALENDAR days and trade the
    whole cut from bar zero. At 4h, 30 days is 180 bars -- fewer than the 200
    a confluence rule needs -- so the rule was blind over the first 200 bars
    of its own window and 40% of MAV's signals never existed. The 30 days
    also scaled with nothing: it was 2,880 spare bars at 15m and not enough
    at 4h. BARS are what a lookback is counted in, so bars are what is kept.
    """
    import pandas as pd

    cut = pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(days=DAYS)
    measured = df[df["Date"] >= cut]
    warm = min(WARMUP_BARS, len(df) - len(measured))
    start = len(df) - len(measured) - warm
    return df.iloc[start:].reset_index(drop=True), warm


# ------------------------------------------------------------ saved positions
PRIOR: dict = {}          # "COIN-tf" -> path of its saved position, if any
STATE_IN_MIN_FREE_GB = 2.0   # kept for the shard's own rows and states


def _free_gb(path: str = ".") -> float:
    try:
        return shutil.disk_usage(path).free / 1e9
    except Exception:                                            # noqa: BLE001
        return float("inf")


def _state_artifact_bytes(run_id: str, repo: str):
    """What a run's `state-*` artifacts weigh, from the API; None when unknown.
    The download extracts to about the same size (the members are .json.gz)."""
    cmd = ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"]
    try:
        got = subprocess.run(cmd, capture_output=True, text=True, timeout=120)  # noqa: S603
        arts = json.loads(got.stdout or "{}").get("artifacts") or []
        return sum(int(a.get("size_in_bytes") or 0) for a in arts
                   if str(a.get("name") or "").startswith("state-")
                   and not a.get("expired"))
    except Exception:                                            # noqa: BLE001
        return None


def _bump(name: str) -> None:
    """report.continued / report.fresh — tolerant of a test's stand-in
    reporter that has no counters."""
    setattr(report, name, int(getattr(report, name, 0) or 0) + 1)


def _span(a_ms, b_ms):
    """The dates a tile shows, both ways: the runner's own text (its clock is
    UTC) for the log and older readers, and the milliseconds the browser
    formats with fmtWhenMs — so the tile and the store's "last bar" beside it
    name one bar the same way (RCA-2026-09-09-S)."""
    a, b = int(a_ms), int(b_ms)
    return f"{fmt_when(a / 1000)} → {fmt_when(b / 1000)}", [a, b]


def fetch_prior_states() -> dict:
    """Download the `state-*` artifacts of every run named in STATE_RUNS and
    index them by pair. NEWEST RUN FIRST, and the first run that has a pair
    keeps it — so the newest position wins, and a runner that runs out of disk
    loses the OLDEST runs rather than the freshest. (Before Sep 10, 2026 this
    walked oldest-first and let later runs overwrite; a named one-coin run then
    made the list longer than one, and oldest-first would have spent the disk
    on stale positions.)

    A run that cannot be downloaded (expired artifact, no permission, a
    network blip) costs nothing but a full measure for the pairs it held —
    named in the log, never a dead shard. Needs `actions: read` on the
    workflow token, which sweep.yml grants.

    Every machine downloads EVERY machine's positions — it cannot know which
    coins it will claim. A whole-market run saves ~2.2 MB per pair, so 5,347
    pairs are ~12 GB on each runner's disk (~21 GB free on ubuntu-latest,
    measured Sep 09, 2026). A run that will not fit is skipped up front, and a
    download that fails half-way is removed, so the shard's own rows and
    states never hit a full disk."""
    if MODE != "update" or not STATE_RUNS:
        return {}
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    index: dict = {}
    for run_id in STATE_RUNS:
        free = _free_gb()
        size = _state_artifact_bytes(run_id, repo) if repo else None
        if size is not None and size / 1e9 > free - STATE_IN_MIN_FREE_GB:
            log(f"saved positions from run {run_id}: {size / 1e9:.1f} GB of "
                f"artifacts against {free:.1f} GB of disk free — not downloaded; "
                f"its pairs are measured in full")
            continue
        dest = os.path.join("state_in", run_id)
        os.makedirs(dest, exist_ok=True)
        cmd = ["gh", "run", "download", str(run_id), "-p", "state-*", "-D", dest]
        if repo:
            cmd += ["--repo", repo]
        try:
            got = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=1800)                        # noqa: S603
        except Exception as exc:                                    # noqa: BLE001
            shutil.rmtree(dest, ignore_errors=True)
            log(f"saved positions from run {run_id}: could not download "
                f"({type(exc).__name__}: {str(exc)[:80]}) — its pairs are "
                f"measured in full")
            continue
        if got.returncode != 0:
            shutil.rmtree(dest, ignore_errors=True)   # a half-download must not eat the disk
            log(f"saved positions from run {run_id}: gh run download failed "
                f"({(got.stderr or '').strip()[:120]}) — its pairs are "
                f"measured in full")
            continue
        n, on_disk, older = 0, 0, 0
        for path in glob.glob(os.path.join(dest, "**", "*.json.gz"),
                              recursive=True):
            pair = os.path.basename(path)[:-len(".json.gz")]
            if pair in index:
                older += 1          # a newer run already has this pair
                continue
            index[pair] = path
            n += 1
            on_disk += os.path.getsize(path)
        log(f"saved positions from run {run_id}: {n} pair(s) · "
            f"{on_disk / 1e6:,.0f} MB on disk · {_free_gb():.1f} GB free"
            + (f" · {older} pair(s) a newer run already had" if older else ""))
    log(f"{len(index)} pair(s) have a saved position to continue from")
    return index


def state_usable(prior: dict) -> str:
    """"" when this saved position can be continued, else why not — the same
    rules market_sweep.run_pair applies to a PC state: a registry that grew a
    signal the state never measured, or another fingerprint, means a full
    measure, never a continuation that silently lacks rules."""
    if not prior or not int(prior.get("__last_ms__") or 0):
        return "no watermark"
    if prior.get("__version__") != VERSION:
        return f"fingerprint {prior.get('__version__')!r} is not {VERSION!r}"
    missing = set(br.SIGNALS) - set(prior.get("__signals__") or [])
    if missing:
        return f"{len(missing)} signal(s) it never measured ({sorted(missing)[0]}…)"
    # one writer per file, so one combination speaks for all of them
    combo = next((v for k, v in prior.items() if not str(k).startswith("__")), None)
    if isinstance(combo, dict) and "exit_at_last" not in combo:
        # saved by a continuation before Sep 09, 2026 (run 34360893326): without
        # the flag the boundary bar cannot be placed, so a full measure it is
        return "saved without the boundary flag (exit_at_last)"
    return ""


def write_state(coin, tf, states: dict, *, last_ms, first_ms, bars, fee) -> None:
    """One gzip'd JSON per pair, the PC's own layout plus meta (see
    resume_state). Written when the pair COMPLETES, beside its rows."""
    states = dict(states)
    states.update({"__last_ms__": int(last_ms), "__first_ms__": int(first_ms),
                   "__bars__": int(bars), "__signals__": sorted(br.SIGNALS),
                   "__version__": VERSION, "__fee__": float(fee)})
    path = os.path.join(STATE_OUT, f"{coin}-{tf}.json.gz")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(rs.pack(states))
    os.replace(tmp, path)


def _row(coin, tf, sig, thp, sl, tp, sz, r, *, days, bars, last_ms, fee, rt,
         liq_known, h1, h2) -> dict:
    """The row both paths write — ONE shape, whichever engine measured it. The
    full path hands fast_grid's report, the continuation the engine's; the
    keys and rounding are identical so the store never learns two dialects."""
    m = r["monthly"]
    return {"coin": coin, "tf": tf, "signal": sig, "th": thp,
            "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
            "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
            "base": BASE_MARGIN, "notional": BASE_MARGIN * at.LEVERAGE,
            "trades": r["trades"], "wins": r["wins"], "losses": r["losses"],
            "winrate": (round(100 * r["wins"] / r["trades"], 2)
                        if r["trades"] else 0.0),
            "profit": round(r["profit"], 2),
            "funding": round(r["funding_total"], 2),
            "h1": round(h1, 2), "h2": round(h2, 2),
            "green": r["months_green"], "months": r["months_total"],
            "worst": round(r["worst_trade"], 2), "dd": round(r["max_dd"], 2),
            "streak": round(r["worst_streak"], 2),
            "streak_len": r["worst_streak_len"],
            "liqs": r["liqs"], "stop_reachable": liq_known,
            "days": days, "last_ms": int(last_ms), "bars": bars,
            "monthly": {k: round(v, 2) for k, v in m.items()},
            "cost_of_tp": round(rt / tp * 100, 1), "rt": round(rt * 100, 4),
            "gate": "warn" if rt / tp >= .2 else "ok",
            # the fee this pair was charged, as the PC's rows carry it
            "fee": round(fee, 8)}


def continue_pair(sym, tf, prior: dict, out, *, i=0, n=0, rows_so_far=0):
    """UPDATE: walk only the bars newer than the saved position's watermark
    (plus the lookback the rules need) and continue every combination from
    where it stopped — the same engine call market_sweep makes on this PC.

    Nothing is written for a pair with no new bar (not even a done marker: the
    collector would take an empty marker as "measured, zero rows" and wipe the
    stored rows). Its saved position is re-emitted unchanged so the chain of
    runs keeps it. Returns the rows kept, like run_pair."""
    iv, bs, cap = br.TFS[tf]
    coin = sym.replace("_USDT", "")
    last_ms = int(prior["__last_ms__"])
    report("testing", i, n, rows=rows_so_far, span="",
           note=f"{coin} {tf}: continuing from {fmt_when(last_ms / 1000)} · "
                f"downloading new candles")
    # how many bars to ask for: the gap plus the lookback, never the cap —
    # a week of 15m is ~700 bars, not 35,000
    bar_ms = bs * 1000
    est_new = int((time.time() * 1000 - last_ms) // bar_ms) + 2
    need = est_new + CONTEXT_BARS + 50
    if need > cap:
        log(f"{coin} {tf}: the saved position is {est_new:,} bars old, more "
            f"than the {cap:,}-bar window — measured in full instead")
        return None                          # caller falls back to the full path
    try:
        fee = at.taker_fee(sym, fx=fx)
        liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
        fund = fx.funding_history(sym)
        book = fx.book_cost(sym, BASE_MARGIN * at.LEVERAGE)
        rt = br.round_trip_cost(fee, book)
        df = at._closed_bars(fx.klines(sym, iv, min(cap, need)), bs)
    except Exception as exc:
        raise PairFailed(f"{sym} {tf}: {str(exc)[:60]}") from exc
    frame, off, new_bars = rs.gap_frame(df, last_ms, CONTEXT_BARS)
    if frame is None or new_bars <= 0:
        log(f"{coin} {tf}: no new bars since {fmt_when(last_ms / 1000)} — "
            f"position kept, nothing written")
        write_state(coin, tf, {k: v for k, v in prior.items()
                               if not str(k).startswith("__")},
                    last_ms=last_ms, first_ms=prior.get("__first_ms__") or last_ms,
                    bars=prior.get("__bars__") or 0, fee=fee)
        _bump("continued")
        span, span_ms = _span(last_ms, last_ms)
        report("testing", i, n, rows=rows_so_far, span=span, span_ms=span_ms,
               note=f"{coin} {tf}: no new bars since the last test")
        return 0
    if off < CONTEXT_BARS and len(df) < need - 10:
        # the venue served fewer bars than asked and the lookback is short:
        # the rules would see less history than a full run did
        log(f"{coin} {tf}: only {off} bars of lookback before the new ones "
            f"(wanted {CONTEXT_BARS}) — measured in full instead")
        return None
    hi = [float(x) for x in frame["High"]]
    lo = [float(x) for x in frame["Low"]]
    cl = [float(x) for x in frame["Close"]]
    op = [float(x) for x in frame["Open"]]
    vol = [float(x) for x in frame["Volume"]] if "Volume" in frame.columns else None
    ts = list(frame["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    first_ms = int(prior.get("__first_ms__") or last_ms)
    bars_total = int(prior.get("__bars__") or 0) + new_bars
    days = int((frame["Date"].iloc[-1].timestamp() * 1000 - first_ms) // 86_400_000)
    span, span_ms = _span(last_ms, ts[-1])
    report("testing", i, n, rows=rows_so_far, span=span, span_ms=span_ms,
           note=f"{coin} {tf}: {new_bars:,} new bars · {len(br.SIGNALS)} rules")
    new_states = {k: v for k, v in prior.items() if not str(k).startswith("__")}
    kept = 0
    no_state = 0
    lines = []
    for si, sig in enumerate(br.SIGNALS, 1):
        key = f"{sig}_gh_{tf}"
        ths = br.THRESHOLDS[tf] if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                                      "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                             funding=fund, ts=ts)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue
            thp = 0.0 if th is None else round(th * 100, 3)
            for (sl, tp) in br.pairs_for(tf):
                if liq is not None and sl * 100 >= liq:
                    continue
                if rt / tp >= GATE_BLOCK:
                    continue
                for sz in br.SIZINGS:
                    ck = combo_key(sig, thp, sl * 100, tp * 100, sz)
                    prev = new_states.get(ck)
                    if prev is None:
                        # never measured before (a barrier the gate let
                        # through only now, a new pair in the grid): it has no
                        # position to continue and no history to measure over
                        # this short frame — counted, and measured on the
                        # next full run
                        no_state += 1
                        continue
                    try:
                        r, st = rs.continue_combo(
                            key, frame, BASE_MARGIN, fee=fee, sizing=sz,
                            dirs=dirs, tp=tp, sl=sl, liq=liq, funding=fund,
                            prev=prev, start_at=off)
                    except Exception:
                        continue
                    new_states[ck] = st
                    if not r["trades"]:
                        continue          # no trade at all is not a row
                    m = r["monthly"]
                    mk = sorted(m)
                    h1 = sum(m[k2] for k2 in mk[:max(1, len(mk) // 2)])
                    h2 = sum(m[k2] for k2 in mk[max(1, len(mk) // 2):])
                    lines.append(json.dumps(_row(
                        coin, tf, sig, thp, sl, tp, sz, r, days=days,
                        bars=bars_total, last_ms=ts[-1], fee=fee, rt=rt,
                        liq_known=liq is not None, h1=h1, h2=h2)) + "\n")
                    kept += 1
            at.STRATEGY_SPECS.pop(key, None)
        report("testing", i, n, rows=rows_so_far + kept, span=span, span_ms=span_ms,
               note=f"{coin} {tf}: rule {si}/{len(br.SIGNALS)} ({sig}) · continuing")
    lines.append(json.dumps({"coin": coin, "tf": tf, "pair_done": True,
                             "last_ms": int(ts[-1]), "rows": kept,
                             "bars": bars_total, "continued": True,
                             "gap_from_ms": last_ms}) + "\n")
    out.write("".join(lines))
    out.flush()
    post_pair(coin, tf, lines)
    write_state(coin, tf, new_states, last_ms=ts[-1], first_ms=first_ms,
                bars=bars_total, fee=fee)
    _bump("continued")
    if no_state:
        log(f"{coin} {tf}: {no_state} combination(s) had no saved position and "
            f"were skipped — a full run measures them")
    return kept


def run_pair(sym, tf, out, *, i=0, n=0, rows_so_far=0):
    """Measure one pair. Rows are BUFFERED and written only when the pair
    completes, so a pair that raises leaves nothing behind to mix with its
    redo. A venue failure raises PairFailed for main() to requeue.

    In UPDATE mode a pair with a usable saved position is CONTINUED over its
    new bars only (continue_pair); anything else is measured in full, and
    every pair leaves a saved position behind for the next run."""
    iv, bs, cap = br.TFS[tf]
    coin = sym.replace("_USDT", "")
    if MODE == "update":
        path = PRIOR.get(f"{coin}-{tf}")
        prior = None
        if path:
            try:
                with open(path, "rb") as fh:
                    prior = rs.unpack(fh.read())
            except Exception as exc:                            # noqa: BLE001
                log(f"{coin} {tf}: saved position unreadable "
                    f"({type(exc).__name__}) — measured in full")
        if prior is not None:
            why = state_usable(prior)
            if why:
                log(f"{coin} {tf}: saved position not continued — {why}; "
                    f"measured in full")
            else:
                got = continue_pair(sym, tf, prior, out, i=i, n=n,
                                    rows_so_far=rows_so_far)
                if got is not None:
                    return got
        else:
            log(f"{coin} {tf}: no saved position — first time on GitHub, "
                f"measured in full")
    _bump("fresh")
    # span="" CLEARS it, deliberately: the dates are not known until this
    # pair's candles are loaded, and carrying the PREVIOUS pair's span here
    # would print one pair's name beside another pair's dates
    # (label-must-match-data). Blank for a few seconds is the honest state.
    report("testing", i, n, rows=rows_so_far, span="",
           note=f"{sym.replace('_USDT', '')} {tf}: downloading candles")
    try:
        fee = at.taker_fee(sym, fx=fx)
        liq = fx.liquidation_move_pct(sym, at.LEVERAGE)
        fund = fx.funding_history(sym)
        book = fx.book_cost(sym, BASE_MARGIN * at.LEVERAGE)
        # ONE definition, shared with the local sweep — see
        # backtest_report.round_trip_cost for why spread/2 must not be added.
        rt = br.round_trip_cost(fee, book)
        df = at._closed_bars(fx.klines(sym, iv, cap), bs)
    except Exception as exc:
        raise PairFailed(f"{sym} {tf}: {str(exc)[:60]}") from exc
    df, warm = window(df)
    # the shared floor (backtest_report.MIN_BARS), never a private 2000: that
    # rejected 1h at 60 days and 1d always, while the local sweep measured them
    if len(df) - warm < br.min_bars(tf):
        log(f"{sym} {tf}: only {len(df) - warm} measurable bars, skipped")
        return 0
    coin = sym.replace("_USDT", "")
    # the MEASURED span, never the warm-up's. A row that says 59 days while
    # 33 of them were only feeding averages is a label over the wrong number.
    days = int((df["Date"].iloc[-1] - df["Date"].iloc[warm]).days)
    hi = [float(x) for x in df["High"]]
    lo = [float(x) for x in df["Low"]]
    cl = [float(x) for x in df["Close"]]
    op = [float(x) for x in df["Open"]]
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = list(df["Date"].to_numpy().astype("datetime64[ms]").astype("int64"))
    # `bars` and the half-split describe the MEASURED region: the warm-up
    # bars are history the rule was allowed to read, not bars it traded.
    nbars = len(df) - warm
    half = warm + (nbars // 2)
    kept = 0
    lines = []                  # written only when the pair completes
    pair_states: dict = {}      # combo key -> saved position (write_state)
    # Once per frame, for fast_grid: funding as cumulative-rate arrays and
    # each bar's month as an index, so no trade ever formats a timestamp.
    f_ms, f_rate = [], []
    for f_ in sorted(fund or [], key=lambda d: d["settle_ms"]):
        f_ms.append(int(f_["settle_ms"]))
        f_rate.append(float(f_["rate"]))
    f_cum = [0.0]
    for r_ in f_rate:
        f_cum.append(f_cum[-1] + r_)
    mo_codes = df["Date"].to_numpy().astype("datetime64[M]")
    mo_labels, mo_seen, mo_idx = [], {}, []
    for v_ in mo_codes:
        k_ = mo_seen.get(v_)
        if k_ is None:
            k_ = mo_seen[v_] = len(mo_labels)
            mo_labels.append(str(v_)[:7])
        mo_idx.append(k_)
    # WITH THE DATES, ON EVERY REPORT FOR THIS PAIR. The tile said "18,959
    # bars, testing 120 rules" and the operator could not answer their own
    # question about it: "i dont see what dates are being tested like is aug 3
    # - sept 27 being tested?" (2026-09-09). The span is THIS PAIR's real
    # first and last bar after the window cut — a young coin's span is
    # honestly shorter — via the one date formatter (CLAUDE.md).
    #
    # It lived INSIDE the note, written once, and the per-rule note below
    # overwrote it 120 times a pair. The reporter publishes at most once every
    # 45 seconds, so a tile showed dates only if its tick landed in the
    # instant between these two lines: measured on run 34307921614, 3 of 20
    # machines had dates and 17 did not, and the operator asked again ("so why
    # does it not show what dates its testing like machine 7"). `span` is its
    # own field now and rides every report until the next pair replaces it.
    # DATES ONLY. Operator, 2026-09-09: "you only need to show what date are
    # you testing like july 18 to sept 9 ... that way i know why its taking so
    # long". The bar count rides in the note; the span answers one question.
    span, span_ms = _span(df["Date"].iloc[0].timestamp() * 1000,
                          df["Date"].iloc[-1].timestamp() * 1000)
    report("testing", i, n, rows=rows_so_far, span=span, span_ms=span_ms,
           note=f"{coin} {tf}: {nbars:,} bars · {len(br.SIGNALS)} rules")
    for si, sig in enumerate(br.SIGNALS, 1):
        key = f"{sig}_gh_{tf}"
        # EVERY threshold, exactly as market_sweep.run_pair does with
        # thresholds=3. Taking only the middle one made the cloud grid a third
        # as wide as the Mac's for every momentum and fade rule, so a coin
        # measured here and the same coin measured locally were not the same
        # search — and the operator asked for a store they can trust.
        ths = br.THRESHOLDS[tf] if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                                      "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi, lo, cl, opens=op, volume=vol,
                                             funding=fund,
                                             ts=ts)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue          # this threshold only, not the whole rule
            thp = 0.0 if th is None else round(th * 100, 3)
            # One walk per combination (fast_grid): sizing never moves an exit
            # and the halves derive from the full walk, so six engine runs
            # collapse into two walks — parity-pinned in tests/test_fast_grid.py.
            # ~3x more market per 6-hour runner.
            # NO TRADING INSIDE THE WARM-UP. Those bars exist so the
            # averages are defined by the time the window starts; a signal
            # there would be measured on an indicator that is still filling.
            dirs_idx = [k2 for k2, v2 in enumerate(dirs) if v2 and k2 >= warm]
            for (sl, tp) in br.pairs_for(tf):
                if liq is not None and sl * 100 >= liq:
                    continue
                if rt / tp >= GATE_BLOCK:
                    continue
                try:
                    six = fg.combo_six(
                        dirs_idx, dirs, op, hi, lo, cl, tp=tp, sl=sl,
                        liq=None if liq is None else abs(liq) / 100.0,
                        half=half, base=BASE_MARGIN, lev=at.LEVERAGE,
                        fee=fee + 0.0003, ladder=at.ladder_margin,
                        mo_idx=mo_idx, mo_labels=mo_labels,
                        f_ms=f_ms, f_cum=f_cum, bar_ms=ts, with_trades=True)
                except Exception:
                    continue
                # the SIZINGS REGISTRY, never a literal. Operator, Sep 11, 2026:
                # "i only want flat so you will need to delete marigingalte for
                # my backtest as well" — and a hardcoded pair here would keep
                # twenty machines measuring the ladder for weeks after the grid
                # stopped asking for it (CLAUDE.md rules 18-19).
                for sz in br.SIZINGS:
                    r = six[sz]["full"]
                    # THE SAVED POSITION, from the same walk: what the next
                    # UPDATE continues from (fast_grid.end_state, parity-pinned
                    # against the engine's own resume state)
                    pair_states[combo_key(sig, thp, sl * 100, tp * 100, sz)] = \
                        fg.end_state(six["trades"], base=BASE_MARGIN,
                                     lev=at.LEVERAGE, fee=fee + 0.0003,
                                     sizing=sz, ladder=at.ladder_margin,
                                     mo_idx=mo_idx, mo_labels=mo_labels,
                                     opens=op, bar_ms=ts, last_ms=int(ts[-1]))
                    # EVERY row, winners and losers alike. This used to drop
                    # `profit <= 0 or trades < 100`, so a merged pair held only
                    # its profitable slice: "how many combinations were tested"
                    # became unanswerable, win/loss across the grid was
                    # meaningless, and a "profitable only" filter was a no-op
                    # because the losers were never written. The local sweep
                    # writes them; the cloud has to as well or the two stores
                    # are not the same measurement.
                    if not r["trades"]:
                        continue          # no trade at all is not a row
                    a = six[sz]["h1"]
                    b = six[sz]["h2"]
                    m = r["monthly"]
                    lines.append(json.dumps({
                        "coin": coin, "tf": tf, "signal": sig, "th": thp,
                        "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                        "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
                        "base": BASE_MARGIN, "notional": BASE_MARGIN * at.LEVERAGE,
                        "trades": r["trades"], "wins": r["wins"], "losses": r["losses"],
                        "winrate": (round(100 * r["wins"] / r["trades"], 2)
                                    if r["trades"] else 0.0),
                        "profit": round(r["profit"], 2),
                        "funding": round(r["funding_total"], 2),
                        "h1": round(a["profit"], 2), "h2": round(b["profit"], 2),
                        "green": r["months_green"], "months": r["months_total"],
                        "worst": round(r["worst_trade"], 2), "dd": round(r["max_dd"], 2),
                        # a cloud row and a local row sit side by side in the
                        # store, so the mandatory streak columns must match
                        "streak": round(r["worst_streak"], 2),
                        "streak_len": r["worst_streak_len"],
                        # honest when liquidation could not be read: unreachable
                        # stops are only screened out when liq is known
                        "liqs": r["liqs"], "stop_reachable": liq is not None,
                        "days": days,
                        # the last bar this pair was measured through, so the
                        # merge can record freshness instead of guessing
                        # int(), because ts comes from a numpy array and a
                        # numpy.int64 is not JSON serializable — every shard
                        # of run 32801805912 died on that at the first row it
                        # tried to write, 93 seconds in.
                        #
                        # And NO *1000: `ts` is already MILLISECONDS
                        # (datetime64[ms]). Multiplying gave 1787623200000000,
                        # a watermark a thousand times too large, which would
                        # have printed "measured through" a date in the year
                        # 58,000 and made every freshness comparison nonsense.
                        "last_ms": int(ts[-1]) if len(ts) else 0,
                        "bars": nbars, "monthly": {k: round(v, 2) for k, v in m.items()},
                        "cost_of_tp": round(rt / tp * 100, 1), "rt": round(rt * 100, 4),
                        "gate": "warn" if rt / tp >= .2 else "ok"}) + "\n")
                    kept += 1
        at.STRATEGY_SPECS.pop(key, None)
        report("testing", i, n, rows=rows_so_far + kept, span=span, span_ms=span_ms,
               note=f"{coin} {tf}: rule {si}/{len(br.SIGNALS)} ({sig})")
    # ONE MARKER PER MEASURED PAIR, rows or no rows. A thin coin whose every
    # combination fell under the trade floor wrote NOTHING, so the collect
    # could never know it was measured: ROAM_USDT 15m (35,764 bars) survived
    # two whole-market sweeps on Sep 06, 2026 and stayed "pending" — every
    # future run re-measured it for nothing. The marker carries the same
    # coin/tf keys as a row so the collector's pair grouping sees it, and
    # last_ms so the pair gets a real watermark.
    lines.append(json.dumps({"coin": coin, "tf": tf, "pair_done": True,
                             "last_ms": int(ts[-1]) if len(ts) else 0,
                             "rows": kept, "bars": nbars}) + "\n")
    out.write("".join(lines))
    out.flush()
    post_pair(coin, tf, lines)
    # and the position to continue from next time, beside the rows
    if len(ts):
        write_state(coin, tf, pair_states, last_ms=int(ts[-1]),
                    first_ms=int(ts[0]), bars=nbars, fee=fee)
    return kept


def main():
    from collections import deque

    t0 = time.time()
    coins = eligible()
    log(f"window: last {DAYS} days (+30 lookback), floors {br.MIN_BARS}")
    log(f"mode: {MODE}" + (f" · saved positions from run(s) "
                           f"{', '.join(STATE_RUNS)}" if STATE_RUNS else ""))
    PRIOR.update(fetch_prior_states())
    # The coins this RUN holds — the same number on every machine — so the
    # panel's "X/Y coins" is coins finished over the run. It used to be the
    # coin a machine is ON over the coins it has claimed, and the one-at-a-time
    # claim board keeps those equal: 100% from the first second
    # (RCA-2026-09-09-S).
    report.board = min(len(coins), PER_SHARD * SHARDS) if PER_SHARD else len(coins)
    total, redos, young = 0, 0, 0
    failed: list = []
    # The queue is PUMPED one claimed coin at a time — the next coin is only
    # claimed when the queue runs dry, so a shard never sits on coins it is
    # not measuring. A pair the venue failed still goes to the BACK and is
    # redone by itself; the other pairs keep going, the shard never restarts.
    stream = coin_stream(coins, t0)
    queue = deque()
    # Failed pairs wait HERE, not in the main queue: a retry runs only when
    # there is no fresh work left to claim — the same "after the others" the
    # up-front slice used to give it — so one venue blip is never re-entered
    # seconds later, burning both redos on the same outage.
    retries = deque()
    tries: dict = {}
    failed_at: dict = {}
    done_pairs = 0
    claimed = 0
    with open(OUT, "w") as out:
        while True:
            if not queue:
                sym = next(stream, None)
                if sym is not None:
                    if not old_enough(sym):
                        young += 1
                        log(f"{sym}: younger than {MIN_DAYS} days, screened out")
                        continue
                    claimed += 1
                    queue.extend((claimed, sym, tf) for tf in TFS)
                elif retries:
                    i2, s2, t2 = retries.popleft()
                    wait = RETRY_COOLDOWN_S - (time.time()
                                               - failed_at.get((s2, t2), 0.0))
                    if wait > 0:
                        time.sleep(wait)
                    queue.append((i2, s2, t2))
                else:
                    break
            i, sym, tf = queue.popleft()
            try:
                total += run_pair(sym, tf, out, i=i, n=claimed,
                                  rows_so_far=total)
                done_pairs += 1
                report.finished = done_pairs // len(TFS)
            except PairFailed as exc:
                n = tries.get((sym, tf), 0)
                if n < PAIR_RETRIES:
                    tries[(sym, tf)] = n + 1
                    failed_at[(sym, tf)] = time.time()
                    redos += 1
                    log(f"{exc} · nothing written, redoing {n + 1}/{PAIR_RETRIES} "
                        f"after the others")
                    retries.append((i, sym, tf))
                    continue
                failed.append(f"{sym} {tf}: {exc}")
                done_pairs += 1
                report.finished = done_pairs // len(TFS)
                log(f"{exc} · gave up after {PAIR_RETRIES} redos")
                # publish it NOW: a runner killed at six hours never reaches
                # the "done" report, and its named losses would die with it
                report("testing", done_pairs // len(TFS), claimed, rows=total,
                       note=f"{len(failed)} pair(s) lost so far", span="",
                       force=True, failed=failed)
            el = time.time() - t0
            if tf == TFS[-1]:
                log(f"{i}/{claimed} {sym} · {total:,} rows · "
                    f"{el / 60:.0f} min elapsed · "
                    f"{el / max(1, done_pairs) * len(TFS) / 60:.1f} min/coin")
            # A runner is killed at six hours with no artifact, so stop early
            # and keep what has been measured.
            if el > 5.2 * 3600:
                log(f"stopping at {i}/{claimed} coins to protect the artifact")
                break
    # span="" again: a finished machine is not testing a span any more, and
    # leaving the last pair's dates under "done" would read as still running
    report("done", claimed, claimed, rows=total, span="",
           note=(f"{total:,} rows · {claimed} coin(s) claimed · {redos} pair "
                 f"redo(s) · {len(failed)} pair(s) lost"
                 + (f" · {young} younger than {MIN_DAYS}d" if young else "")),
           force=True, failed=failed)
    log(f"done: {total:,} rows in {(time.time() - t0) / 60:.0f} min · "
        f"{redos} redo(s) · lost: {failed or 'none'}")
    log("PARITY: every threshold and every row, winners and losers, exactly "
        "as market_sweep.run_pair measures them — a cloud pair and a local "
        "pair are the same measurement and can be compared row for row.")


if __name__ == "__main__":
    main()
