"""The ids the app SAVED while the exchange was hashed into them — rewritten once.

From the move to Gate (Oct 10, 2026) to Oct 13, 2026, `row_code` hashed
`|venue=gate` into every id, so every strategy the operator knew got a new
one. The operator: *"i dont understand why did you changed the ids just
because i switched to gate"*, then *"yes"* to taking it out, and *"just to be
clear i dont need the mexc results anymore"*. The ids are plain again
(`backtest_report.row_code`). What the app SAVED in those three days still
holds the old ones, and two of those files are not only read by a person:

* each room's watcher record (`strategy_watcher.json`) — `cooling` keeps a
  switched-off row off for 7 days and `reported` quiets a repeat, both BY ID,
  on every pass. A cooling mark from BEFORE the switch is DROPPED: it was
  MEXC's, it never matched a Gate row while ids carried the exchange, and
  kept it would now hold Gate rows off on MEXC's numbers.
* each room's switched-on rows (`auto_trade.json` `watcher_slots`) — the
  watcher compares their ids with the list's on every switch-on pass.
* each room's decisions (`strategy_watcher.jsonl`) and deploy log — what the
  Watcher panel prints and Backtest a room pairs by id.
* Forecast v2's streaks (`forecast_v2/streaks.npz`) and the Room strategies
  re-test (`backtest/forecast_v2/room_strategies_now.npz`, its
  `[id, coin, tf, signal, th, TP, SL]` list) — ids on the page until the
  next daily run writes plain ones.

An old id is rewritten only when a record PROVES it: the record's own coin,
frame, signal and barriers hash to it with the exchange in. A bare id (a
cooling mark) is rewritten only when some record proved it. Anything else is
left exactly as it is.

It runs from the API's FIRST startup step, before the watcher's thread can
read or write a room's record, and once (`MARK_NAME`); a file that could not
be written leaves no mark, so the next start tries again.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from tradingagents import backtest_report as br

MARK_NAME = "ids_without_exchange.json"
# an id as `row_code` spells it: 8 of its 32 letters, standing alone
_ID = re.compile(r"(?<![A-Z0-9])([2-9A-HJ-NP-Z]{8})(?![A-Z0-9])")


def gate_code(coin, tf, signal, th, sl, tp, sizing="flat", res=None) -> str:
    """The id `row_code` gave this combination from Oct 10 to Oct 13, 2026."""
    return br._code(br._seed(coin, tf, signal, th, sl, tp, sizing, res=res) + "|venue=gate")


def _ths(signal: str, th) -> list:
    if th is not None:
        return [float(th)]
    if signal not in br.THRESH_SIGNALS:
        return [0.0]
    # the decisions log keeps no threshold: try the grid's
    return sorted({0.0} | {float(x) for v in br.THRESHOLDS.values() for x in v})


def plain_for(rid: str, coin, tf, signal, sl, tp, th=None) -> str | None:
    """The plain id of Gate-era `rid`, when this combination hashes to it."""
    coin = str(coin or "").removesuffix("_USDT")
    try:
        sl, tp = float(sl), float(tp)
        ths = _ths(str(signal or ""), th)
    except (TypeError, ValueError):
        return None
    for res in ("1m", None):
        for t in ths:
            for sizing in ("flat", "martingale"):
                if gate_code(coin, str(tf or ""), str(signal or ""), t, sl, tp,
                             sizing, res=res) == rid:
                    return br.row_code(coin, str(tf or ""), str(signal or ""), t, sl, tp,
                                       sizing, res=res)
    return None


def _rooms(home: Path) -> list:
    prof = home / "profiles"
    return [home] + (sorted(p for p in prof.iterdir() if p.is_dir()) if prof.is_dir() else [])


def _lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for ln in text.splitlines():
        try:
            yield json.loads(ln)
        except ValueError:
            continue


def _read_json(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def mapping(home: Path, since: float) -> dict:
    """{Gate-era id: plain id}, each one proved by a record that holds it."""
    out: dict = {}

    def prove(rid, *combo, th=None):
        rid = str(rid or "").lstrip("#")
        if rid and rid not in out:
            new = plain_for(rid, *combo, th=th)
            if new and new != rid:
                out[rid] = new

    for room in _rooms(home):
        for e in _lines(room / "strategy_watcher.jsonl"):
            if float(e.get("at") or 0) >= since:
                prove(e.get("id"), e.get("coin"), e.get("tf"), e.get("signal"),
                      e.get("sl"), e.get("tp"))
        for m in (_read_json(room / "auto_trade.json").get("watcher_slots") or {}).values():
            if isinstance(m, dict):
                prove(m.get("id"), m.get("coin"), m.get("tf"), m.get("signal"),
                      m.get("sl"), m.get("tp"), th=m.get("th"))
    z = _streaks(home)
    if z is not None:
        for i, raw in enumerate(z["id"]):
            prove(raw.decode(), str(z["coin_names"][z["coin"][i]]),
                  str(z["tf_names"][z["tf"][i]]), str(z["signal_names"][z["signal"][i]]),
                  float(z["sl"][i]), float(z["tp"][i]), th=float(z["th"][i]))
    got = _retest_strategies(home)
    for row in (got[1].get("strategies") or []) if got else []:
        if isinstance(row, list) and len(row) >= 7:
            # [id, coin, tf, signal, th, TP, SL] (room_strategies.retested)
            prove(row[0], row[1], row[2], row[3], row[6], row[5], th=row[4])
    return out


def _streaks(home: Path):
    p = home / "forecast_v2" / "streaks.npz"
    if not p.exists():
        return None
    import numpy as np

    with np.load(p, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _swap(text: str, m: dict) -> tuple[str, int]:
    n = 0

    def one(mo):
        nonlocal n
        new = m.get(mo.group(1))
        if new:
            n += 1
            return new
        return mo.group(1)

    return _ID.sub(one, text), n


def _replace(tmp: Path, path: Path) -> None:
    """The swap, retried like Forecast v2's: on Windows a reader holding the
    file open refuses it for milliseconds."""
    from tradingagents import forecast_v2 as f2

    f2.replace_retry(tmp, path)


def _write_text(path: Path, before: str, text: str) -> None:
    """`text` over `path` — only if nobody wrote it since it was read."""
    if path.read_text(encoding="utf-8") != before:
        raise RuntimeError(f"{path.name} changed while its ids were rewritten")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.ids.tmp")
    tmp.write_text(text, encoding="utf-8")
    _replace(tmp, path)


def _room(room: Path, m: dict, since: float, done: dict) -> None:
    st = room / "strategy_watcher.json"
    if st.exists():
        before = st.read_text(encoding="utf-8")
        d = json.loads(before)
        cooling = d.get("cooling") or {}
        kept = {k: v for k, v in cooling.items() if float(v or 0) >= since}
        dropped = len(cooling) - len(kept)
        if dropped:
            d["cooling"] = kept
        text, n = _swap(json.dumps(d), m)
        if n or dropped:
            _write_text(st, before, text)
            done[str(st)] = {"ids": n, "mexc_cooling_dropped": dropped}
    for name in ("strategy_watcher.jsonl", "deployments.jsonl", "auto_trade.json"):
        p = room / name
        if not p.exists():
            continue
        before = p.read_text(encoding="utf-8")
        text, n = _swap(before, m)
        if n:
            if name.endswith(".json"):
                json.loads(text)                    # never write a broken settings file
            _write_text(p, before, text)
            done[str(p)] = {"ids": n}


def _retest_path(home: Path) -> Path:
    return home / "backtest" / "forecast_v2" / "room_strategies_now.npz"


def _retest_strategies(home: Path):
    p = _retest_path(home)
    if not p.exists():
        return None
    import numpy as np

    with np.load(p, allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    return arrays, json.loads(str(arrays["meta"]))


def _rewrite_retest(home: Path, m: dict, done: dict) -> None:
    got = _retest_strategies(home)
    if got is None:
        return
    import numpy as np

    arrays, meta = got
    n = 0
    for row in meta.get("strategies") or []:
        new = m.get(str(row[0]))
        if new:
            row[0] = new
            n += 1
    if not n:
        return
    arrays["meta"] = np.array(json.dumps(meta, allow_nan=False))
    p = _retest_path(home)
    tmp = p.with_name(f"room_strategies_now.{os.getpid()}.ids.tmp.npz")
    np.savez(tmp, **arrays)
    _replace(tmp, p)
    done[str(p)] = {"ids": n}


def _rewrite_streaks(home: Path, m: dict, done: dict) -> None:
    z = _streaks(home)
    if z is None:
        return
    import numpy as np

    ids = [m.get(x.decode(), x.decode()) for x in z["id"]]
    n = sum(1 for a, b in zip(z["id"], ids, strict=True) if a.decode() != b)
    if not n:
        return
    z["id"] = np.array([x.encode() for x in ids], dtype=z["id"].dtype)
    p = home / "forecast_v2" / "streaks.npz"
    tmp = p.with_name(f"streaks.{os.getpid()}.ids.tmp.npz")
    np.savez_compressed(tmp, **z)
    _replace(tmp, p)
    done[str(p)] = {"ids": n}


def migrate(home: Path | None = None, since: float | None = None) -> dict:
    """Rewrite the Gate-era ids saved under `home`, once. Never raises."""
    if home is None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return {"skipped": "under pytest: never the real home"}
        from tradingagents import profiles

        home = profiles.HOME
    home = Path(home)
    mark = home / MARK_NAME
    if mark.exists():
        return {"skipped": f"done before ({mark})"}
    if since is None:
        from tradingagents import venue

        since = venue.since()
    out: dict = {"mapped": 0, "changed": {}, "failed": {}}
    if since:
        try:
            m = mapping(home, float(since))
        except Exception as exc:                                # noqa: BLE001
            out["failed"]["mapping"] = repr(exc)
            return out
        out["mapped"] = len(m)
        for room in _rooms(home):
            try:
                _room(room, m, float(since), out["changed"])
            except Exception as exc:                            # noqa: BLE001
                out["failed"][str(room)] = repr(exc)
        for name, step in (("streaks", _rewrite_streaks), ("retest", _rewrite_retest)):
            try:
                step(home, m, out["changed"])
            except Exception as exc:                            # noqa: BLE001
                out["failed"][name] = repr(exc)
    if not out["failed"]:
        from tradingagents.positions_view import fmt_when

        mark.write_text(json.dumps({**out, "done_at": time.time(),
                                    "done": fmt_when(time.time())}, indent=1),
                        encoding="utf-8")
    return out
