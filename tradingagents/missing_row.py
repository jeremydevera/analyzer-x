"""Why the Backtest list does not hold an id — said from the app's OWN records.

Oct 13, 2026 12:45pm, the operator: *"still not worked / 2WCGB7VB is existing
in practice, but when i search 2WCGB7VB in backtest tab its not existing"*.
#2WCGB7VB is FASTSTOCK 15m prank, TP 1.5% / SL 1.2%: nine rooms switched it on
while the app traded on MEXC, and Gate's 1,038 contracts do not include
FASTSTOCK, so no Gate backtest of it can exist. The tab printed a command to
run instead — for an id the app had printed itself, one tab over
(RCA-2026-10-13-C).

The ids the operator copies come from the app's own screens: the trade
history (`api.row_id_for` over each trade's strategy and coin), the Watcher
panel and the deploy log. So a miss is answered from those same records —
each room's watcher decisions (`strategy_watcher.jsonl`, the id with its coin,
timeframe, signal, TP and SL) and deploy log (`deployments.jsonl`, every
strategy and coin ever switched on, named by the SAME `row_id_for`) — and then
by the first reason that holds, each one CHECKED, never assumed (a review of
the first draft on the operator's 13,141 recorded ids found six sentences that
were false on real rows):

* the exchange does not sell the coin — or sells the same STOCK under its own
  short name (MEXC's ABNBSTOCK is Gate's ABNB; a crypto coin that shares the
  short name, like QNT for QNTSTOCK, is a different asset and never offered);
* the id is the other resolution's (a row switched off loses its v2 mark, so
  the trade history prints its v1 hash) — the same strategy on THIS list is
  named when it is there;
* the strategy itself on this list: TP not bigger than SL; flat rows only; the
  pair never measured; measured and nothing kept; measured and waiting to be
  filed; the cost of a round trip at least half the target (the shard skips
  it, `GATE_BLOCK`); the grid never measures that TP and SL; or measured and
  not kept.

A twin id is only called "the same strategy there" when that row exists. An
exchange list that cannot be read never claims a coin is not sold — unknown is
not "no". Never the 144-second enumerator (`rows_index.resolve_row_code`):
this runs only when an id search found nothing, and its parsed logs are kept
per file until the file changes.
"""
from __future__ import annotations

import contextlib
import json
import re
import threading
from pathlib import Path

from tradingagents import backtest_report as br

_CODE = re.compile(r"^[2-9A-HJ-NP-Z]{8}$")
# A switch-on, as each log spells it: the watcher's "on", the deploy log's
# "deployed" (19,604 "disarmed", 17,042 "deployed", 467 "changed" across the
# 13 rooms on Oct 13, 2026).
_ON = {"on", "deployed"}
# A watcher record that proves the room RAN the row: it switched it on, off,
# or noted it was switched off by hand. A refusal never ran it.
_RAN = {"on", "off", "report"}

_CACHE: dict = {}
_LOCK = threading.Lock()


def _clean(code) -> str:
    return str(code or "").strip().lstrip("#").strip().upper()


def _cached(path: Path, tag: str, build, *extra):
    """`build(path)`, kept until the file (and any `extra` file) changes."""
    stamp = []
    for p in (path, *extra):
        try:
            st = Path(p).stat()
            stamp.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamp.append(None)
    key = (tag, str(path), *[str(e) for e in extra])
    with _LOCK:
        hit = _CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = build(path)
    with _LOCK:
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = (stamp, value)
    return value


def _rooms(home: Path) -> list[tuple[str, str, Path]]:
    """(room id, name as the screens print it, folder) — Main first."""
    from tradingagents import profiles

    out = [(profiles.MAIN, profiles.name_of(profiles.MAIN), Path(home))]
    prof = Path(home) / "profiles"
    if prof.is_dir():
        out += [(p.name, f"#{p.name}", p) for p in sorted(prof.iterdir()) if p.is_dir()]
    return out


