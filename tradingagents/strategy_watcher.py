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

It only ever touches the slots it armed itself (`settings["watcher_slots"]`).
It never writes "real" into a book, never touches a slot holding "real", never
changes a row the operator armed by hand (those are REPORTED), and never
closes a position: a switched-off practice trade is finished by the runner's
own rule (7897c110). Every decision is a line in the log with the row's id and
the numbers it was judged on.
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
OFF_EVERY_S = 3600
RETRY_S = 30 * 60
MODES = ("off", "preview", "act")
MARGIN = 5.0


# ------------------------------------------------------------------ state
def _read() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    with contextlib.suppress(OSError):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, STATE)


def cfg_of(st: dict | None = None) -> dict:
    st = _read() if st is None else st
    return {**wp.DEFAULTS, **(st.get("cfg") or {})}


def mode_of(st: dict | None = None) -> str:
    st = _read() if st is None else st
    m = st.get("mode") or "act"
    return m if m in MODES else "act"


def set_mode(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    st = _read()
    st["mode"] = mode
    st["why"] = {"off": "switched off", "preview": "preview: decides, changes nothing",
                 "act": "switching practice rows on and off"}[mode]
    _write(st)
    return status()


def set_cfg(partial: dict) -> dict:
    """Change some rules. Every key must be a known rule of the same type."""
    st = _read()
    cfg = dict(st.get("cfg") or {})
    for k, v in (partial or {}).items():
        if k not in wp.DEFAULTS:
            raise ValueError(f"unknown rule {k!r}")
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
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            for d in decisions:
                fh.write(json.dumps(d) + "\n")


def recent(n: int = 50) -> list[dict]:
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        with contextlib.suppress(ValueError):
            out.append(json.loads(line))
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------ seams (tests replace)
def _candidates(cfg: dict, now: float) -> dict:
    from tradingagents import watcher_candidates as wc

    return wc.fresh_candidates(cfg, now=now)


def _fresh_row(meta: dict, now: float, cfg: dict):
    """(row or None, readable) — `readable` False when the pair file could not
    be read at all, which is NOT the same as the row being gone."""
    from tradingagents import watcher_candidates as wc

    rows = wc._pair_rows(meta["coin"], meta["tf"])
    if not rows:
        return None, False
    return wc.fresh_row(meta["id"], meta["coin"], meta["tf"], meta, now=now, cfg=cfg), True


def _practice(slots: dict, now: float) -> dict:
    from tradingagents import watcher_results as wres

    return wres.practice(slots, now=now)


def _register(key: str, spec: dict) -> str:
    from tradingagents import auto_trader as at
    from tradingagents import runtime_specs as rs

    got = rs.register(key, spec)
    at.merge_runtime_specs()            # this process trades it too (edge_check)
    return got


def _edge(key: str, symbol: str) -> dict:
    from tradingagents import auto_trader as at

    try:
        return at.edge_check(key, symbol, MARGIN)
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


def _arm(s: dict, key: str, symbol: str, meta: dict) -> dict:
    slot = f"{key}|{symbol}"
    s["strategies"] = sorted(set(s.get("strategies") or []) | {key})
    coins = dict(s.get("strategy_coins") or {})
    coins[key] = sorted(set(coins.get(key) or []) | {symbol})
    s["strategy_coins"] = coins
    books = dict(s.get("strategy_books") or {})
    books[slot] = ["paper"]
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
    left = [c for c in (coins.get(key) or []) if c != symbol]
    if left:
        coins[key] = left
    else:
        coins.pop(key, None)
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


def _off_pass(now: float, cfg: dict, st: dict, act: bool, out: list) -> list[str]:
    from tradingagents import auto_trader as at

    settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    drop = []
    for slot, meta in sorted(ws.items()):
        if "real" in at.book_names(settings, *slot.split("|", 1)):
            continue                       # never touch a slot holding real money
        fresh, readable = _fresh_row(meta, now, cfg)
        if not readable:
            out.append(_d(now, st, "report", meta, "its backtest file could not be "
                          "read this hour — kept, checked again next hour"))
            continue
        why = wp.judge({"id": meta["id"]}, fresh, cfg)
        if why:
            drop.append(slot)
            st.setdefault("cooling", {})[meta["id"]] = now
            out.append(_d(now, st, "off", meta, why, fresh))
    # the operator's own practice rows: judged the same way, only REPORTED
    seen = st.setdefault("reported", {})
    import datetime as _dt

    day = str(_dt.date.fromtimestamp(now))           # a key, never printed
    for key, sym in _hand_slots(settings):
        # judged on the Backtest v2 file, so only rows armed FROM v2
        if (settings.get("strategy_res") or {}).get(f"{key}|{sym}") != "1m":
            continue
        meta = _meta_of_key(key, sym)
        if not meta:
            continue
        meta = {**meta, "id": _row_id(settings, key, sym, meta)}
        if seen.get(meta["id"]) == day:
            continue
        fresh, readable = _fresh_row(meta, now, cfg)
        if not readable:
            continue
        why = wp.judge({"id": meta["id"]}, fresh, cfg)
        if why:
            seen[meta["id"]] = day
            out.append(_d(now, st, "report", meta,
                          f"one of YOUR practice rows would be switched off: {why}", fresh))
    if act and drop:
        def mutate(s):
            for slot in drop:
                _disarm(s, slot)
            return s
        if not _write_settings(mutate):
            out.append({"at": now, "mode": mode_of(st), "action": "refused",
                        "id": "", "why": "the settings file kept changing — nothing "
                        "switched off this hour, trying again next hour"})
    return drop


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
    rows = [r for r in got["rows"] if not wp.passes_on(r, cfg)]
    picks = wp.pick(rows, running, cooling, now, cfg)
    arm = []
    for p in picks:
        r = p["row"]
        sym = f"{r['coin']}_USDT"
        meta = {"id": r["id"], "coin": r["coin"], "tf": r["tf"], "signal": r["signal"],
                "th": r["th"], "sl": r["sl"], "tp": r["tp"], "on_at": now}
        try:
            key, spec = sk.key_for(r), sk.spec_for(r)
        except ValueError as exc:
            out.append(_d(now, st, "refused", meta, str(exc), r))
            continue
        if _sig_of(key) != r["signal"]:
            out.append(_d(now, st, "refused", meta, f"its key {key} would read as "
                          f"{_sig_of(key)!r}, not {r['signal']!r}", r))
            continue
        slot = f"{key}|{sym}"
        mine_already = slot in ws
        by_hand = (slot in (settings.get("strategy_books") or {})
                   or sym in ((settings.get("strategy_coins") or {}).get(key) or []))
        if by_hand and not mine_already:
            out.append(_d(now, st, "refused", meta, "you already run this row "
                          "yourself — the watcher leaves it alone", r))
            continue
        try:
            _register(key, spec)
        except ValueError as exc:
            out.append(_d(now, st, "refused", meta, f"its recipe clashes: {exc}", r))
            continue
        edge = _edge(key, sym)
        if edge.get("verdict") != "ok":
            out.append(_d(now, st, "refused", meta, f"the cost check said "
                          f"{edge.get('verdict')}: {edge.get('reason', '')[:160]}", r))
            continue
        out.append(_d(now, st, "on", meta, p["why"], r))
        arm.append((key, sym, meta))
        time.sleep(0.5 if act else 0)    # edge_check reads the live book
    if act and arm:
        def mutate(s):
            for key, sym, meta in arm:
                _arm(s, key, sym, meta)
            return s
        if not _write_settings(mutate):
            return "the settings file kept changing — nothing switched on, trying again"
    st["last_candidates"] = got.get("why", "")
    return ""


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
        _off_pass(now, cfg, st, act, out)
        st["last_off_pass"] = now
    due_on = now - float(st.get("last_on_pass") or 0) >= ON_EVERY_S
    tried = now - float(st.get("last_on_try") or 0) >= RETRY_S
    if due_on and tried:
        st["last_on_try"] = now
        wait = _on_pass(now, cfg, st, act, out)
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
                nt.record("trade", f"Watcher{' (preview)' if not act else ''}: "
                          f"{n_on} switched on, {n_off} switched off", ok=True,
                          detail="; ".join(d["why"] for d in out[:6]))
    _write(st)
    return {"decisions": out, "why": st.get("why", "")}


def _when(ts: float) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(ts)


def status() -> dict:
    from tradingagents import auto_trader as at

    st = _read()
    settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    return {"mode": mode_of(st), "cfg": cfg_of(st), "why": st.get("why", ""),
            "last_on_pass": st.get("last_on_pass"), "last_off_pass": st.get("last_off_pass"),
            "next_on_pass": (float(st["last_on_pass"]) + ON_EVERY_S) if st.get("last_on_pass") else None,
            "running": len(ws), "slots": [{"slot": k, **v} for k, v in sorted(ws.items())],
            "cooling": len(st.get("cooling") or {}), "decisions": recent(50)}


_LAST_SAID = {"why": ""}


def tick() -> dict:
    """`consider()`, logged when its answer changes. NEVER under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"decisions": [], "why": "never under a test run"}
    got = consider()
    why = str(got.get("why") or "")
    if why and why != _LAST_SAID["why"]:
        print(f"[watcher] {why}", flush=True)
    _LAST_SAID["why"] = why
    return got
