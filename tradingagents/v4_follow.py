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
* Every cost is the strategy's own: its fee and gap from the list it was switched on by (kept with
  the trade to its exit), and the coin's funding settled inside the hold (CLAUDE.md rule 9).
* A coin the exchange no longer lists - or a HELD strategy whose candles cannot be read on
  `DELIST_AFTER_FAILS` passes running - closes its trade at the last candle read, `why`
  "DELISTED", named. One failed read is not a delisting: it is retried once later in the same
  pass, then named, and the strategy's state is left where it was so the next pass catches up.
* A row is never written twice: before appending, the follower checks the room's own trade
  record (and the keys it remembers) for that trade id and action - a pass killed between a row and
  its state is replayed by the next one without a duplicate.
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
DELIST_AFTER_FAILS = 2        # passes a HELD strategy's coin may go unread before it is closed
SPARE_BARS = 5
WRITTEN_KEEP = 5000           # trade rows (id + action) remembered as written, newest last
REPLACE_BUDGET_S = 3.0


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


def load() -> dict:
    """The current room's follower state; {} when it has none (or it cannot be read)."""
    try:
        st = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


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


def _funding_default(sym):
    from tradingagents.dataflows import exchange as fx

    return fx.funding_history(sym)


def _listed_default():
    from tradingagents.dataflows import exchange as fx

    return {str(r["symbol"]) for r in fx.list_contracts() if r.get("symbol")}


