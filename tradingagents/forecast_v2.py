"""Forecast v2 — what is hot, what loses, where the money goes, and which room
rules will make the most this month.

Operator, Oct 01, 2026: *"when i say forecast, i mean you should be predicting
what's the best combination of criteria to be using for deployed rooms, based
on overall backtest results"*, *"i want prediction like for example, you are
seeing a coin is winning 9 streak then inform me that specific coin i want it
in a Streak section / then predict what combination of room will be
effective, for example: 90% winrate with 40trade, tp is greater than SL will
have profit of x this month"*, then *"okay run that prompt and create
Forecast v2"* (the prompt: docs/FORECAST-V2.md, "The build prompt").

THE ONE PLACE for every Forecast v2 number. Two halves:

* LIVE — the PRACTICE half, worked out here from each room's own files:
  its trade record (room_stats.ledger, read incrementally), its open trades,
  its switched-on rows (auto_trade.json `watcher_slots`), its switch-on and
  switch-off history (deployments.jsonl) and the rebuilt backtest trades of
  those rows (rolling30's cache). Cheap; the API makes a copy in the
  background (`live()`).
* MEASURED ON GITHUB — the BACKTEST half: the replay of every strategy that
  could pass (.github/workflows/replay.yml) and the forecast research over it
  (.github/workflows/forecast.yml -> .github/scripts/forecast_shard.py),
  merged by forecast_v2_merge.py into ~/.tradingagents/forecast_v2/latest.json
  and only READ here.

READ ONLY on trading: nothing here switches a room on or off, changes a
watcher rule or touches real money. Every prediction and warning is a note.

THE DEFINITIONS (the same as everywhere else in the project):
* a win = profit after all costs > 0; everything else is a loss.
* a WINNING streak = wins in a row ending with the most recent closed trade,
  a LOSING streak the opposite; a practice streak is per room and coin (every
  strategy of that coin in that room, by exit time), a backtest streak per
  stored combination (coin + timeframe + signal + TP + SL).
* break-even win rate of a strategy = (SL + cost) / (TP + SL), all in percent
  of the trade's size: a win pays TP less the cost, a loss costs SL plus the
  cost (CLAUDE.md rule 11). For a group of trades, the average over them.
* a finding resting on fewer than THIN trades is "too few trades to mean
  anything", and the screen says so.
* REALITY CHECK: the same rows over the same hours — every row a room
  switched on, from its switch-on to the end of its rebuilt backtest
  (rolling30), its BACKTEST trades against its PRACTICE trades. The money the
  backtest made that practice did not, per backtest trade, is the shortfall
  every prediction is corrected by.
"""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import json
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path

from tradingagents import room_stats as rs

WIN_N = 9                     # the winning streak shown by default
LOSS_M = 5                    # the losing streak shown by default
THIN = 30                     # fewer trades than this: too few to mean anything


# ------------------------------------------------------------------ helpers
def _home() -> Path:
    """Beside the rest of the app's state (a test's sandbox moves it)."""
    from tradingagents import auto_trader as at

    return Path(at.STATE_DIR) / "forecast_v2"


# how long a finished file keeps trying to swap into place — db_jobs'
# WRITE_REPLACE_BUDGET_S, for the same reason (RCA-2026-09-18-B)
REPLACE_BUDGET_S = 3.0


def replace_retry(tmp: Path, path: Path) -> None:
    """`tmp` swapped into place, the swap retried for REPLACE_BUDGET_S: on
    Windows a reader holding the destination open refuses it for
    milliseconds — and on Sep 17, 2026 longer than 0.2 s, which ended a 96%
    finished backtest. Forecast v2's files are read by the page every 30
    seconds (bug hunt, round 8)."""
    deadline = time.monotonic() + REPLACE_BUDGET_S
    pause = 0.005
    while True:
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            time.sleep(pause)
            pause = min(pause * 1.5, 0.1)


