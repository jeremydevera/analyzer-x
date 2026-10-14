# Main tab = every room strategy's past trades; the room that was Main = #09439DC2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Auto Trade tab labelled Main shows one list of every room strategy's closed trades with a Room column; the room that used to be Main gets its own tab named #09439DC2 and that name everywhere.

**Architecture:** A display name per room comes from ONE place (`profiles.name_of` in Python, `roomName` / `PROFILES` in TypeScript); the room keeps its internal id `main`, so no file moves. One new server route builds every room's history rows with the SAME row builder `/api/trade/history` uses (extracted from it), merges the rooms, then searches, totals and pages on the server. The page's Trade history panel gains an `allRooms` mode that the new "Main" tab (not a room) renders alone.

**Tech Stack:** Python 3 / FastAPI (`tradingagents/api.py`), pytest; Next.js + TypeScript (`webapp/`).

**Spec:** `docs/superpowers/specs/2026-10-14-main-tab-all-rooms-past-trades-design.md`

## Global Constraints

- The room's internal id stays `main`; its folder stays `~/.tradingagents`; nothing about trading, PANIC, the orphan sweep or real money changes.
- The printed name of that room is `#09439DC2` everywhere; the word "Main" is the all-rooms tab only.
- Every date printed goes through `positions_view.fmt_when` / `fmtWhen` (CLAUDE.md date format).
- Filter where the data is: search, totals and pages for the all-rooms list are done on the server, never with a `.filter(` over rows the browser received.
- An empty answer names what it examined (rooms and closed trades), never speaks for the store.
- `webapp/src/lib/api.ts` `PROFILES` ids stay equal to `profiles.shown()` (two tests hold it).
- Room-panel components keep calling `useRoomApis()` and never import `api`/`tradeApi` from `@/lib/api` (test_every_profile_is_its_own_room).
- Commit through `python scripts/commit_own.py -F msg.txt <paths>`, push to `origin` AND `colleague`.

## Review Focus

1. The same trade id in two rooms (two rooms ran the same strategy on the same coin at the same signal — the id hashes coin, strategy, time and side) must show as TWO rows, each with its own room, never merged. Test in Task 2.
2. A room whose record does not exist yet (a new room) must add nothing and must NOT be listed as unreadable. Test in Task 2.
3. A browser that saved the old tab value `main` must open the #09439DC2 tab; one that saved nothing or something unknown must open the all-rooms Main tab. Test in Task 3.
4. Same-second exits across rooms must keep a fixed order so the running total does not jump between refreshes (sort by close time, then room order, then file order). Test in Task 2.
5. While another tab is on screen the all-rooms list must refresh every 15 s, not 5 s, and its request must carry no room header. Test in Task 3.

---

### Task 1: One printed name per room — `profiles.name_of`, and #09439DC2 for the room that was Main

**Files:**
- Modify: `tradingagents/profiles.py` (BUILTIN main entry; new `name_of`)
- Modify: `tradingagents/error_issues.py:463`, `tradingagents/forecast_v2.py:586`, `tradingagents/missing_row.py:92,365`, `tradingagents/room_replay.py:1555`, `tradingagents/room_restart.py:90`, `tradingagents/room_stats.py:556`
- Test: `tests/test_main_tab_shows_every_rooms_trades.py` (new)

**Interfaces:**
- Produces: `profiles.name_of(pid: str) -> str` — `"#09439DC2"` for `"main"`, `"#<id>"` for any other id (known or not). `profiles.MAIN_DISPLAY_ID = "09439DC2"`.

- [ ] **Step 1: Write the failing tests**

