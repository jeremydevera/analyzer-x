"""Each deployed id's win rate over the LAST 30 DAYS, up to the minute.

Operator, `Sep 29, 2026`: *"in the DEMO W/L · $ column i want the winrate for
that id for the past 30 days / not the winrate strating when i deployed it"*,
then: *"backtest last 30 days then include the websocket trade ... for
excample the backtest for last 30 days is 95% then i have 5 losing trades in
live, and the scheduled backtest is not running, this is where you should
calculate it, i need the live winrate for past 30 days"*.

So the figure is TWO sources joined at one moment, never overlapping:

    [now - 30 days ............ backtest's last candle]  the id's backtest trades
                               [backtest's last candle ...... now]  its practice trades

* The BACKTEST part is the id's own stored row, its trades rebuilt with the
  engine that measured it (`backtest_strategy`, minute-exact for a v2 id) on
  MEXC's candles cut at the row's own last candle — proved on #E2J3AJ6Z
  (APHSTOCK 30m cf_obretest): 25 trades, 22 won, +$4.56, exactly the stored
  row, rebuilt in 3.5 s. Rebuilt once per backtest update (the pair's
  watermark), in the background, and kept under ~/.tradingagents/rolling30/.
  A rebuild that does NOT match its stored row says so (`match: false`).
* The PRACTICE part is every practice exit of that slot (`key|COIN`) after
  the backtest's last candle — the trades the websocket-filled demo book
  actually made — read incrementally from the trade record, so five losses
  an hour after the backtest show at once.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

DAY_MS = 86_400_000
WINDOW_MS = 30 * DAY_MS


def home() -> Path:
    """Beside the rest of the app's state (a test's sandbox moves it)."""
    from tradingagents import auto_trader as at

    return Path(at.STATE_DIR) / "rolling30"


# ------------------------------------------------------------ the row itself
def _identity(settings: dict, slot: str) -> dict | None:
    """coin, tf, signal, th, sl, tp (percent) and which store, from the key."""
    from tradingagents import auto_trader as at
    from tradingagents import stores
    from tradingagents import strategy_keys as sk
    from tradingagents.local_history import _sig_of

    key, sym = slot.split("|", 1)
    spec = at.STRATEGY_SPECS.get(key)
    if not spec:
        return None
    tf = {v[0]: k for k, v in sk.TF_SPEC.items()}.get(spec.get("interval"))
    if not tf:
        return None
    sig = _sig_of(key)
    res = (settings.get("strategy_res") or {}).get(slot) or ""
    return {"key": key, "sym": sym, "coin": sym.replace("_USDT", ""), "tf": tf,
            "signal": sig, "sl": round(float(spec["sl"]) * 100, 3),
            "tp": round(float(spec["tp"]) * 100, 3),
            "th": round(float(spec.get("threshold") or 0) * 100, 3)
            if sig in sk.THRESHOLD_SIGNALS else 0.0,
            "res": res, "store": stores.V2 if res == "1m" else stores.V1}


def _stored(ident: dict) -> tuple[dict | None, int]:
    """(the stored flat row, the pair's watermark) in the row's own store."""
    from tradingagents import market_sweep as msw
    from tradingagents import watcher_candidates as wc

    root = ident["store"].home
    # THE LAST PAIR FILE PARSED IS KEPT (Oct 01, 2026): refresh() walks the
    # slots pair by pair, and #4FC03172 alone runs 2,594 rows on 515 pairs —
    # one parse per pair, not one per slot
    key = (str(root), ident["coin"], ident["tf"])
    try:
        mtime = (Path(root) / "rows" / f"{ident['coin']}-{ident['tf']}.json").stat().st_mtime
    except OSError:
        mtime = None
    hit = _PAIR_MEMO.get("last")
    if hit and hit[0] == key and hit[1] == mtime and mtime is not None:
        rows = hit[2]
    else:
        rows = msw.pair_rows(ident["coin"], ident["tf"], root=root)
        _PAIR_MEMO["last"] = (key, mtime, rows)
    return (wc._match(rows, ident), int(msw.pair_watermark(ident["coin"], ident["tf"], root=root) or 0))


_PAIR_MEMO: dict = {}


def _file_stamp(ident: dict) -> tuple | None:
    """(mtime_ns, size) of the pair's result file — a stat, never a parse;
    None when its store is not named (the watermark alone decides then)."""
    home_ = getattr(ident.get("store"), "home", None)
    if home_ is None:
        return None
    p = Path(home_) / "rows" / f"{ident['coin']}-{ident['tf']}.json"
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _current(have: dict | None, ident: dict, wm: int) -> bool:
    """Is a saved figure still the one its row would give? The same
    watermark AND the same result file."""
    if not have or have.get("wm") != wm:
        return False
    stamp = _file_stamp(ident)
    return stamp is None or list(have.get("file") or ()) == list(stamp)


def _watermark(ident: dict) -> int:
    """The pair's watermark alone — a 256-byte tail read
    (market_sweep.pair_watermark), never a parse of the ~6 MB pair file."""
    from tradingagents import market_sweep as msw

    return int(msw.pair_watermark(ident["coin"], ident["tf"], root=ident["store"].home) or 0)


def _cache_path(slot: str) -> Path:
    return home() / (slot.replace("|", "__") + ".json")


def _parse_when(s: str) -> int:
    """`Aug 30, 2026 6:30am` (fmt_when) back to epoch ms — parsing is allowed,
    printing is what CLAUDE.md's date rule governs."""
    return int(dt.datetime.strptime(s.strip(), "%b %d, %Y %I:%M%p").timestamp() * 1000)


def log_to_trades(log: list[dict]) -> list[list]:
    """The engine's trade log as [entry_ms, exit_ms, pnl] for every trade that
    CLOSED — one still open at the backtest's last candle has no result yet,
    and the practice book is what will say how it ended."""
    out = []
    for t in log:
        if t.get("why") == "END":
            continue
        exit_ms = t.get("exit_minute_ms") or _parse_when(t["exit time"])
        out.append([_parse_when(t["entry time"]), int(exit_ms), float(t["pnl $"])])
    return out


def rebuild(slot: str, settings: dict, *, deployed_at: float | None = None) -> dict:
    """Rebuild one slot's backtest trades and save them. Returns the record.
    `deployed_at`: the last time the slot was seen switched on — None means
    it is switched on now; the switched-off pass passes the record's own."""
    import numpy as np

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import exchange as fx

    ident = _identity(settings, slot)
    if ident is None:
        return {"slot": slot, "error": "its strategy recipe is not known"}
    row, wm = _stored(ident)
    if row is None or not wm:
        return {"slot": slot, "error": "no stored backtest row for it"}
    iv, bs, cap = br.TFS[ident["tf"]]
    # enough bars to reach back past the row's own start even when its
    # backtest is days old: the venue counts back from NOW, not from it
    behind = max(0, int((time.time() * 1000 - wm) / (bs * 1000)))
    df = at._closed_bars(fx.klines(ident["sym"], iv,
                                   min(cap, int(row["bars"]) + 400 + behind)), bs)
    ts_all = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    df = df[ts_all <= wm].reset_index(drop=True)
    # A GATE v2 ROW: the history GitHub's shard read — the row's own candles
    # and 300 in front of them — never the 400 asked for above, or a rule
    # that remembers further back reads another side (Oct 18, 2026)
    from tradingagents import market_sweep as _msw, venue as _venue

    if ident["res"] == "1m" and _venue.current() == "gate":
        df = df.iloc[_msw.shard_history_start(len(df), int(row["bars"])):].reset_index(drop=True)
    warm = max(0, len(df) - int(row["bars"]))
    fine = None
    if ident["res"] == "1m":
        # the finest bars the exchange has, the way every v2 caller reads
        # them (backtest_report.fine_bars; on Gate 5-minute bars over the
        # current month's hole, Oct 10, 2026)
        _t, _h, _l, _n5 = br.fine_bars(ident["sym"], int(time.time()) - 31 * 86400,
                                       fx=fx)
        fine = (_t, _h, _l)
    hi, lo, cl, op = ([float(x) for x in df[c]] for c in ("High", "Low", "Close", "Open"))
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = [int(x) for x in df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    fund = fx.funding_history(ident["sym"])
    liq = fx.liquidation_move_pct(ident["sym"], at.LEVERAGE)
    key = ident["key"]
    dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol, funding=fund, ts=ts)
    # the row's OWN cost, per side: its round trip is what the store charged
    side = float(row.get("rt") or 0) / 100 / 2
    # A ROW MEASURED WITH THE ORDER BOOK OF EACH MINUTE (Gate) is rebuilt with
    # the same book, up to the minute it was measured against, so it refuses
    # what the row refused (RCA-2026-10-10-H). The book's fills are the
    # slippage then: the fee is the taker's, and the coin's usual slippage
    # (round trip / 2 - fee) pays only a minute with no reading — never the
    # whole round trip as a fee, which would charge the spread twice.
    from tradingagents import cost_store as _cst

    _bend = _cst.row_book_end(row, wm // 1000)
    _book = (_cst.engine_book(ident["sym"], int(df["Date"].iloc[0].timestamp()), _bend)
             if _bend is not None and len(df) else None)
    if _book is not None:
        _fee = float(row.get("fee") or 0) or at.fee_floor()
        _cost = dict(fee=_fee, slippage=max(0.0, side - _fee), book=_book,
                     book_hold_s=bs * at.FUNDING_HOLD_BARS)
    else:
        _cost = dict(fee=side, slippage=0.0)
    # THE ROW'S OWN RULE (Oct 13, 2026): its `reenter` stamp — a row measured
    # since reads the candle a trade closed in, as the runner does; an
    # unstamped one was measured before, and its figure must add up to it
    _re = bool(row.get("reenter"))
    # ...and its closed-market rule, the same way (Oct 18, 2026): a stock
    # token's dead candle the row did not buy is not bought here either
    _cs = bool(row.get("closed_skip")) and _msw.closed_rule(ident["sym"])
    r = at.backtest_strategy(key, df, 5.0, sizing="flat",
                             dirs=dirs, tp=ident["tp"] / 100, sl=ident["sl"] / 100,
                             liq_move_pct=liq, funding=fund, keep_log=True,
                             start_at=warm, fine=fine, reenter=_re,
                             closed_skip=_cs, **_cost)
    rebuilt = {"trades": int(r["trades"]), "wins": int(r["wins"]),
               "profit": round(float(r["profit"]), 2)}
    stored = {"trades": int(row["trades"]), "wins": int(row["wins"]),
              "profit": round(float(row["profit"]), 2)}
    rec = {"slot": slot, "wm": wm, "bar_s": bs, "end_ms": wm + bs * 1000,
           "trades": log_to_trades(r["log"]), "stored": stored, "rebuilt": rebuilt,
           "match": same_result(stored, rebuilt), "at": time.time(),
           # the rule it was walked under — its row's, which changes only
           # when the row is re-measured, and that moves the watermark
           "reenter": _re,
           "closed_skip": _cs,
           # and its own store, so it can be rebuilt after its slot is
           # switched off and the room's `strategy_res` entry is gone
           "res": ident.get("res") or "",
           # the first ENTRY the walk could make: the reality check compares
           # only the hours both sides walked (forecast_v2.reality)
           "start_ms": int(ts[min(warm + 1, len(ts) - 1)]) if ts else None,
           # and the result file it was built from: a one-strategy UPDATE on
           # the candle the daily run measured through re-stamps the row
           # without moving the watermark (second review, Oct 14, 2026)
           "file": list(_file_stamp(ident) or ()),
           # the last time it was seen switched on: a switched-off figure
           # whose walk reaches it is settled (_settled)
           "deployed_at": time.time() if deployed_at is None else float(deployed_at)}
    home().mkdir(parents=True, exist_ok=True)
    tmp = _cache_path(slot).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, _cache_path(slot))
    return rec


def same_result(stored: dict, rebuilt: dict) -> bool:
    """The same trades and wins, and the profit to within rounding: the store
    rounds each trade's result before summing, the engine sums first, so
    FASTSTOCK 30m prank read +$96.64 stored against +$96.65 rebuilt."""
    return (stored["trades"] == rebuilt["trades"] and stored["wins"] == rebuilt["wins"]
            and abs(stored["profit"] - rebuilt["profit"]) <= 0.05)


_STATUS = {"last": None, "errors": {}, "running": False}


def refresh(settings: dict | None = None, *, pause: float = 0.3) -> dict:
    """Rebuild every deployed slot whose backtest moved since its last rebuild
    (its pair's watermark) — every row the grid prints a demo cell for. One at
    a time, a short pause between (each reads the live venue). Never under
    pytest: it would fetch real candles into the real cache."""
    from tradingagents import auto_trader as at

    if os.environ.get("PYTEST_CURRENT_TEST") and settings is None:
        return {"rebuilt": 0, "errors": {}, "skipped": "under pytest"}
    # EVERY PROFILE's rows (Sep 29, 2026): a slot's backtest is the same in
    # every room, so it is rebuilt once however many rooms run it
    if settings is None:
        from tradingagents import profiles

        each = []
        for pid in profiles.ids():
            with profiles.using(pid):
                each.append(at.load_settings())
    else:
        each = [settings]
    done, errors = 0, {}
    seen: set = set()
    _STATUS["running"] = True
    # PAIR BY PAIR: slots on one coin and timeframe in a row, so _stored's
    # memo parses each pair file once (a key names its timeframe, `c` the coin)
    def _order(kc):
        k, c = kc
        tf = next((t for t in ("15m", "30m", "1h", "4h", "1d") if f"_{t}_" in f"_{k}_"), "")
        return (c, tf, k)
    try:
        for key, c in sorted([(k, c) for st_ in each
                              for k, cs in (st_.get("strategy_coins") or {}).items()
                              for c in cs or []], key=_order):
            settings = next(st_ for st_ in each
                            if c in ((st_.get("strategy_coins") or {}).get(key) or []))
            slot = f"{key}|{c}"
            if slot in seen:
                continue
            seen.add(slot)
            try:
                ident = _identity(settings, slot)
                if ident is None:
                    continue
                # THE WATERMARK FIRST, from the file's tail (Oct 01, 2026): this
                # parsed every slot's whole pair file just to compare one
                # number — 3,000+ slots, ~6 MB each, every pass — and after a
                # restart that pass held 72% of the API's time (py-spy,
                # 1,120 samples): /api/health 59-77 s, a room's tiles 57.7 s.
                wm = _watermark(ident)
                have = _load(slot)
                if _current(have, ident, wm):
                    continue
                got = rebuild(slot, settings)
                if got.get("error"):
                    errors[slot] = got["error"]
                else:
                    done += 1
                time.sleep(pause)
            except Exception as exc:                       # noqa: BLE001
                errors[slot] = f"{type(exc).__name__}: {str(exc)[:160]}"
        done += _refresh_orphans(seen, errors, pause)
    finally:
        _STATUS.update(running=False, last=time.time(), errors=errors)
    return {"rebuilt": done, "errors": errors}


# THE FIGURES OF SWITCHED-OFF ROWS TOO (review, Oct 13, 2026). The Forecast
# reality check (forecast_v2.reality: took / gap, which corrects every
# Forecast v2 and Room strategies prediction) is read off the records of PAST
# switch-on stretches. All 19 on this PC belonged to slots no room runs any
# more; refresh walked deployed slots only and their `strategy_res` entries
# were gone, so none was ever rebuilt — their numbers, and from Oct 13, 2026
# their rule, stayed as they were for good. Each is rebuilt from its own store
# when its row is re-measured (the watermark moves), until it is SETTLED.
#
# AND THE PASS IS BOUNDED (second review, Oct 14, 2026): nothing deletes a
# figure — the MEXC era left 6,579 in 11 days, 308.5 s to read cold — and a
# Gate rebuild takes ~14 s in this process. Rebuilding every one whenever its
# row moved would grow without end, hold up the figures of the strategies
# switched on now, and slide each window away from the stretch it is read
# for. So a figure is settled once it reaches back to the last time its
# strategy was seen switched on under its store's rule of today, a pass
# rebuilds at most ORPHANS_PER_PASS, and a figure nobody wrote for
# ORPHAN_DAYS is not opened. A rebuild that fails, or raises, is not asked
# again until the row moves.
ORPHANS_PER_PASS = 20
ORPHAN_DAYS = 7
_ORPHANS_FAILED: dict = {}
_HEADS: dict = {}       # file name -> (mtime_ns, size, the record's small fields)


def _orphan_res(rec: dict) -> str | None:
    """The store a record belongs to: its own `res`, else — a record from
    before it was written — Backtest v2 when it was made on Gate after the
    move (Gate has no v1 rows), else unknown."""
    from tradingagents import venue

    if rec.get("res") is not None:
        return str(rec.get("res") or "")
    since = venue.since() or 0.0
    if venue.current() == "gate" and since and float(rec.get("at") or 0) >= since:
        return "1m"
    return None


def _head(entry) -> dict | None:
    """A record's small fields — parsed once per version of its file, and
    never its trades (the figures of strategies switched on are read through
    `_load`)."""
    st = entry.stat()
    hit = _HEADS.get(entry.name)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        rec = json.loads(Path(entry.path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    head = {k: rec.get(k) for k in ("slot", "wm", "file", "end_ms", "reenter")}
    head["res"] = _orphan_res(rec)
    # a record from before the field: its last rebuild was a switched-on one
    head["deployed_at"] = rec.get("deployed_at") or rec.get("at")
    _HEADS[entry.name] = (st.st_mtime_ns, st.st_size, head)
    return head


def _settled(head: dict) -> bool:
    """Nothing a rebuild could add: the figure walks up to the last time its
    strategy was seen switched on, under its store's rule of today. A later
    rebuild would only slide its 30 days off the stretch."""
    from tradingagents import backtest_report as br

    on = float(head.get("deployed_at") or 0)
    return (on > 0 and float(head.get("end_ms") or 0) >= on * 1000
            and bool(head.get("reenter")) == br.reenter_for(head.get("res")))


def _refresh_orphans(seen: set, errors: dict, pause: float) -> int:
    from tradingagents import auto_trader as at

    # a switched-off slot's key may be a runtime recipe no room loads now
    with contextlib.suppress(Exception):
        at.merge_runtime_specs()
    cutoff = time.time() - ORPHAN_DAYS * 86_400
    due, live = [], set()
    try:
        with os.scandir(home()) as it:
            entries = sorted((e for e in it if e.name.endswith(".json")), key=lambda e: e.name)
    except OSError:
        return 0
    for e in entries:
        try:
            if e.stat().st_mtime < cutoff:
                continue
            head = _head(e)
        except OSError:
            continue
        live.add(e.name)
        slot = str((head or {}).get("slot") or "")
        if not slot or "|" not in slot or slot in seen:
            continue
        seen.add(slot)
        if head["res"] is not None and not _settled(head):
            due.append((slot, head))
    for k in [k for k in _HEADS if k not in live]:
        _HEADS.pop(k, None)
    for k in [k for k in _ORPHANS_FAILED if k not in {s for s, _h in due}]:
        _ORPHANS_FAILED.pop(k, None)
    done = tried = 0
    for slot, head in due:
        if tried >= ORPHANS_PER_PASS:
            break
        own = {"strategy_res": {slot: head["res"]}}
        wm = 0
        try:
            ident = _identity(own, slot)
            if ident is None:
                continue
            wm = _watermark(ident)
            if not wm or _current(head, ident, wm) or _ORPHANS_FAILED.get(slot) == wm:
                continue
            tried += 1
            got = rebuild(slot, own, deployed_at=head["deployed_at"])
            if got.get("error"):
                _ORPHANS_FAILED[slot] = wm
                errors[slot] = got["error"]
            else:
                _ORPHANS_FAILED.pop(slot, None)
                done += 1
            time.sleep(pause)
        except Exception as exc:                               # noqa: BLE001
            if wm:
                _ORPHANS_FAILED[slot] = wm
            errors[slot] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return done


def status() -> dict:
    return dict(_STATUS)


# ------------------------------------------------------------- reading it
_MEMO: dict = {}


def _load(slot: str) -> dict | None:
    p = _cache_path(slot)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    hit = _MEMO.get(slot)
    if hit and hit[0] == mtime:
        return hit[1]
    with contextlib.suppress(OSError, ValueError):
        rec = json.loads(p.read_text(encoding="utf-8"))
        _MEMO[slot] = (mtime, rec)
        return rec
    return None


class _PracticeExits:
    """The trade record's practice exits of the last 31 days, read
    INCREMENTALLY: the file only grows, so each call parses only what was
    appended since the last one (the whole file is 16 MB and 2.5 s)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.path = None                 # the file the offset belongs to
        self.offset = 0
        self.rows: list[tuple] = []      # (ts, slot, pnl)

    def get(self, now: float) -> list[tuple]:
        from tradingagents import auto_trader as at

        with self.lock:
            path = Path(at._pp(at.LEDGER_PATH))
            if path != self.path:                  # an offset is one file's
                self.path, self.offset, self.rows = path, 0, []
            try:
                size = path.stat().st_size
            except OSError:
                return []
            if size < self.offset:                 # reset or rewritten
                self.offset, self.rows = 0, []
            if size > self.offset:
                with path.open("rb") as fh:
                    fh.seek(self.offset)
                    chunk = fh.read(size - self.offset)
                cut = chunk.rfind(b"\n")
                if cut >= 0:
                    self.offset += cut + 1
                    for line in chunk[:cut].splitlines():
                        with contextlib.suppress(ValueError):
                            e = json.loads(line)
                            if e.get("action") == "exit" and e.get("dry_run"):
                                self.rows.append((float(e.get("ts") or 0),
                                                  at.book_slot(e.get("strategy") or "",
                                                               e.get("symbol")),
                                                  float(e.get("pnl_est") or 0)))
            floor = now - 31 * 86_400
            if self.rows and self.rows[0][0] < floor:
                self.rows = [r for r in self.rows if r[0] >= floor]
            return list(self.rows)


class _PerRecord:
    """One incremental reader PER trade record: each profile has its own
    (tradingagents/profiles.py), and one shared reader would start over from
    the top every time the screen switched rooms."""

    def __init__(self):
        self.lock = threading.Lock()
        self.readers: dict = {}

    def get(self, now: float) -> list[tuple]:
        from tradingagents import auto_trader as at

        key = str(at._pp(at.LEDGER_PATH))
        with self.lock:
            r = self.readers.setdefault(key, _PracticeExits())
        return r.get(now)


PRACTICE = _PerRecord()


def figure(slot: str, *, now: float | None = None, exits: list | None = None,
           window_ms: int = WINDOW_MS) -> dict | None:
    """This slot's last-30-days record, or None when its backtest trades have
    not been rebuilt yet (the screen says so rather than print a guess).
    `window_ms` shortens it for a room that judges on 15 days (Sep 30, 2026);
    the DEMO column always asks for 30."""
    now = time.time() if now is None else now
    rec = _load(slot)
    if rec is None:
        return None
    lo = now * 1000 - int(window_ms)
    end = int(rec["end_ms"])
    bt = [t for t in rec["trades"] if lo <= t[1] <= end]
    pr = [e for e in (PRACTICE.get(now) if exits is None else exits)
          if e[1] == slot and e[0] * 1000 > end and e[0] * 1000 >= lo]
    pnls = [t[2] for t in bt] + [e[2] for e in pr]
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    return {"wins": wins, "losses": n - wins, "trades": n,
            "pnl": round(sum(pnls), 2), "winrate": round(100 * wins / n, 2) if n else None,
            "from_backtest": len(bt), "from_practice": len(pr),
            "backtest_through_ms": end,
            "match": same_result(rec["stored"], rec["rebuilt"]),
            "stored": rec["stored"], "rebuilt": rec["rebuilt"]}
