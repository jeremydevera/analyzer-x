"""The room rule sets Forecast v2 predicts, and the options it tests one at a
time — ONE definition, read by the GitHub shard (.github/scripts/
forecast_shard.py) and the merge (forecast_v2_merge.py). (The page's what-if
box read it too until it went on Oct 08, 2026.)

Operator, Oct 01, 2026: *"then predict what combination of room will be
effective, for example: 90% winrate with 40trade, tp is greater than SL will
have profit of x this month"* — and the build prompt's grid and options
(docs/FORECAST-V2.md).

A RULE SET is the watcher's own cfg (watcher_policy), run the way the rooms
run it: RAW (no daily, total or per-coin switch-on limits, no waits) and the
runner's own open-trade limit per coin (`coin_slices`, 4). The switch-off
line is the switch-on line, as the operator set every room.

AN OPTION is something the rooms cannot do today, measured so the operator can
decide whether it is worth building: a row filter (which strategies may be
switched on), a trade filter (which of a switched-on strategy's trades the
runner would take) or the daily loss limit (a day's new trades stop once the
day's closed trades have lost that much). Options are tested ONE AT A TIME on
top of the best base rule sets and the rooms' own rules — never all
combined, which would be a search for luck, not a test of a rule.

Pure: no files, no network, no clock.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

# THE BASE GRID (the build prompt, item D.1) — every combination.
BASE = {"window_days": [15, 30],
        "on_winrate": [70.0, 75.0, 80.0, 85.0, 90.0, 95.0],
        "min_trades": [20, 30, 40, 50],
        # ">" target wider than the stop; "1.5x" / "2x" the target at least
        # that many times the stop; "any" every shape, the stop wider too
        "tp_rule": [">", "1.5x", "2x", "any"],
        "max_sl": [1.0, 1.5, 2.0]}
TOP_FOR_OPTIONS = 20          # options are tested on this many best base sets
COIN_SLICES = 4               # the runner's own open trades per coin (auto_trader.max_slices)

# THE OPTIONS (item D.2): (key, value, plain words). Each is one rule set
# per base set it is added to.
OPTIONS = [("skip_jp", True, "Japanese stocks skipped"),
           ("own_market", True, "stocks only while their own market is open"),
           ("max_cost", 5.0, "cost at most 5% of the target"),
           ("max_cost", 10.0, "cost at most 10% of the target"),
           ("max_cost", 15.0, "cost at most 15% of the target"),
           ("only_tf", "15m", "15m only"), ("only_tf", "30m", "30m only"),
           ("only_tf", "1h", "1h only"), ("only_tf", "4h", "4h only"),
           ("only_tf", "1d", "1d only"),
           ("skip_families", True, "the worst signal families skipped"),
           ("kind", "crypto", "crypto only"), ("kind", "stocks", "stocks only"),
           ("no_ny_morning", True, "no new trades from 9am to noon New York"),
           ("day_loss", 10.0, "no new trades that day after losing 10"),
           ("day_loss", 20.0, "no new trades that day after losing 20"),
           ("day_loss", 40.0, "no new trades that day after losing 40"),
           ("stop_vs_move", True, "no stop smaller than the coin's normal 15-minute move"),
           ("coin_slices", 1, "at most 1 trade per coin"),
           ("coin_slices", 2, "at most 2 trades per coin"),
           ("coin_slices", 3, "at most 3 trades per coin")]
# NO LONGER MEASURED (operator, Oct 07, 2026: "remove the section coins to
# avoid i dont need its logic"): no new rule set carries "skip_coins" and the
# what-if box no longer offers it — but a set measured before still reads as
# what it was, so its label is kept here, and so is its id key below (ID_KEYS
# hashes OPTION_KEYS: dropping the key would give those sets their base's id)
RETIRED_OPTIONS = [("skip_coins", True, "the coins to avoid skipped (removed Oct 07, 2026)")]
_LABELS = OPTIONS + RETIRED_OPTIONS
OPTION_KEYS = ("skip_coins", "skip_jp", "own_market", "max_cost", "only_tf",
               "skip_families", "kind", "no_ny_morning", "day_loss", "stop_vs_move")
# the cost the replay already holds every strategy under: replay_shard only
# writes a strategy whose round trip is under 20% of its target (its gate)
REPLAY_COST_CEILING = 20.0
NY_MORNING = (9 * 60, 12 * 60)          # 9am to noon New York, in minutes


def cfg_of(window_days: int, on_winrate: float, min_trades: int, tp_rule: str,
           max_sl: float, **opts) -> dict:
    """One rule set as the watcher's cfg, raw, the rooms' way."""
    from tradingagents import watcher_research as rs

    c = {**rs.CURRENT, **rs.RAW, "window_days": int(window_days),
         "on_winrate": float(on_winrate), "off_winrate": float(on_winrate),
         "min_trades": int(min_trades), "tp_rule": str(tp_rule), "max_sl": float(max_sl),
         "coin_slices": COIN_SLICES}
    for k, v in opts.items():
        if v is not None and v is not False:
            c[k] = v
    return c


def base_grid() -> list[dict]:
    out = [cfg_of(w, on, mt, tr, sl) for w in BASE["window_days"] for on in BASE["on_winrate"]
           for mt in BASE["min_trades"] for tr in BASE["tp_rule"] for sl in BASE["max_sl"]]
    assert len(out) == 576
    return out


def with_options(bases: list[dict]) -> list[dict]:
    """Every option, one at a time, on top of each of `bases`."""
    out = []
    for b in bases:
        for key, val, _words in OPTIONS:
            c = {**b, key: val}
            if key == "only_tf" and b.get("only_tf"):
                continue
            out.append(c)
    return out


# ----------------------------------------------- short form, for a workflow
def encode(cfg: dict) -> str:
    """A base rule set in one short line — `30:90:90:40:>:2` (window, on,
    off, trades, TP rule, stop cap) — because a GitHub workflow input is a
    string and ten of them is the most a dispatch may carry."""
    w = int(cfg["window_days"])
    j = int(cfg.get("judge_days") or 0)
    # `:j30` only on a room whose switch-off reads another window (Oct 07,
    # 2026), so every line made before it is exactly what it was
    return (f"{w}:{float(cfg['on_winrate']):g}:"
            f"{float(cfg.get('off_winrate', cfg['on_winrate'])):g}:{int(cfg['min_trades'])}:"
            f"{cfg['tp_rule']}:{float(cfg.get('max_sl') or 0):g}"
            + (f":j{j}" if j and j != w else ""))


def decode(text: str) -> dict:
    parts = str(text).strip().split(":")
    w, on, off, mt, tp, sl = parts[:6]
    c = cfg_of(int(w), float(on), int(mt), tp, float(sl))
    c["off_winrate"] = float(off)
    for extra in parts[6:]:
        if extra.startswith("j"):
            c["judge_days"] = int(extra[1:])
    return c


def encode_rooms(rooms: dict) -> str:
    """{room id: cfg} -> `4FC03172=30:70:70:50:>:2;...`."""
    return ";".join(f"{rid}={encode(c)}" for rid, c in rooms.items())


def decode_rooms(text: str) -> dict:
    out = {}
    for part in str(text or "").split(";"):
        if "=" in part:
            rid, enc = part.split("=", 1)
            out[rid.strip()] = decode(enc)
    return out


# ------------------------------------------------------------------ naming
ID_KEYS =("window_days", "on_winrate", "off_winrate", "min_trades", "tp_rule",
           "max_sl", "coin_slices") + OPTION_KEYS + (
    # prompt 4's smallest target (Oct 02, 2026). A key at 0 or missing is left
    # out of the hash, so every id made before it is unchanged
    "min_tp",
    # the switch-off's own window (Oct 07, 2026: the 1-4 day rooms). Hashed
    # only when it differs from window_days, so no id made before it moves
    "judge_days")


def rule_id(cfg: dict) -> str:
    """A stable short id, hashed from the rule set's own values — never a
    position on a page (CLAUDE.md kit H)."""
    key = {k: cfg.get(k) for k in ID_KEYS if cfg.get(k) not in (None, False)}
    for k in ("on_winrate", "off_winrate", "max_sl", "max_cost", "day_loss", "min_tp"):
        if k in key:
            key[k] = float(key[k])
    for k in ("window_days", "min_trades", "coin_slices", "judge_days"):
        if k in key:
            key[k] = int(key[k])
    if "judge_days" in key and key["judge_days"] == int(cfg.get("window_days") or 30):
        del key["judge_days"]            # the same window twice is the one window
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:8].upper()


TP_WORDS = {">": "TP wider than SL", "1.5x": "TP at least 1.5x SL", "2x": "TP at least 2x SL",
            "any": "any TP", ">=": "TP at least SL", "<": "TP narrower than SL",
            "=": "TP equal to SL"}


def words(cfg: dict) -> str:
    """The rule set in the operator's words: "90% wins, 40+ trades in 30
    days, TP wider than SL, stop 2% or tighter"."""
    w = int(cfg["window_days"])
    out = [f"{float(cfg['on_winrate']):g}% wins",
           f"{int(cfg['min_trades'])}+ trades in {w} day{'' if w == 1 else 's'}",
           TP_WORDS.get(str(cfg["tp_rule"]), str(cfg["tp_rule"]))]
    if float(cfg.get("max_sl") or 0) > 0:
        out.append(f"stop {float(cfg['max_sl']):g}% or tighter")
    if float(cfg.get("min_tp") or 0) > 0:
        out.append(f"target {float(cfg['min_tp']):g}% or wider")
    j = int(cfg.get("judge_days") or 0)
    if j and j != w:
        out.append(f"switched off on its last {j} days")
    for key, val, w in _LABELS:
        if key == "coin_slices":
            continue
        if cfg.get(key) == val:
            out.append(w)
    cs = int(cfg.get("coin_slices") or COIN_SLICES)
    if cs != COIN_SLICES:
        out.append(f"at most {cs} trade{'s' if cs != 1 else ''} per coin")
    return ", ".join(out)


