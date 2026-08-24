"""Live runner for the validated SPX500 perpetual strategy.

    Strategy (from 51,192 backtested combinations, validated on 300 start paths):
        always-long SPX500_USDT, take-profit +2% as a LIMIT order,
        stop-loss -10%, re-enter after each exit, 3x leverage, never short.

    Measured on 188 days of 5-minute bars: +47.6% on margin, 15 trades,
    87% win rate, worst mark-to-market equity 62.5% of margin.

WHAT THIS IS NOT: an edge. Roughly 11 of the 14.7 percentage points of unlevered
return were the index rising over the sample; the barriers added ~3. The sample
was a single 188-day uptrend, funding costs are NOT in the backtest, and the
take-profit advantage disappears past ~25bp of slippage. Size accordingly.

SAFETY MODEL — three independent gates, all must open before money moves:
    1. ``--live`` on the command line
    2. ``SPX_BOT_ARMED=yes`` in the environment
    3. no kill file at the configured path
Default with no flags is a dry run that prints what it would do.

Usage:
    python spx_bot.py preflight                 # what can this key actually do
    python spx_bot.py run                       # dry run, no orders
    python spx_bot.py run --live                # needs SPX_BOT_ARMED=yes too
    python spx_bot.py status                    # position + ledger
    python spx_bot.py flat --live               # close everything now
    python spx_bot.py watchdog --live           # run, and restart after a crash
    python spx_bot.py reset-losses              # clear the losing-trade counter
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field, replace as dataclasses_replace
from datetime import datetime, timezone
from pathlib import Path

from tradingagents.dataflows import mexc_futures as fx

LOG = logging.getLogger("spx_bot")

SYMBOL = "SPX500_USDT"
STATE_DIR = Path(os.path.expanduser("~/.tradingagents/spx_bot"))
STATE_PATH = STATE_DIR / "state.json"
LEDGER_PATH = STATE_DIR / "ledger.jsonl"
KILL_PATH = STATE_DIR / "KILL"
PID_PATH = STATE_DIR / "bot.pid"
LOG_PATH = STATE_DIR / "bot.log"
HEARTBEAT_PATH = STATE_DIR / "heartbeat"


@dataclass
class Config:
    """Every risk limit in one place. Edit here, not in the logic below."""
    symbol: str = SYMBOL
    strategy: str = "barrier_harvest"
    timeframe: str = "Min5"           # the bars this strategy is measured on;
                                      # poll_seconds is derived from it
    # Several (timeframe, strategy) lanes may be selected. Only ONE can place
    # orders per symbol, and that is the exchange's rule rather than a shortcut
    # here. Established against the live API:
    #   * same settings          -> the orders merge into one position, which
    #                               carries a single stop
    #   * different leverage     -> "code 2021: Order leverage is inconsistent
    #                               with the existing position leverage"
    #   * isolated plus cross    -> "code 2027: Cross and isolated position of
    #                               the same direction are alternative"
    # So two lanes cannot each hold their own barriers; one lane's stop would
    # close part of the other's position. The remaining lanes are evaluated and
    # logged as signals. Running lanes in parallel for real needs one symbol
    # each — MEXC keeps positions on different contracts separate.
    lanes: list = field(default_factory=list)
    leverage: int = 3                 # 3x was the cap that survived the worst
                                      # drawdown in the sample; 8x liquidated
    margin_usd: float = 115.0         # ~PHP 7,000
    take_profit_pct: float = 2.0
    stop_loss_pct: float = 10.0
    # --- circuit breakers ---
    max_notional_usd: float = 400.0   # refuse to size beyond this
    daily_loss_limit_usd: float = 25.0    # halt for the day past this
    max_losses: int = 0               # halt after this many losing trades in
                                      # total; 0 disables it. Counts losses
                                      # ever, not per day, and only a manual
                                      # reset clears it — a limit that resets
                                      # itself overnight is not a limit.
    max_open_positions: int = 1
    poll_seconds: int = 0             # 0 = derive from the timeframe. Polling
                                      # faster than the bar cannot change the
                                      # decision; slower risks missing a bar.
    min_equity_usd: float = 20.0      # halt if the wallet falls below this

    @classmethod
    def load(cls) -> Config:
        p = STATE_DIR / "config.json"
        if p.exists():
            try:
                return cls(**{**asdict(cls()), **json.loads(p.read_text())})
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                LOG.warning("bad config, using defaults: %s", exc)
        return cls()

    def active_lanes(self) -> list:
        """Normalised lanes, primary first. Falls back to the single pairing."""
        out = []
        for lane in (self.lanes or []):
            tf = str(lane.get("timeframe") or "").strip()
            st = str(lane.get("strategy") or "").strip()
            if tf and st:
                out.append({"timeframe": tf, "strategy": st})
        if not out:
            out = [{"timeframe": self.timeframe, "strategy": self.strategy}]
        # de-duplicate while keeping order
        seen, uniq = set(), []
        for lane in out:
            key = (lane["timeframe"], lane["strategy"])
            if key not in seen:
                seen.add(key)
                uniq.append(lane)
        return uniq

    def primary_lane(self) -> dict:
        """The one lane allowed to place orders."""
        return self.active_lanes()[0]

    @property
    def poll(self) -> int:
        """Effective poll interval: the explicit override, or half a bar."""
        if self.poll_seconds and self.poll_seconds > 0:
            return int(self.poll_seconds)
        from tradingagents.strategies import poll_seconds_for
        # The finest lane sets the cadence: polling slower than its bars would
        # miss them entirely.
        return min(poll_seconds_for(l["timeframe"]) for l in self.active_lanes())

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "config.json").write_text(json.dumps(asdict(self), indent=2))


# --------------------------------------------------------------- state
def _read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"position": None, "day": None, "realised_today": 0.0,
                "losses": 0, "halted": False, "halt_reason": ""}


def _write_state(s: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s, indent=2))


def _append_ledger(entry: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _touch_heartbeat() -> None:
    """Record that a cycle completed, so anything watching can tell the
    difference between "running" and "the process died with a position open"."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(
            datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except OSError:
        pass


