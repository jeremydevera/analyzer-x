"""THE SKILL ROOMS' FOLLOWER (Nov 10, 2026): practice trades written by Backtest v4's OWN engine.

The operator, Nov 10, 2026: *"can you deploy this 3 and remove the existing strategy in my auto
trade"*, then *"okay es for this"* to "you want practice to trade these exactly the way their
backtest did, so the forecast's dollars carry over". Spec:
docs/superpowers/specs/2026-11-10-skill-rooms-design.md, "3. The follower" and "4. The daily
refresh".

The three rooms #D7EN8BNV, #RSS7CUKH and #7T3VJU82 (`profiles.follows(pid) == "v4"`) have no runner
and no watcher. This module walks every strategy switched on in them through every CLOSED candle,
one candle at a time, with the backtest's own `skill_bt.step` - so practice and backtest cannot drift
apart: there is one set of rules. It writes each room's trade record (`at.append_ledger`) and open
positions (`at.save_state(keys=[slot])`) in the practice runner's shapes, so every Auto Trade panel
reads them unchanged. IT PLACES NO ORDER, EVER: nothing here imports an order call, and every row it
writes says `dry_run: true`.

The rules, each one from the spec:

* A candle belongs to the UTC day it OPENED on, and is processed only once that day's list
  (`stores.V4.home/rooms/<YYYY-MM-DD>.json`, written by the daily refresh) has landed. Until it
  does the room HOLDS at that midnight - entries and exits alike - and when the list lands every
  candle since is replayed at its real candle time (`filled_in` says how many trades that was).
* A strategy takes a NEW trade on a candle only when its id is on that candle's day list; a trade
  it already holds is always finished by its own rules (stop, target, its opposite signal).
* Switched on, a strategy is first WARMED UP: `skill_bt.run` over the newest `BARS[tf]` candles
  that opened before that midnight. A trade the warm-up leaves open is CARRIED - followed to its
  exit, so the strategy cannot buy before the backtest could, but never written (Forecast v4 did not
  count it either). Switched off and holding nothing, it goes COLD; switched on again later, it is
  warmed up again at that candle, as a fresh switch-on is.
* A signal is `skill_bt.signal_at` over a frame holding the full `BARS[tf]` candles ending at that
  candle, so a technical-analysis family reads the window its backtest read.
* A STOP OR TARGET IS SETTLED BY THE MINUTE (Nov 11, 2026, operator: "okay then change backtest and
  the practice rooms together, so they keep matching each other"): once a trade is open, each later
  candle's minutes are walked in order by the same `skill_bt.step` the daily run uses, and the first
  minute that touched the stop or target ends the trade - written at THAT minute (`ts`), with the
  candle it belongs to beside it (`v4_candle`, the agreement check's key). A candle is waited for
  until its last minute is final (`FINE_WAIT_S`), then - the exchange having no minutes under it -
  settled by its close as before. The minutes come from `skill_bt.read_fine`, one read a coin a pass.
* Every cost is the strategy's own: its fee and gap from the list it was switched on by (kept with
  the trade to its exit), and the coin's funding settled inside the hold (CLAUDE.md rule 9).
* A trade is closed DELISTED - at the last candle read, named - ONLY when the exchange's own
  contract list, read successfully, no longer has the coin (final review, Nov 11, 2026). A candle
  read that fails, however many passes running, never closes a trade: the record is append-only and
  a run of "too many requests" answers must not write a false exit. It is retried once later in the
  same pass, then named with how many passes it has failed, and the strategy waits where it was so
  the next pass catches up.
* Every exit pays the funding settled inside its hold, read as the backtest's shard reads it: back
  to the shard's 1d frame start (or the oldest open trade, if older), and from a read made DURING
  this pass - the adapter's half-hour copy would miss a settlement at the exit's own close.
* A row is never written twice: before appending, the follower checks the room's own trade
  record (and the keys it remembers) for that trade id and action - a pass killed between a row and
  its state is replayed by the next one without a duplicate. And only ONE pass runs at a time:
  `pass_once` itself holds `follow.lock` (a second pass, from the command line or a test beside the
  API's thread, writes nothing and says so), because the writer reads the record once at its start.
* A room's follower record that cannot be read is NAMED and never overwritten: nothing is done in
  that room until it is repaired or moved aside (a fresh start would rebuild an open trade as
  carried, or lose it). A pass that fails for a whole room saves its reason for the screen.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import os
import time
from pathlib import Path

DAY_MS = 86_400_000
DAY_S = 86_400
EVERY_S = 900                 # a pass after every 15-minute close ...
AFTER_CLOSE_S = 20            # ... 20 seconds after it
STALE_S = 1800                # a heartbeat older than this is a room "not following"
START_BACK_DAYS = 7           # a room with no state starts at its oldest list this recent
SPARE_BARS = 5
FINE_WAIT_S = 600             # a candle's last minute not final yet: wait this long, then the close decides
WRITTEN_KEEP = 5000           # trade rows (id + action) remembered as written, newest last
REPLACE_BUDGET_S = 3.0
BUSY = ("another follower pass is running (it holds the follow lock); this pass wrote nothing and "
        "the next one catches up")


# ------------------------------------------------------------------ where things are
def lists_home() -> Path:
    """The day lists' folder, resolved at the call (a test moves `stores.V4`)."""
    from tradingagents import stores

    return stores.V4.home / "rooms"


def list_path(day_s: int, lists_dir: Path | None = None) -> Path:
    """The list of the UTC day starting at `day_s`: `<lists>/<YYYY-MM-DD>.json`."""
    d = dt.datetime.fromtimestamp(int(day_s), dt.timezone.utc).date().isoformat()
    return Path(lists_dir or lists_home()) / f"{d}.json"