def options_of(cfg: dict) -> list[str]:
    """The plain words of the options this rule set carries (empty = base)."""
    return [w for key, val, w in _LABELS if cfg.get(key) == val
            and not (key == "coin_slices" and int(val) == COIN_SLICES)]


def deployable(cfg: dict) -> tuple[bool, str]:
    """Whether a room can run it today with its own switches."""
    extra = [w for key, val, w in _LABELS if cfg.get(key) == val and key != "coin_slices"]
    if str(cfg.get("tp_rule")) in ("1.5x", "2x"):
        # watcher_policy.passes_on knows ">", ">=", "=", "<" and "any" only
        extra.insert(0, TP_WORDS[str(cfg["tp_rule"])])
    from tradingagents import backtest_report as br

    if int(cfg.get("window_days") or 30) not in br.RECENT_WINDOWS + (30,):
        # a room judges on a window every v2 row is measured over: its last
        # 1, 2, 3, 4 or 15 days, or the store's 30 (strategy_watcher.set_cfg)
        extra.insert(0, f"a {int(cfg['window_days'])}-day window")
    if extra:
        return False, "needs a new switch before a room can run it: " + "; ".join(extra)
    if int(cfg.get("coin_slices") or COIN_SLICES) != COIN_SLICES:
        return False, ("the trades-per-coin limit is set per runner "
                       "(partial_max_slices), not per rule set")
    return True, ""