def running_pid() -> int | None:
    """The live runner's pid, or None. Verifies the process actually exists —
    a stale pid file after a crash would otherwise read as "running"."""
    try:
        pid = int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)          # signal 0 only checks for existence
    except (OSError, ProcessLookupError):
        return None
    return pid


def health() -> dict:
    """Everything a dashboard needs to say whether this bot is alive."""
    pid = running_pid()
    beat = None
    age = None
    try:
        beat = HEARTBEAT_PATH.read_text().strip()
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(beat)).total_seconds()
    except (OSError, ValueError):
        pass
    st = _read_state()
    cfg = Config.load()
    stale = age is not None and age > max(180, cfg.poll * 3)
    return {"running": pid is not None, "pid": pid, "last_cycle": beat,
            "seconds_since_cycle": age, "stale": stale,
            "position_open": bool(st.get("position")),
            "halted": bool(st.get("halted")),
            "halt_reason": st.get("halt_reason", ""),
            "losses": int(st.get("losses", 0) or 0),
            "orphaned": pid is None and bool(st.get("position")),
            "log_path": str(LOG_PATH)}


# The runner implements ONE execution model: enter long, rest a take-profit and a
# stop on the exchange, repeat. Four of the six registered strategies instead
# emit a per-bar target exposure and need a rebalancing engine that does not
# exist yet. Silently running barrier_harvest when the operator selected
# vol_target is worse than refusing: they would believe they were running
# something they were not.
RUNNABLE_STRATEGIES = ("barrier_harvest", "buy_hold")

# As an ENTRY GATE every strategy is runnable: its signal only decides whether to
# open one bracketed trade, and the barriers bound the turnover. That is a
# different thing from the exposure form the backtest measures — no sizing, no
# scaling out — so the backtested figures do not transfer, and anything reporting
# a gate result has to say so.
GATE_STRATEGIES = ("barrier_harvest", "buy_hold", "trend_filter", "trend50",
                         "session_long", "ladder_dca", "vol_target")


def lane_may_gate(key: str) -> bool:
    return key in GATE_STRATEGIES


# Liquidation happens before the stop can fire once the stop sits further away
# than the margin can absorb. At 200x that is a 0.5% move against a 10% stop —
# the stop is decoration and the real exit is the venue taking the position. MEXC
# also holds a maintenance margin, so liquidation arrives slightly EARLIER than
# 100/leverage; the margin of safety below accounts for that.
LIQUIDATION_SAFETY = 0.7        # the stop must sit inside 70% of the wipe-out move


def stop_is_reachable(leverage: int, stop_loss_pct: float,
                     symbol: str | None = None) -> tuple[bool, str]:
    """Can this stop actually fire before the position is liquidated?

    Uses the exchange's published maintenance margin rather than 100/leverage. The
    naive figure overstates the survivable move fivefold at 200x — 0.50% against
    MEXC's actual 0.10% — because the venue keeps a maintenance margin back.
    """
    if leverage <= 1 or stop_loss_pct <= 0:
        return True, ""
    wipeout = fx.liquidation_move_pct(symbol or SYMBOL, leverage)
    if wipeout <= 0:
        return False, (
            f"{leverage}x is not usable on {symbol or SYMBOL}: the maintenance "
            f"margin alone exhausts the position, so it is liquidated on entry.")
    if stop_loss_pct >= wipeout:
        return False, (
            f"a {stop_loss_pct:.1f}% stop at {leverage}x can never fire: the "
            f"margin is gone after about {wipeout:.2f}%, so the venue liquidates "
            f"the position first and the loss is the whole margin. Use leverage "
            f"below {100.0 / stop_loss_pct:.0f}x, or a stop under "
            f"{wipeout * LIQUIDATION_SAFETY:.2f}%.")
    if stop_loss_pct > wipeout * LIQUIDATION_SAFETY:
        return True, (
            f"a {stop_loss_pct:.1f}% stop at {leverage}x sits close to the "
            f"{wipeout:.2f}% wipe-out point; maintenance margin means liquidation "
            f"can arrive first. Consider a stop under "
            f"{wipeout * LIQUIDATION_SAFETY:.2f}%.")
    return True, ""


def strategy_is_runnable(key: str) -> tuple[bool, str]:
    if key in RUNNABLE_STRATEGIES:
        return True, ""
    return False, (
        f"{key!r} sets a target exposure each bar and needs a rebalancing "
        f"engine this runner does not have. Runnable today: "
        f"{', '.join(RUNNABLE_STRATEGIES)}.")


# --------------------------------------------------------------- gates
def gates_open(live: bool, *, closing: bool = False) -> tuple[bool, str]:
    """All three safety gates. Returns (may_trade_live, reason_if_not).

    ``closing=True`` ignores the kill file. The kill switch exists to stop the
    bot TAKING risk; if it also blocked flattening it would trap the operator in
    the position they pulled the switch to escape. Opening is gated, closing is
    always allowed.
    """
    if not live:
        return False, "dry run (no --live)"
    if os.getenv("SPX_BOT_ARMED", "").strip().lower() not in ("yes", "true", "1"):
        return False, "SPX_BOT_ARMED is not set to yes"
    if KILL_PATH.exists() and not closing:
        return False, f"kill file present at {KILL_PATH}"
    return True, ""