def _day_of(name: str) -> int | None:
    try:
        d = dt.date.fromisoformat(name)
    except ValueError:
        return None
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def state_path() -> Path:
    """The CURRENT room's follower state, beside its book (call inside `profiles.using`)."""
    import tradingagents.auto_trader as at

    return at._pp(at.STATE_PATH).with_name("v4_follow.json")


def _load() -> tuple[dict, str | None]:
    """(the current room's follower state, None) - {} when it has none - or ({}, why) when the file
    EXISTS but cannot be read. An unreadable one is named and never overwritten: read as "never ran",
    a fresh start would rebuild an open trade as carried, or lose it."""
    p = state_path()
    if not p.exists():
        return {}, None
    st = None
    for attempt in range(3):          # a swap under the reader (Windows) is a moment, not a fault
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            break
        except OSError as exc:
            if attempt == 2:
                return {}, f"{type(exc).__name__}: {exc.strerror or exc.errno}"
            time.sleep(0.05)
        except ValueError as exc:
            return {}, f"{type(exc).__name__}: {str(exc)[:160]}"
    if not isinstance(st, dict):
        return {}, f"it holds a {type(st).__name__}, not a record"
    return st, None


def load() -> dict:
    """The current room's follower state; {} when it has none or it cannot be read (`_load` says
    which)."""
    return _load()[0]


def unreadable_words(bad: str) -> str:
    """What every screen says about a room whose follower record cannot be read (never its path)."""
    return (f"this room's follower record cannot be read ({bad}); nothing is done in this room until it "
            f"is repaired or moved aside - it is never overwritten")


class _Unreadable(Exception):
    """The room's follower record exists and cannot be read: the room is left exactly as it is."""


def _save(st: dict) -> None:
    from tradingagents import portable

    st["written"] = list(st.get("written") or [])[-WRITTEN_KEEP:]
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st), encoding="utf-8")
    portable.replace_retry(tmp, p, REPLACE_BUDGET_S)


def rooms() -> list[str]:
    """The rooms this module follows, in tab order."""
    from tradingagents import profiles

    return [pid for pid in profiles.ids() if profiles.follows(pid) == "v4"]


def _bar_ms(tf: str) -> int:
    from tradingagents import backtest_report as br

    return int(br.TFS[tf][1]) * 1000


def _name(e: dict, sid: str) -> str:
    return f"{e['row']['coin']} {e['row']['tf']} {sid}"


def _px(x: float | None) -> float | None:
    return None if x is None else float(f"{float(x):.10g}")


# ------------------------------------------------------------------ the exchange (defaults)
def _fetch_default(sym, tf, bars=None, end_ms=None):
    from tradingagents import skill_frames

    return skill_frames.frame(sym, tf, bars, end_ms=end_ms)


def _funding_default(sym, since_ms=None, fresh_after_s=None):
    """The coin's settlements since `since_ms`, from a read made at or after `fresh_after_s` (the
    wall clock): the adapter's own copy is used only while it is that fresh (`max_age_s`)."""
    from tradingagents.dataflows import exchange as fx

    age = None if fresh_after_s is None else max(0.0, time.time() - float(fresh_after_s))
    return fx.funding_history(sym, since_ms=since_ms, max_age_s=age)


def _minutes_default(sym, start_s, end_s):
    """The coin's minutes between two instants (the archive, 5-minute bars over its monthly hole, the
    last week from REST): one door, `fx.minutes`."""
    from tradingagents.dataflows import exchange as fx

    return fx.minutes(sym, int(start_s), int(end_s))


def _listed_default():
    """{symbol: contract size} of every contract the exchange trades: one read gives both the
    delisting check and the size a position's `vol` is counted in (contracts, as the runner's)."""
    from tradingagents.dataflows import exchange as fx

    return {str(r["symbol"]): float(r.get("contract_size") or 0.0)
            for r in fx.list_contracts() if r.get("symbol")}