# --------------------------------------------------------------- the rules
def tp_ok(tp, sl, rule: str):
    """The TP-vs-SL shape over arrays (or numbers)."""
    tp, sl = np.asarray(tp, float), np.asarray(sl, float)
    if rule == "any":
        return np.ones(np.shape(tp), bool)
    if rule == "1.5x":
        return tp >= 1.5 * sl - 1e-9
    if rule == "2x":
        return tp >= 2.0 * sl - 1e-9
    if rule == "<":
        return tp < sl
    if rule == "=":
        return np.abs(tp - sl) < 1e-6
    return tp > sl if rule == ">" else tp >= sl


def row_mask(meta: list[dict], cfg: dict, ctx: dict) -> np.ndarray:
    """Which strategies may be switched on at all, by the rule set's
    shape and its row options. `ctx`: families (signal families), move
    (coin -> its normal 15-minute move, %)."""
    from tradingagents import forecast_v2 as f2, room_stats as rs

    n = len(meta)
    tp = np.array([float(m["tp"]) for m in meta]) if n else np.zeros(0)
    sl = np.array([float(m["sl"]) for m in meta]) if n else np.zeros(0)
    ok = tp_ok(tp, sl, str(cfg["tp_rule"]))
    cap = float(cfg.get("max_sl") or 0)
    if cap > 0:
        ok &= sl <= cap + 1e-9
    floor = float(cfg.get("min_tp") or 0)
    if floor > 0:
        ok &= tp >= floor - 1e-9
    if cfg.get("only_tf"):
        ok &= np.array([m["tf"] == cfg["only_tf"] for m in meta], bool)
    if cfg.get("kind") in ("crypto", "stocks"):
        want = cfg["kind"] == "stocks"
        ok &= np.array([rs.is_stock(m["coin"] + "_USDT") == want for m in meta], bool)
    if cfg.get("skip_jp"):
        ok &= np.array([not (rs.is_stock(m["coin"]) and rs.home_market(m["coin"]) == "Tokyo")
                        for m in meta], bool)
    if cfg.get("skip_families"):
        fam = set(ctx.get("families") or ())
        ok &= np.array([f2.family(m["signal"]) not in fam for m in meta], bool)
    if cfg.get("max_cost"):
        ok &= np.array([float(m.get("cost_of_tp") or 0.0) <= float(cfg["max_cost"]) + 1e-9
                        for m in meta], bool)
    if cfg.get("stop_vs_move"):
        move = ctx.get("move") or {}
        ok &= np.array([float(m["sl"]) >= float(move[m["coin"]]) if m["coin"] in move else True
                        for m in meta], bool)
    return ok