def publish(path: Path, text: str) -> None:
    """A file written WHOLE: a temp file unique to this call (two threads
    never share one), then `replace_retry`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_retry(tmp, path)


def pct_decode(code: str) -> float | None:
    """strategy_keys.pct_code backwards: '03' -> 0.3, '15' -> 1.5, '2' -> 2,
    '125' -> 1.25, '12p5' -> 12.5."""
    code = str(code or "")
    if not code or not re.fullmatch(r"[0-9p]+", code):
        return None
    if "p" in code:
        return float(code.replace("p", "."))
    return float(code[0] + ("." + code[1:] if len(code) > 1 else ""))


@lru_cache(maxsize=20_000)
def spec_of(key: str) -> dict:
    """timeframe, signal, threshold, TP and SL (percent) of a strategy key —
    from the runner's own recipe when it has one, else read off the key the
    way strategy_keys.key_for wrote it."""
    from tradingagents import auto_trader as at, strategy_keys as sk
    from tradingagents.local_history import _sig_of

    key = str(key or "")
    out = {"tf": None, "signal": _sig_of(key) if key else "", "th": 0.0,
           "tp": None, "sl": None}
    m = re.search(r"_(15m|30m|1h|4h|1d)(?:_|$)", key)
    if m:
        out["tf"] = m.group(1)
    spec = at.STRATEGY_SPECS.get(key)
    if spec:
        tf = {v[0]: k for k, v in sk.TF_SPEC.items()}.get(spec.get("interval"))
        out["tf"] = tf or out["tf"]
        out["tp"] = round(float(spec["tp"]) * 100, 3)
        out["sl"] = round(float(spec["sl"]) * 100, 3)
        if out["signal"] in sk.THRESHOLD_SIGNALS:
            out["th"] = round(float(spec.get("threshold") or 0) * 100, 3)
        return out
    m = re.search(r"_sl([0-9p]+)tp([0-9p]+)$", key)
    if m:
        out["sl"], out["tp"] = pct_decode(m.group(1)), pct_decode(m.group(2))
    m = re.search(r"_t([0-9p]+)_", key)
    if m and out["signal"] in sk.THRESHOLD_SIGNALS:
        out["th"] = pct_decode(m.group(1)) or 0.0
    return out


def family(signal: str) -> str:
    """A signal's family: the learned models and formulas are one family each
    (they are one per coin), every other signal is its own."""
    s = str(signal or "")
    if s.startswith("ml_"):
        return "ml (learned models)"
    if s.startswith("lx_"):
        return "lx (learned formulas)"
    return s or "unknown"


def break_even(tp: float | None, sl: float | None, cost_pct: float) -> float | None:
    """(SL + cost) / (TP + SL), in percent — the win rate a strategy needs."""
    if not tp or not sl or tp + sl <= 0:
        return None
    return 100.0 * (float(sl) + max(float(cost_pct), 0.0)) / (float(tp) + float(sl))


def _group(rows: list[dict]) -> dict:
    g = rs._group(rows)
    g["thin"] = g["trades"] < THIN
    return g


def _worst_run(pnls: list[float]) -> tuple[float, int]:
    return rs.worst_run(pnls)


# ------------------------------------------------------------- one room
_READS: dict = {}


def _read_cached(p: Path, parse):
    """A file read again only when it changes (a room's settings file and
    deploy log are read every refresh; #4FC03172's hold 2,362 rows)."""
    try:
        st = p.stat()
    except OSError:
        return parse(None)
    stamp = (st.st_mtime_ns, st.st_size)
    got = _READS.get(str(p))
    if got and got[0] == stamp:
        return got[1]
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return got[1] if got else parse(None)
    value = parse(text)
    _READS[str(p)] = (stamp, value)
    return value


def _settings(pid: str) -> dict:
    """The room's own settings file, read without the runner's defaults
    (load_settings writes nothing either, but this must not depend on it)."""
    from tradingagents import auto_trader as at, profiles

    def parse(text):
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {}

    return _read_cached(Path(profiles.path(at.SETTINGS_PATH, pid)), parse)


def _intervals(pid: str, now_s: float) -> dict:
    """{slot: [(on_s, off_s or now_s), ...]} — every stretch a row was
    switched on in this room's PRACTICE account, from its deploy log
    (`_switches`: real money alone is not practice), and
    the room's current `watcher_slots` for a row whose deploy line is
    missing."""
    from tradingagents import local_history as lh, profiles

    out: dict = {}
    try:
        with profiles.using(pid):
            path = Path(lh._deploy_log())
        lines = _read_cached(path, lambda t: (t or "").splitlines())
    except Exception:                                          # noqa: BLE001
        lines = []
    open_at: dict = {}
    for at_s, slot, act in _switches(lines):
        if act == "deployed":
            open_at.setdefault(slot, at_s)
        elif act == "disarmed" and slot in open_at:
            out.setdefault(slot, []).append((open_at.pop(slot), at_s))
    for slot, at_s in open_at.items():
        out.setdefault(slot, []).append((at_s, now_s))
    for slot, v in (_settings(pid).get("watcher_slots") or {}).items():
        on = rs._num(v.get("on_at"), None)
        if on is not None and slot not in out:
            out[slot] = [(on, now_s)]
    # THE WATCHER'S OWN DECISIONS fill in what the deploy log lost: it dropped
    # every second switch-off of a strategy until Oct 06, 2026
    # (RCA-2026-10-05-H — 43 of #CC94D9FB's 497), and those rows then read
    # as switched on in the reality check
    decided = _watcher_decisions(pid)
    if decided:
        for slot in sorted(out):
            rid = _row_id_of_slot(slot)
            if not rid or not (decided.get((rid, "on")) or decided.get((rid, "off"))):
                continue
            spans = out.get(slot) or []
            still_on = bool(spans) and spans[-1][1] == now_s
            merged = merge_decisions([(a * 1000, b * 1000) for a, b in spans], still_on,
                                     decided, rid)
            out[slot] = [(a / 1000, now_s if b is None else b / 1000) for a, b in merged]
            if not out[slot]:
                del out[slot]
    _end_stretches_no_longer_on(pid, out, now_s)
    return out


def _end_stretches_no_longer_on(pid: str, out: dict, now_s: float) -> None:
    """A stretch the history leaves running for a slot the room's settings do
    NOT have switched on did end - the history just never said when. It ends
    at the slot's last exit in the trade record, and is dropped when it has
    none. Main, Oct 06, 2026: 40 rows switched on Sep 03-05, 2026 with no
    switch-off line (written before the deploy log recorded every path), the
    last of their trades on Sep 15 - each would otherwise read as switched on
    to this day. Nothing is touched while the settings cannot be read."""
    st = _settings(pid)
    if "strategy_coins" not in st:
        return
    armed = {f"{k}|{c}" for k, cs in (st.get("strategy_coins") or {}).items() for c in cs or []}
    armed |= set(st.get("watcher_slots") or {})      # the watcher writes both
    ghosts =[slot for slot, v in out.items() if v and v[-1][1] == now_s and slot not in armed]
    if not ghosts:
        return
    last: dict = {}
    try:
        led = rs.ledger(rs._paths(pid)[0])
        for e in led.get("exits") or []:
            slot = f"{e.get('key')}|{e.get('symbol')}"
            if e.get("ts") is not None:
                last[slot] = max(last.get(slot, 0.0), float(e["ts"]))
    except Exception:                                          # noqa: BLE001
        return
    for slot in ghosts:
        on = out[slot][-1][0]
        end = last.get(slot)
        if end is not None and end > on:
            out[slot][-1] = (on, end)
        else:
            out[slot].pop()
            if not out[slot]:
                del out[slot]


_NO_COIN = ("", "\u2014", "-", None)


def _books_of(e: dict, act: str) -> list:
    """The accounts a deploy-log line leaves on. A line written without the
    field (the delisted cleanup's, a test's) is on for "deployed"/"changed"
    and off for "disarmed"."""
    raw = e.get("books")
    if raw is None:
        return ["paper"] if act in ("deployed", "changed") else []
    return [b for b in str(raw).split(",") if b]


def _same_margin(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _switches(lines: list) -> list:
    """[(at_s, slot, "deployed"|"disarmed")] — when each strategy-and-coin
    started and stopped trading on the PRACTICE account, read off a room's
    deploy log in order.

    The log is a diff of three settings and is replayed as them, never line
    by line (`local_history.deploy_diff`; the runner's `auto_trader.books_for`):

      * "key|COIN", symbol "-": one coin's own accounts. Set, or REMOVED - and
        a removed one falls back to the bare key's accounts, so it is a
        switch-off only when the bare key does not carry the coin on practice.
      * "key", symbol "COIN_USDT": the key's accounts and its coin list, one
        line per coin AFTER the change (a second apart, so lines for one key
        with the same coins-before within a minute are one change), the coins
        before in prev_json. When no coin is left, deploy_diff lists the coins
        BEFORE - spotted as a line whose coins, accounts and margin all equal
        the ones before it, which deploy_diff never writes otherwise.
      * a delisted cleanup's "key", "COIN" disarmed line, without prev_json.

    Main, Sep 24, 2026 7:45am: keltner_30m_sl2tp2 on GPNSTOCK moved from its
    own switch to the key's (`key|GPNSTOCK` removed, `key` on for GPNSTOCK and
    KKRSTOCK in the same second). Read line by line, that was a switch-off,
    and its two practice trades of Oct 01, 2026 had nothing to pair with; it
    really went off at Oct 01, 2026 11:51am, when the key's coin list
    emptied."""
    rows = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        at_s = rs._num(e.get("changed_at"), None)
        key, act = e.get("strategy_key"), e.get("action")
        if not key or at_s is None or act not in ("deployed", "disarmed", "changed"):
            continue
        rows.append((at_s, str(key), act, e))
    events: list = []                # (at_s, order, kind, key, data)
    open_group: dict = {}            # (key, prev_json) -> the change it is filling
    for n, (at_s, key, act, e) in enumerate(rows):
        if "|" in key:
            events.append([at_s, n, "slot", key, _books_of(e, act)])
            continue
        sym, prev = e.get("symbol"), e.get("prev_json")
        if prev is None and act == "disarmed":
            if sym not in _NO_COIN:
                events.append([at_s, n, "drop", key, sym])
            continue
        g = open_group.get((key, prev))
        if g is None or at_s - g[0] > 60:
            g = [at_s, n, "bare", key, {"now": set(), "books": _books_of(e, act),
                                        "known": e.get("books") is not None, "margin": e.get("base_margin"),
                                        "prev": prev}]
            events.append(g)
            open_group[(key, prev)] = g
        g[4]["now"].add(sym)
    events.sort(key=lambda x: (x[0], x[1]))

    own: dict = {}                   # "key|COIN" -> its own accounts
    books: dict = {}                 # key -> its accounts
    coins: dict = {}                 # key -> its coin list
    # A COIN'S OWN SWITCH THE LOG NEVER SET was written straight into the
    # settings - Main's per-coin move of Sep 16, 2026 took every key's
    # accounts onto its coins without a line, so what this replay holds for
    # the key is stale from then on. Removing such a switch falls back to the
    # key only when a line for the key in the same save says what the key
    # is; otherwise the coin is off until the key is written again
    # (macddiv_4h_sl25tp25 on STBL, removed Sep 24, 2026 7:45am, the key's
    # accounts gone since Sep 16 - the settings copies say so).
    set_here: set = set()
    unknown: set = set()
    bare_at: dict = collections.defaultdict(list)
    for ev in events:
        if ev[2] == "bare":
            bare_at[ev[3]].append(ev[0])

    def on(slot):
        if slot in own:
            return "paper" in own[slot]
        if slot in unknown:
            return False
        k, _, c = slot.partition("|")
        return c in coins.get(k, ()) and "paper" in books.get(k, ())

    out: list = []
    state: dict = {}                 # slot -> on, as last written to `out`
    for at_s, _n, kind, key, data in events:
        if kind == "slot":
            if data:
                own[key] = data
                set_here.add(key)
                unknown.discard(key)
            else:
                k = key.partition("|")[0]
                if (key not in set_here
                        and not any(abs(t - at_s) <= 60 for t in bare_at.get(k, ()))):
                    unknown.add(key)
                own.pop(key, None)
            touched = [key]
        elif kind == "drop":
            coins[key] = set(coins.get(key, ())) - {data}
            own.pop(f"{key}|{data}", None)
            touched = [f"{key}|{data}"]
        else:
            listed = {c for c in data["now"] if c not in _NO_COIN}
            try:
                p = json.loads(data["prev"] or "{}") or {}
            except (TypeError, ValueError):
                p = {}
            before = {c for c in (p.get("coins") or []) if c not in _NO_COIN}
            if (data["known"] and listed and listed == before
                    and sorted(data["books"]) == sorted(p.get("books") or [])
                    and _same_margin(data["margin"], p.get("base_margin"))):
                listed = set()       # deploy_diff listed the coins before: none left
            books[key] = data["books"]
            touched = [f"{key}|{c}" for c in sorted(set(coins.get(key, ())) | listed | before)]
            coins[key] = listed
            unknown.difference_update(touched)
        for slot in touched:
            now_on = on(slot)
            if now_on != state.get(slot, False):
                state[slot] = now_on
                out.append((at_s, slot, "deployed" if now_on else "disarmed"))
    # one save writes its lines over a second or two, so a switch-off and the
    # switch-on that replaces it can land apart: no gap was ever traded
    last: dict = {}
    keep = [True] * len(out)
    for i, (at_s, slot, act) in enumerate(out):
        j = last.get(slot)
        if (act == "deployed" and j is not None and out[j][2] == "disarmed"
                and at_s - out[j][0] <= 60):
            keep[i] = keep[j] = False
        last[slot] = i
    return [x for x, k in zip(out, keep) if k]


def _watcher_decisions(pid: str) -> dict:
    """{(id, "on"|"off"): [(at_ms, why), ...]} — every switch the room's
    watcher CARRIED OUT (mode act; a decision that was not carried out is
    written "refused"), re-read only when the log changes."""
    from tradingagents import profiles
    from tradingagents import strategy_watcher as sw

    def parse(text):
        out: dict = {}
        for line in (text or "").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if (not isinstance(e, dict) or e.get("mode") != "act"
                    or e.get("action") not in ("on", "off")):
                continue
            with contextlib.suppress(TypeError, ValueError):
                # the time only: the reasons are ~11 MB across the rooms and
                # nothing here reads them (Backtest a room reads its own)
                out.setdefault((str(e.get("id")), e["action"]), []).append(
                    (int(float(e["at"]) * 1000), ""))
        return out
    try:
        with profiles.using(pid):
            path = Path(sw._log_path())
    except Exception:                                          # noqa: BLE001
        return {}
    return _read_cached(path, parse)


_ROW_IDS: dict = {}


def _row_id_of_slot(slot: str) -> str:
    """The Backtest v2 id the watcher writes for a slot ("key|COIN_USDT"),
    from the key's own recipe (spec_of) - the same row_code the watcher's
    decisions carry. A key the static recipes do not hold is looked up again
    after the watcher's runtime recipes are merged: read off the name alone,
    cx_4h_15m_sl1tp12 is a 4h key and its id is wrong (review, Oct 06,
    2026). Only an answer read from a recipe is remembered."""
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br

    got = _ROW_IDS.get(slot)
    if got is not None:
        return got
    key, _, sym = str(slot).partition("|")
    if key not in at.STRATEGY_SPECS:
        with contextlib.suppress(Exception):                   # noqa: BLE001
            at.merge_runtime_specs()
    from_recipe = key in at.STRATEGY_SPECS
    sp = spec_of(key)
    if not (sym and sp.get("tf") and sp.get("signal") and sp.get("tp") is not None
            and sp.get("sl") is not None):
        return ""
    try:
        rid = br.row_code(sym.removesuffix("_USDT"), sp["tf"], sp["signal"],
                          float(sp.get("th") or 0), float(sp["sl"]), float(sp["tp"]),
                          "flat", res="1m")
    except Exception:                                          # noqa: BLE001
        return ""
    if from_recipe:
        _ROW_IDS[slot] = rid
    return rid


def merge_decisions(spans_ms: list, still_on: bool, decided: dict, rid: str) -> list:
    """[(on_ms, off_ms or None)]: a slot's deploy-log stretches (`spans_ms`,
    the last one still running while `still_on`) MERGED with the watcher's
    carried-out switches for its id. A watcher decision fills in only where
    the deploy log has no line of the same kind within 15 minutes (the deploy
    log stamps the settings write, which is when the runner can act). Shared
    by Backtest a room (room_replay) and the reality check (_intervals)."""
    ev = []
    for i, (a, b) in enumerate(spans_ms):
        ev.append((int(a), 1))
        if not (still_on and i == len(spans_ms) - 1):
            ev.append((int(b), 0))
    # THE WATCHER STAMPS A DECISION WHEN ITS PASS STARTS, the deploy log when
    # the settings are written - up to 36 minutes later (#55D32617; #4FC03172
    # median 24.9 min). A deploy line from 5 minutes before to 45 minutes
    # after a decision IS that decision, and only the deploy time is kept:
    # it is when the runner could act (review, Oct 06, 2026 - a 15-minute
    # window moved 3,416 of #4FC03172's switch-ons up to 25 minutes early).
    before, after = 300_000, 2_700_000
    mine = sorted([(int(t), 1) for t, _w in decided.get((rid, "on"), ())]
                  + [(int(t), 0) for t, _w in decided.get((rid, "off"), ())])
    for k, (t, flag) in enumerate(mine):
        logged = [x for x, f in ev if f == flag]
        if any(t - before <= x <= t + after for x in logged):
            continue
        # A SWITCH-OFF THE NEXT DECISION REPEATS was not carried out: the
        # pass that logged it failed to write (#4FC03172, Oct 02, 2026
        # 9:20am, 20 of them; the next pass switched 19 off at 10:21am and
        # the runner traded #3L97L8ZF in between)
        if flag == 0 and k + 1 < len(mine) and mine[k + 1][1] == 0:
            continue
        ev.append((t, flag))
    out, start = [], None
    for t, on in sorted(ev):
        if on and start is None:
            start = t
        elif not on and start is not None:
            if t > start:
                out.append((start, t))
            start = None
    if start is not None:
        out.append((start, None))
    return out


def room_data(pid: str, now_s: float) -> dict:
    """Everything Forecast v2 reads about one room."""
    from tradingagents import profiles

    ledger_path, state_path = rs._paths(pid)
    led = rs.ledger(ledger_path)
    exits = [e for e in led["exits"] if e["dry"]]
    exits.sort(key=lambda e: (e["ts"], e["trade_id"]))
    costs = rs.costs(exits, led["enters"])
    cost_pct = {r["trade_id"]: 100.0 * r["cost"] / r["size"] for r in costs["rows"] if r["size"]}
    settings = _settings(pid)
    return {"id": pid, "name": "Main" if pid == profiles.MAIN else f"#{pid}",
            "retired": profiles.retired(pid), "exits": exits, "enters": led["enters"],
            "costs": costs, "cost_pct": cost_pct,
            "avg_cost_pct": (sum(cost_pct.values()) / len(cost_pct)) if cost_pct else 0.0,
            "open": [o for o in rs.open_trades(state_path) if o["dry"]],
            "slots": settings.get("watcher_slots") or {},
            "coins_on": {c for cs in (settings.get("strategy_coins") or {}).values()
                         for c in (cs or [])},
            "intervals": _intervals(pid, now_s), "unreadable": led["bad"],
            "cap": _coin_cap(settings)}


def _coin_cap(settings: dict) -> int:
    """How many practice trades the room's runner holds on one coin at once —
    the runner's own rule (auto_trader.max_slices, 4 unless set)."""
    from tradingagents import auto_trader as at

    return at.max_slices(settings) if at.partial_on(settings, True) else 1


def _trade_be(e: dict, room: dict) -> float | None:
    sp = spec_of(e["key"])
    return break_even(sp["tp"], sp["sl"], room["cost_pct"].get(e["trade_id"], room["avg_cost_pct"]))


# ------------------------------------------------------------- A. streaks
def streak_of(trades: list[dict]) -> dict | None:
    """The run at the END of `trades` (sorted by exit time): wins in a row
    (a loss ends it) or losses in a row (a win ends it)."""
    if not trades:
        return None
    won = trades[-1]["pnl"] > 0
    n = 0
    for t in reversed(trades):
        if (t["pnl"] > 0) != won:
            break
        n += 1
    run = trades[-n:]
    return {"kind": "win" if won else "loss", "length": n,
            "started_at": run[0].get("opened_at") or run[0]["ts"], "last_at": run[-1]["ts"],
            "profit": round(sum(t["pnl"] for t in run), 2),
            "keys": sorted({t["key"] for t in run if t["key"]})}


def practice_streaks(rooms: list[dict]) -> list[dict]:
    """Every room and coin's current streak, longest first."""
    out = []
    for r in rooms:
        by: dict = {}
        for e in r["exits"]:
            by.setdefault(e["symbol"], []).append(e)
        for sym, trades in by.items():
            s = streak_of(trades)
            if s is None:
                continue
            wins = sum(1 for t in trades if t["pnl"] > 0)
            bes = [b for b in (_trade_be(t, r) for t in trades) if b is not None]
            one = s["keys"][0] if len(s["keys"]) == 1 else None
            sp = spec_of(one) if one else {}
            slot = f"{one}|{sym}" if one else None
            row_id = (r["slots"].get(slot) or {}).get("id") if slot else None
            out.append({**s, "source": "practice", "room": r["id"], "room_name": r["name"],
                        "coin": sym.replace("_USDT", ""), "id": row_id,
                        "strategies": len(s["keys"]), "tf": sp.get("tf"),
                        "signal": sp.get("signal"), "tp": sp.get("tp"), "sl": sp.get("sl"),
                        "trades": len(trades), "wins": wins, "losses": len(trades) - wins,
                        "winrate": round(100 * wins / len(trades), 1),
                        "break_even": round(sum(bes) / len(bes), 1) if bes else None,
                        "switched_on": sym in r["coins_on"]})
    out.sort(key=lambda x: (-x["length"], x["room"], x["coin"]))
    return out


# B. (coins to avoid) was removed on Oct 07, 2026 — the operator: "remove the
# section coins to avoid i dont need its logic"
# ------------------------------------------------ C. where the money goes
def families(rooms: list[dict]) -> list[dict]:
    """Practice trades by signal family, worst first, each with `thin` when it
    rests on too few trades to mean anything — what the forecast's "skip the
    worst families" option skips (forecast_v2_daily.skip_families).

    The rest of "Where the money goes" — costs per room, a win against a
    loss, the splits by timeframe, market, hour and stop-out, and one coin in
    many rooms — went with its section on Oct 08, 2026 (operator: "delete
    Where the money goes section i dont need it anymore"), so none of it is
    worked out any more."""
    groups: dict = {}
    for r in rooms:
        for e in r["exits"]:
            groups.setdefault(family(spec_of(e["key"])["signal"]), []).append(e)
    out = [{"group": k, **_group(v)} for k, v in groups.items()]
    out.sort(key=lambda g: (g["profit"], str(g["group"])))
    return out


# --------------------------------------------------------- the reality check
_ROLL: dict = {}
_ROLL_LOCK = threading.Lock()
_ROLL_DIR: dict = {"stamp": None}


def _rolling(slot: str) -> dict | None:
    """rolling30's rebuilt backtest of one row, re-read when its file changes.

    ONE STAT A REFRESH, not one per row (bug hunt, round 2, Oct 01, 2026):
    3,868 rows meant 3,868 stats every 30 seconds, and under a CPU-bound
    neighbour each stat waits its turn for Python's lock — the same queue
    that made /api/health take 60 s. rolling30 replaces a file by renaming a
    new one into the folder, which moves the FOLDER's own time; while that
    time stands still, every row's last read stands."""
    from tradingagents import rolling30 as r30

    p = r30._cache_path(slot)
    try:
        dstamp = p.parent.stat().st_mtime_ns
    except OSError:
        return None
    with _ROLL_LOCK:
        if _ROLL_DIR["stamp"] != dstamp:
            _ROLL_DIR["stamp"] = dstamp
            for k in list(_ROLL):
                _ROLL[k] = (None, _ROLL[k][1])          # re-check each row once
        got = _ROLL.get(slot)
        if got and got[0] == dstamp:
            return got[1]
    try:
        st = p.stat()
    except OSError:
        with _ROLL_LOCK:
            _ROLL[slot] = (dstamp, None)
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _ROLL_LOCK:
        got = _ROLL.get(slot)
        if got and got[1] is not None and got[1].get("_stamp") == stamp:
            _ROLL[slot] = (dstamp, got[1])
            return got[1]
    try:
        rec = rs.loads(p.read_text(encoding="utf-8"))
        rec = {"end_ms": int(rec["end_ms"]), "_stamp": stamp,
               "trades": [[float(a), float(b), float(c)] for a, b, c in rec.get("trades") or []]}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    with _ROLL_LOCK:
        _ROLL[slot] = (dstamp, rec)
    return rec


def reality(rooms: list[dict]) -> dict:
    """THE SAME ROWS OVER THE SAME HOURS. For every stretch a row was switched
    on in a room, up to the end of its rebuilt backtest: the backtest's trades
    that OPENED in it against the practice trades that opened in it (both
    closed by that end). Rows with no rebuilt backtest are counted apart.

    THE BACKTEST SIDE KEEPS THE RUNNER'S PER-COIN LIMIT (found in the bug hunt,
    Oct 01, 2026): uncapped, #4FC03172's 2,592 rows "made" 7,470 trades in
    fourteen hours against practice's 138, and the gap read as practice
    failing when it was mostly the 4-a-coin rule — the same rule the research
    applies (coin_slices), so a prediction corrected by an uncapped gap would
    count that rule twice. First come, first served in entry order, exactly
    watcher_replay.cap_per_coin. The runner's other rule (no slice against an
    open one) cannot be applied: a backtest trade does not record its side."""
    from tradingagents import watcher_replay as wr

    out_rooms = []
    tot = {"bt_trades": 0, "bt_wins": 0, "bt_profit": 0.0,
           "pr_trades": 0, "pr_wins": 0, "pr_profit": 0.0, "rows": 0, "bt_uncapped": 0}
    for r in rooms:
        by_slot: dict = {}
        for e in r["exits"]:
            if e["key"]:
                by_slot.setdefault(f"{e['key']}|{e['symbol']}", []).append(e)
        t = {"bt_trades": 0, "bt_wins": 0, "bt_profit": 0.0,
             "pr_trades": 0, "pr_wins": 0, "pr_profit": 0.0, "rows": 0,
             "no_backtest": 0, "after_backtest": 0, "first": None, "last": None,
             "bt_uncapped": 0}
        capped: list = []                  # one slot per row, for cap_per_coin
        for slot, spans in r["intervals"].items():
            rec = _rolling(slot)
            if rec is None:
                t["no_backtest"] += 1
                continue
            end_s = rec["end_ms"] / 1000
            usable = [(a, min(b, end_s)) for a, b in spans if a < end_s]
            if not usable:
                t["after_backtest"] += 1
                continue
            t["rows"] += 1
            mine = []
            for a, b in usable:
                t["first"] = a if t["first"] is None else min(t["first"], a)
                t["last"] = b if t["last"] is None else max(t["last"], b)
                mine += [[en, ex, p, 1.0] for en, ex, p in rec["trades"]
                         if a * 1000 <= en < b * 1000 and ex <= rec["end_ms"]]
                for e in by_slot.get(slot, []):
                    opened = e.get("opened_at") or e["ts"]
                    if a <= opened < b and e["ts"] * 1000 <= rec["end_ms"]:
                        t["pr_trades"] += 1
                        t["pr_wins"] += e["pnl"] > 0
                        t["pr_profit"] += e["pnl"]
            t["bt_uncapped"] += len(mine)
            capped.append({"coin": slot.split("|", 1)[1], "trades": sorted(mine)})
        wr.cap_per_coin(capped, r["cap"])
        for c in capped:
            for _en, _ex, p, _closed in c["trades"]:
                t["bt_trades"] += 1
                t["bt_wins"] += p > 0
                t["bt_profit"] += p
        for k in tot:
            tot[k] += t[k]
        out_rooms.append({"room": r["id"], "name": r["name"], "cap": r["cap"],
                          **_reality_numbers(t)})
    return {"rooms": out_rooms, "all": _reality_numbers(tot),
            "rule": ("the same rows over the same hours: from each switch-on to the end of "
                     "its rebuilt backtest, the backtest's trades against the practice trades")}


def _reality_numbers(t: dict) -> dict:
    """TWO measured numbers carry the correction (the bug hunt, Oct 01, 2026:
    one "dollars short per backtest trade" figure could not tell a rule set
    practice barely trades from one it trades badly):
    * took — of the trades the backtest made, the share practice also made
      (the runner refuses many: the cost check at entry, a stale candle, a
      coin already full);
    * gap — on the trades it did make, how much less practice made per trade
      than the backtest made per trade."""
    n, m = t["bt_trades"], t["pr_trades"]
    out = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()}
    out["bt_winrate"] = round(100 * t["bt_wins"] / n, 1) if n else None
    out["pr_winrate"] = round(100 * t["pr_wins"] / m, 1) if m else None
    out["bt_per_trade"] = round(t["bt_profit"] / n, 4) if n else None
    out["pr_per_trade"] = round(t["pr_profit"] / m, 4) if m else None
    out["took"] = round(m / n, 4) if n else None
    out["gap"] = (round(out["bt_per_trade"] - out["pr_per_trade"], 4)
                  if n and m else None)
    return out


def corrected(profit: float, trades: int, r: dict) -> float | None:
    """A backtest prediction after the reality check: practice makes `took` of
    its trades, each `gap` worse than the backtest's average — so P over T
    trades becomes took x (P - gap x T). Exact on the window it was measured
    on: the backtest's own numbers there come back as practice's."""
    if r.get("took") is None or r.get("gap") is None:
        return None
    return round(float(r["took"]) * (float(profit) - float(r["gap"]) * int(trades)), 2)


# ------------------------------------------------- this month, day by day
def month_so_far(r: dict, now: float) -> dict:
    """A room's practice trades of THIS calendar month: the total and the
    running total day by day, every day from the 1st to today."""
    first = dt.date.fromtimestamp(now).replace(day=1)
    lo = time.mktime(first.timetuple())
    rows = [e for e in r["exits"] if e["ts"] >= lo]
    per: dict = {}
    for e in rows:
        per[rs._day(e["ts"])] = per.get(rs._day(e["ts"]), 0.0) + e["pnl"]
    days, total, d = [], 0.0, first
    last = dt.date.fromtimestamp(now)
    while d <= last:
        total += per.get(d.isoformat(), 0.0)
        days.append({"day": d.isoformat(), "total": round(total, 2)})
        d += dt.timedelta(days=1)
    wins = sum(1 for e in rows if e["pnl"] > 0)
    return {"trades": len(rows), "wins": wins, "losses": len(rows) - wins,
            "profit": round(sum(e["pnl"] for e in rows), 2), "days": days}


# ------------------------------------------------------------ the live copy
def live(now: float | None = None) -> dict:
    """Every practice-side number of Forecast v2, RIGHT NOW."""
    from tradingagents import profiles

    now = time.time() if now is None else float(now)
    t0 = time.perf_counter()
    rooms = [room_data(pid, now) for pid in profiles.ids()]
    on_ids: dict = {}
    for r in rooms:
        for v in r["slots"].values():
            if v.get("id"):
                on_ids.setdefault(v["id"], []).append(r["id"])
    month = dt.datetime.fromtimestamp(now).strftime("%Y-%m")
    return {"at": int(now), "rooms": [{"id": r["id"], "name": r["name"], "retired": r["retired"],
                                       "trades": len(r["exits"]), "unreadable": r["unreadable"],
                                       "month": month_so_far(r, now)}
                                      for r in rooms],
            "on_ids": on_ids, "month": month,
            # NO COINS TO AVOID (operator, Oct 07, 2026: "remove the section
            # coins to avoid i dont need its logic")
            "streaks": practice_streaks(rooms),
            "families": families(rooms), "reality": reality(rooms),
            "defaults": {"win_n": WIN_N, "loss_m": LOSS_M, "thin": THIN},
            "took_ms": round(1000 * (time.perf_counter() - t0))}