# ------------------------------------------------------------------ one pass's reads, shared by the rooms
class _Reads:
    """Every read a pass makes, made once: candle frames, funding, the contract list, day lists and
    signals. Nothing here is kept between passes."""

    def __init__(self, now_s, fetch, funding_of, listed, lists_dir, minutes=None):
        self.now_s = float(now_s)
        self.now_ms = int(now_s * 1000)
        self._fetch, self._funding_of, self._listed = fetch, funding_of, listed
        self._minutes = minutes
        self._fine: dict = {}
        self.lists_dir = Path(lists_dir) if lists_dir else lists_home()
        self._frames: dict = {}
        self._warm: dict = {}
        self._fund: dict = {}
        self._lists: dict = {}
        self._sigs: dict = {}
        self._opens: dict = {}
        self._listed_set: set | None = None
        self._sizes: dict = {}
        self._listed_read = False
        self.listed_error: str | None = None
        self.list_errors: dict = {}

    # -- candles
    def frame(self, sym: str, tf: str, from_ms: int):
        """Closed candles of (sym, tf) reaching back `BARS[tf]` candles before `from_ms`."""
        from tradingagents.skill_frames import BARS

        bar = _bar_ms(tf)
        n = BARS[tf] + max(0, (self.now_ms - int(from_ms)) // bar) + SPARE_BARS
        hit = self._frames.get((sym, tf))
        if hit is not None and hit[0] >= n:
            return hit[1]
        df = self._fetch(sym, tf, bars=n)
        self._frames[(sym, tf)] = (n, df)
        return df

    def warm_frame(self, sym: str, tf: str, end_ms: int):
        k = (sym, tf, int(end_ms))
        if k not in self._warm:
            self._warm[k] = self._fetch(sym, tf, end_ms=int(end_ms))
        return self._warm[k]

    def fine(self, sym: str, from_ms: int):
        """The coin's minutes from `from_ms` to now (`skill_bt.read_fine`), read ONCE a pass - again
        only to reach further back. A read that raises propagates: the strategy waits for the next
        pass, never decided on candles because its minutes could not be read."""
        from tradingagents import skill_bt as sb

        from_ms = int(from_ms) // sb.MINUTE_MS * sb.MINUTE_MS
        hit = self._fine.get(sym)
        if hit is None or from_ms < hit.from_ms:
            hit = sb.read_fine(sym, from_ms, minutes=self._minutes, now_s=self.now_s)
            self._fine[sym] = hit
        return hit

    def opens(self, df) -> list:
        k = id(df)
        if k not in self._opens:
            from tradingagents import skill_bt as sb

            self._opens[k] = (df, [int(x) for x in sb._ms(df.index)] if len(df) else [])
        return self._opens[k][1]

    def fund_since(self, since_ms: int | None = None) -> int:
        """Where a funding read starts: the shard's 1d frame start (its `BARS["1d"]` closed daily
        candles to today's midnight - `skill_shard.funding_of` reads from there), or `since_ms` (an
        open trade's fill) when that is older. Never later than the 1d start, so practice charges
        exactly the settlements the next day's backtest charges."""
        from tradingagents.skill_frames import BARS

        start = (self.now_ms // DAY_MS - BARS["1d"]) * DAY_MS
        return start if since_ms is None else min(start, int(since_ms))

    def funding(self, sym: str, since_ms: int | None = None):
        """The coin's funding, read ONCE a pass (again only to reach further back), from a read
        made during this pass: an exit written now pays every settlement up to its own close."""
        want = self.fund_since(since_ms)
        hit = self._fund.get(sym)
        if hit is None or want < hit[0]:
            from tradingagents import skill_bt as sb

            rows = self._funding_of(sym, since_ms=want, fresh_after_s=self.now_s)
            self._fund[sym] = (want, sb.Funding(rows))
        return self._fund[sym][1]

    # -- signals
    def signal(self, row: dict, df, i: int):
        """The signal of candle i, as the backtest computes it, over `df` up to and including i."""
        from tradingagents import skill_bt as sb
        from tradingagents.skill_frames import BARS

        k = (id(df), row["strategy"], json.dumps(row["params"], sort_keys=True), i)
        if k not in self._sigs:
            part = df.iloc[: i + 1]
            # signal_at reads the last candle by position: an empty frame has none (no signal)
            self._sigs[k] = None if len(part) == 0 else sb.signal_at(part, row["strategy"], row["params"],
                                                                      BARS[row["tf"]])
        return self._sigs[k]

    def warm_signals(self, row: dict, df, end_ms: int) -> list:
        from tradingagents import skill_bt as sb

        k = (row["coin"], row["tf"], int(end_ms), row["strategy"], json.dumps(row["params"], sort_keys=True))
        if k not in self._sigs:
            self._sigs[k] = sb.signals(df, row["strategy"], row["params"]) if len(df) else []
        return self._sigs[k]

    # -- the contract list
    def listed(self) -> set | None:
        """The exchange's contracts, or None when they cannot be read - then no coin is judged
        delisted this pass (an unreadable list is not an empty one), and no unread candle is
        counted toward closing a trade. `listed()` may answer a set of symbols or {symbol:
        contract size}; only the second can size a position."""
        if not self._listed_read:
            self._listed_read = True
            got: set = set()
            try:
                raw = self._listed() or ()
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        try:
                            self._sizes[str(k)] = float(v)
                        except (TypeError, ValueError):
                            pass
                got = {str(k) for k in raw}
            except Exception as exc:                                    # noqa: BLE001
                self.listed_error = f"{type(exc).__name__}: {exc}"
            if not got and self.listed_error is None:
                self.listed_error = "the list came back empty"
            self._listed_set = got or None
        return self._listed_set

    def contract_size(self, sym: str) -> float | None:
        """The exchange's contract size of `sym`, from the same read as `listed()`; None unknown."""
        self.listed()
        v = self._sizes.get(sym)
        return v if v and v > 0 else None

    def delisted(self, coin: str) -> bool:
        got = self.listed()
        return got is not None and f"{coin}_USDT" not in got and coin not in got

    # -- the day lists
    def list_days(self) -> list[int]:
        try:
            names = [p.stem for p in self.lists_dir.glob("*.json")]
        except OSError:
            return []
        return sorted(d for d in (_day_of(n) for n in names) if d is not None)

    def room_list(self, day_s: int, pid: str) -> dict | None:
        """{id: row} switched on in room `pid` on the day starting `day_s`; None while that day's
        list has not landed (or cannot be read - named in `list_errors`)."""
        day_s = int(day_s)
        if day_s not in self._lists:
            p = list_path(day_s, self.lists_dir)
            doc = None
            if p.exists():
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(doc, dict) or not isinstance(doc.get("rooms", {}), dict):
                        raise ValueError("not a day list")
                except (OSError, ValueError) as exc:
                    # never the file's name or path on a screen (final review, Nov 11, 2026)
                    from tradingagents.positions_view import fmt_when

                    said = (exc.strerror or exc.errno) if isinstance(exc, OSError) else str(exc)[:120]
                    self.list_errors[day_s] = (f"the list of the day that began {fmt_when(day_s)} cannot be "
                                               f"read ({type(exc).__name__}: {said})")
                    doc = None
            self._lists[day_s] = doc
        doc = self._lists[day_s]
        if doc is None:
            return None
        return {str(r["id"]): r for r in (doc.get("rooms") or {}).get(pid) or [] if r.get("id")}


# ------------------------------------------------------------------ what a room writes
class _Writer:
    """Ledger rows and state slots in the practice runner's shapes (auto_trader.py, the practice
    `enter` row ~7342, its position ~7314, the `exit` row ~6793), each written once."""

    def __init__(self, st: dict, out: dict, now_s: float, release_ms: int | None, size_of=None):
        import tradingagents.auto_trader as at

        self.at = at
        self.size_of = size_of or (lambda sym: None)
        self.unsized: set = set()
        self.st = st
        self.out = out
        self.now_s = now_s
        self.release_ms = release_ms
        self.filled: set = set()
        st.setdefault("written", [])
        self.written = set(st["written"])
        # THE RECORD ITSELF: a pass killed after a row and before its state was saved has the row
        # here and not in `written`
        for r in at.ledger_trades(0):
            if str(r.get("strategy") or "").startswith("v4_") and r.get("trade_id"):
                self.written.add(f"{r['trade_id']}:{r.get('action')}")

    def _put(self, row: dict, candle_ms: int) -> bool:
        k = f"{row['trade_id']}:{row['action']}"
        if k in self.written:
            return False
        self.at.append_ledger(row)
        self.written.add(k)
        self.st["written"].append(k)
        if self.release_ms is not None and candle_ms >= self.release_ms:
            self.filled.add(row["trade_id"])
        return True

    def _slot(self, sym: str, key: str, position: dict | None) -> None:
        slot = self.at.state_key(sym, True, key)
        book = self.at.load_state()
        book[slot] = {"step": 0, "last_ts": {}, "position": position}
        self.at.save_state(book, keys=[slot])

    def enter(self, sid: str, row: dict, pos: dict, fee: float, slip: float, bar_ms: int) -> None:
        from tradingagents import skill_bt as sb

        sym, key = f"{row['coin']}_USDT", f"v4_{sid}"
        side = 1 if pos["dir"] == "long" else -1
        entry_ts = int(pos["t"]) // 1000
        fill_s = (int(pos["t"]) + bar_ms) // 1000
        px = float(pos["px"])
        stop, target = float(row["stop"]), row.get("target")
        sl = _px(px * (1 - side * stop))
        tp = _px(px * (1 + side * float(target))) if target else None
        tid = self.at.trade_code(sym, key, entry_ts, side, dry=True)
        lev = self.at.LEVERAGE
        margin = sb.NOTIONAL / lev
        # IN CONTRACTS, as the runner's (`fx.contracts_for`) and as every reader multiplies it
        # (positions_view: notional = entry x vol x contract size). A size the exchange did not
        # give is left BLANK and named - a wrong size prints wrong dollars, a blank prints none
        cs = self.size_of(sym)
        vol = sb.NOTIONAL / (px * cs) if cs else None
        if vol is None and sym not in self.unsized:
            self.unsized.add(sym)
            self.out["errors"].append(f"{row['coin']} {row['tf']} {sid}: the exchange gave no contract size "
                                      f"for {sym}, so the position's size (vol) is left blank")
        if self._put({"ts": fill_s, "symbol": sym, "action": "enter", "strategy": key, "entry_ts": entry_ts,
                      "trade_id": tid, "opened_at": fill_s, "side": "LONG" if side > 0 else "SHORT",
                      "vol": vol, "entry": px, "tp": tp, "sl": sl, "margin": margin, "leverage": lev,
                      "step": 0, "dry_run": True, "fee": fee, "slip": slip, "v4_id": sid,
                      "written_at": self.now_s}, int(pos["t"])):
            self.out["entered"] += 1
        self._slot(sym, key, {"side": side, "vol": vol, "entry": px, "tp": tp, "sl": sl, "margin": margin,
                              "strategy": key, "entry_ts": entry_ts, "opened_at": fill_s, "trade_id": tid,
                              "dry": True, "bracket": True, "v4_id": sid})

    def exit(self, sid: str, row: dict, trade: dict, bar_ms: int) -> None:
        sym, key = f"{row['coin']}_USDT", f"v4_{sid}"
        entry_ts = int(trade["entry_ms"]) // 1000
        fill_s = (int(trade["entry_ms"]) + bar_ms) // 1000
        # a trade the minutes settled ends in its own minute (`at`); any other at its candle's close
        exit_s = int(trade["at"]) // 1000 if trade.get("at") is not None else (int(trade["exit_ms"]) + bar_ms) // 1000
        tid = self.at.trade_code(sym, key, entry_ts, trade["side"], dry=True)
        x = {"ts": exit_s, "symbol": sym, "action": "exit", "why": trade["why"], "strategy": key,
             "trade_id": tid, "entry_ts": entry_ts, "opened_at": fill_s, "held_s": exit_s - fill_s,
             "side": "LONG" if trade["side"] > 0 else "SHORT", "entry": float(trade["entry_px"]),
             "exit": float(trade["exit_px"]), "pnl_est": float(trade["pnl"]), "pnl_source": "v4_engine",
             "step_next": 0, "dry_run": True, "v4_id": sid, "written_at": self.now_s,
             "v4_candle": int(trade["exit_ms"]) // 1000}      # the candle it ended in: the agreement's key
        if trade.get("at") is not None:
            x["by_minute"] = True
        if "fund" in trade:
            x["fund"] = float(trade["fund"])
        else:
            x["fund_unknown"] = True
        if self._put(x, int(trade["exit_ms"])):
            self.out["exited"] += 1
        self._slot(sym, key, None)


# ------------------------------------------------------------------ one room
class _Room:
    def __init__(self, pid: str, R: _Reads):
        self.pid, self.R = pid, R
        self.st, bad = _load()
        if bad:
            raise _Unreadable(bad)
        self.st.setdefault("strats", {})
        self.st.setdefault("pending", {})
        self.errors: list[str] = []
        self.tally: dict = {}          # candle-steps of a held trade settled by minute / by candle
        self.out = {"processed": 0, "entered": 0, "exited": 0, "held_at": None, "errors": self.errors}
        self.newest_close = int(self.st.get("last_candle_ms") or 0)

    # -- the days whose lists have landed
    def _open_days(self) -> tuple[int | None, int | None, list[int]]:
        R = self.R
        today = R.now_ms // DAY_MS * DAY_S
        nd = self.st.get("next_day_s")
        if nd is None:
            days = [d for d in R.list_days() if today - START_BACK_DAYS * DAY_S <= d <= today]
            nd = days[0] if days else None
        if nd is None:
            return None, today, []
        nd, held, opened = int(nd), None, []
        while nd <= today:
            if R.room_list(nd, self.pid) is None:
                held = nd
                if nd in R.list_errors:
                    self.errors.append(R.list_errors[nd])
                break
            opened.append(nd)
            nd += DAY_S
        return nd, held, opened

    def run(self) -> dict:
        R, st = self.R, self.st
        prev_held = st.get("held_at")
        nd, held, opened = self._open_days()
        st["next_day_s"] = nd
        self.frontier_ms = None if nd is None else nd * 1000
        release = int(prev_held) * 1000 if prev_held is not None and int(prev_held) in opened else None
        self.W = _Writer(st, self.out, R.now_s, release, size_of=R.contract_size)
        for d in opened:
            for sid, row in (R.room_list(d, self.pid) or {}).items():
                if sid not in st["strats"] and sid not in st["pending"]:
                    st["pending"][sid] = {"day_s": d, "row": row}
        if (st["strats"] or st["pending"]) and R.listed() is None:
            self.errors.append(f"could not read the exchange's contract list ({R.listed_error}): no coin "
                               f"was judged delisted")
        self._warm_pending()
        self._follow_all()
        self._drop_cold()
        st["held_at"] = held
        if release is not None:
            st["filled_in"] = len(self.W.filled)
            st["filled_day_s"] = int(prev_held)
        st.setdefault("filled_in", 0)
        st["last_pass_s"] = R.now_s
        st["last_candle_ms"] = self.newest_close or None
        st["errors"] = list(self.errors)
        st.pop("pass_error", None)            # a pass that ran: an earlier failure is no longer the news
        st.pop("pass_error_s", None)
        _save(st)
        self.out["held_at"] = held
        return self.out

    # -- switch-on: the warm-up
    def _warm(self, sid: str, row: dict, end_ms: int) -> dict:
        """The strategy as the backtest stands at `end_ms`: `skill_bt.run` over the newest BARS[tf]
        candles that opened before it, its open trade CARRIED."""
        from tradingagents import skill_bt as sb

        R = self.R
        sym, tf, bar_ms = f"{row['coin']}_USDT", row["tf"], _bar_ms(row["tf"])
        df = R.warm_frame(sym, tf, end_ms)
        opens = R.opens(df)
        fund = R.funding(sym, opens[0] if opens else None)
        pos = None
        if len(df):
            # the minutes the daily run read for THIS midnight: MINUTE_DAYS back from it, so a candle is
            # settled by the minute here exactly when it was in the backtest this room was chosen from
            fine = R.fine(sym, sb.fine_from_ms(int(end_ms) // DAY_MS * DAY_MS))
            _done, pos = sb.run(df, R.warm_signals(row, df, end_ms), stop=float(row["stop"]),
                                fee=float(row["fee"]), slip=float(row["slip"]), target=row.get("target"),
                                funding=fund, bar_ms=bar_ms, fine=fine)
        return {"row": row, "last_ms": opens[-1] if opens else int(end_ms) - 1,
                "last_close": float(df["close"].iloc[-1]) if len(df) else None,
                "pos": pos, "carried": pos is not None, "cold": False, "fails": 0,
                "pos_fee": float(row["fee"]), "pos_slip": float(row["slip"])}

    def _warm_pending(self) -> None:
        st, retry = self.st, []
        for sid, p in sorted(st["pending"].items()):
            row = p["row"]
            if self.R.delisted(row["coin"]):
                del st["pending"][sid]
                self.errors.append(f"{row['coin']} {row['tf']} {sid}: delisted, not switched on")
                continue
            try:
                st["strats"][sid] = self._warm(sid, row, int(p["day_s"]) * 1000)
                del st["pending"][sid]
            except Exception:                                          # noqa: BLE001
                retry.append(sid)
        for sid in retry:                     # once more, after the others
            p = st["pending"][sid]
            try:
                st["strats"][sid] = self._warm(sid, p["row"], int(p["day_s"]) * 1000)
                del st["pending"][sid]
            except Exception as exc:                                    # noqa: BLE001
                self.errors.append(f"{p['row']['coin']} {p['row']['tf']} {sid}: {type(exc).__name__}: {exc}")
        if st["strats"] or retry:
            _save(st)

    # -- every closed candle, in order
    def _follow_all(self) -> None:
        st = self.st
        groups: dict = {}
        for sid, e in st["strats"].items():
            groups.setdefault((f"{e['row']['coin']}_USDT", e["row"]["tf"]), []).append(sid)
        failed = []
        for key, sids in sorted(groups.items()):
            if not self._follow_group(key, sids, last_try=False):
                failed.append((key, sids))
        for key, sids in failed:              # once more, after the others
            self._follow_group(key, sids, last_try=True)

    def _follow_group(self, key: tuple, sids: list, *, last_try: bool) -> bool:
        st, R = self.st, self.R
        sym, tf = key
        coin = sym[: -len("_USDT")] if sym.endswith("_USDT") else sym
        gone = R.delisted(coin)
        try:
            df = R.frame(sym, tf, min(int(st["strats"][s]["last_ms"]) for s in sids))
        except Exception as exc:                                        # noqa: BLE001
            if not last_try:
                return False
            for sid in sids:
                self._unread(sid, exc, gone)
            return True
        for sid in sids:
            st["strats"][sid]["fails"] = 0        # the candles were read: a run of failures ends
        try:
            fund = R.funding(sym, self._oldest_fill(sids))
        except Exception as exc:                                        # noqa: BLE001
            # NOT A DELISTING (review, Nov 10, 2026): a funding read that fails alone skips the
            # coin's candles this pass - never charged as free, never counted toward closing a
            # trade - and the next pass catches up. Only a coin the exchange no longer lists is
            # closed, at the last candle read, its funding marked unknown.
            if not last_try:
                return False
            for sid in sids:
                e = st["strats"][sid]
                if gone:
                    self._delist(sid, e, None, "delisted by the exchange")
                else:
                    self.errors.append(f"{_name(e, sid)}: its funding could not be read ({type(exc).__name__}: "
                                       f"{exc}); its candles wait for the next pass")
            _save(st)
            return True
        for sid in sids:
            e = st["strats"][sid]
            try:
                self._advance(sid, e, df, fund, entries=not gone)
            except Exception as exc:                                    # noqa: BLE001
                self.errors.append(f"{_name(e, sid)}: {type(exc).__name__}: {exc}")
            if gone:
                self._delist(sid, e, fund, "delisted by the exchange")
            _save(st)
        return True

    def _oldest_fill(self, sids: list) -> int | None:
        """The earliest entry fill among the trades `sids` hold (carried ones too), or None."""
        fills = []
        for sid in sids:
            e = self.st["strats"][sid]
            pos = e.get("pos")
            if pos is not None:
                fills.append(int(pos.get("fill_ms", int(pos["t"]) + _bar_ms(e["row"]["tf"]))))
        return min(fills) if fills else None

    def _unread(self, sid: str, exc: Exception, gone: bool) -> None:
        """A strategy whose candles could not be read this pass (after the retry): named with how many
        passes running it has failed, its candles left where they were - it WAITS. A failed read never
        closes a trade (final review, Nov 11, 2026: the record is append-only, and a run of "too many
        requests" answers is not a delisting). Only a coin the exchange's own contract list, read
        successfully, no longer has is closed, at the last candle read."""
        st = self.st
        e = st["strats"][sid]
        e["fails"] = int(e.get("fails") or 0) + 1
        if gone:
            fund = None
            try:
                fund = self.R.funding(f"{e['row']['coin']}_USDT", self._oldest_fill([sid]))
            except Exception:                                           # noqa: BLE001
                fund = None
            self.errors.append(f"{_name(e, sid)}: {type(exc).__name__}: {exc}")
            self._delist(sid, e, fund, "delisted by the exchange")
        else:
            n = e["fails"]
            self.errors.append(
                f"{_name(e, sid)}: {type(exc).__name__}: {exc}; its candles could not be read "
                f"({n} pass{'' if n == 1 else 'es'} running) - it waits for the next pass, and only the "
                f"exchange's own contract list can close its trade"
                + ("" if self.R.listed() is not None else
                   "; the exchange's contract list could not be read either"))
        _save(st)

    def _delist(self, sid: str, e: dict, fund, why: str) -> None:
        """Close what `sid` holds at the last candle it read (`why` DELISTED) and stop following it."""
        from tradingagents import skill_bt as sb

        pos, row = e.get("pos"), e["row"]
        if pos is not None and e.get("last_close") is not None:
            c, slip = float(e["last_close"]), float(e.get("pos_slip", row["slip"]))
            px = c * (1 - slip) if pos["dir"] == "long" else c * (1 + slip)
            bar_ms = _bar_ms(row["tf"])
            trade = sb.close_position(pos, px, int(e["last_ms"]), why="DELISTED", stop=float(row["stop"]),
                                      fee=float(e.get("pos_fee", row["fee"])), target=row.get("target"),
                                      bar_ms=bar_ms, funding=fund)
            if not e.get("carried"):
                self.W.exit(sid, row, trade, bar_ms)
            from tradingagents.positions_view import fmt_when

            why += f"; its trade closed at the candle of {fmt_when(int(e['last_ms']) // 1000)}"
        self.errors.append(f"{_name(e, sid)}: {why}")
        self.st["strats"].pop(sid, None)

    def _advance(self, sid: str, e: dict, df, fund, *, entries: bool = True) -> None:
        """Every closed candle of `df` after `e["last_ms"]`, up to the first held day."""
        from tradingagents import skill_bt as sb

        R = self.R
        bar_ms = _bar_ms(e["row"]["tf"])
        opens = R.opens(df)
        closes = df["close"].to_numpy() if len(df) else []
        i = bisect.bisect_right(opens, int(e["last_ms"]))
        # a frame that starts after the next candle this strategy needs (the read was cut short);
        # never after an EMPTY warm-up, whose `last_ms` is only "anything from midnight on"
        if i == 0 and opens and opens[0] > int(e["last_ms"]) + bar_ms and e.get("last_close") is not None:
            from tradingagents.positions_view import fmt_when

            self.errors.append(f"{_name(e, sid)}: the candles from {fmt_when(int(e['last_ms']) // 1000)} "
                               f"could not be read; it follows on from {fmt_when(opens[0] // 1000)}")
        while i < len(opens):
            o = opens[i]
            if o + bar_ms > R.now_ms or self.frontier_ms is None or o >= self.frontier_ms:
                break                         # not closed yet, or its day's list has not landed
            day_list = R.room_list(o // DAY_MS * DAY_S, self.pid)
            if day_list is None:
                self.errors.append(f"{_name(e, sid)}: the list of its candle's day cannot be read")
                break
            on = entries and sid in day_list
            if on:
                e["row"] = day_list[sid]
            row = e["row"]
            close = float(closes[i])
            if e.get("cold"):
                if not on:
                    self._done_candle(e, o, close, bar_ms)
                    i += 1
                    continue
                e.update(self._warm(sid, row, o))       # switched on again: warmed up at this candle
            elif e.get("pos") is None and not on:
                e["cold"] = True                         # switched off, holding nothing
                self._done_candle(e, o, close, bar_ms)
                i += 1
                continue
            pos = e.get("pos")
            sig = R.signal(row, df, i)
            fee, slip = ((float(e["pos_fee"]), float(e["pos_slip"])) if pos is not None
                         else (float(row["fee"]), float(row["slip"])))
            fine = None
            if pos is not None:
                # a held trade's candle is settled by its minutes: read them (once a pass), and wait
                # for the candle's last minute to be final rather than decide on its close
                fine = R.fine(f"{row['coin']}_USDT", o)
                # WAIT only for a minute that is on its way: minutes up to just short of the candle's
                # end are there. No minute at all under the range (a coin the exchange keeps none
                # for) is settled by the close at once, as the daily run settles it.
                if len(fine.t) and not fine.covers(o, bar_ms) and o + bar_ms > fine.to_ms and \
                        R.now_ms - (o + bar_ms) < FINE_WAIT_S * 1000:
                    break
            new, done = sb.step(pos, sig, close=close, when_ms=o, bar_ms=bar_ms, stop=float(row["stop"]),
                                fee=fee, slip=slip, target=row.get("target"), funding=fund, fine=fine,
                                tally=self.tally)
            if done is not None:
                if not e.get("carried"):
                    self.W.exit(sid, row, done, bar_ms)
                e["carried"] = False
            if new is not None and new is not pos:      # a new trade on this candle's close
                if on:
                    self.W.enter(sid, row, new, fee, slip, bar_ms)
                    e["carried"] = False
                    e["pos_fee"], e["pos_slip"] = fee, slip
                else:
                    # switched off: no new trade - but the backtest HOLDS the one it opened here, so
                    # the strategy goes cold: switched on again later it is warmed up afresh (the
                    # trade carried), never left flat to buy before the backtest could
                    new = None
                    e["cold"] = True
            e["pos"] = new
            self._done_candle(e, o, close, bar_ms)
            i += 1

    def _done_candle(self, e: dict, o: int, close: float, bar_ms: int) -> None:
        e["last_ms"], e["last_close"] = int(o), close
        self.out["processed"] += 1
        self.newest_close = max(self.newest_close, int(o) + bar_ms)

    def _drop_cold(self) -> None:
        """A cold strategy that has read every candle of every landed day is let go: if a later
        list switches it on, it is warmed up as new at that midnight."""
        if self.frontier_ms is None:
            return
        for sid, e in list(self.st["strats"].items()):
            if e.get("cold") and e.get("pos") is None:
                nxt = int(e["last_ms"]) + _bar_ms(e["row"]["tf"])
                if nxt // DAY_MS * DAY_MS >= self.frontier_ms:
                    del self.st["strats"][sid]


# ------------------------------------------------------------------ the pass
def pass_once(now_s: float | None = None, *, fetch=None, funding_of=None, listed=None,
              lists_dir: Path | None = None, minutes=None) -> dict:
    """One pass over every follower room: each strategy advanced through every closed candle not
    yet processed. Returns {pid: {processed, entered, exited, held_at, errors}}. `fetch(sym, tf,
    bars=None, end_ms=None)`, `funding_of(sym)` and `listed()` default to the exchange (one door)."""
    from tradingagents import profiles

    now_s = time.time() if now_s is None else float(now_s)
    with _follow_lock() as held:
        if not held:
            # ANOTHER PASS IS WRITING (final review, Nov 11, 2026): the writer reads the room's record
            # once when it starts, so two passes at once would write every row twice, for good
            return {pid: {"processed": 0, "entered": 0, "exited": 0, "held_at": None, "skipped": True,
                          "errors": [BUSY]} for pid in rooms()}
        R = _Reads(now_s, fetch or _fetch_default, funding_of or _funding_default, listed or _listed_default,
                   lists_dir, minutes or _minutes_default)
        out = {}
        for pid in rooms():
            with profiles.using(pid):
                try:
                    out[pid] = _Room(pid, R).run()
                except _Unreadable as exc:
                    out[pid] = {"processed": 0, "entered": 0, "exited": 0, "held_at": None,
                                "unreadable": True, "errors": [unreadable_words(str(exc))]}
                except Exception as exc:                               # noqa: BLE001
                    reason = f"{type(exc).__name__}: {exc}"
                    out[pid] = {"processed": 0, "entered": 0, "exited": 0, "held_at": None,
                                "errors": [f"the pass failed: {reason}"]}
                    _keep_failure(reason, now_s, out[pid]["errors"])
    return out


def _follow_lock():
    """`follow.lock` under Backtest v4's folder, tried once (never waited on): a context manager
    answering True when this pass holds it. One pass at a time, whoever starts it."""
    import contextlib

    @contextlib.contextmanager
    def held():
        from tradingagents import portable, stores

        home = Path(stores.V4.home)
        home.mkdir(parents=True, exist_ok=True)
        with open(home / "follow.lock", "a+b") as fh:
            try:
                portable.lock_exclusive(fh, blocking=False)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                portable.unlock(fh)

    return held()


def _keep_failure(reason: str, now_s: float, errors: list) -> None:
    """A pass that failed for a whole room: its reason saved into the room's record for the screen,
    on top of what is ON DISK (never the half-run pass's memory). An unreadable record is never
    written over."""
    try:
        st, bad = _load()
        if bad:
            return
        st["pass_error"], st["pass_error_s"] = reason, float(now_s)
        _save(st)
    except Exception as exc:                                            # noqa: BLE001
        errors.append(f"and its reason could not be saved: {type(exc).__name__}: {exc}")


# ------------------------------------------------------------------ the heartbeat
def status(pid: str, now_s: float | None = None, lists_dir: Path | None = None) -> dict:
    """What room `pid`'s screen says about its follower. `last_candle_ms` is when the newest candle
    it processed CLOSED; `why` is None while it is following, else the reason in plain words;
    `switched_on` is TODAY's list (UTC) only - never yesterday's shown as today's."""
    from tradingagents import profiles
    from tradingagents.positions_view import fmt_when

    now_s = time.time() if now_s is None else float(now_s)
    with profiles.using(pid):
        st, bad = _load()
    last, held, errs = st.get("last_pass_s"), st.get("held_at"), list(st.get("errors") or [])
    failed, failed_s = st.get("pass_error"), st.get("pass_error_s")
    if bad:
        why = unreadable_words(bad)
        errs = [why]
    elif failed and (not last or float(failed_s or 0) >= float(last)):
        why = f"the pass of {fmt_when(float(failed_s or now_s))} failed: {failed}"
        errs = [f"the pass failed: {failed}", *errs]
    elif not last:
        why = "the follower has not run yet"
    elif now_s - float(last) > STALE_S:
        why = f"the last pass was {fmt_when(float(last))}"
    elif held is not None:
        why = (f"waiting for the list of {fmt_when(int(held))}; trades since then are filled in "
               f"when it lands")
    elif errs:
        why = errs[0] + (f" (and {len(errs) - 1} more)" if len(errs) > 1 else "")
    else:
        why = None
    today = int(now_s) // DAY_S * DAY_S
    on, fallback, landed, list_error = [], None, False, None
    p = list_path(today, lists_dir)
    if p.exists():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not isinstance(doc.get("rooms", {}), dict):
                raise ValueError("not a day list")
            on = list((doc.get("rooms") or {}).get(pid) or [])
            fallback = doc.get("fallback_from")
            landed = True
        except (OSError, ValueError) as exc:
            said = (exc.strerror or exc.errno) if isinstance(exc, OSError) else str(exc)[:120]
            list_error = f"today's list cannot be read ({type(exc).__name__}: {said})"
    fb_day = _day_of(str(fallback)) if fallback else None
    return {"last_pass_s": last, "last_candle_ms": st.get("last_candle_ms"), "held_at": held, "why": why,
            "filled_in": int(st.get("filled_in") or 0), "errors": errs, "switched_on": on,
            # WAS TODAY'S LIST EXAMINED AT ALL (final review, Nov 11, 2026): an empty `switched_on`
            # before the list lands is "nothing looked at yet", never "nothing passes"
            "today_s": today, "today_landed": landed, "today_list_error": list_error,
            "fallback_from": fallback, "fallback_day_s": fb_day, "agreement": agreement_of(pid, lists_dir)}


def agreement_of(pid: str, lists_dir: Path | None = None) -> dict | None:
    """Room `pid`'s line of the NEWEST daily agreement check (`v4_daily` writes
    `<lists>/agree-<YYYY-MM-DD>.json` = {room: result} beside the day lists - never into this module's
    state, which only this thread writes). None when there is none, or the newest has no line for it."""
    try:
        files = sorted(Path(lists_dir or lists_home()).glob("agree-*.json"), key=lambda p: p.name)
    except OSError:
        return None
    for p in reversed(files):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                      # half-written or unreadable: the one before it
        got = doc.get(pid) if isinstance(doc, dict) else None
        return got if isinstance(got, dict) else None
    return None


# ------------------------------------------------------------------ the supervisor's tick
_DONE: dict = {"slot": None}
_SAID: dict = {"text": None}


def _slot(now_s: float) -> float:
    """The newest 15-minute close + 20 s at or before `now_s`."""
    s = now_s - now_s % EVERY_S + AFTER_CLOSE_S
    return s if s <= now_s else s - EVERY_S


def _say(text: str) -> None:
    if text != _SAID["text"]:
        _SAID["text"] = text
        print(f"[v4-follow] {text}", flush=True)


def _sentence(res: dict) -> str:
    from tradingagents import profiles
    from tradingagents.positions_view import fmt_when

    bits = []
    for pid, r in res.items():
        if r.get("held_at") is not None:
            bits.append(f"{profiles.name_of(pid)} waiting for the list of {fmt_when(int(r['held_at']))}")
        if r.get("errors"):
            bits.append(f"{profiles.name_of(pid)}: {len(r['errors'])} problem(s), first: {r['errors'][0]}")
        if r.get("unreadable"):           # the log (never a screen) says WHERE, for the repair
            with profiles.using(pid):
                bits.append(f"{profiles.name_of(pid)}'s follower record is {state_path()}")
    return "; ".join(bits) if bits else f"following {len(res)} room(s)"


def tick(now_s: float | None = None) -> dict | None:
    """The supervisor's call: one pass 20 s after every 15-minute close. Nothing under pytest. Never
    raises."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    return _tick(now_s)


def _tick(now_s: float | None = None) -> dict | None:
    """The pass for the newest slot, once. It takes NO lock of its own: `pass_once` holds
    `follow.lock`, and a pass that finds it held (another pass is writing) leaves the slot to be
    tried again at the next poll."""
    try:
        now_s = time.time() if now_s is None else float(now_s)
        slot = _slot(now_s)
        if _DONE["slot"] is not None and _DONE["slot"] >= slot:
            return None
        was, _DONE["slot"] = _DONE["slot"], slot
        res = pass_once(now_s)
        if any(r.get("skipped") for r in res.values()):
            _DONE["slot"] = was
            return None
        _say(_sentence(res))
        return res
    except Exception as exc:                                            # noqa: BLE001
        _say(f"the pass failed: {type(exc).__name__}: {exc}")
        return None