# --------------------------------------------------------- time of day
def local_minutes(ms: np.ndarray, zone: str) -> tuple[np.ndarray, np.ndarray]:
    """(minute of the day, weekday Monday=0) of each moment in `zone` — the
    offset taken once per UTC day (a trade within an hour of a clock change
    can be read an hour off; there are two such nights a year)."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    ms = np.asarray(ms, dtype=np.int64)
    if not len(ms):
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    day = ms // 86_400_000
    z = ZoneInfo(zone)
    off = {}
    for d in np.unique(day):
        noon = dt.datetime.fromtimestamp(int(d) * 86400 + 43200, dt.timezone.utc)
        off[int(d)] = int(noon.astimezone(z).utcoffset().total_seconds() * 1000)
    local = ms + np.array([off[int(d)] for d in day], dtype=np.int64)
    minute = (local // 60_000) % 1440
    weekday = ((local // 86_400_000) + 3) % 7          # Jan 01, 1970 was a Thursday
    return minute, weekday


def trade_keep(coin: str, entry_ms: np.ndarray, cfg: dict) -> np.ndarray:
    """Which of a strategy's trades the runner would take under the rule
    set's trade options (own market hours, no New York morning)."""
    from tradingagents import room_stats as rs

    keep = np.ones(len(entry_ms), bool)
    if not len(entry_ms):
        return keep
    if cfg.get("no_ny_morning"):
        m, _w = local_minutes(entry_ms, "America/New_York")
        keep &= ~((m >= NY_MORNING[0]) & (m < NY_MORNING[1]))
    if cfg.get("own_market") and rs.is_stock(coin + "_USDT"):
        market = rs.home_market(coin + "_USDT")
        if market is None:
            keep &= False                       # no market at all: never open
        else:
            zone, (oh, om), (ch, cm) = rs.MARKETS[market]
            m, w = local_minutes(entry_ms, zone)
            keep &= (w < 5) & (m >= oh * 60 + om) & (m < ch * 60 + cm)
    return keep


def day_loss(slots: list[dict], limit: float) -> None:
    """THE DAILY LOSS LIMIT, the way the account loss cap works (auto_trader.
    loss_limit_hit — realized only): a new trade is not taken once the trades
    that CLOSED earlier the same New York day have lost `limit` or more.
    Walks every kept trade in entry order and drops the ones the limit
    refuses, in place."""
    import heapq

    events = []
    for i, s in enumerate(slots):
        for k in range(len(s["trades"])):
            t = s["trades"][k]
            events.append((float(t[0]), i, k, float(t[1]), float(t[2]), bool(t[3])))
    events.sort()
    if not events:
        return
    days_e = _ny_days(np.array([e[0] for e in events], dtype=np.int64))
    days_x = _ny_days(np.array([e[3] for e in events], dtype=np.int64))
    tally: dict = {}
    pending: list = []                       # (exit_ms, day, pnl) of kept trades
    keep = {i: [] for i in range(len(slots))}
    for (entry, i, k, exit_, pnl, closed), d, xd in zip(events, days_e, days_x, strict=True):
        while pending and pending[0][0] <= entry:
            _x, dd, p = heapq.heappop(pending)
            tally[dd] = tally.get(dd, 0.0) + p
        if tally.get(int(d), 0.0) <= -float(limit):
            continue
        keep[i].append(k)
        if closed:
            heapq.heappush(pending, (exit_, int(xd), pnl))
    for i, s in enumerate(slots):
        tr = s["trades"]
        s["trades"] = tr[keep[i]] if hasattr(tr, "shape") else [tr[k] for k in keep[i]]


def _ny_days(ms: np.ndarray) -> np.ndarray:
    """The New York calendar day (days since Jan 01, 1970) of each moment."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    if not len(ms):
        return np.zeros(0, np.int64)
    z = ZoneInfo("America/New_York")
    day = ms // 86_400_000
    off = {}
    for d in np.unique(day):
        noon = dt.datetime.fromtimestamp(int(d) * 86400 + 43200, dt.timezone.utc)
        off[int(d)] = int(noon.astimezone(z).utcoffset().total_seconds() * 1000)
    return (ms + np.array([off[int(d)] for d in day], dtype=np.int64)) // 86_400_000


def finite(x, default=None):
    """A finite float, or `default` (NaN/inf never reach a page)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default