# ------------------------------------------------------------------ one pass's reads, shared by the rooms
class _Reads:
    """Every read a pass makes, made once: candle frames, funding, the contract list, day lists and
    signals. Nothing here is kept between passes."""

    def __init__(self, now_s, fetch, funding_of, listed, lists_dir):
        self.now_s = float(now_s)
        self.now_ms = int(now_s * 1000)
        self._fetch, self._funding_of, self._listed = fetch, funding_of, listed
        self.lists_dir = Path(lists_dir) if lists_dir else lists_home()
        self._frames: dict = {}
        self._warm: dict = {}
        self._fund: dict = {}
        self._lists: dict = {}
        self._sigs: dict = {}
        self._opens: dict = {}
        self._listed_set: set | None = None
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

    def opens(self, df) -> list:
        k = id(df)
        if k not in self._opens:
            from tradingagents import skill_bt as sb

            self._opens[k] = (df, [int(x) for x in sb._ms(df.index)] if len(df) else [])
        return self._opens[k][1]

    def funding(self, sym: str):
        if sym not in self._fund:
            from tradingagents import skill_bt as sb

            self._fund[sym] = sb.Funding(self._funding_of(sym))
        return self._fund[sym]

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
        delisted this pass (an unreadable list is not an empty one)."""
        if not self._listed_read:
            self._listed_read = True
            try:
                got = set(self._listed() or ())
            except Exception as exc:                                    # noqa: BLE001
                got = set()
                self.listed_error = f"{type(exc).__name__}: {exc}"
            if not got and self.listed_error is None:
                self.listed_error = "the list came back empty"
            self._listed_set = got or None
        return self._listed_set

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
                    self.list_errors[day_s] = f"the list {p.name} cannot be read: {type(exc).__name__}: {exc}"
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

    def __init__(self, st: dict, out: dict, now_s: float, release_ms: int | None):
        import tradingagents.auto_trader as at

        self.at = at
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
        vol = sb.NOTIONAL / px
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
        exit_s = (int(trade["exit_ms"]) + bar_ms) // 1000
        tid = self.at.trade_code(sym, key, entry_ts, trade["side"], dry=True)
        x = {"ts": exit_s, "symbol": sym, "action": "exit", "why": trade["why"], "strategy": key,
             "trade_id": tid, "entry_ts": entry_ts, "opened_at": fill_s, "held_s": exit_s - fill_s,
             "side": "LONG" if trade["side"] > 0 else "SHORT", "entry": float(trade["entry_px"]),
             "exit": float(trade["exit_px"]), "pnl_est": float(trade["pnl"]), "pnl_source": "v4_engine",
             "step_next": 0, "dry_run": True, "v4_id": sid, "written_at": self.now_s}
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
        self.st = load()
        self.st.setdefault("strats", {})
        self.st.setdefault("pending", {})
        self.errors: list[str] = []
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
        self.W = _Writer(st, self.out, R.now_s, release)
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
        fund = R.funding(sym)
        pos = None
        if len(df):
            _done, pos = sb.run(df, R.warm_signals(row, df, end_ms), stop=float(row["stop"]),
                                fee=float(row["fee"]), slip=float(row["slip"]), target=row.get("target"),
                                funding=fund, bar_ms=bar_ms)
        opens = R.opens(df)
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
            fund = R.funding(sym)
        except Exception as exc:                                        # noqa: BLE001
            if not last_try:
                return False
            for sid in sids:
                self._unread(sid, exc, gone)
            return True
        for sid in sids:
            e = st["strats"][sid]
            e["fails"] = 0
            try:
                self._advance(sid, e, df, fund, entries=not gone)
            except Exception as exc:                                    # noqa: BLE001
                self.errors.append(f"{_name(e, sid)}: {type(exc).__name__}: {exc}")
            if gone:
                self._delist(sid, e, fund, "delisted by the exchange")
            _save(st)
        return True

    def _unread(self, sid: str, exc: Exception, gone: bool) -> None:
        """A strategy whose candles could not be read this pass (after the retry): named, its
        candles left where they were. Held through DELIST_AFTER_FAILS passes, or on a coin the
        exchange no longer lists, its trade is closed at the last candle read."""
        st = self.st
        e = st["strats"][sid]
        e["fails"] = int(e.get("fails") or 0) + 1
        self.errors.append(f"{_name(e, sid)}: {type(exc).__name__}: {exc}")
        if gone or e["fails"] >= DELIST_AFTER_FAILS:
            fund = None
            try:
                fund = self.R.funding(f"{e['row']['coin']}_USDT")
            except Exception:                                           # noqa: BLE001
                fund = None
            if gone or e.get("pos") is not None or e.get("cold"):
                self._delist(sid, e, fund, "delisted by the exchange" if gone else
                             f"its candles could not be read on {e['fails']} passes running")
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
            new, done = sb.step(pos, sig, close=close, when_ms=o, bar_ms=bar_ms, stop=float(row["stop"]),
                                fee=fee, slip=slip, target=row.get("target"), funding=fund)
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
                    new = None                           # switched off: no new trade
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
              lists_dir: Path | None = None) -> dict:
    """One pass over every follower room: each strategy advanced through every closed candle not
    yet processed. Returns {pid: {processed, entered, exited, held_at, errors}}. `fetch(sym, tf,
    bars=None, end_ms=None)`, `funding_of(sym)` and `listed()` default to the exchange (one door)."""
    from tradingagents import profiles

    now_s = time.time() if now_s is None else float(now_s)
    R = _Reads(now_s, fetch or _fetch_default, funding_of or _funding_default, listed or _listed_default,
               lists_dir)
    out = {}
    for pid in rooms():
        with profiles.using(pid):
            try:
                out[pid] = _Room(pid, R).run()
            except Exception as exc:                                   # noqa: BLE001
                out[pid] = {"processed": 0, "entered": 0, "exited": 0, "held_at": None,
                            "errors": [f"the pass failed: {type(exc).__name__}: {exc}"]}
    return out


# ------------------------------------------------------------------ the heartbeat
def status(pid: str, now_s: float | None = None, lists_dir: Path | None = None) -> dict:
    """What room `pid`'s screen says about its follower. `last_candle_ms` is when the newest candle
    it processed CLOSED; `why` is None while it is following, else the reason in plain words;
    `switched_on` is TODAY's list (UTC) only - never yesterday's shown as today's."""
    from tradingagents import profiles
    from tradingagents.positions_view import fmt_when

    now_s = time.time() if now_s is None else float(now_s)
    with profiles.using(pid):
        st = load()
    last, held, errs = st.get("last_pass_s"), st.get("held_at"), list(st.get("errors") or [])
    if not last:
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
    on, fallback = [], None
    try:
        doc = json.loads(list_path(today, lists_dir).read_text(encoding="utf-8"))
        on = list((doc.get("rooms") or {}).get(pid) or [])
        fallback = doc.get("fallback_from")
    except (OSError, ValueError, AttributeError):
        pass
    return {"last_pass_s": last, "last_candle_ms": st.get("last_candle_ms"), "held_at": held, "why": why,
            "filled_in": int(st.get("filled_in") or 0), "errors": errs, "switched_on": on,
            "fallback_from": fallback, "agreement": st.get("agreement")}


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
    return "; ".join(bits) if bits else f"following {len(res)} room(s)"


def tick(now_s: float | None = None) -> dict | None:
    """The supervisor's call: one pass 20 s after every 15-minute close, under `follow.lock` (held
    by another pass = skipped). Nothing under pytest. Never raises."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        from tradingagents import portable, stores

        now_s = time.time() if now_s is None else float(now_s)
        slot = _slot(now_s)
        if _DONE["slot"] is not None and _DONE["slot"] >= slot:
            return None
        stores.V4.home.mkdir(parents=True, exist_ok=True)
        with open(stores.V4.home / "follow.lock", "a+b") as fh:
            try:
                portable.lock_exclusive(fh, blocking=False)
            except OSError:
                return None
            try:
                _DONE["slot"] = slot
                res = pass_once(now_s)
            finally:
                portable.unlock(fh)
        _say(_sentence(res))
        return res
    except Exception as exc:                                            # noqa: BLE001
        _say(f"the pass failed: {type(exc).__name__}: {exc}")
        return None