def use_dry_book() -> None:
    """Point state and ledger at a separate dry-run book.

    Dry runs used to write the SAME ``state.json`` the live bot trades from, so a
    simulated cycle planted a phantom position that a live bot would later send a
    real close-long for, and a simulated ``flat`` erased a real position from the
    live book while the position itself stayed open. A simulation must keep its
    own books.
    """
    global STATE_PATH, LEDGER_PATH
    STATE_PATH = STATE_DIR / "state.dry.json"
    LEDGER_PATH = STATE_DIR / "ledger.dry.jsonl"


def check_breakers(cfg: Config, state: dict) -> tuple[bool, str]:
    """Circuit breakers evaluated before every action."""
    if state.get("halted"):
        return False, f"halted: {state.get('halt_reason', '')}"
    if state.get("day") == _today() and \
            state.get("realised_today", 0.0) <= -abs(cfg.daily_loss_limit_usd):
        return False, (f"daily loss limit hit "
                       f"({state['realised_today']:+.2f} USD)")
    if cfg.max_losses > 0 and state.get("losses", 0) >= cfg.max_losses:
        return False, (f"loss limit reached: {state['losses']} losing trades "
                       f"(limit {cfg.max_losses}) — reset it to trade again")
    return True, ""


# --------------------------------------------------------------- actions
def do_preflight(cfg: Config) -> int:
    print(f"preflight for {cfg.symbol}\n")
    rep = fx.preflight(cfg.symbol)
    for k in ("credentials", "read_assets", "read_positions",
              "order_permission", "equity_usdt"):
        print(f"  {k:<18}{rep.get(k)}")
    for n in rep.get("notes", []):
        print(f"  note: {n}")
    spec = fx.contract_spec(cfg.symbol)
    px = fx.last_price(cfg.symbol)
    n = fx.contracts_for(cfg.symbol, cfg.margin_usd * cfg.leverage, px)
    print(f"\n  price              {px:,.2f}")
    print(f"  contractSize       {spec.get('contractSize')}")
    print(f"  maxLeverage        {spec.get('maxLeverage')}")
    print(f"  planned notional   ${cfg.margin_usd * cfg.leverage:,.2f} "
          f"({cfg.leverage}x on ${cfg.margin_usd:,.2f})")
    print(f"  -> contracts       {n}")
    # Use preflight's own verdict. Recomputing it here dropped read_positions
    # and edge_blocked, so a key that could not read positions — precisely the
    # key that cannot reconcile after a timeout — reported ready.
    ok = rep.get("ready")
    print(f"\n  VERDICT: {'ready (still dry-run by default)' if ok else 'NOT ready'}")
    return 0 if ok else 1


def do_status(cfg: Config) -> int:
    s = _read_state()
    # Every lane is runnable as a gate, so the old runnable/fit verdicts no longer
    # describe anything: printing "NOT RUNNABLE" for a working gate lane was a lie.
    _owner = (s.get("position") or {}).get("lane")
    for i, lane in enumerate(_lane_order(cfg)):
        owns = _owner and _owner.get("strategy") == lane["strategy"] \
            and _owner.get("timeframe") == lane["timeframe"]
        print(f"lane {i}   : {lane['strategy']} on {lane['timeframe']} bars"
              + ("  <- HOLDS THE POSITION" if owns else ""))
    print(f"poll     : every {cfg.poll}s (half a bar of the finest lane)")
    print(f"position : {s.get('position')}")
    print(f"day      : {s.get('day')}  realised today "
          f"{s.get('realised_today', 0.0):+.2f} USD")
    print(f"losses   : {s.get('losses', 0)}"
          + (f" of {cfg.max_losses} (limit)" if cfg.max_losses else " (no limit set)"))
    print(f"halted   : {s.get('halted')} {s.get('halt_reason', '')}")
    print(f"kill file: {'PRESENT' if KILL_PATH.exists() else 'absent'} ({KILL_PATH})")
    h = health()
    print(f"running  : {h['running']}" + (f" (pid {h['pid']})" if h['pid'] else ""))
    if h["last_cycle"]:
        print(f"last cycle {h['last_cycle']}"
              + ("  ** STALE **" if h["stale"] else ""))
    if h["orphaned"]:
        print("** ORPHANED POSITION: the runner is not alive and a position is "
              "open. Its exchange stop still applies; close with "
              "`python spx_bot.py flat --live` **")
    if fx.has_credentials():
        try:
            print(f"wallet   : {fx.usdt_equity():.2f} USDT")
            for p in fx.open_positions(cfg.symbol):
                print(f"exchange : {p.get('positionType')} vol={p.get('holdVol')} "
                      f"entry={p.get('holdAvgPrice')} pnl={p.get('realised')}")
        except fx.MexcFuturesError as exc:
            print(f"exchange : unavailable ({exc})")
    return 0


def do_flat(cfg: Config, live: bool) -> int:
    """Close any open position immediately (market)."""
    may, why = gates_open(live, closing=True)
    dry = not may
    if dry:
        print(f"DRY RUN ({why}) — NOTHING WILL BE SENT TO THE EXCHANGE")
    try:
        pos = fx.open_positions(cfg.symbol)
    except fx.MexcFuturesError as exc:
        print(f"cannot read positions: {exc}")
        return 1
    if not pos:
        print("no open position")
        return 0
    for p in pos:
        vol = int(float(p.get("holdVol") or 0))
        if vol <= 0:
            continue
        r = fx.close_long(cfg.symbol, vol, leverage=cfg.leverage, dry_run=dry)
        print(f"close {vol} contracts -> {r}")
        _append_ledger({"action": "flat", "vol": vol, "dry_run": dry})
    if dry:
        print("simulated only — the position is STILL OPEN on the exchange")
        return 0
    s = _read_state(); s["position"] = None; _write_state(s)
    return 0