```python
"""The Main tab is every room strategy's past trades; the room that was Main
is #09439DC2 (operator, Oct 14, 2026: "the main tab is a room strategy so what
i want is to assign and id for it and create a new tab for it / the main tab
is for seeing all room strategy past trades"). Spec:
docs/superpowers/specs/2026-10-14-main-tab-all-rooms-past-trades-design.md"""
from __future__ import annotations

import re
from pathlib import Path

from tradingagents import forecast_rules as fr, forecast_v2_daily as fd, profiles

ROOT = Path(__file__).resolve().parents[1]


def test_the_room_that_was_main_is_named_by_its_rules():
    assert profiles.name_of("main") == "#09439DC2"
    assert profiles.name_of("55D32617") == "#55D32617"
    assert profiles.name_of("NOPE1234") == "#NOPE1234"
    assert profiles.MAIN == "main", "only the NAME changes; the id and folder stay"
    # 09439DC2 is its rules' id, worked out the way the 1-4 day rooms were named
    assert fr.rule_id(fd.room_rules()["main"]) == profiles.MAIN_DISPLAY_ID == "09439DC2"


def test_no_module_prints_main_for_a_room():
    """Seven Python places spelled the name by hand ("Main" if pid == MAIN);
    every printed room name now comes from profiles.name_of."""
    hand = re.compile(r'"Main" if \w+ ==|\(profiles\.MAIN, "Main"|r != "Main"')
    found = [f"{p.name}:{i}" for p in (ROOT / "tradingagents").glob("*.py")
             for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if hand.search(line)]
    assert not found, found
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_main_tab_shows_every_rooms_trades.py`
Expected: FAIL — `AttributeError: module 'tradingagents.profiles' has no attribute 'name_of'`, and the second test lists the seven places.

- [ ] **Step 3: Implement**

In `tradingagents/profiles.py`, change the main entry and add `name_of` right after `get`:

```python
# THE ROOM THAT WAS MAIN IS #09439DC2 (operator, Oct 14, 2026: "the main tab is
# a room strategy so what i want is to assign and id for it and create a new
# tab for it"). 09439DC2 is forecast_rules.rule_id of its rules — 90% wins,
# 20+ trades in 30 days, TP wider than SL, stop 2% or tighter — the way the
# 1-4 day rooms were named. ONLY THE NAME: its id stays "main" and its folder
# stays ~/.tradingagents, so no file moves and nothing about trading changes.
MAIN_DISPLAY_ID = "09439DC2"
BUILTIN = [
    {"id": MAIN, "name": f"#{MAIN_DISPLAY_ID}", "display_id": MAIN_DISPLAY_ID, "rules": None},
```

