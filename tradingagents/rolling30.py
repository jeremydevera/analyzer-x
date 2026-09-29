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
    rows = msw.pair_rows(ident["coin"], ident["tf"], root=root)
    return (wc._match(rows, ident), int(msw.pair_watermark(ident["coin"], ident["tf"], root=root) or 0))


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


def rebuild(slot: str, settings: dict) -> dict:
    """Rebuild one slot's backtest trades and save them. Returns the record."""
    import numpy as np

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents.dataflows import mexc_futures as fx

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
    warm = max(0, len(df) - int(row["bars"]))
    fine = None
    if ident["res"] == "1m":
        iv1, bs1, cap1 = br.TFS["1m"]
        m1 = at._closed_bars(fx.klines(ident["sym"], iv1, cap1), bs1)
        fine = (m1["Date"].to_numpy().astype("datetime64[ms]").astype("int64"),
                np.asarray(m1["High"], float), np.asarray(m1["Low"], float))
    hi, lo, cl, op = ([float(x) for x in df[c]] for c in ("High", "Low", "Close", "Open"))
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    ts = [int(x) for x in df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]
    fund = fx.funding_history(ident["sym"])
    liq = fx.liquidation_move_pct(ident["sym"], at.LEVERAGE)
    key = ident["key"]
    dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol, funding=fund, ts=ts)
    # the row's OWN cost, per side: its round trip is what the store charged
    side = float(row.get("rt") or 0) / 100 / 2
    r = at.backtest_strategy(key, df, 5.0, fee=side, slippage=0.0, sizing="flat",
                             dirs=dirs, tp=ident["tp"] / 100, sl=ident["sl"] / 100,
                             liq_move_pct=liq, funding=fund, keep_log=True,
                             start_at=warm, fine=fine)
    rebuilt = {"trades": int(r["trades"]), "wins": int(r["wins"]),
               "profit": round(float(r["profit"]), 2)}
    stored = {"trades": int(row["trades"]), "wins": int(row["wins"]),
              "profit": round(float(row["profit"]), 2)}
    rec = {"slot": slot, "wm": wm, "bar_s": bs, "end_ms": wm + bs * 1000,
           "trades": log_to_trades(r["log"]), "stored": stored, "rebuilt": rebuilt,
           "match": same_result(stored, rebuilt), "at": time.time()}
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
    settings = at.load_settings() if settings is None else settings
    done, errors = 0, {}
    _STATUS["running"] = True
    try:
        for key, coins in (settings.get("strategy_coins") or {}).items():
            for c in coins or []:
                slot = f"{key}|{c}"
                try:
                    ident = _identity(settings, slot)
                    if ident is None:
                        continue
                    _row, wm = _stored(ident)
                    have = _load(slot)
                    if have and have.get("wm") == wm:
                        continue
                    got = rebuild(slot, settings)
                    if got.get("error"):
                        errors[slot] = got["error"]
                    else:
                        done += 1
                    time.sleep(pause)
                except Exception as exc:                       # noqa: BLE001
                    errors[slot] = f"{type(exc).__name__}: {str(exc)[:160]}"
    finally:
        _STATUS.update(running=False, last=time.time(), errors=errors)
    return {"rebuilt": done, "errors": errors}


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
            path = Path(at.LEDGER_PATH)
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


PRACTICE = _PracticeExits()


def figure(slot: str, *, now: float | None = None, exits: list | None = None) -> dict | None:
    """This slot's last-30-days record, or None when its backtest trades have
    not been rebuilt yet (the screen says so rather than print a guess)."""
    now = time.time() if now is None else now
    rec = _load(slot)
    if rec is None:
        return None
    lo = now * 1000 - WINDOW_MS
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