def _snap(cfg: Config, target: float) -> float:
    """Round a price to the contract's own tick.

    ``round(target, 1)`` returned 0.0 for every contract priced under $0.05 —
    and the Trade tab offers ~920 of them — which made the take-profit raise on
    EVERY cycle, always after the live entry had already gone out.
    """
    try:
        unit = float(fx.contract_spec(cfg.symbol).get("priceUnit") or 0)
    except (fx.MexcFuturesError, TypeError, ValueError, KeyError):
        unit = 0.0
    if unit > 0:
        snapped = round(round(target / unit) * unit, 10)
        if snapped > 0:
            return snapped
    return target


def _snap_tp_price(cfg: Config, px: float) -> float:
    return _snap(cfg, px * (1 + cfg.take_profit_pct / 100))


def _snap_sl_price(cfg: Config, px: float) -> float:
    return _snap(cfg, px * (1 - cfg.stop_loss_pct / 100))


def _attach_bracket(cfg: Config, vol: int, entry_px: float,
                    dry: bool) -> dict:
    """Rest the take-profit AND the stop on MEXC, then prove they are there.

    One position-scoped record rather than two independent close orders: two
    full-size orders are not a linked pair, so after one fills the other stays
    live and can flip the account short.

    Returns a dict describing what actually happened. Callers must treat
    ``protected=False`` as "this position has no exchange-side stop", because
    MEXC accepts requests that never become active — two of three historical
    records on this account finished with errorCode 8912 and vol 0.
    """
    sl_price = _snap_sl_price(cfg, entry_px)
    # buy_hold is a bracket with no target: enter once, hold, keep the stop.
    tp_price = (None if cfg.strategy == "buy_hold"
                else _snap_tp_price(cfg, entry_px))
    if dry:
        payload = fx.place_position_stop(
            cfg.symbol, 0, vol, stop_loss_price=sl_price, dry_run=True)
        return {"protected": False, "dry_run": True, "tp": tp_price,
                "sl": sl_price, "request": payload.get("request")}
    live = [p for p in fx.open_positions(cfg.symbol)
            if int(float(p.get("holdVol") or 0)) > 0]
    if not live:
        raise fx.MexcFuturesError(
            "the entry order left no open position to attach a stop to")
    pid = int(live[0]["positionId"])
    # The two barriers live in different places, because MEXC only supports one
    # of them in each: the stop goes on the position record (survives this
    # process dying), and the target has to be a resting limit close order (a
    # LIMIT take-profit on the position record is accepted and silently
    # attaches nothing). A market target would cost ~25bp, which is the entire
    # measured edge, so it must be a limit.
    resp = fx.place_position_stop(cfg.symbol, pid, vol,
                                  stop_loss_price=sl_price, dry_run=False)
    tp_resp = None
    if tp_price:
        tp_resp = fx.limit_close_long(cfg.symbol, vol, tp_price,
                                      leverage=cfg.leverage, dry_run=False)
    check = fx.verify_bracket(cfg.symbol, pid, tp_price)
    return {"protected": check["protected"], "dry_run": False,
            "stop_active": check["stop_active"],
            "target_resting": check["target_resting"],
            "position_id": pid, "tp": tp_price, "sl": sl_price,
            "error_codes": check["stop_error_codes"],
            "response": resp, "tp_response": tp_resp}


def _lane_order(cfg: Config) -> list:
    """Lanes in race order: finest bars first.

    'Whichever signals first' needs a deterministic tie-break, because a single
    poll can find several lanes ready at once. The finest timeframe wins: its bar
    closed most recently, so in real time its signal did arrive first.
    """
    from tradingagents.strategies import TIMEFRAME_SECONDS
    return sorted(cfg.active_lanes(),
                  key=lambda l: TIMEFRAME_SECONDS.get(l["timeframe"], 300))


# A lane that means "enter once" must decline afterwards. Without this, buy_hold
# in a race re-entered every time a stop closed it, which is "hold until stopped,
# then buy again" — a different strategy wearing the same name.
ONE_SHOT_STRATEGIES = ("buy_hold",)


def lane_key(lane: dict) -> str:
    return f"{lane['strategy']}@{lane['timeframe']}"


def pick_lane(cfg: Config, state: dict | None = None) -> tuple:
    """Which lane gets the position? Returns (lane, reason) or (None, why not).

    Each lane is asked on ITS OWN bars whether it wants to be long. The first one
    that says yes takes the trade and owns it until the position closes — MEXC
    allows a single position per symbol, so ownership has to be exclusive rather
    than shared.
    """
    from tradingagents.strategies import gate_reason, wants_long
    used = set((state or {}).get("lanes_used") or [])
    misses = []
    for lane in _lane_order(cfg):
        if not lane_may_gate(lane["strategy"]):
            misses.append(f"{lane['strategy']}/{lane['timeframe']}: not runnable")
            continue
        if lane["strategy"] in ONE_SHOT_STRATEGIES and lane_key(lane) in used:
            misses.append(f"{lane['strategy']}/{lane['timeframe']}: already had "
                          f"its one entry")
            continue
        try:
            candles = fx.klines(cfg.symbol, lane["timeframe"], 400)
        except fx.MexcFuturesError as exc:
            misses.append(f"{lane['strategy']}/{lane['timeframe']}: no bars ({exc})")
            continue
        if wants_long(lane["strategy"], candles):
            return lane, gate_reason(lane["strategy"], candles)
        misses.append(f"{lane['strategy']}/{lane['timeframe']}: "
                      f"{gate_reason(lane['strategy'], candles)}")
    return None, "; ".join(misses) or "no lanes configured"


