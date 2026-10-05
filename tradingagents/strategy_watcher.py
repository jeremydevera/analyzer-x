"""The strategy watcher: switches practice rows on and off by itself.

Operator, `Sep 29, 2026`: *"deploy now the wathcer replay, /goal i want this
fully working, the backtest everyday the promotion and demotion"*. Task 6 of
docs/superpowers/plans/2026-09-28-strategy-watcher.md, with the rules the
operator set on Sep 28, 2026 (watcher_policy.DEFAULTS): switch on at 90%+ over
the last 30 days with TP wider than SL and 20+ trades; switch off under 90%.

The day, end to end:

    daily_update presses UPDATE ALL BACKTESTS (v2, GitHub) once every 24 h
      -> the rows land in the v2 store
      -> the ON pass (once a day) nominates from the v2 index, judges each row
         on its fresh pair file, picks with watcher_policy.pick, and arms the
         picks in the PRACTICE account after edge_check says ok
      -> the OFF pass (every hour) re-reads each armed row's pair file and
         switches off what watcher_policy.judge rejects

It SWITCHES ON only into slots of its own (`settings["watcher_slots"]`), and
SWITCHES OFF every practice-only row under the line — the operator's own
included. Operator, Sep 29, 2026, on #LLC76MPD at 89%: *"as i said it should
be switched off, you should follow my criteria"*; it had only been reported.
Every row is judged on the number the DEMO column prints (`rolling30`: the
backtest to its last candle, then the practice trades since), falling back to
the backtest's own 30 days while that is not worked out yet.
It never writes "real" into a book, never touches a slot holding "real", and
never closes a position: a switched-off practice trade is finished by the
runner's own rule (7897c110). Every decision is a line in the log with the
row's id and the numbers it was judged on.

"Smart Watcher" on the screen is this module's mode: ticked is "act",
unticked is "off", and off switches NOTHING on or off. It has nothing to do
with the daily UPDATE ALL BACKTESTS (`daily_update`), which runs either way.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from tradingagents import strategy_keys as sk
from tradingagents import watcher_policy as wp

HOME = Path(os.path.expanduser("~/.tradingagents"))
STATE = HOME / "strategy_watcher.json"
LOG = HOME / "strategy_watcher.jsonl"
ON_EVERY_S = 24 * 3600
# THE SWITCH-ON PASS RUNS ONCE A DAY, AT OR AFTER NOON (local). The first dry
# run was at Sep 29, 2026 3:36am and the cost check blocked IGV 1h on a 0.675%
# gap between buy and sell — a stock token's book at night. At noon the US
# market is open (the books are tight) and that morning's UPDATE ALL
# BACKTESTS (daily_update, ~11:49am) has been dispatched. The hourly
# switch-off pass runs round the clock.
ON_HOUR = 12
# edge_check's verdicts that may trade: the runner itself trades on "warn"
# (cost over 20% of the target) and only "block" stops it; "unknown" is never
# ok (rule 12). Refusing "warn" refused #GUCXTP4L VUG 30m (91.3%, 37%) and
# six more that the runner would have traded.
EDGE_OK = ("ok", "warn")
OFF_EVERY_S = 3600
RETRY_S = 30 * 60
MODES = ("off", "preview", "act")
MARGIN = 5.0


# ------------------------------------------------------------------ state
# ONE WATCHER PER PROFILE (Sep 29, 2026, tradingagents/profiles.py): each room
# keeps its own state and log in its own folder. Main is STATE/LOG themselves,
# read at the call, so a test that points them at tmp_path still works.
def _state_path() -> Path:
    from tradingagents import profiles

    return profiles.path(STATE)


def _log_path() -> Path:
    from tradingagents import profiles

    return profiles.path(LOG)


def _seed() -> dict:
    """A new profile's watcher: ON, with that profile's own rules, practice
    only until its live switch is turned on."""
    from tradingagents import profiles

    pid = profiles.current()
    rules = (profiles.get(pid) or {}).get("rules")
    if pid == profiles.MAIN or not rules:
        return {}
    return {"mode": "act", "cfg": dict(rules), "live": False,
            "why": f"started for {pid} with its own rules"}


def _read() -> dict:
    path = _state_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seed = _seed()
        if seed and not path.exists():
            _write(seed)
        return dict(seed)


def _write(d: dict) -> None:
    path = _state_path()
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, path)


# The rules the LIVE watcher actually reads. The replay and the research dial
# more (window_days, off_streak_live, judge_after, off_streak), but the live
# watcher judges each row on the v2 store's own window — 30 days, measured
# daily on GitHub — and the practice record is shown, never obeyed. A rule it
# cannot honour is refused by name rather than printed on the screen as if it
# were in force (label-must-match-data).
LIVE_RULES = ("on_winrate", "off_winrate", "min_trades", "tp_rule",
              "max_sl", "profit_floor", "max_slots", "max_per_coin",
              "max_new_per_day", "cooldown_days", "fresh_hours", "rank", "raw",
              # 15 or the store's 30 (Sep 30, 2026): on 15 a row is judged on
              # its own measured last-15-day count (backtest_report.RECENT_DAYS)
              "window_days",
              # the smallest target (Oct 01, 2026); tp_rule also takes "="
              "min_tp")


def store_window_days() -> int:
    """The window every v2 row was measured over (cloud_sweep.SWEEP_DAYS)."""
    with contextlib.suppress(Exception):                       # noqa: BLE001
        from tradingagents import cloud_sweep as cs

        return int(cs.SWEEP_DAYS)
    return 30


def cfg_of(st: dict | None = None) -> dict:
    from tradingagents import backtest_report as br

    st = _read() if st is None else st
    cfg = {**wp.DEFAULTS, **(st.get("cfg") or {})}
    w = int(cfg.get("window_days") or 0)
    return {**cfg, "window_days": br.RECENT_DAYS if w == br.RECENT_DAYS
            else store_window_days(), "off_streak_live": 0}


def mode_of(st: dict | None = None) -> str:
    from tradingagents import profiles

    if profiles.retired(profiles.current()):
        return "off"          # a retired room switches nothing on (Sep 30, 2026)
    st = _read() if st is None else st
    m = st.get("mode") or "act"
    return m if m in MODES else "act"


def live_of(st: dict | None = None) -> bool:
    """Does this profile's watcher also switch REAL-money rows? Off unless
    the operator turned it on (Sep 29, 2026: "i want both, if i enable live
    trade, then it should be included")."""
    st = _read() if st is None else st
    return bool(st.get("live"))


def set_live(on: bool) -> dict:
    """Turn the profile's live switch on or off. OFF also takes REAL off
    every row this watcher armed with it, keeping their practice half: the
    operator's "no" to real money reaches the rows it already armed."""
    st = _read()
    st["live"] = bool(on)
    _write(st)
    if not on:
        def drop_real(s):
            books = dict(s.get("strategy_books") or {})
            ws = dict(s.get("watcher_slots") or {})
            for slot, meta in ws.items():
                if meta.get("real") and "real" in (books.get(slot) or []):
                    books[slot] = [b for b in books[slot] if b != "real"] or ["paper"]
                    ws[slot] = {**meta, "real": False}
            s["strategy_books"], s["watcher_slots"] = books, ws
            return s
        _write_settings(drop_real)
    return status()


def set_mode(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    st = _read()
    st["mode"] = mode
    st["why"] = {"off": "switched off", "preview": "preview: decides, changes nothing",
                 "act": "switching practice rows on and off"}[mode]
    _write(st)
    return status()


def retire_room() -> dict:
    """Switch the CURRENT room off for good (Sep 30, 2026: "undeploy my
    current live then deploy the table you mentined"): the watcher OFF, and
    every practice-only row taken off. A row holding REAL money is never
    touched here — it is listed back instead. Open practice trades are left
    to the runner, which finishes them at their own TP or SL."""
    from tradingagents import auto_trader as at

    set_mode("off")
    kept_real: list = []
    off: list = []

    def mutate(s):
        kept_real.clear()
        off.clear()
        for key, coins in list((s.get("strategy_coins") or {}).items()):
            for c in list(coins or []):
                slot = f"{key}|{c}"
                if "real" in at.book_names(s, key, c):
                    kept_real.append(slot)
                    continue
                _disarm(s, slot)
                off.append(slot)
        return s
    if not _write_settings(mutate):
        raise RuntimeError("the settings file kept changing — nothing switched off")
    return {"switched_off": len(off), "real_kept": kept_real}


def set_cfg(partial: dict) -> dict:
    """Change some rules. Every key must be a known rule of the same type."""
    st = _read()
    cfg = dict(st.get("cfg") or {})
    for k, v in (partial or {}).items():
        if k not in wp.DEFAULTS:
            raise ValueError(f"unknown rule {k!r}")
        if k not in LIVE_RULES:
            raise ValueError(f"{k} is a replay/research rule the live watcher does not "
                             f"use — it judges every row on the store's own "
                             f"{store_window_days()}-day window")
        if k == "tp_rule" and v not in wp.TP_RULES:
            raise ValueError(f"tp_rule must be one of {wp.TP_RULES}")
        if k == "window_days":
            from tradingagents import backtest_report as br

            ok = (br.RECENT_DAYS, store_window_days())
            if v not in ok:
                raise ValueError(f"window_days must be one of {ok} — the only "
                                 f"windows every Backtest v2 row is measured over")
        want = type(wp.DEFAULTS[k])
        if want is float and isinstance(v, int):
            v = float(v)
        if not isinstance(v, want) or isinstance(v, bool) != isinstance(wp.DEFAULTS[k], bool):
            raise ValueError(f"{k} must be a {want.__name__}")
        cfg[k] = v
    st["cfg"] = cfg
    _write(st)
    return status()


def _log(decisions: list[dict]) -> None:
    if not decisions:
        return
    with contextlib.suppress(OSError):
        _log_path().parent.mkdir(parents=True, exist_ok=True)
        with _log_path().open("a", encoding="utf-8") as fh:
            for d in decisions:
                fh.write(json.dumps(d) + "\n")


def recent(n: int = 50) -> list[dict]:
    """The newest `n` decisions, read from the log's TAIL — the panel asks
    every 30 seconds and the log only ever grows."""
    try:
        size = _log_path().stat().st_size
        with _log_path().open("rb") as fh:
            fh.seek(max(0, size - 256 * 1024))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
        if len(out) >= n:
            break
    return out


PER_PAGE = 10
# (path, bytes counted, lines counted): the log only grows, so each call
# counts only the newlines appended since the last one
_COUNT = {"path": None, "size": 0, "lines": 0}
_COUNTS: dict = {}          # one count per profile's log


def _log_lines() -> int:
    try:
        size = _log_path().stat().st_size
    except OSError:
        return 0
    key = str(_log_path())
    if _COUNT["path"] != key:
        # another room's log: keep this one's count, pick up that one's
        if _COUNT["path"] is not None:
            _COUNTS[_COUNT["path"]] = dict(_COUNT)
        _COUNT.update(_COUNTS.get(key) or {"path": key, "size": 0, "lines": 0})
    if size < _COUNT["size"]:
        _COUNT.update(path=key, size=0, lines=0)
    if size > _COUNT["size"]:
        with contextlib.suppress(OSError), _log_path().open("rb") as fh:
            fh.seek(_COUNT["size"])
            chunk = fh.read(size - _COUNT["size"])
            _COUNT["lines"] += chunk.count(b"\n")
            _COUNT["size"] = size
    return _COUNT["lines"]


def decisions_page(page: int = 1, per: int = PER_PAGE) -> dict:
    """One page of decisions, newest first, and how many there are in all.

    PAGED HERE, never in the browser (operator, Sep 29, 2026: "paginate the
    Watcher"): the screen used to receive only the newest 50, so page numbers
    drawn over that would have ended at 5 while the log held more — a pager
    over a list the server already cut (CLAUDE.md, kit item G). Read from
    the END, only as far back as this page needs."""
    per = max(1, min(int(per or PER_PAGE), 100))
    total = _log_lines()
    pages = max(1, -(-total // per))
    page = max(1, min(int(page or 1), pages))
    need = page * per
    lines: list[bytes] = []
    try:
        size = _log_path().stat().st_size
        with _log_path().open("rb") as fh:
            end, block, tail = size, 64 * 1024, b""
            while end > 0 and len(lines) < need:
                start = max(0, end - block)
                fh.seek(start)
                buf = fh.read(end - start) + tail
                parts = buf.split(b"\n")
                tail = parts[0] if start > 0 else b""
                got = [p for p in (parts[1:] if start > 0 else parts) if p.strip()]
                lines = got + lines
                end = start
                block *= 2
    except OSError:
        lines = []
    newest = list(reversed(lines))[(page - 1) * per:page * per]
    out = []
    for line in newest:
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
    return {"decisions": out, "decisions_total": total, "decisions_page": page,
            "decisions_pages": pages, "decisions_per": per}


# ------------------------------------------------------ seams (tests replace)
def _candidates(cfg: dict, now: float) -> dict:
    from tradingagents import watcher_candidates as wc

    # a fresh order-book memory for each switch-on pass
    _PASS_FX["fx"] = _PassFx()
    # 15 days: only the index's own t15/w15 can answer, raw or not
    if cfg.get("raw") or wc.window_of(cfg) != 30:
        return wc.raw_candidates(cfg)
    # NO LIMIT ON THE LIST EITHER when there is none on the picks: stopping
    # at 5,000 left "rows ranked below it were not examined" (#B52662ED,
    # Sep 29, 2026 4:18pm)
    if not int(cfg.get("max_new_per_day") or 0) and not int(cfg.get("max_slots") or 0):
        return wc.fresh_candidates(cfg, now=now, limit=0)

    return wc.fresh_candidates(cfg, now=now)


def _fresh_row(meta: dict, now: float, cfg: dict):
    """(row or None, readable). A pair file that is NOT THERE (a delisted
    coin's, removed by the cleanup) is a row that is gone: (None, True), and
    judge() switches it off. A file that IS there but reads empty or broken is
    `readable` False — kept, and checked again next hour. The file is read
    once (and only again when it changes)."""
    from tradingagents import watcher_candidates as wc

    if not wc.pair_file(meta["coin"], meta["tf"]).exists():
        return None, True
    got = wc.matched_rows(meta["coin"], meta["tf"], [meta])
    if got is None:
        return None, False
    row = got.get(wc._sig(meta))
    last = wc._last_ms(meta["coin"], meta["tf"]) or 0.0
    return (None if row is None else wc._fresh(meta["coin"], meta["tf"], row, last,
                                               wc.window_of(cfg))), True


def _judged(slot: str, fresh: dict | None, now: float | None = None,
            window_days: int = 30) -> dict | None:
    """The row as the DEMO column prints it: its last 30 days from `rolling30`
    (backtest to its last candle, then its practice trades since) — so a row
    whose practice losses pulled it under the line is judged on them, not on
    a backtest that has not run since. A row gone from the store stays gone;
    one whose 30 days are not worked out yet is judged on its backtest."""
    if fresh is None:
        return None
    try:
        from tradingagents import rolling30 as r30

        fig = r30.figure(slot, now=now, window_ms=int(window_days) * 86_400_000)
    except Exception:                                          # noqa: BLE001
        fig = None
    if not fig or not fig.get("trades") or fig.get("winrate") is None:
        return fresh
    return {**fresh, "winrate": fig["winrate"], "trades": fig["trades"],
            "wins": fig["wins"], "losses": fig["losses"], "profit": fig["pnl"],
            "from_backtest": fig["from_backtest"], "from_practice": fig["from_practice"],
            "unmeasured": False}


def _practice(slots: dict, now: float) -> dict:
    from tradingagents import watcher_results as wres

    return wres.practice(slots, now=now)


def _register(key: str, spec: dict, persist: bool = True) -> str:
    """Make `key` a known recipe. PREVIEW (`persist=False`) writes nothing:
    the recipe lives in this process only, long enough for edge_check."""
    from tradingagents import auto_trader as at
    from tradingagents import runtime_specs as rs

    if not persist:
        have = at.STRATEGY_SPECS.get(key) or rs.load().get(key)
        if have is not None and dict(have) != dict(spec):
            raise ValueError(f"{key} already means {have}, not {spec}")
        if key in at.STRATEGY_SPECS:
            return "same"
        at.STRATEGY_SPECS[key] = dict(spec)
        return "in memory"         # the caller takes it out after edge_check
    got = rs.register(key, spec)
    at.merge_runtime_specs()            # this process trades it too (edge_check)
    return got


class _PassFx:
    """The MEXC module for ONE switch-on pass, with each coin's order book
    read ONCE and reused (Sep 30, 2026). With no limit a pass checks every
    row that passes — 5,000+ for #B52662ED — and edge_check reads the book
    for each: 5,000 calls in a burst is how Aug 19, 2026's 166 `code=510`
    refusals happened. The venue is asked once per coin, a little apart."""

    TTL_S = 600
    GAP_S = 0.2

    def __init__(self):
        from tradingagents.dataflows import mexc_futures as fx

        self._fx, self._book, self._cost = fx, {}, {}

    def __getattr__(self, name):
        return getattr(self._fx, name)

    def _fresh(self, store, key):
        hit = store.get(key)
        return hit if hit and time.time() - hit[0] < self.TTL_S else None

    def order_book(self, symbol, *a, **k):
        hit = self._fresh(self._book, symbol)
        if hit:
            return hit[1]
        time.sleep(self.GAP_S)
        got = self._fx.order_book(symbol, *a, **k)
        self._book[symbol] = (time.time(), got)
        return got

    def book_cost(self, symbol, notional_usd=200.0):
        key = (symbol, round(float(notional_usd), 2))
        hit = self._fresh(self._cost, key)
        if hit:
            return hit[1]
        time.sleep(self.GAP_S)
        got = self._fx.book_cost(symbol, notional_usd)
        self._cost[key] = (time.time(), got)
        return got


_PASS_FX: dict = {"fx": None}


def _edge(key: str, symbol: str) -> dict:
    from tradingagents import auto_trader as at

    try:
        return at.edge_check(key, symbol, MARGIN, fx=_PASS_FX["fx"])
    except Exception as exc:                                   # noqa: BLE001
        return {"verdict": "unknown", "reason": f"{type(exc).__name__}: {exc}"}


def _sig_of(key: str) -> str:
    from tradingagents.local_history import _sig_of

    return _sig_of(key)


# --------------------------------------------------------------- settings
def _copy(s: dict) -> dict:
    return {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
            for k, v in s.items()}


def _write_settings(mutate) -> bool:
    """Apply `mutate(settings)` to the file AS IT IS NOW, never to the copy
    read at the start of the pass: the operator may press SAVE while the pass
    reads the store (plan, Review Focus 1). Retries if the file changes
    between this re-read and the write."""
    from tradingagents import auto_trader as at

    for _ in range(3):
        before = at.load_settings()
        after = mutate(_copy(before))
        if at.load_settings() != before:
            continue
        at.save_settings(after)          # also writes the deploy log (deployed_at)
        return True
    return False


def _arm(s: dict, key: str, symbol: str, meta: dict, live: bool = False) -> dict:
    """Switch one row on: practice, and REAL too when the profile's live
    switch is on (`meta["real"]` remembers which, so the switch-off pass may
    take back what it armed and nothing else)."""
    slot = f"{key}|{symbol}"
    meta = {**meta, "real": bool(live)}
    s["strategies"] = sorted(set(s.get("strategies") or []) | {key})
    coins = dict(s.get("strategy_coins") or {})
    coins[key] = sorted(set(coins.get(key) or []) | {symbol})
    s["strategy_coins"] = coins
    books = dict(s.get("strategy_books") or {})
    books[slot] = ["paper", "real"] if live else ["paper"]
    s["strategy_books"] = books
    margins = dict(s.get("strategy_margins") or {})
    margins.setdefault(key, MARGIN)
    s["strategy_margins"] = margins
    sizing = dict(s.get("strategy_sizing") or {})
    sizing.setdefault(key, "flat")
    s["strategy_sizing"] = sizing
    res = dict(s.get("strategy_res") or {})
    res[slot] = "1m"
    s["strategy_res"] = res
    ws = dict(s.get("watcher_slots") or {})
    ws[slot] = meta
    s["watcher_slots"] = ws
    return s


def _disarm(s: dict, slot: str) -> dict:
    key, symbol = slot.split("|", 1)
    coins = dict(s.get("strategy_coins") or {})
    # EMPTY, NEVER MISSING. coins_for() reads a missing key as "every coin in
    # the global list" (the Aug 19, 2026 fallback), and with no book entry left
    # _armed_here() is False, so a popped key would trade every global coin on
    # the GLOBAL switches — real money included. `[]` means none; the same
    # rule disarm_coins keeps.
    coins[key] = [c for c in (coins.get(key) or []) if c != symbol]
    s["strategy_coins"] = coins
    for field in ("strategy_books", "strategy_res", "watcher_slots"):
        d = dict(s.get(field) or {})
        d.pop(slot, None)
        s[field] = d
    return s


# ------------------------------------------------------------------ passes
def _hand_slots(settings: dict) -> list[tuple[str, str]]:
    """(key, symbol) of every PRACTICE-only slot the operator armed by hand."""
    from tradingagents import auto_trader as at

    mine = set((settings.get("watcher_slots") or {}))
    out = []
    for key, coins in (settings.get("strategy_coins") or {}).items():
        for c in coins or []:
            slot = f"{key}|{c}"
            if slot in mine:
                continue
            if at.book_names(settings, key, c) == ["paper"]:
                out.append((key, c))
    return out


def _meta_of_key(key: str, symbol: str) -> dict | None:
    """The row identity of a hand-armed key, from its own recipe."""
    from tradingagents import auto_trader as at

    spec = at.STRATEGY_SPECS.get(key)
    if not spec:
        return None
    tf = {v[0]: k for k, v in sk.TF_SPEC.items()}.get(spec.get("interval"))
    if not tf:
        return None
    return {"coin": symbol.replace("_USDT", ""), "tf": tf, "signal": _sig_of(key),
            "th": round(float(spec.get("threshold") or 0) * 100, 3)
            if _sig_of(key) in sk.THRESHOLD_SIGNALS else 0.0,
            "sl": round(float(spec["sl"]) * 100, 3), "tp": round(float(spec["tp"]) * 100, 3)}


# MEXC lists ~1,000 contracts; a list far shorter than that is a response that
# came back useless, never a market that emptied overnight
MIN_LIVE_LIST = 500


def _delisted(symbols) -> set:
    """The symbols MEXC no longer lists, or an empty set when the list could
    not be read or looks wrong — "I could not look" is never "it is gone".

    SUPRA_USDT left MEXC ("Contract not exists") by Oct 04, 2026 3:15am while
    five practice strategies stayed switched on for it in #55D32617 and
    #4FC03172: 1,924 "no Min15 candles for SUPRA_USDT" failures in 21 hours,
    because the only thing that switched a delisted coin off was the
    hand-pressed delisted cleanup, and it only ever touched Main
    (RCA-2026-10-05-A)."""
    want = {str(x) for x in symbols or () if x}
    if not want:
        return set()
    try:
        from tradingagents import db_jobs

        live = db_jobs.live_symbols()
    except Exception:                                          # noqa: BLE001
        return set()
    if not live or len(live) < MIN_LIVE_LIST:
        return set()
    return {x for x in want if x not in live}


def _off_pass(now: float, cfg: dict, st: dict, act: bool, out: list) -> list[str]:
    from tradingagents import auto_trader as at

    settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    drop = []
    gone_by_hand = []
    hand = _hand_slots(settings)
    gone = _delisted({k.split("|", 1)[1] for k in ws} | {c for _k, c in hand})
    for slot, meta in sorted(ws.items()):
        key, sym = slot.split("|", 1)
        if sym not in at.coins_for(key, settings):
            # YOU switched it off (or the delisted cleanup did): it is no
            # longer the watcher's, and must not count toward its 100 or its
            # 3 per coin for ever. Said once a day — in PREVIEW the slot stays
            # (nothing is written) and would otherwise be reported hourly.
            gone_by_hand.append(slot)
            mark = st.setdefault("reported", {})
            if mark.get(f"gone:{slot}") != _today(now):
                mark[f"gone:{slot}"] = _today(now)
                out.append(_d(now, st, "report", meta, "switched off outside the "
                              "watcher — no longer counted as one of its rows"))
            continue
        if "real" in at.book_names(settings, key, sym) and not meta.get("real"):
            # a real book the WATCHER did not arm is the operator's: never
            # touched. One it armed under the live switch it may switch off.
            continue
        if sym in gone:
            # nothing can trade it: no candles, no book, no price — switched
            # off at once, whatever its win rate
            drop.append((slot, meta["id"], len(out)))
            out.append(_d(now, st, "off", meta, f"MEXC no longer lists {sym} — "
                          f"it cannot trade"))
            continue
        fresh, readable = _fresh_row(meta, now, cfg)
        if not readable:
            out.append(_d(now, st, "report", meta, "its backtest file could not be "
                          "read this hour — kept, checked again next hour"))
            continue
        fresh = _judged(slot, fresh, now, cfg["window_days"])
        if fresh and fresh.get("unmeasured"):
            out.append(_d(now, st, "report", meta, f"no {cfg['window_days']}-day count "
                          f"for it yet — kept until the daily update measures it"))
            continue
        why = wp.judge({"id": meta["id"]}, fresh, cfg)
        if why:
            drop.append((slot, meta["id"], len(out)))
            out.append(_d(now, st, "off", meta, why, fresh))
    # THE OPERATOR'S OWN PRACTICE ROWS: judged the same way and SWITCHED OFF
    # the same way ("as i said it should be switched off, you should follow my
    # criteria", Sep 29, 2026 — #LLC76MPD sat at 89% and was only reported).
    # Practice-only rows only: _hand_slots never returns one holding "real".
    # In preview each is said once a day, not every hour.
    seen = st.setdefault("reported", {})
    import datetime as _dt

    day = str(_dt.date.fromtimestamp(now))           # a key, never printed
    for key, sym in hand:
        if sym in gone:
            # a practice row on a coin MEXC dropped: off, whichever backtest it
            # was armed from (Practice only — _hand_slots never holds "real")
            m = _meta_of_key(key, sym) or {"coin": sym.removesuffix("_USDT"), "tf": "",
                                            "signal": key, "th": 0.0, "sl": "", "tp": ""}
            rid = _row_id(settings, key, sym, m) if _meta_of_key(key, sym) else key
            drop.append((f"{key}|{sym}", rid, len(out)))
            out.append(_d(now, st, "off", {**m, "id": rid}, f"one of YOUR practice rows: "
                          f"MEXC no longer lists {sym} — it cannot trade"))
            continue
        # judged on the Backtest v2 file, so only rows armed FROM v2
        if (settings.get("strategy_res") or {}).get(f"{key}|{sym}") != "1m":
            continue
        meta = _meta_of_key(key, sym)
        if not meta:
            continue
        meta = {**meta, "id": _row_id(settings, key, sym, meta)}
        # a "reported today" mark only quiets PREVIEW: #LLC76MPD was reported
        # at Sep 29, 2026 3:40am and must not then wait a day to be switched off
        if not act and seen.get(meta["id"]) == day:
            continue
        fresh, readable = _fresh_row(meta, now, cfg)
        if not readable:
            continue
        slot = f"{key}|{sym}"
        fresh = _judged(slot, fresh, now, cfg["window_days"])
        if fresh and fresh.get("unmeasured"):
            continue
        why = wp.judge({"id": meta["id"]}, fresh, cfg)
        if why:
            if not act:
                seen[meta["id"]] = day
            drop.append((slot, meta["id"], len(out)))
            out.append(_d(now, st, "off", meta, f"one of YOUR practice rows: {why}", fresh))
    if act and gone_by_hand:
        def forget(s):
            ws2 = dict(s.get("watcher_slots") or {})
            for slot in gone_by_hand:
                ws2.pop(slot, None)
            s["watcher_slots"] = ws2
            return s
        if not _stopped_meanwhile():
            _write_settings(forget)
    if act and drop:
        def mutate(s):
            for slot, _id, _i in drop:
                _disarm(s, slot)
            return s
        stop = _stopped_meanwhile()
        if stop or not _write_settings(mutate):
            # NOTHING WAS SWITCHED OFF — say so on every line that claimed it
            reason = stop or ("the settings file kept changing — nothing switched "
                              "off this hour, trying again next hour")
            for _slot, _id, i in drop:
                _undo(out[i], reason)
        else:
            # the wait starts only for a switch-off that really happened
            for _slot, rid, _i in drop:
                st.setdefault("cooling", {})[rid] = now
    return [slot for slot, _id, _i in drop]


def _undo(d: dict, reason: str) -> None:
    """A decision that was not carried out is logged as what it is."""
    d["action"] = "refused"
    d["why"] = f"{d['why']} — NOT DONE: {reason}"


def _stopped_meanwhile() -> str:
    """Why a pass must not write, if the operator changed the mode while it
    ran (set_mode writes the state file; the pass holds an older copy)."""
    m = mode_of(_read())
    return "" if m == "act" else f"the watcher was set to {m} while this pass ran"


def _today(now: float) -> str:
    import datetime as _dt

    return str(_dt.date.fromtimestamp(now))          # a key, never printed


def _row_id(settings: dict, key: str, sym: str, meta: dict) -> str:
    from tradingagents import backtest_report as br

    res = (settings.get("strategy_res") or {}).get(f"{key}|{sym}") or ""
    return br.row_code(meta["coin"], meta["tf"], meta["signal"], meta["th"],
                       meta["sl"], meta["tp"], "flat", res=res)


def _d(now, st, action, meta, why, row=None) -> dict:
    d = {"at": now, "mode": mode_of(st), "action": action, "id": meta.get("id", ""),
         "coin": meta.get("coin"), "tf": meta.get("tf"), "signal": meta.get("signal"),
         "tp": meta.get("tp"), "sl": meta.get("sl"),
         "why": f"#{meta.get('id', '')} {meta.get('coin')} {meta.get('tf')} "
                f"{meta.get('signal')} TP {meta.get('tp')}% / SL {meta.get('sl')}% — {why}"}
    if row:
        d["numbers"] = {k: row.get(k) for k in ("trades", "wins", "losses", "winrate",
                                                "profit", "measured_ms")}
    return d


def _try_picks(picks, now, st, act, out, settings, ws, arm, refused) -> None:
    """Check each pick in turn; the ones that pass go into `arm`, the rest
    into `refused` (by id), every one of them with its sentence in `out`."""
    for p in picks:
        r = p["row"]
        sym = f"{r['coin']}_USDT"
        meta = {"id": r["id"], "coin": r["coin"], "tf": r["tf"], "signal": r["signal"],
                "th": r["th"], "sl": r["sl"], "tp": r["tp"], "on_at": now}
        try:
            key, spec = sk.key_for(r), sk.spec_for(r)
        except ValueError as exc:
            out.append(_d(now, st, "refused", meta, str(exc), r))
            refused.add(r["id"])
            continue
        if _sig_of(key) != r["signal"]:
            out.append(_d(now, st, "refused", meta, f"its key {key} would read as "
                          f"{_sig_of(key)!r}, not {r['signal']!r}", r))
            refused.add(r["id"])
            continue
        slot = f"{key}|{sym}"
        mine_already = slot in ws
        by_hand = (slot in (settings.get("strategy_books") or {})
                   or sym in ((settings.get("strategy_coins") or {}).get(key) or []))
        if by_hand and not mine_already:
            out.append(_d(now, st, "refused", meta, "you already run this row "
                          "yourself — the watcher leaves it alone", r))
            refused.add(r["id"])
            continue
        # THE STAKE IS PER STRATEGY NAME, not per coin (auto_trader.margin_for).
        # A name the operator runs at another stake would trade the watcher's
        # coin at THAT stake — never what the replay measured ($5).
        have = (settings.get("strategy_margins") or {}).get(key)
        if have is not None and float(have) != MARGIN:
            out.append(_d(now, st, "refused", meta, f"its strategy name {key} is "
                          f"set to ${float(have):g} a trade, and the watcher only "
                          f"trades ${MARGIN:g}", r))
            refused.add(r["id"])
            continue
        try:
            reg = _register(key, spec, persist=act)
        except ValueError as exc:
            out.append(_d(now, st, "refused", meta, f"its recipe clashes: {exc}", r))
            refused.add(r["id"])
            continue
        try:
            # RAW deploys what the table says; the runner still checks the
            # cost at the moment of every trade (gate_blocked), so no order
            # goes out on a contract its edge cannot survive (rule 12)
            edge = ({"verdict": "ok", "reason": "raw: checked at each trade"}
                    if st.get("cfg", {}).get("raw") else _edge(key, sym))
        finally:
            if reg == "in memory":
                # a PREVIEW recipe must not outlive its check: left in memory
                # it would make a later act pass answer "same" and never
                # write the file the runner reads
                from tradingagents import auto_trader as _at

                _at.STRATEGY_SPECS.pop(key, None)
        if edge.get("verdict") not in EDGE_OK:
            out.append(_d(now, st, "refused", meta, f"the cost check said "
                          f"{edge.get('verdict')}: {edge.get('reason', '')[:160]}", r))
            refused.add(r["id"])
            continue
        out.append(_d(now, st, "on", meta, p["why"], r))
        arm.append((key, sym, meta))
        time.sleep(0.5 if act else 0)    # edge_check reads the live book


def _on_pass(now: float, cfg: dict, st: dict, act: bool, out: list) -> str:
    """Returns "" when the pass ran, else why it has to be tried again."""
    from tradingagents import auto_trader as at

    got = _candidates(cfg, now)
    if got.get("not_ready"):
        return got.get("why") or "the list is not ready"
    settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    running = [{"id": m["id"], "coin": m["coin"]} for m in ws.values()]
    cooling = st.get("cooling") or {}
    # JUDGED ON THE NUMBER THE SWITCH-OFF WILL READ (RCA-2026-10-01-B): the
    # list nominates, the row's own result file (and its 30/15-day record,
    # once it has one) decides — the same `_fresh` + `_judged` the hourly
    # check applies. #FR34HHN4 went on at 71.13% from the list and off 33
    # minutes later at 69.06% from its file, twice in five hours.
    cands = _as_the_off_check_sees(got["rows"], now, cfg)
    rows = [r for r in cands if not wp.passes_on(r, cfg)]
    arm = []
    refused: set = set()
    # A REFUSED PICK DOES NOT USE UP A PLACE: the day's 20 new are 20 that
    # passed every check, so after a refusal the next candidate in line is
    # tried — up to 5 rounds, each over what is still untried.
    for _round in range(5):
        taken = running + [{"id": m["id"], "coin": m["coin"]} for _, _, m in arm]
        # 0 is NO LIMIT, so a used-up day must stop here rather than turn
        # into 0 and mean "unlimited" (found building "no limit", Sep 30, 2026)
        per_day = int(cfg["max_new_per_day"])
        if per_day and len(arm) >= per_day:
            break
        room_cfg = {**cfg, "max_new_per_day": (per_day - len(arm)) if per_day else 0}
        picks = wp.pick([r for r in rows if r["id"] not in refused], taken, cooling, now,
                        room_cfg)
        if not picks:
            break
        _try_picks(picks, now, st, act, out, settings, ws, arm, refused)
    if act and arm:
        live = live_of(st)

        def mutate(s):
            for key, sym, meta in arm:
                _arm(s, key, sym, meta, live=live)
            return s
        stop = _stopped_meanwhile()
        if stop or not _write_settings(mutate):
            reason = stop or "the settings file kept changing — nothing switched on"
            for d in out:
                if d["action"] == "on":
                    _undo(d, reason)
            if not stop:
                return f"{reason}, trying again"
    # the count that passes EVERY rule, beside the one the list was asked for
    # (RCA-2026-09-30-C): "1,511 meet the criteria" over 539 switched on read
    # as 972 rows lost
    gone = len(got["rows"]) - len(cands)
    st["last_candidates"] = (f"{got.get('why', '')} — {len(rows):,} pass every rule "
                             f"on their own result file"
                             + (f" ({len(cands) - len(rows):,} fail one, most often "
                                f"{_top_fail(cands, cfg)})"
                                if len(cands) > len(rows) else "")
                             + (f" · {gone:,} could not be read from their file"
                                if gone else ""))
    return ""


def _as_the_off_check_sees(rows: list, now: float, cfg: dict) -> list:
    """Each candidate as `_off_pass` would judge it: its row in its pair
    file (one parse per pair), then `_judged` over the room's window. A
    candidate whose file is missing, unreadable or no longer holds it is
    dropped — the switch-off would remove it at once."""
    from tradingagents import watcher_candidates as wc

    by_pair: dict = {}
    for r in rows:
        by_pair.setdefault((r["coin"], r["tf"]), []).append(r)
    out = []
    window = int(cfg.get("window_days") or 30)
    for (coin, tf), want in by_pair.items():
        have = wc.matched_rows(coin, tf, want) or {}
        if not have:
            continue
        last = wc._last_ms(coin, tf) or 0.0
        for r in want:
            got = have.get(wc._sig(r))
            if got is None:
                continue
            fresh = wc._fresh(coin, tf, got, last, wc.window_of(cfg))
            try:
                slot = f"{sk.key_for(fresh)}|{coin}_USDT"
            except ValueError:
                out.append(fresh)          # refused by name in _try_picks
                continue
            out.append(_judged(slot, fresh, now, window) or fresh)
    return out


def _top_fail(rows: list, cfg: dict) -> str:
    """The reason most of the refused candidates share, numbers taken out."""
    import collections
    import re

    c = collections.Counter(" ".join(re.sub(r"[+-]?\d[\d.,]*%?", " ", wp.passes_on(r, cfg)).split())
                            for r in rows if wp.passes_on(r, cfg))
    return c.most_common(1)[0][0] if c else "?"


def _on_due(now: float, last: float, raw: bool = False) -> bool:
    """Once per local day, at or after ON_HOUR — any hour when RAW: the noon
    rule existed for the switch-on cost check (stock books are wide before
    the open), and raw leaves that check to the runner at each trade."""
    import datetime as _dt

    here = _dt.datetime.fromtimestamp(now)
    if here.hour < ON_HOUR and not raw:
        return False
    return not last or _dt.date.fromtimestamp(last) < here.date()


def next_on(now: float, last: float) -> float:
    """When the next switch-on pass is due (epoch seconds)."""
    import datetime as _dt

    here = _dt.datetime.fromtimestamp(now)
    noon = here.replace(hour=ON_HOUR, minute=0, second=0, microsecond=0)
    if _on_due(now, last):
        return now
    if here < noon and (not last or _dt.date.fromtimestamp(last) < here.date()):
        return noon.timestamp()
    return (noon + _dt.timedelta(days=1)).timestamp()


def consider(*, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st = _read()
    mode = mode_of(st)
    if mode == "off":
        return {"decisions": [], "why": "switched off"}
    cfg = cfg_of(st)
    act = mode == "act"
    out: list[dict] = []
    if now - float(st.get("last_off_pass") or 0) >= OFF_EVERY_S:
        # stamped FIRST: a pass that raises is retried next hour, never every
        # minute (the tick only prints the error; nothing else would stop it)
        st["last_off_pass"] = now
        try:
            _off_pass(now, cfg, st, act, out)
        except Exception as exc:                               # noqa: BLE001
            st["why"] = f"the switch-off check failed: {type(exc).__name__}: {str(exc)[:160]}"
        st["practice"] = _practice_now(now, cfg)
    due_on = _on_due(now, float(st.get("last_on_pass") or 0), bool(cfg.get("raw")))
    tried = now - float(st.get("last_on_try") or 0) >= RETRY_S
    if due_on and tried:
        st["last_on_try"] = now
        try:
            wait = _on_pass(now, cfg, st, act, out)
        except Exception as exc:                               # noqa: BLE001
            wait = f"it failed: {type(exc).__name__}: {str(exc)[:160]}"
        if wait:
            st["why"] = f"switch-on pass waiting: {wait}"
        else:
            st["last_on_pass"] = now
            st["why"] = f"last switch-on pass {_when(now)}: {st.get('last_candidates', '')}"
    _log(out)
    if out:
        with contextlib.suppress(Exception):                   # noqa: BLE001
            from tradingagents import notifications as nt

            n_on = sum(d["action"] == "on" for d in out)
            n_off = sum(d["action"] == "off" for d in out)
            if n_on or n_off:
                from tradingagents import profiles as _pf

                nt.record("trade", f"Watcher {_pf.current()}{' (preview)' if not act else ''}: "
                          f"{n_on} switched on, {n_off} switched off", ok=True,
                          detail="; ".join(d["why"] for d in out[:6]))
    # ONLY THE PASS'S OWN FIELDS go back, onto the state file as it is NOW: a
    # mode or rule the operator set while this pass ran (it can take a minute
    # of live book reads) must survive the pass writing its results.
    wait_s = float(cfg.get("cooldown_days", 7)) * 86_400
    st["cooling"] = {k: v for k, v in (st.get("cooling") or {}).items()
                     if now - float(v) < wait_s}
    import datetime as _dt

    today = str(_dt.date.fromtimestamp(now))
    st["reported"] = {k: v for k, v in (st.get("reported") or {}).items() if v == today}
    fresh = _read()
    for k in PASS_FIELDS:
        if k in st:
            fresh[k] = st[k]
    _write(fresh)
    return {"decisions": out, "why": st.get("why", "")}


PASS_FIELDS = ("last_on_pass", "last_off_pass", "last_on_try", "cooling",
               "reported", "why", "last_candidates", "practice")


def _practice_now(now: float, cfg: dict) -> dict:
    """{slot: practice record + its warning} for every running watcher slot —
    SHOWN on the screen, never a reason to switch off (the operator gave one
    off rule, the 30-day win rate). Computed once an hour, so the panel's
    30-second poll never reads the whole trade record."""
    from tradingagents import auto_trader as at

    with contextlib.suppress(Exception):                       # noqa: BLE001
        ws = at.load_settings().get("watcher_slots") or {}
        rec = _practice({slot: float(m.get("on_at") or now) for slot, m in ws.items()}, now)
        return {slot: {**p, "warn": wp.warn(p, {**wp.DEFAULTS, **cfg})}
                for slot, p in rec.items()}
    return {}


def _when(ts: float) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(ts)


def status(page: int = 1, per: int = PER_PAGE) -> dict:
    from tradingagents import auto_trader as at

    st = _read()
    settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    practice = st.get("practice") or {}
    cfg = cfg_of(st)
    from tradingagents import profiles

    return {"profile": profiles.current(), "live": live_of(st),
            "mode": mode_of(st), "cfg": {k: cfg[k] for k in LIVE_RULES},
            "window_days": cfg["window_days"], "why": st.get("why", ""),
            "last_on_pass": st.get("last_on_pass"), "last_off_pass": st.get("last_off_pass"),
            "next_on_pass": next_on(time.time(), float(st.get("last_on_pass") or 0)),
            "running": len(ws),
            "slots": [{"slot": k, **v, "practice": practice.get(k)} for k, v in sorted(ws.items())],
            "cooling": len(st.get("cooling") or {}), **decisions_page(page, per)}


_LAST_SAID: dict = {}          # per profile


def tick() -> dict:
    """`consider()` for the CURRENT profile, logged when its answer changes.
    NEVER under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"decisions": [], "why": "never under a test run"}
    from tradingagents import profiles

    pid = profiles.current()
    got = consider()
    why = str(got.get("why") or "")
    if why and why != _LAST_SAID.get(pid):
        print(f"[watcher] {pid}: {why}", flush=True)
    _LAST_SAID[pid] = why
    return got
