"""Move the app from one exchange to another — the cutover (Oct 10, 2026).

The operator: *"okay switch to gate from now on, this means every logic in my
app will be gate instead of mexc"*. Spec D7 and D8 in
docs/superpowers/specs/2026-10-10-switch-to-gate-design.md.

    python -m tradingagents.venue_switch gate            # do it
    python -m tradingagents.venue_switch gate --dry-run  # say what it would do

In this order, and nothing after a refusal:

1. REFUSE while anything holds the store (the API, a room's runner, the row
   indexer, a disk job) or while any room holds REAL money — the cutover is
   practice-only by design, and real money is the operator's to move.
2. Read every open PRACTICE trade's last price on the exchange it was opened
   on. One price that cannot be read refuses the whole cutover: a trade left
   open on a coin the new exchange may not even list would never close.
3. Close those trades at that price (`VENUE_SWITCH`, a normal practice exit
   row with the same cost rule as every other) and switch every practice row
   off in every room, each removal a `disarmed` line naming why.
4. RENAME the exchange's data into `~/.tradingagents/archive-<from>-<when>/`
   on the same drive — seconds, no copy, nothing deleted. What stays is the
   app's own: rooms, their trade records, the deploy history, notifications,
   credentials, error issues, runtime recipes, logs.
5. LAST, write venue.json. A cutover that stopped half-way leaves the app on
   the old exchange with its data where it was found, never on the new one
   with the old one's numbers.

Moving the folder back and writing the old name reverses it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from tradingagents import venue

HOME = Path(os.path.expanduser("~/.tradingagents"))

# What belongs to the EXCHANGE: candles, backtests, their indexes, replays,
# forecasts built from them, cost readings, and the state of the jobs that
# fill them (a job file left behind would tell the daily update the new
# exchange was measured yesterday).
EXCHANGE_DIRS = ("backtest", "v2", "parquet", "parquet-v2", "kline_cache",
                 "shared", "replay", "forecast_v2", "rolling30")
EXCHANGE_FILES = ("book_readings.jsonl", "room_forecasts.jsonl",
                  "daily_update.json", "candle_autopilot.json",
                  "cloud_autopilot.json", "rows_index_asked.json",
                  "rows_rebuild.json", "rows_rebuild.log", "rows_rebuild.err",
                  "live_price.json")
EXCHANGE_GLOBS = ("pending_*.json", "db_*.json", "db_*.log", "db_*.pid",
                  "db_*.STOP", "db_*.HANDOFF", "book_readings.jsonl.*")

REASON = ("switched to {to} on {when}: this row was measured on {frm}'s "
          "candles and costs")


class SwitchRefused(RuntimeError):
    """The cutover did not start; nothing was changed."""


def _blockers() -> list[str]:
    """Everything that holds the store open right now, named."""
    from tradingagents import auto_trader as at, portable, profiles

    out = []
    try:
        import start as _start  # noqa: PLC0415

        for pid in _start.port_pids(_start.API_PORT):
            out.append(f"the API (pid {pid}) on port {_start.API_PORT}")
    except Exception:                                          # noqa: BLE001
        pass
    for pid in profiles.ids():
        with profiles.using(pid):
            rp = at.runner_pid()
            if rp:
                out.append(f"room {pid}'s runner (pid {rp})")
    for f in HOME.glob("db_*.pid"):
        try:
            p = int(f.read_text().strip())
        except (OSError, ValueError):
            continue
        if portable.pid_alive(p):
            out.append(f"the {f.stem} job (pid {p})")
    for f in (HOME / "backtest" / "rows_index.pid", HOME / "v2" / "rows_index.pid"):
        try:
            p = int(f.read_text().strip())
        except (OSError, ValueError):
            continue
        if portable.pid_alive(p):
            out.append(f"the row indexer (pid {p})")
    return out


def exchange_data(home: Path | None = None) -> list[Path]:
    """Every path the cutover moves, in a stable order."""
    home = Path(home or HOME)
    out = [home / d for d in EXCHANGE_DIRS if (home / d).exists()]
    out += [home / f for f in EXCHANGE_FILES if (home / f).exists()]
    seen = set(out)
    for g in EXCHANGE_GLOBS:
        for p in sorted(home.glob(g)):
            if p not in seen and p.is_file():
                out.append(p)
                seen.add(p)
    return out


def _real_rows(settings: dict) -> list[str]:
    return [slot for slot, books in (settings.get("strategy_books") or {}).items()
            if "real" in (books or [])]


def _open_practice(state: dict) -> list[tuple[str, dict]]:
    from tradingagents import auto_trader as at

    return [(k, st["position"]) for k, st in state.items()
            if isinstance(st, dict) and at.is_paper_slot(k) and st.get("position")]


def _mexc_price(symbol: str) -> float:
    """The last price on MEXC, read directly: the door may already point
    elsewhere by the time a trade opened there is closed."""
    from tradingagents.dataflows import mexc_futures

    return float(mexc_futures.last_price(symbol))


def switch(target: str, *, rooms=None, price_of=None, now: float | None = None,
           dry_run: bool = False) -> dict:
    """Move the app to `target`. See the module docstring for the order."""
    from tradingagents import auto_trader as at, profiles

    target = venue._check(target, "venue_switch")
    frm = venue.current()
    if frm == target:
        return {"already": True, "venue": target,
                "said": f"already on {venue.NAMES[target]} — nothing to do"}
    now = time.time() if now is None else float(now)
    rooms = list(rooms) if rooms is not None else profiles.ids()
    price_of = price_of or (_mexc_price if frm == "mexc" else None)

    held = _blockers()
    if held and not dry_run:
        raise SwitchRefused("stop these first — they hold the store: "
                            + "; ".join(held))
    # 1-2. read everything BEFORE changing anything
    plan: dict = {}
    for room in rooms:
        with profiles.using(room):
            s = at.load_settings()
            real = _real_rows(s)
            if real:
                raise SwitchRefused(
                    f"room {room} holds real money on {len(real)} row(s) "
                    f"({', '.join(real[:5])}) — the cutover moves practice "
                    f"only; take the real money off first")
            opened = _open_practice(at.load_state())
            prices = {}
            for key, pos in opened:
                sym = at.coin_of_slot(key)
                if sym in prices:
                    continue
                try:
                    px = float(price_of(sym))
                    if not px > 0:
                        raise ValueError(f"price {px!r}")
                except Exception as exc:                        # noqa: BLE001
                    raise SwitchRefused(
                        f"cannot read {venue.NAMES[frm]}'s last price for "
                        f"{sym} (room {room}): {exc} — nothing was changed") from exc
                prices[sym] = px
            coins = sorted({c for cs in (s.get("strategy_coins") or {}).values()
                            for c in (cs or [])})
            plan[room] = {"open": opened, "prices": prices, "coins": coins}
    moving = exchange_data()
    if dry_run:
        return {"dry_run": True, "from": frm, "to": target,
                "would_close": {r: len(p["open"]) for r, p in plan.items()},
                "would_switch_off": {r: len(p["coins"]) for r, p in plan.items()},
                "would_move": [p.name for p in moving], "blocked_by": held}

    from tradingagents.positions_view import fmt_when

    when = fmt_when(now)
    why = REASON.format(to=venue.NAMES[target], frm=venue.NAMES[frm], when=when)
    closed, switched_off = [], {}
    # 3. close practice trades and switch every practice row off
    for room, p in plan.items():
        with profiles.using(room):
            state = at.load_state()
            touched = []
            for key, pos in p["open"]:
                sym = at.coin_of_slot(key)
                px = p["prices"][sym]
                move = (px / float(pos["entry"]) - 1) * int(pos.get("side") or 0)
                cost = at.paper_round_trip(pos, sym)
                pnl = (move - cost) * float(pos.get("margin") or 0) * at.LEVERAGE
                _op = pos.get("opened_at") or pos.get("entry_ts")
                at.append_ledger({
                    "symbol": sym, "action": "exit", "why": "VENUE_SWITCH",
                    "strategy": pos.get("strategy"),
                    "trade_id": at.trade_id_of(sym, pos),
                    "entry_ts": pos.get("entry_ts"), "opened_at": _op,
                    "held_s": (int(now) - int(_op)) if _op else None,
                    "side": "LONG" if pos.get("side", 0) > 0 else "SHORT",
                    "entry": pos.get("entry"), "exit": px,
                    "pnl_est": round(pnl, 2), "pnl_source": "simulated",
                    "note": why, "dry_run": True})
                state[key]["position"] = None
                touched.append(key)
                closed.append({"room": room, "symbol": sym, "slot": key,
                               "exit": px, "pnl": round(pnl, 2)})
            if touched:
                at.save_state(state, keys=touched)
            got = at.disarm_coins(p["coins"], why=why) if p["coins"] else {"rows": 0}
            switched_off[room] = int(got.get("rows") or 0)
    # 4. move the exchange's data aside
    stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime(now))
    arch = HOME / f"archive-{frm}-{stamp}"
    arch.mkdir(parents=True, exist_ok=True)
    moved = []
    for src in moving:
        dst = arch / src.name
        os.replace(src, dst) if src.is_file() else shutil.move(str(src), str(dst))
        moved.append(src.name)
    summary = {"from": frm, "to": target, "at": now, "when": when,
               "archive": str(arch), "moved": moved, "closed": closed,
               "switched_off": switched_off}
    (arch / "switch.json").write_text(json.dumps(summary, indent=1),
                                      encoding="utf-8")
    # 5. last: the switch itself
    venue.set_current(target)
    try:
        from tradingagents import notifications as _nt

        _nt.record("venue_switch",
                   f"Switched to {venue.NAMES[target]}: {len(closed)} practice "
                   f"trade(s) closed, {sum(switched_off.values())} practice "
                   f"row(s) off, {venue.NAMES[frm]}'s data kept in {arch.name}",
                   ok=True)
    except Exception:                                          # noqa: BLE001
        pass
    return summary


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in venue.NAMES:
        print(f"usage: python -m tradingagents.venue_switch "
              f"[{'|'.join(sorted(venue.NAMES))}] [--dry-run]")
        return 2
    try:
        got = switch(args[0], dry_run="--dry-run" in args)
    except SwitchRefused as exc:
        print(f"refused: {exc}")
        return 3
    print(json.dumps(got, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