def _reconcile(cfg: Config, s: dict, px: float, dry: bool) -> bool:
    """Ask MEXC what we actually hold, and believe THAT.

    Without this the bot reads its own notes. Those notes go stale the instant
    the exchange closes a position on its own — which is the normal case, because
    the take-profit rests on MEXC and fires without telling anyone. The bot then
    holds a belief ("I am long") that nothing will ever contradict, so it never
    trades again: 1 trade instead of the backtest's 15.

    Returns True when the caller should carry on to the position branch, False
    when this cycle is finished (position closed and booked, or the exchange
    could not be reached).
    """
    pos = s.get("position")
    if not pos or dry:
        # A dry run has no exchange position to reconcile against; its book is
        # a simulation and must not be "corrected" by live data.
        return True
    try:
        live = [p for p in fx.open_positions(cfg.symbol)
                if int(float(p.get("holdVol") or 0)) > 0]
    except fx.MexcFuturesError as exc:
        # Never assume "closed" from a failed read: that would book a phantom
        # profit and then re-enter on top of a position that is still open.
        LOG.warning("cannot reconcile with the exchange this cycle: %s", exc)
        return False
    if live:
        held = int(float(live[0].get("holdVol") or 0))
        if held != int(pos.get("vol") or 0):
            LOG.warning("size drift: notes say %s, exchange holds %s — "
                        "trusting the exchange", pos.get("vol"), held)
            pos["vol"] = held
        pos["position_id"] = int(live[0].get("positionId") or
                                 pos.get("position_id") or 0) or None
        return True

    # The exchange holds nothing, so our barriers did their job. Work out which
    # one fired from the exit price MEXC reports, not from a guess.
    entry = float(pos["entry"])
    exit_px = px
    for rec in _closed_stop_records(cfg, pos):
        exit_px = float(rec.get("takeProfitPrice") or rec.get("stopLossPrice")
                        or px)
        break
    # The stop and the target are separate orders, so whichever did NOT fire can
    # be left resting. It is a close-long order and cannot open a short, but a
    # stale order is still a surprise waiting to happen.
    try:
        if fx.open_orders(cfg.symbol):
            fx.cancel_all_orders(cfg.symbol)
            LOG.info("cancelled the leftover resting order")
    except fx.MexcFuturesError as exc:
        LOG.warning("could not cancel leftover orders: %s", exc)
    pnl = (exit_px / entry - 1) * float(pos["notional"])
    won = pnl > 0
    s["realised_today"] = s.get("realised_today", 0.0) + pnl
    if not won:
        s["losses"] = int(s.get("losses", 0)) + 1
    s["position"] = None
    _append_ledger({"action": "closed_by_exchange",
                    "reason": "take-profit" if won else "stop-loss",
                    "entry": entry, "exit": exit_px, "pnl_usd": pnl,
                    "losses": s.get("losses", 0)})
    _write_state(s)
    LOG.warning("the exchange closed the position: %s at %.6f (%+.2f USD) — "
                "flat again, may re-enter",
                "take-profit" if won else "stop-loss", exit_px, pnl)
    if cfg.max_losses and s.get("losses", 0) >= cfg.max_losses:
        LOG.error("LOSS LIMIT REACHED (%d of %d) — no further trades until you "
                  "reset the counter", s["losses"], cfg.max_losses)
    return False


def _closed_stop_records(cfg: Config, pos: dict) -> list:
    """Finished TP/SL records for this position, newest first. Best effort."""
    pid = pos.get("position_id")
    if not pid:
        return []
    try:
        recs = [r for r in fx.list_position_stops(cfg.symbol)
                if str(r.get("positionId")) == str(pid)
                and int(r.get("isFinished") or 0) == 1
                and int(r.get("errorCode") or 0) == 0]
    except fx.MexcFuturesError as exc:
        LOG.info("could not read the TP/SL record for the exit price: %s", exc)
        return []
    return sorted(recs, key=lambda r: int(r.get("updateTime") or 0), reverse=True)


def do_reset_losses(cfg: Config) -> int:
    """Clear the losing-trade counter. The only way it ever clears."""
    s = _read_state()
    was = int(s.get("losses", 0))
    s["losses"] = 0
    if "loss limit reached" in str(s.get("halt_reason", "")):
        s["halted"] = False
        s["halt_reason"] = ""
    _write_state(s)
    _append_ledger({"action": "reset_losses", "was": was})
    print(f"losing-trade counter reset: {was} -> 0")
    return 0