```python
def name_of(pid: str) -> str:
    """How a room is PRINTED — the one place: `#09439DC2` for the room whose
    id is `main`, `#<id>` for every other room, known or not."""
    p = get(pid)
    return p["name"] if p else f"#{pid}"
```

Then replace each hand-written name:

- `error_issues.py:463`: `return ", ".join(profiles.name_of(r) for r in rooms) or "none"` (add `from tradingagents import profiles` inside the function if the module has no import of it).
- `forecast_v2.py:586`: `return {"id": pid, "name": profiles.name_of(pid),`
- `missing_row.py:92`: `out = [(profiles.MAIN, profiles.name_of(profiles.MAIN), Path(home))]`
- `missing_row.py:365`: `rooms = sorted({h["room"] for h in named}, key=lambda r: (r != profiles.name_of(profiles.MAIN), r))`
- `room_replay.py:1555`: `return {"room": room, "name": profiles.name_of(room),`
- `room_restart.py:90`: `names = ", ".join(profiles.name_of(r) for r in done)`
- `room_stats.py:556`: `"id": room_id, "name": profiles.name_of(room_id),`

- [ ] **Step 4: Run the tests and the suites that read room names**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_main_tab_shows_every_rooms_trades.py tests/test_every_profile_is_its_own_room.py tests/test_forecast_v2.py tests/test_errors_become_issues.py tests/test_the_errors_tab_shows_each_rooms_errors.py`
Expected: the two new tests PASS; any test that pinned the old name "Main" for the room now fails and is updated to `#09439DC2` (a fixture that USES "Main" as made-up data is left alone).

- [ ] **Step 5: Commit** (`commit_own.py` with the files above; message names the operator's words and the id's origin).

---

### Task 2: `GET /api/trade/history/rooms` — every room's closed trades, built by the one row builder

**Files:**
- Modify: `tradingagents/api.py` (`trade_history` split into `_history_rows` + `_history_page`; new route `trade_history_rooms`)
- Test: `tests/test_main_tab_shows_every_rooms_trades.py`

**Interfaces:**
- Consumes: `profiles.name_of`, `profiles.shown()`, `profiles.using(pid)` (context manager), `auto_trader.ledger_trades(ts)`, `auto_trader.load_settings()`.
- Produces:
  - `_history_rows(books: tuple[bool, ...]) -> tuple[list[dict], int]` — the CURRENT room's closed trades on `books`, oldest first, each `{ts, id, opened, held, when, coin, side, strategy, strategy_id, why, profit, book}` (no `running`), and how many closed trades were examined.
  - `_history_page(rows, *, books, q, per_page, page, examined, match=("id", "strategy_id")) -> dict` — adds `running` per book oldest first, filters by `q` over the `match` fields, builds `months`/`totals`, sorts newest first, pages; returns Trade history's payload shape.
  - Route `GET /api/trade/history/rooms?dry=&per_page=&page=&q=` → Trade history's payload plus `rooms: [{room, name}]` (covered), `unreadable: [{room, name, why}]`, each row with `room` and `room_name`.

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
import json

import pytest
from fastapi.testclient import TestClient

import tradingagents.auto_trader as at


def _exit(ts, pnl, tid, *, sym="KITE_USDT", strat="squeeze_1h_sl3tp3", dry=True):
    return {"ts": ts, "action": "exit", "symbol": sym, "strategy": strat, "dry_run": dry,
            "why": "TP" if pnl > 0 else "SL", "pnl_est": pnl, "trade_id": tid,
            "opened_at": ts - 600, "held_s": 600, "side": "LONG"}


@pytest.fixture
def two_rooms(write_ledger, monkeypatch):
    """Main (#09439DC2) and #55D32617 on ONE timeline; the other rooms have no
    record yet — which is not 'unreadable', just nothing."""
    monkeypatch.setattr(profiles, "shown", lambda: ["main", "55D32617", "4FC03172"])
    write_ledger([_exit(1_000, 1.0, "AAAA1111"), _exit(3_000, -0.5, "SAME0000")])
    with profiles.using("55D32617"):
        write_ledger([_exit(2_000, 2.0, "BBBB2222"), _exit(3_000, 0.25, "SAME0000")])
    from tradingagents.api import app
    return TestClient(app)


def test_every_room_in_one_list_newest_first_with_its_room(two_rooms):
    got = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=50").json()
    assert [(r["id"], r["room_name"]) for r in got["rows"]] == [
        ("SAME0000", "#55D32617"), ("SAME0000", "#09439DC2"),   # same second: room order, newest first
        ("BBBB2222", "#55D32617"), ("AAAA1111", "#09439DC2")]
    # ONE running total across the rooms, oldest first
    assert [r["running"] for r in reversed(got["rows"])] == [1.0, 3.0, 2.5, 2.75]
    assert got["total"] == 4 and got["examined"] == 4 and got["unreadable"] == []
    assert [r["room"] for r in got["rooms"]] == ["main", "55D32617", "4FC03172"]


def test_a_room_id_trade_id_or_strategy_id_finds_its_trades(two_rooms):
    by_room = two_rooms.get("/api/trade/history/rooms?q=%2355d32617&per_page=50").json()
    assert {r["id"] for r in by_room["rows"]} == {"BBBB2222", "SAME0000"}
    assert {r["room"] for r in by_room["rows"]} == {"55D32617"}
    same = two_rooms.get("/api/trade/history/rooms?q=SAME0000&per_page=50").json()
    assert sorted(r["room_name"] for r in same["rows"]) == ["#09439DC2", "#55D32617"], \
        "one trade id in two rooms is two trades"
    none = two_rooms.get("/api/trade/history/rooms?q=ZZZZ9999").json()
    assert none["total"] == 0 and none["examined"] == 4


def test_pages_are_cut_on_the_server(two_rooms):
    p2 = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=3&page=2").json()
    assert (p2["page"], p2["pages"], len(p2["rows"])) == (2, 2, 1)
    assert p2["rows"][0]["id"] == "AAAA1111"


def test_a_room_that_raises_is_named_and_the_others_still_show(two_rooms, monkeypatch):
    real = at.ledger_trades

    def boom(ts=0):
        from tradingagents import profiles as pf
        if pf.current() == "55D32617":
            raise OSError("the disk said no")
        return real(ts)
    monkeypatch.setattr(at, "ledger_trades", boom)
    got = two_rooms.get("/api/trade/history/rooms?dry=true&per_page=50").json()
    assert [u["name"] for u in got["unreadable"]] == ["#55D32617"]
    assert {r["room"] for r in got["rows"]} == {"main"}


def test_the_one_room_history_is_unchanged(two_rooms):
    one = two_rooms.get("/api/trade/history?dry=true&per_page=50").json()
    assert [r["id"] for r in one["rows"]] == ["SAME0000", "AAAA1111"]
    assert [r["running"] for r in one["rows"]] == [0.5, 1.0]
    assert "room" not in one["rows"][0]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_main_tab_shows_every_rooms_trades.py`
Expected: FAIL — 404 on `/api/trade/history/rooms`.

- [ ] **Step 3: Implement** in `tradingagents/api.py`

Move the body of `trade_history` that builds rows into `_history_rows(books)` (the `_all`/`_exits`/`_entries`/`_side_for`/`_strategy_id` code, unchanged, appending each row WITHOUT `running`), and the search, running total, months, sort and paging into `_history_page`. `trade_history` becomes:

```python
    _q = (q or "").strip().lstrip("#").upper()
    books = (False, True) if _q else (dry,)
    rows, examined = _history_rows(books)
    return _history_page(rows, books=books, q=_q, per_page=per_page, page=page,
                         examined=examined)
```

`_history_page` (running total per book, oldest first, BEFORE the search filter so a match shows its real running figure, as today):

```python
def _history_page(rows: list, *, books: tuple, q: str, per_page: int, page: int,
                  examined: int, match: tuple = ("id", "strategy_id")) -> dict:
    """One page of closed trades and the months behind it — the one shape both
    history lists answer. `rows` are oldest first; `q` is already upper-cased
    with no '#'. The running total is per BOOK over every row, so a match and
    page 3 both show the real running figure."""
    import datetime as dt

    run = {"live": 0.0, "demo": 0.0}
    for r in rows:
        run[r["book"]] = round(run[r["book"]] + r["profit"], 2)
        r["running"] = run[r["book"]]
    if q:
        rows = [r for r in rows if any(q in str(r.get(k) or "").upper() for k in match)]
    months: dict = {}
    for r in rows:
        k = dt.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m")
        m = months.setdefault(k, {"key": k, "trades": 0, "wins": 0, "losses": 0, "profit": 0.0})
        m["trades"] += 1
        m["wins" if r["profit"] > 0 else "losses"] += 1
        m["profit"] = round(m["profit"] + r["profit"], 2)
    rows = list(reversed(rows))                                  # newest first
    per = max(1, min(per_page, 100))
    pages = max(1, -(-len(rows) // per))
    page = max(1, min(page, pages))
    mrows = sorted(months.values(), key=lambda m: m["key"], reverse=True)
    for m in mrows:
        m["win_rate"] = round(100 * m["wins"] / m["trades"], 1) if m["trades"] else 0.0
        m["label"] = dt.datetime.strptime(m["key"], "%Y-%m").strftime("%b %Y")
    return {"rows": rows[(page - 1) * per:page * per], "total": len(rows), "page": page,
            "pages": pages, "per_page": per, "q": q, "examined": examined,
            "books": ["live", "demo"] if q else (["demo"] if books == (True,) else ["live"]),
            "months": mrows,
            "totals": {"trades": sum(m["trades"] for m in mrows),
                       "wins": sum(m["wins"] for m in mrows),
                       "losses": sum(m["losses"] for m in mrows),
                       "profit": round(sum(m["profit"] for m in mrows), 2)}}
```

`_history_rows` returns rows sorted oldest first with Python's stable sort on `ts`, starting from the record in FILE order (so same-second trades keep the order they were written — today's behaviour).

The new route:

```python
@app.get("/api/trade/history/rooms")
def trade_history_rooms(dry: bool = False, per_page: int = 5, page: int = 1,
                        q: str = "") -> dict:
    """EVERY room strategy's closed trades in one list (operator, Oct 14, 2026:
    "the main tab is for seeing all room strategy past trades"): each room's
    rows built by `_history_rows` under that room, the room added, the rooms
    merged, then searched (trade, strategy or ROOM id), totalled and paged here
    — never in the browser. A room that raises is named in `unreadable`; one
    with no record yet simply has no trades."""
    from tradingagents import profiles as _pf

    _q = (q or "").strip().lstrip("#").upper()
    books = (False, True) if _q else (dry,)
    rooms = _pf.shown()
    rows, examined, unreadable = [], 0, []
    for order, rid in enumerate(rooms):
        try:
            with _pf.using(rid):
                got, n = _history_rows(books)
        except Exception as exc:                                   # noqa: BLE001
            unreadable.append({"room": rid, "name": _pf.name_of(rid),
                               "why": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        examined += n
        for r in got:
            r.update(room=rid, room_name=_pf.name_of(rid), _order=order)
        rows += got
    rows.sort(key=lambda r: (r["ts"], r["_order"]))                 # stable: file order within a room
    for r in rows:
        r.pop("_order", None)
    out = _history_page(rows, books=books, q=_q, per_page=per_page, page=page,
                        examined=examined, match=("id", "strategy_id", "room"))
    out["rooms"] = [{"room": r, "name": _pf.name_of(r)} for r in rooms]
    out["unreadable"] = unreadable
    return out
```

- [ ] **Step 4: Run the new tests and every history test**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_main_tab_shows_every_rooms_trades.py tests/test_api_trade.py tests/test_find_a_trade_by_its_id.py tests/test_history_shows_the_trades_not_the_refusals.py tests/test_a_book_switch_never_shows_the_other_book.py tests/test_the_screen_reads_trades_not_the_whole_record.py`
Expected: all PASS — the one-room history is byte-for-byte what it was.

- [ ] **Step 5: Commit.**

---

### Task 3: The page — a Main tab with only the all-rooms list, a #09439DC2 tab, one room name

**Files:**
- Modify: `webapp/src/lib/api.ts` (`PROFILES` main entry + `display_id`, `roomName`, `tradeApi.historyRooms`, `HistoryPayload` room fields)
- Modify: `webapp/src/components/trade/TradeHistory.tsx` (`allRooms`, `active` props)
- Modify: `webapp/src/components/trade/AutoTradeScreen.tsx` (the "Main" tab, `ALL_ROOMS = "all"`, `firstRoom`, `pick`, tab labels)
- Modify: `webapp/src/components/errors/DeployedTabsErrors.tsx`, `webapp/src/components/forecast/ForecastV2.tsx`, `webapp/src/components/forecast/RoomForecasts.tsx` (use `roomName`)
- Test: `tests/test_main_tab_shows_every_rooms_trades.py`

**Interfaces:**
- Consumes: `GET /api/trade/history/rooms` (Task 2).
- Produces: `roomName(id: string): string`, `PROFILES` entries `{ id; name; display_id? }`, `tradeApi.historyRooms(dry, page, per, q)`, `TradeHistory({ allRooms?: boolean; active?: boolean })`.

- [ ] **Step 1: Write the failing tests**

```python
def _web(rel: str) -> str:
    return (ROOT / "webapp/src" / rel).read_text(encoding="utf-8")


def test_the_main_tab_draws_only_the_all_rooms_list():
    s = _web("components/trade/AutoTradeScreen.tsx")
    assert 'const ALL_ROOMS = "all";' in s
    body = s[s.index("<AllRoomsBody"):][:400]
    assert "<TradeHistory allRooms active={room === ALL_ROOMS} />" in s
    for panel in ("SummaryRibbon", "PositionsPanel", "PnlPanel", "FeedPanel"):
        assert panel not in body, panel
    # a browser that saved the old "main" opens the SAME room (#09439DC2);
    # nothing saved, or something unknown, opens the all-rooms Main tab
    first = s[s.index("function firstRoom"):s.index("/** ONE ROOM'S PANELS")]
    assert "let id = ALL_ROOMS;" in first
    assert "if (id !== ALL_ROOMS) setProfile(id); else setProfile(\"main\");" in s


def test_one_name_for_the_room_that_was_main_on_every_screen():
    ts = _web("lib/api.ts")
    assert '{ id: "main", name: "#09439DC2", display_id: "09439DC2" },' in ts
    assert "export function roomName(id: string): string" in ts
    for rel in ("components/errors/DeployedTabsErrors.tsx", "components/forecast/ForecastV2.tsx",
                "components/forecast/RoomForecasts.tsx", "components/trade/AutoTradeScreen.tsx"):
        src = _web(rel)
        assert '=== "main" ? "Main"' not in src and '"Main" :' not in src, rel


def test_the_all_rooms_list_asks_the_server_and_waits_behind_its_tab():
    th = _web("components/trade/TradeHistory.tsx")
    assert "tradeApi.historyRooms(dry, page, 5, q.trim())" in th
    assert "allRooms && !active ? 15_000 : 5_000" in th
    assert 'markReady(allRooms ? "past trades" : "trade history")' in th
    assert ".filter(" not in th, "the server searches and pages"
    assert "historyRooms: (dry: boolean, page = 1, per_page = 5, q = \"\") =>" in _web("lib/api.ts")
```

- [ ] **Step 2: Run them to see them fail.** Expected: FAIL on the missing strings.

- [ ] **Step 3: Implement**

`webapp/src/lib/api.ts`:

```ts
export const PROFILES: readonly { id: string; name: string; display_id?: string }[] = [
  // THE ROOM THAT WAS MAIN (operator, Oct 14, 2026: "the main tab is a room
  // strategy so what i want is to assign and id for it and create a new tab
  // for it"): id still "main" (its folder and its runner), name #09439DC2
  { id: "main", name: "#09439DC2", display_id: "09439DC2" },
  ...
];

/** How a room is PRINTED — the one place (profiles.name_of on the server). */
export function roomName(id: string): string {
  return PROFILES.find((p) => p.id === id)?.name ?? `#${id}`;
}
```

and in `tradeApi`, beside `history`:

```ts
  // EVERY room strategy's closed trades (Oct 14, 2026), searched and paged
  // by the server: tradingagents/api.py trade_history_rooms
  historyRooms: (dry: boolean, page = 1, per_page = 5, q = "") =>
    get<HistoryPayload>(`/api/trade/history/rooms?dry=${dry}&page=${page}&per_page=${per_page}&q=${encodeURIComponent(q)}`),
```

`HistoryPayload` rows gain `room?: string; room_name?: string`, and the payload `rooms?: { room: string; name: string }[]; unreadable?: { room: string; name: string; why: string }[]`.

`TradeHistory.tsx`: `export default function TradeHistory({ allRooms = false, active = true }: { allRooms?: boolean; active?: boolean } = {})`; the load calls `allRooms ? tradeApi.historyRooms(dry, page, 5, q.trim()) : tradeApi.history(dry, page, 5, q.trim())`; the interval is `allRooms && !active ? 15_000 : 5_000` (with `active` in the deps); `markReady(allRooms ? "past trades" : "trade history")`; the title is `allRooms ? "Past trades — all room strategies" : "Trade history"`; the heads gain `"room"` first when `allRooms`, each row's first cell `{r.room_name}` (and on the phone cards a room badge); the placeholder becomes `allRooms ? "find by trade, strategy or room id" : "find by id, e.g. LG9NSU4B"`. OPEN ON THE BOOK THAT HAS TRADES, as PnlPanel does: a `picked` ref set by `pickBook`; when `allRooms` and not `picked` and not searching and a LIVE answer has `total === 0`, `setDry(true)`. Under the label: `` `${d.rooms?.length ?? 0} rooms` `` covered, and when `d.unreadable?.length`: `` `${d.unreadable.map((u) => u.name).join(", ")} could not be read` ``. The empty sentence for `allRooms`: `` `No closed trades on the ${dry ? "demo" : "live"} book in the ${d.rooms?.length ?? 0} rooms examined.` ``.

`AutoTradeScreen.tsx`:

```tsx
// THE MAIN TAB IS NOT A ROOM (operator, Oct 14, 2026: "the main tab is for
// seeing all room strategy past trades"): every room's closed trades and
// nothing else. The room that was Main is the #09439DC2 tab after it.
const ALL_ROOMS = "all";
```

`firstRoom()` starts `let id = ALL_ROOMS;`, accepts a saved value equal to `ALL_ROOMS` or a `PROFILES` id, and ends `if (id !== ALL_ROOMS) setProfile(id); else setProfile("main");`; `pick(id)` does the same. The tab strip renders a first tab `Main` (no "i" button) before `PROFILES.map(...)`, each room tab printing `p.name`, and the popup's copyable id is `<CopyableId id={p.display_id ?? p.id} prefix="#" />` for every room. Below the overlay:

```tsx
      {room && (
        <AllRoomsBody hidden={room !== ALL_ROOMS}
                      blurred={room === ALL_ROOMS && blurred} />
      )}
```

with

```tsx
function AllRoomsBody({ hidden, blurred }: { hidden: boolean; blurred: boolean }) {
  return (
    <div hidden={hidden} className={`min-w-0 flex-col gap-5 ${hidden ? "" : "flex"} ${blurred
      ? "pointer-events-none select-none blur-sm" : ""}`}>
      <TradeHistory allRooms active={room === ALL_ROOMS} />
    </div>
  );
}
```

(`active` passed as a prop: `<AllRoomsBody ... active={room === ALL_ROOMS} />` and `<TradeHistory allRooms active={active} />` inside — the test string `<TradeHistory allRooms active={room === ALL_ROOMS} />` is written in the screen's JSX exactly; keep the body inline in `AutoTradeScreen` if that is simpler.) `begin([...])` gains `"past trades"`.

`DeployedTabsErrors.tsx`, `ForecastV2.tsx`, `RoomForecasts.tsx`: import `roomName` from `@/lib/api` and delete each local `roomName` / `=== "main" ? "Main"` expression.

- [ ] **Step 4: Run the tests, the type check and the room-screen guards**

Run: `.venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_main_tab_shows_every_rooms_trades.py tests/test_every_profile_is_its_own_room.py tests/test_rooms_judge_on_15_days.py tests/test_a_book_switch_never_shows_the_other_book.py tests/test_find_a_trade_by_its_id.py` and `cd webapp && npx tsc --noEmit -p .`
Expected: PASS; tsc clean.

- [ ] **Step 5: Commit.**

---

### Task 4: Docs, the rule for every session, and the real site

**Files:**
- Modify: `CLAUDE.md` ("Every trading profile is its own room" and STANDING SETUP: the Main tab is the all-rooms past trades; the room that was Main is #09439DC2, id `main`, folder `~/.tradingagents`), `docs/TRADING-ROOMS.md` where it names Main.

- [ ] **Step 1:** Update both documents with the operator's words and the id's origin.
- [ ] **Step 2:** Run every test file that touches rooms, history, Forecast or CLAUDE.md (`grep -l` over `tests/*.py` for `profiles|history|forecast|CLAUDE.md`), compare failures with the same run on the commit before Task 1.
- [ ] **Step 3:** Commit and push both remotes; warn the operator, then `python start.py start` (the page changed), and check in WebKit: Main shows only "Past trades — all room strategies" with room ids, #09439DC2 shows the tiles, buttons and calendar, the Errors and Forecast pages print #09439DC2.
- [ ] **Step 4:** One code review of the whole change (superpowers:requesting-code-review), fix what it finds, push.

---

## Execution record (Oct 14, 2026)

Run inline (superpowers:executing-plans), on `main` in the shared checkout.
Commits: c81d07b..10a9dba (tasks 1-4), 876d2da (RCA-2026-10-14-I),
5e12bfd (final review fixes, RCA-2026-10-14-K), d906759 and eeec5c2 (what the
live check of those fixes found, RCA-2026-10-14-L).

**Rulings made on the operator's behalf, in order, each with its cost if wrong:**

1. Setup: work on `main` in the shared checkout, no worktree — the standing
   rule is `commit_own` + push both remotes on main, and a worktree would
   drift from what the site runs. Cost if wrong: none; commits are isolated
   by `commit_own`.
2. Pre-flight: Task 3's test wanted both `<AllRoomsBody` and the literal
   `<TradeHistory allRooms active={room === ALL_ROOMS} />` in the screen —
   `AllRoomsBody` takes children and the list is written inside it. Cost if
   wrong: one wrapper.
3. Task 3: the plan's `.filter(` check matched a comment that warns against
   `.filter()`; the test reads code only. Cost if wrong: a `.filter(` inside
   a comment-like string would slip by.
4. Task 3: two room-list tests read `display_id` as a room id; anchored on a
   word boundary (`\bid:`). Cost if wrong: none.
5. Task 3: a book-switch test pinned the old 5-second interval and the old
   `pickBook`; updated to the new expressions, same intent. Cost if wrong:
   none.
6. Task 3: `test_every_room_stays_loaded_in_its_own_scope` held two BACKSPACE
   characters where `\b` was meant (since c9862eee3fa7, Oct 01, 2026), so it
   could never fire; it now checks the imported names between the braces.
   Cost if wrong: none; proven to catch `{ api }` and `{ tradeApi }`.
7. Final review #2 (the RCA-J fix was not live yet): not a code finding; the
   page was rebuilt and re-probed. Cost if wrong: none.
8. Final review #4 re-graded Minor to Important: an unreadable room was
   counted as examined — a false label; fixed. Cost if wrong: none.
9. Final review #6 re-graded Minor to Important: the venue switch still
   printed "room main"; fixed, and the Python name guard widened to every
   non-docstring string. Cost if wrong: none.
10. Final review #5: the per-month summary is not drawn on the Main tab — the
    panel has had no month table since a948a345a7b1 (Auto Trade fits the
    width); the spec's line came from the payload, not a screen ask. Cost if
    wrong: one table to add.
11. The review's "declined to judge" lines accepted as listed (the notify
    skill bundled into aa06b322; same-second order within a room; one search
    id shared by both lists; the side lookup's speed; `load_settings` writing
    a missing settings file; the rooms count against their names; an old
    page against a new API; one refresh on leaving Main; the single-line
    import guard). Cost if wrong: small; none changes what the operator gets.
12. Final review #8 re-graded Minor to Important after the live check showed
    "loading profit…" over the Main tab, a panel it does not have — a false
    label at any duration; fixed (RCA-2026-10-14-L). Cost if wrong: none.

**Deferred minor:** final review #7 — `test_the_room_that_was_main_is_named_by_its_rules`
hashes the watcher's DEFAULT rules inside the test sandbox; it should pin
`fr.cfg_of(30, 90.0, 20, ">", 2.0)` literally, so a change to the defaults
cannot move the id the test expects.

**Found by the live check, not the review:** the Main tab's strategy cell
overflowed at 1,024 and 1,280 px; the first fix (a table-wide wrap rule)
measured ineffective and was replaced by `break-all` on the cell
(RCA-2026-10-14-L).