def _lines(path: Path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for ln in text.splitlines():
        try:
            got = json.loads(ln)
        except ValueError:
            continue
        if isinstance(got, dict):
            yield got


def _watch_index(path: Path) -> dict:
    """{id: [watcher line, ...]} for one room's decisions log."""
    out: dict = {}
    for e in _lines(path):
        rid = _clean(e.get("id"))
        if rid:
            out.setdefault(rid, []).append(e)
    return out


def _deployed(path: Path) -> dict:
    """{(key, SYMBOL): {"ons": [switch-on times], "last": last change}}."""
    out: dict = {}
    for e in _lines(path):
        key = str(e.get("strategy_key") or "")
        sym = str(e.get("symbol") or "")
        if "|" in key:
            key, sym = key.split("|", 1)
        if not key or not sym or sym == "—":
            continue
        rec = out.setdefault((key, sym), {"ons": [], "last": 0.0})
        at = float(e.get("changed_at") or 0)
        rec["last"] = max(rec["last"], at)
        if str(e.get("action") or "").lower() in _ON:
            rec["ons"].append(at)
    return out


def _proved(code: str, coin, tf, signal, sl, tp, th=None) -> dict | None:
    """The combination behind `code` when these fields hash to it — the
    threshold (in the percent ids carry), resolution and sizing the record
    did not say."""
    try:
        sl, tp = float(sl), float(tp)
        ths = ([float(th)] if th is not None else
               br.threshold_grid() if str(signal or "") in br.THRESH_SIGNALS else [0.0])
    except (TypeError, ValueError):
        return None
    coin = str(coin or "").removesuffix("_USDT")
    for res in ("1m", None):
        for t in ths:
            for sizing in ("flat", "martingale"):
                if br.row_code(coin, str(tf or ""), str(signal or ""), t, sl, tp,
                               sizing, res=res) == code:
                    return {"coin": coin, "tf": str(tf), "signal": str(signal), "th": t,
                            "sl": sl, "tp": tp, "sizing": sizing, "res": res or ""}
    return None


def _settings_of(folder: Path) -> dict:
    """The room's settings file AS IT IS — read, never through
    `load_settings`, which seeds a missing room's file: this runs inside a
    request and must write nothing. `row_id_for` reads only `strategy_res`
    from it (and the runner's flat sizing)."""
    from tradingagents import auto_trader as at

    with contextlib.suppress(Exception):
        at.merge_runtime_specs()          # the watcher's keys, as the runner has them
    try:
        got = json.loads((Path(folder) / "auto_trade.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _id_map(path: Path, room: str, folder: Path) -> dict:
    """{id: [(key, SYMBOL)]} — every strategy and coin of one deploy log,
    named by `api.row_id_for` with the room's own settings: the function the
    trade history prints its strategy ids with."""
    from tradingagents import api

    def build(p):
        settings = _settings_of(folder)
        out: dict = {}
        for key, sym in _cached(p, "deployed", _deployed):
            try:
                rid = api.row_id_for(key, sym, settings)
            except Exception:                                   # noqa: BLE001
                rid = ""
            if rid:
                out.setdefault(rid, []).append((key, sym))
        return out

    return _cached(path, f"ids:{room}", build, folder / "auto_trade.json")


def _default_spec_of(key: str) -> dict:
    from tradingagents import forecast_v2 as f2

    return f2.spec_of(key)


def records(code: str, home: Path, *, id_of=None, spec_of=None) -> list[dict]:
    """Every record in every room that names `code`: room, when, whether the
    room ran it, and the combination it proves."""
    spec_of = spec_of or _default_spec_of
    hits: list = []
    for pid, label, room in _rooms(home):
        for e in _cached(room / "strategy_watcher.jsonl", "watch", _watch_index).get(code, []):
            combo = _proved(code, e.get("coin"), e.get("tf"), e.get("signal"),
                            e.get("sl"), e.get("tp"))
            if combo:
                act = str(e.get("action") or "")
                at = float(e.get("at") or 0)
                hits.append({**combo, "room": label, "at": at, "ran": act in _RAN,
                             "ons": [at] if act in _ON and at else []})
        dlog = room / "deployments.jsonl"
        if id_of is None:
            pairs = _id_map(dlog, pid, room).get(code, [])
        else:
            pairs = [kp for kp in _cached(dlog, "deployed", _deployed)
                     if id_of(kp[0], kp[1], pid) == code]
        deployed = _cached(dlog, "deployed", _deployed) if pairs else {}
        for key, sym in pairs:
            rec = deployed.get((key, sym)) or {"ons": [], "last": 0.0}
            sp = spec_of(key) or {}
            combo = _proved(code, sym, sp.get("tf"), sp.get("signal"), sp.get("sl"),
                            sp.get("tp"), th=sp.get("th"))
            if combo is None and sp.get("tf"):
                # the id came from row_id_for itself: its fields are the spec's
                combo = {"coin": sym.removesuffix("_USDT"), "tf": sp["tf"],
                         "signal": sp.get("signal"), "th": float(sp.get("th") or 0),
                         "sl": float(sp.get("sl") or 0), "tp": float(sp.get("tp") or 0),
                         "sizing": "flat", "res": sp.get("res") or ""}
            if combo is None:
                continue
            if "res" in sp:
                combo["res"] = sp.get("res") or ""
            # ANY deploy-log line means the row was switched on at some point:
            # a "disarmed" or "changed" row was running before it
            hits.append({**combo, "room": label, "at": rec["last"], "ran": True,
                         "ons": list(rec["ons"])})
    return hits


def _rooms_text(rooms: list) -> str:
    return rooms[0] if len(rooms) == 1 else f"{len(rooms)} of your rooms"


def _rows_file(path: Path):
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return []
    return got if isinstance(got, list) else []


def _last_ms(path: Path):
    try:
        return int(json.loads(Path(path).read_text(encoding="utf-8")).get("__last_ms__") or 0) or None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def _pair_state(code: str, combo: dict, store_home: Path | None,
                store_res: str | None) -> tuple[str, dict]:
    """Where THIS combination stands in this store, checked on its pair file."""
    coin, tf = combo["coin"], combo["tf"]
    if store_res and not br.target_over_stop(combo):
        return "tp_not_over_sl", {}
    if store_res and combo.get("sizing", "flat") not in br.sizings_for(store_res):
        return "flat_only", {}
    if store_home is None:
        return "unknown", {}
    rows_path = Path(store_home) / "rows" / f"{coin}-{tf}.json"
    rows = _cached(rows_path, "rows", _rows_file)
    last_ms = _last_ms(Path(store_home) / "state" / f"{coin}-{tf}.json")
    if rows is None and not last_ms:
        return "not_measured", {}
    if not rows:
        return "measured_empty", {"last_ms": last_ms}

    def ids_of(p):
        out = {}
        for r in _rows_file(p) or []:
            try:
                out[br.row_code(coin, tf, r["signal"], r.get("th") or 0, r["sl"],
                                r["tp"], r.get("sizing") or "flat",
                                res=store_res or None)] = r
            except (KeyError, TypeError, ValueError):
                continue
        return out

    found = _cached(rows_path, f"ids:{store_res}", ids_of).get(code)
    if found is not None:
        # 2:1 AFTER FEES (Oct 16, 2026): measured, and never listed — it does
        # not "wait to be added"
        if store_res and not br.pays_two_to_one({**found, "res": store_res}):
            got = br.win_and_loss(found)
            return "not_two_to_one", ({"win": got[0], "loss": got[1]} if got else {})
        return "measured", {}
    sl, tp = float(combo["sl"]), float(combo["tp"])
    in_grid = any(abs(s * 100 - sl) < 1e-6 and abs(t * 100 - tp) < 1e-6
                  for s, t in br.pairs_for(tf))
    if not in_grid:
        return "not_in_grid", {}
    rt = next((float(r["rt"]) for r in rows if r.get("rt") is not None), None)
    if rt is not None and tp > 0 and rt / tp >= br.GATE_BLOCK:
        return "cost_skip", {"rt": rt}
    return "not_kept", {}


def _clause(state: str, info: dict, coin: str, tf: str, combo: dict, now: str) -> str:
    """The reason, in plain words, for one state of one strategy."""
    from tradingagents.positions_view import fmt_when

    if state == "tp_not_over_sl":
        return ("this list shows only strategies whose TP is bigger than their SL, "
                "so it is measured but not listed here")
    if state == "not_two_to_one":
        if "win" in info:
            return (f"this list shows only strategies whose win pays at least two losses "
                    f"after fees; here a win pays +{info['win']:.2f}% and a loss costs "
                    f"-{info['loss']:.2f}% after fees, so it is measured but not listed")
        return ("this list shows only strategies whose win pays at least two losses "
                "after fees, and this one's trading fee could not be read")
    if state == "flat_only":
        return "this list keeps flat rows only, so a martingale id is never on it"
    if state == "not_measured":
        return f"{now} sells {coin}, but the backtest has not measured {coin} {tf} yet"
    if state == "measured_empty":
        through = (f" (candles to {fmt_when(info['last_ms'] / 1000)})"
                   if info.get("last_ms") else "")
        return (f"the backtest measured {coin} {tf}{through} and kept none of its "
                f"strategies")
    if state == "measured":
        return "it is measured and waits to be added to this list"
    if state == "cost_skip":
        return (f"on {now} a round trip on {coin} costs {info['rt']:.2f}%, at least half "
                f"of its {combo['tp']:g}% target, so the backtest skips it")
    if state == "not_in_grid":
        return (f"the backtest does not measure TP {combo['tp']:g}% / "
                f"SL {combo['sl']:g}% on {tf}")
    if state == "not_kept":
        return (f"the backtest measured {coin} {tf} but kept no row for this signal, "
                f"TP and SL")
    return "this list has no row for it"


def explain(code, *, home: Path | None = None, store_home: Path | None = None,
            store_res: str | None = None, listed=None, id_of=None,
            spec_of=None, kind_of=None) -> dict | None:
    """The reason `code` is not in this Backtest list, in plain words — or
    None when none of the app's records names it (the screen keeps its old
    answer for a typo or a foreign id)."""
    from tradingagents import profiles, venue
    from tradingagents.positions_view import fmt_when

    code = _clean(code)
    if not _CODE.match(code):
        return None
    home = Path(home) if home is not None else profiles.HOME
    hits = records(code, home, id_of=id_of, spec_of=spec_of)
    if not hits:
        return None
    c = hits[0]
    coin, tf, signal = c["coin"], c["tf"], c["signal"]
    head = f"#{code} is {coin} {tf} {signal}, TP {c['tp']:g}% / SL {c['sl']:g}%"
    now = venue.name()
    since = venue.since() or 0.0
    old = next((n for v, n in venue.NAMES.items() if v != venue.current()), now)
    ran = [h for h in hits if h["ran"]]
    named = ran or hits
    rooms = sorted({h["room"] for h in named},
                   key=lambda r: (r != profiles.name_of(profiles.MAIN), r))
    last = max(h["at"] for h in named)
    ons = [t for h in ran for t in h["ons"]]
    # THE EXCHANGE IT RAN ON is decided by its switch-ons: a row switched on
    # before the move and switched off after it ran on the old exchange
    # (#2WCGB7VB: on Sep 30 - Oct 06, noted off Oct 10, 2026 4:51am)
    first_run = min(ons) if ons else (min(h["at"] for h in ran) if ran else 0.0)
    then = now if (any(t >= since for t in ons) or not since or
                   (first_run and first_run >= since)) else old
    if ran:
        lead = (f"{_rooms_text(rooms)} switched it on while the app traded on {then}"
                + (f" (last change {fmt_when(last)})" if last else ""))
    else:
        lead = (f"{_rooms_text(rooms)} named it but never switched it on"
                + (f" (last {fmt_when(last)})" if last else ""))
    out = {"id": code, "coin": coin, "tf": tf, "signal": signal, "tp": c["tp"],
           "sl": c["sl"], "rooms": rooms, "last": last, "exchange_then": then}

    def said(reason: str, why: str, **more) -> dict:
        return {**out, **more, "reason": reason, "words": f"{head}: {lead}{why}"}

    names = None
    try:
        names = set((listed or _default_listed)())
    except Exception:                                           # noqa: BLE001
        names = None                      # unknown is not "not sold"
    kind_of = kind_of or venue.kind
    if names is not None and f"{coin}_USDT" not in names:
        # THE SAME STOCK UNDER THE EXCHANGE'S OWN NAME: MEXC's ABNBSTOCK is
        # Gate's ABNB. Only a STOCK of that name: Gate's QNT, DASH, OPEN and C
        # are crypto coins, other assets entirely.
        short = coin[:-5] if coin.endswith("STOCK") else ""
        stock = False
        if short and f"{short}_USDT" in names:
            try:
                stock = kind_of(f"{short}_USDT") != "crypto"
            except Exception:                                   # noqa: BLE001
                stock = False
        if stock:
            tw = {**c, "coin": short, "res": store_res or ""}
            twin = br.row_code(short, tf, signal, c["th"], c["sl"], c["tp"],
                               c.get("sizing") or "flat", res=store_res or None)
            state, info = _pair_state(twin, tw, store_home, store_res)
            if state == "measured":
                return said("listed_as", f"; {now} sells it as {short}, and the same "
                                         f"strategy there is #{twin}.", twin=twin)
            return said("listed_as_absent",
                        f"; {now} sells it as {short}, but the same strategy there, "
                        f"#{twin}, is not on this list either: "
                        f"{_clause(state, info, short, tf, tw, now)}.", twin=twin)
        return said("not_listed", f", and {now} does not sell {coin}, so {now} has no "
                                  f"backtest of it.")
    res = c.get("res") or ""
    if res != (store_res or ""):
        # A SWITCHED-OFF ROW LOSES ITS v2 MARK, so the trade history prints its
        # v1 hash (#2H8Z7JCP: KII 15m stoch14, whose v2 row #WTDBZ4N8 is on
        # this list). Name the same strategy here when it is here.
        tw = {**c, "res": store_res or ""}
        twin = br.row_code(coin, tf, signal, c["th"], c["sl"], c["tp"],
                           c.get("sizing") or "flat", res=store_res or None)
        state, info = _pair_state(twin, tw, store_home, store_res)
        which = "Backtest v2" if res else "Backtest v1"
        if state == "measured":
            return said("other_store", f"; that is its {which} id, and this list holds "
                                       f"the same strategy as #{twin}.", twin=twin)
        return said("other_store_absent",
                    f"; that is its {which} id, and the same strategy on this list, "
                    f"#{twin}, is not here either: {_clause(state, info, coin, tf, tw, now)}.",
                    twin=twin)
    state, info = _pair_state(code, c, store_home, store_res)
    reason = "waiting" if state == "measured" else state
    return said(reason, f"; {_clause(state, info, coin, tf, c, now)}.")


def _default_listed():
    from tradingagents.dataflows import exchange as fx

    return fx.trading_symbols()


def warm(home: Path | None = None) -> int:
    """Read every room's logs into the cache, so the first id search after a
    start answers from memory: cold, the 13 rooms' logs and 14,821 deploy-log
    ids measured 3.9 s on an idle PC and 29 s while the test suite ran — past
    the page's 30 s limit (Oct 13, 2026). Returns how many rooms it read;
    never raises."""
    from tradingagents import profiles

    home = Path(home) if home is not None else profiles.HOME
    n = 0
    for pid, _label, room in _rooms(home):
        try:
            _cached(room / "strategy_watcher.jsonl", "watch", _watch_index)
            _id_map(room / "deployments.jsonl", pid, room)
            n += 1
        except Exception:                                       # noqa: BLE001
            continue
    return n