def step(cfg: Config, live: bool) -> None:
    """One decision cycle: hold, exit, or enter."""
    if KILL_PATH.exists():
        # Previously the kill file only flipped the run to dry, so the position
        # branch still executed: it booked a loss that never happened, cleared
        # the position from state, and left a live levered long with no stop.
        held = (_read_state() or {}).get("position")
        extra = ""
        if held:
            extra = (f"; POSITION STILL OPEN ({held.get('vol')} contracts) and "
                     f"its stop is NOT being monitored — close it with "
                     f"`python spx_bot.py flat --live`")
        LOG.error("kill file present at %s — no action taken%s", KILL_PATH, extra)
        return
    s = _read_state()
    if s.get("day") != _today():
        s["day"] = _today(); s["realised_today"] = 0.0

    # Breakers block OPENING risk. They must not short-circuit the branch that
    # manages an open position: returning here with a position on the books
    # would stop the stop-loss being watched at exactly the moment the account
    # is already in trouble.
    # While a position is open, the lane that opened it owns it: its barriers are
    # already resting on the exchange, and a different lane's stop would close
    # part of a position it does not own.
    _held = s.get("position") or {}
    _owner = _held.get("lane")
    if _owner:
        cfg = dataclasses_replace(cfg, strategy=_owner["strategy"],
                                  timeframe=_owner["timeframe"])
    may_enter, breaker_why = check_breakers(cfg, s)
    if not may_enter and not s.get("position"):
        LOG.warning("no action: %s", breaker_why)
        _write_state(s)
        return
    may, gate_why = gates_open(live)
    dry = not may

    px = fx.last_price(cfg.symbol)
    if px <= 0:
        LOG.warning("no price for %s", cfg.symbol)
        return

    # equity guard
    try:
        eq = fx.usdt_equity()
        if eq < cfg.min_equity_usd:
            s["halted"] = True
            s["halt_reason"] = f"equity {eq:.2f} below floor {cfg.min_equity_usd}"
            _write_state(s)
            alert("halted", s["halt_reason"])
            return
    except fx.MexcFuturesError as exc:
        LOG.warning("equity check failed, standing down this cycle: %s", exc)
        return

    # Believe the exchange, not this file. If it closed the position while we
    # were asleep, book it here and fall through to the entry logic.
    if not _reconcile(cfg, s, px, dry):
        _write_state(s)
        return

    pos = s.get("position")
    if pos:
        entry = float(pos["entry"])
        tp = entry * (1 + cfg.take_profit_pct / 100)
        sl = entry * (1 - cfg.stop_loss_pct / 100)
        LOG.info("holding %s contracts from %.2f  (tp %.2f / sl %.2f, now %.2f)",
                 pos["vol"], entry, tp, sl, px)
        if not pos.get("protected"):
            # The entry succeeded but its barriers did not. Retry rather than
            # leave the position depending on this loop staying alive.
            try:
                br = _attach_bracket(cfg, int(pos["vol"]), entry, dry)
                pos["tp"], pos["sl"] = br["tp"], br["sl"]
                pos["protected"] = br["protected"]
                pos["position_id"] = br.get("position_id") or pos.get("position_id")
                pos.pop("tp_error", None)
                _append_ledger({"action": "bracket_retry", "tp": br["tp"],
                                "sl": br["sl"], "protected": br["protected"],
                                "dry_run": dry})
                LOG.warning("re-placed the barriers (protected=%s)",
                            br["protected"])
            except fx.MexcFuturesError as exc:
                LOG.error("still cannot rest the barriers: %s", exc)
        # Both barriers now rest on the exchange, so this check is a BACKUP for
        # the case where they failed to activate. Kept deliberately: MEXC has
        # accepted stop records that never became active (errorCode 8912).
        if px <= sl:
            r = fx.close_long(cfg.symbol, int(pos["vol"]),
                              leverage=cfg.leverage, dry_run=dry)
            pnl = (px / entry - 1) * float(pos["notional"])
            s["realised_today"] = s.get("realised_today", 0.0) + pnl
            s["position"] = None
            if pnl < 0:
                s["losses"] = int(s.get("losses", 0)) + 1
            _append_ledger({"action": "stop", "price": px, "entry": entry,
                            "pnl_usd": pnl, "losses": s.get("losses", 0),
                            "dry_run": dry, "resp": r})
            LOG.warning("STOP hit at %.2f (%.2f USD) — losing trades: %d%s",
                        px, pnl, s.get("losses", 0),
                        f" of {cfg.max_losses}" if cfg.max_losses else "")
            if cfg.max_losses and s.get("losses", 0) >= cfg.max_losses:
                alert("loss-limit",
                      f"loss limit reached: {s['losses']} of {cfg.max_losses} "
                      f"losing trades. No further trades until you reset the "
                      f"counter.")
        _write_state(s)
        return

    # flat -> enter
    if not may_enter:
        LOG.warning("not entering: %s", breaker_why)
        _write_state(s)
        return
    # NB: `pos` is always falsy here, so the max_open_positions comparison below
    # can never fail. Kept as a guard for when more than one position is
    # supported; it is not doing any work today.
    if int(bool(pos)) >= cfg.max_open_positions:
        return

    # Trust the exchange, not this file. When the take-profit call failed, the
    # exception used to unwind step() before any state was written, so the next
    # cycle believed it was flat and opened ANOTHER live long: three cycles
    # produced three real positions and an empty ledger. Reconciling here turns
    # "stacks forever" into "refuses once".
    if not dry:
        try:
            live_pos = fx.open_positions(cfg.symbol)
        except fx.MexcFuturesError as exc:
            LOG.warning("cannot reconcile with the exchange, "
                        "standing down this cycle: %s", exc)
            return
        held = [p for p in live_pos if int(float(p.get("holdVol") or 0)) > 0]
        if held:
            s["halted"] = True
            s["halt_reason"] = (
                f"state says flat but {cfg.symbol} holds "
                f"{[p.get('holdVol') for p in held]} — refusing to enter")
            _write_state(s)
            LOG.error("HALT: %s", s["halt_reason"])
            return

    # Flat: race the lanes. First to want exposure takes the trade.
    _lane, _why = pick_lane(cfg, s)
    if _lane is None:
        LOG.info("no lane wants exposure — %s", _why)
        _write_state(s)
        return
    if _lane["strategy"] != cfg.strategy or _lane["timeframe"] != cfg.timeframe:
        LOG.info("lane %s on %s bars won the entry: %s",
                 _lane["strategy"], _lane["timeframe"], _why)
        cfg = dataclasses_replace(cfg, strategy=_lane["strategy"],
                                  timeframe=_lane["timeframe"])
    else:
        LOG.info("lane %s on %s bars takes the entry: %s",
                 _lane["strategy"], _lane["timeframe"], _why)

    notional = min(cfg.margin_usd * cfg.leverage, cfg.max_notional_usd)
    vol = fx.contracts_for(cfg.symbol, notional, px)
    if vol < 1:
        LOG.error("sizing gives %d contracts — margin too small", vol)
        return
    # The barrier prices belong to _attach_bracket, which is the only place that
    # knows whether this strategy has a take-profit at all — buy_hold does not.
    if _snap_sl_price(cfg, px) <= 0:
        LOG.error("no usable stop price for %s at %s — not entering",
                  cfg.symbol, px)
        return

    r = fx.open_long(cfg.symbol, vol, leverage=cfg.leverage, dry_run=dry)
    # Persist the position BEFORE the take-profit goes out. Everything after
    # this line may fail without the bot forgetting that it is long.
    s["position"] = {"entry": px, "vol": vol, "notional": notional,
                     "tp": None, "opened": _today(), "lane": _lane}
    if _lane["strategy"] in ONE_SHOT_STRATEGIES:
        s["lanes_used"] = sorted(set(s.get("lanes_used") or [])
                                 | {lane_key(_lane)})
    _append_ledger({"action": "open", "price": px, "vol": vol,
                    "notional": notional, "dry_run": dry,
                    "gate": gate_why or "LIVE", "open_resp": r})
    _write_state(s)
    LOG.info("%s %d contracts at %.2f", "DRY-RUN opened" if dry else "OPENED",
             vol, px)

    try:
        br = _attach_bracket(cfg, vol, px, dry)
    except fx.MexcFuturesError as exc:
        s["position"]["tp_error"] = str(exc)
        _append_ledger({"action": "bracket_failed", "error": str(exc),
                        "dry_run": dry})
        _write_state(s)
        LOG.error("POSITION IS OPEN WITH NO EXCHANGE-SIDE BARRIERS (%s) — the "
                  "stop is only enforced by this loop, which protects nothing "
                  "if this process stops. The next cycle will retry.", exc)
        return
    s["position"]["tp"] = br["tp"]
    s["position"]["sl"] = br["sl"]
    s["position"]["position_id"] = br.get("position_id")
    s["position"]["protected"] = br["protected"]
    _append_ledger({"action": "bracket_placed", "tp": br["tp"], "sl": br["sl"],
                    "protected": br["protected"], "dry_run": dry,
                    "error_codes": br.get("error_codes"), "resp": br.get("response")})
    _write_state(s)
    if br["protected"]:
        LOG.info("exchange holds both barriers: stop %.6f on the position, "
                 "target %s resting as a limit — they fire even if this process "
                 "stops", br["sl"], br["tp"])
    elif not dry:
        LOG.error("MEXC ACCEPTED THE BARRIERS BUT THEY ARE NOT ACTIVE "
                  "(error codes %s) — this loop is the only stop. Investigate "
                  "before leaving it unattended.", br.get("error_codes"))


def do_run(cfg: Config, live: bool, once: bool) -> int:
    lanes = _lane_order(cfg)
    for lane in lanes:
        if not lane_may_gate(lane["strategy"]):
            LOG.error("refusing to start: %s cannot be used even as an entry "
                      "gate", lane["strategy"])
            return 2
    reachable, why_stop = stop_is_reachable(cfg.leverage, cfg.stop_loss_pct,
                                           cfg.symbol)
    if not reachable:
        LOG.error("refusing to start: %s", why_stop)
        return 6
    if why_stop:
        LOG.warning("%s", why_stop)
    LOG.warning("racing %d lane(s), finest bars first — the first to want "
                "exposure takes the trade and owns it until it closes:",
                len(lanes))
    for i, lane in enumerate(lanes):
        LOG.warning("  %d. %s on %s bars", i + 1, lane["strategy"],
                    lane["timeframe"])
    if len(lanes) > 1:
        LOG.warning("Entry gates only: a lane's signal decides WHETHER to open "
                    "one bracketed trade. That is not the exposure form the "
                    "backtest measures, so those figures do not transfer.")
    try:
        skew = fx.clock_skew_ms()
        if abs(skew) > 5000:
            LOG.error("refusing to start: this machine's clock is %+.1fs from "
                      "MEXC's. Every signed request would be rejected, and MEXC "
                      "reports that as an auth failure — which looks exactly "
                      "like a wrong secret. Fix the system clock first.",
                      skew / 1000)
            return 4
        LOG.info("clock skew %+dms", skew)
    except fx.MexcFuturesError as exc:
        LOG.warning("could not check the clock: %s", exc)
    may, why = gates_open(live)
    mode = "LIVE — REAL MONEY" if may else f"DRY RUN ({why})"
    LOG.warning("spx_bot starting: %s  %s on %s bars (poll %ds)  %s %dx  "
                "tp %.1f%% sl %.1f%%  margin $%.2f", mode, cfg.strategy,
                cfg.timeframe, cfg.poll, cfg.symbol, cfg.leverage,
                cfg.take_profit_pct, cfg.stop_loss_pct, cfg.margin_usd)
    if may:
        LOG.warning("kill switch: touch %s to stop trading", KILL_PATH)
    other = running_pid()
    if other and other != os.getpid():
        LOG.error("another runner is already live as pid %s — refusing to start "
                  "a second one, they would both trade the same position", other)
        return 3
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()))
    except OSError as exc:
        LOG.warning("could not write the pid file: %s", exc)
    try:
        return _run_loop(cfg, live, once)
    finally:
        if running_pid() == os.getpid():
            PID_PATH.unlink(missing_ok=True)


MAX_CONSECUTIVE_FAULTS = 5
ALERT_PATH = STATE_DIR / "alerts.jsonl"

# Exit codes the watchdog must NOT retry: they are configuration, not weather.
# Restarting on a bad clock or an unrunnable strategy would just spin.
PERMANENT_EXIT_CODES = {2, 3, 4, 5, 6}


def alert(kind: str, message: str) -> None:
    """Tell the operator something happened while they were not looking.

    A bot that halts silently at 3am is discovered at 9am. This writes an append
    only record and raises a desktop notification, so the state is visible both
    on screen and after the fact.
    """
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "kind": kind, "message": message}
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with ALERT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        LOG.warning("could not write the alert: %s", exc)
    LOG.error("ALERT [%s] %s", kind, message)
    if sys.platform == "darwin":
        try:
            # osascript rather than a dependency; failure here must never affect
            # trading, so it is fire-and-forget with a short timeout.
            import subprocess
            safe = message.replace('"', "'")[:200]
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe}" with title "spx_bot: {kind}"'],
                capture_output=True, timeout=5, check=False)
        except Exception:                                  # noqa: BLE001
            pass


def recent_alerts(limit: int = 20) -> list:
    try:
        lines = ALERT_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))


def do_watchdog(cfg: Config, live: bool) -> int:
    """Keep the runner alive across faults, and say so when it cannot.

    Separate from the in-loop retry: that handles a bad cycle, this handles the
    process giving up entirely. Backs off so a permanent fault cannot spin, and
    refuses to restart on a configuration error, which would spin forever.
    """
    delay = 30
    restarts = 0
    while True:
        rc = do_run(cfg, live, once=False)
        if rc == 0:
            return 0
        if rc in PERMANENT_EXIT_CODES:
            alert("stopped", f"the bot exited with code {rc}, which is a "
                             f"configuration problem — not restarting. See "
                             f"{LOG_PATH}")
            return rc
        restarts += 1
        held = (_read_state() or {}).get("position")
        alert("restarting",
              f"the bot died (code {rc}); restart {restarts} in {delay}s"
              + (f". A POSITION IS OPEN ({held.get('vol')} contracts) — its "
                 f"exchange stop still applies" if held else ""))
        time.sleep(delay)
        delay = min(600, delay * 2)


def _run_loop(cfg: Config, live: bool, once: bool) -> int:
    consecutive_faults = 0
    while True:
        try:
            step(cfg, live)
        except fx.MexcFuturesForbidden as exc:
            LOG.error("permission problem, halting: %s", exc)
            s = _read_state(); s["halted"] = True
            s["halt_reason"] = f"forbidden: {exc}"; _write_state(s)
            return 1
        except fx.MexcFuturesError as exc:
            LOG.warning("cycle failed, will retry: %s", exc)
        except Exception as exc:                          # noqa: BLE001
            # Exiting on the first unexpected fault abandoned the position: the
            # exchange stop still applies, but nothing retries the barriers,
            # notices a fill, or enforces the breakers. Retry with backoff, then
            # give up loudly rather than spinning on a permanent bug.
            consecutive_faults += 1
            LOG.exception("unexpected error (%d of %d before giving up): %s",
                          consecutive_faults, MAX_CONSECUTIVE_FAULTS, exc)
            if consecutive_faults >= MAX_CONSECUTIVE_FAULTS:
                held = (_read_state() or {}).get("position")
                if held:
                    alert("giving-up",
                          f"{MAX_CONSECUTIVE_FAULTS} consecutive faults WITH AN "
                          f"OPEN POSITION ({held.get('vol')} contracts). Its "
                          f"exchange stop still applies, but nothing is managing "
                          f"the trade. Close it with "
                          f"`python spx_bot.py flat --live`.")
                else:
                    alert("giving-up", f"{MAX_CONSECUTIVE_FAULTS} consecutive "
                                       f"faults, flat, stopping. See {LOG_PATH}")
                return 1
            _touch_heartbeat()
            if once:
                return 1
            time.sleep(min(600, cfg.poll * consecutive_faults))
            continue
        else:
            consecutive_faults = 0
        _touch_heartbeat()
        if once:
            return 0
        time.sleep(cfg.poll)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("preflight", "run", "watchdog", "status",
                                       "flat", "reset-losses"))
    ap.add_argument("--live", action="store_true",
                    help="actually place orders (also needs SPX_BOT_ARMED=yes)")
    ap.add_argument("--once", action="store_true", help="single cycle, then exit")
    ap.add_argument("--leverage", type=int)
    ap.add_argument("--margin", type=float, help="margin in USD")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")
    # THE date format, like the runner's log — see positions_view.WhenFormatter
    try:
        from tradingagents.positions_view import WhenFormatter

        for _h in logging.getLogger().handlers:
            _h.setFormatter(WhenFormatter("%(asctime)s %(levelname)-7s "
                                          "%(message)s"))
    except Exception:
        pass
    # The UI saves keys to the credential store; without this the bot read only
    # its own shell environment, so "Test connection" could pass on one key
    # while the bot traded with another.
    try:
        from tradingagents.dataflows import mexc_credentials as _cred
        _cred.load_into_env()
    except Exception as exc:                              # noqa: BLE001
        LOG.warning("could not load saved credentials: %s", exc)
    cfg = Config.load()
    if a.leverage:
        cfg.leverage = a.leverage
    if a.margin:
        cfg.margin_usd = a.margin
    if a.command == "preflight":
        return do_preflight(cfg)
    if a.command == "status":
        return do_status(cfg)
    if a.command == "reset-losses":
        return do_reset_losses(cfg)
    if a.command == "flat":
        if not gates_open(a.live, closing=True)[0]:
            use_dry_book()
        return do_flat(cfg, a.live)
    if not gates_open(a.live)[0]:
        use_dry_book()
    if a.command == "watchdog":
        return do_watchdog(cfg, a.live)
    return do_run(cfg, a.live, a.once)


if __name__ == "__main__":
    sys.exit(main())
