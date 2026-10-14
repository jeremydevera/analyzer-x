# The Main tab shows every room strategy's past trades; the room that was Main becomes #09439DC2

*Design, Oct 14, 2026. Approved in chat the same day ("yes to this").*

## What the operator asked

In their words, in order:

> in auto trade -> main i want to see past trades for the deployed room what want
> to see is like the trade history but include the id of the room strategy
> then no need to show the tiles like FUTURES WALLET, REAL · ALL TIME etc
> no need to show day by day calendar the purpose of this is to see past trades
> for all deployed room

Asked what the Main tab keeps besides the list: **"Only the all-rooms list"**.
Asked whether Start/Stop runner, Halt and PANIC stay on Main: **"Remove them too"**.
Then:

> take note the main tab is a room strategy so what i want is to assign and id
> for it and create a new tab for it
> the main tab is for seeing all room strategy past trades

## What changes

### 1. The "Main" tab becomes "Past trades — all room strategies"

The tab labelled **Main** stops being a room. It shows ONE panel and nothing
else: every closed trade of every room strategy that has a tab, newest first.

| Room | Trade id | Strategy id | Opened | Closed | Held | Coin | Side | Strategy | Closed by | Profit | Running |
|---|---|---|---|---|---|---|---|---|---|---|---|

* **Room** is the room strategy's id (`#55D32617`, `#09439DC2`, …), first
  column, the thing the operator asked for. The other columns are Trade
  history's own.
* **LIVE / DEMO** switch, as Trade history. It opens on the book that has
  trades (DEMO while no room trades real money); once the operator picks one,
  it stays picked.
* **Search** finds a trade id, a strategy id or a room id, with or without
  `#`, either case. Like Trade history, a search spans both books.
* **Five a page**, the same pager as Trade history, and a per-month summary
  of the rows shown (all rooms, or the search's matches).
* **Running** is one running total across all the rooms on that book,
  oldest first, so page 3's running figure is the real one.
* **Which rooms** — every room with a tab (`profiles.shown()`): the ten room
  strategies as of Oct 14, 2026, #09439DC2 included. Switched-off rooms with
  no tab are left out. The panel says which rooms it covers and how many
  closed trades it examined, so an empty answer names what it checked
  (CLAUDE.md, "an empty page may never speak for the store").
* Nothing else is on the tab: no tiles, no buttons, no open trades, no
  strategies, no watcher, no keys, no calendar, no feed.

### 2. A new tab, #09439DC2, right after Main — the room that was Main

`09439DC2` is `forecast_rules.rule_id` of the room's own rules — *90% wins,
20+ trades in 30 days, TP wider than SL, stop 2% or tighter* — the same way
the four newest rooms (#99E79CBA, #C7396286, #1D4274C1, #8F0C7926) got their
ids.

The tab shows everything the Main tab shows today: the tiles, Start/Stop
runner, Halt, PANIC (which still also closes any real position no room
owns), open trades, deployed strategies, the watcher, the exchange keys,
Trade history, the day-by-day calendar and the runner feed.

**Only the NAME changes.** The room keeps its internal id `main`, its folder
(`~/.tradingagents` itself), its settings, trade record, state, runner,
watcher rules and every rule that treats it specially (it is the room whose
PANIC and orphan sweep cover positions no other room owns). Nothing moves on
disk and nothing about trading changes.

### 3. One name everywhere

Wherever the app PRINTS that room's name it says `#09439DC2`, never "Main":
the Auto Trade tab, the Errors tab (its rows and room filter), Forecast's room
pickers, the streak lists, the alerts, the room-restart note and the
error-issues text. Today ten places spell it out by hand (`"Main" if pid ==
MAIN`); they all read one name instead:

* Python — `profiles.name_of(pid)`: `#09439DC2` for `main`, `#<id>` for the
  rest. `profiles.BUILTIN[0]` carries `"name": "#09439DC2"` and
  `"display_id": "09439DC2"`.
* TypeScript — `roomName(id)` in `webapp/src/lib/api.ts`, from the `PROFILES`
  list, whose `main` entry becomes `{ id: "main", name: "#09439DC2" }`.

The word **Main** is left for the new all-rooms tab only.

## How it works

### Server: one route, every room, filtered where the data is

`GET /api/trade/history/rooms?dry=&page=&per_page=&q=`

For each room in `profiles.shown()`, under `profiles.using(room)`:
`auto_trader.ledger_trades(0)` (each room's ENTER and EXIT rows, already kept
in memory and read incrementally since RCA-2026-10-07-L, so this is cheap),
and that room's settings once (`load_settings()`), for the strategy ids.

The rows are built by ONE function shared with `/api/trade/history`,
extracted from `trade_history` (the side lookup, the strategy id, the
opened/held/closed fields, the book), so the two lists can never disagree on
a trade. The new route adds `room` and `room_name` to each row, merges every
room, then filters (book or search), runs the running total oldest first,
builds the months and pages — all on the server. A filter in the browser over
a page the server already cut is the shape CLAUDE.md forbids ("filter where
the data is").

It answers `rows`, `total` (matches), `examined` (closed trades looked at),
`page`, `pages`, `months`, `totals`, `rooms` (the ids covered) and
`unreadable` (rooms that raised).

The request carries no room header: it is not one room's route, and the
profile middleware's per-room switch is not used.

### The page

* `PROFILES` gains no new room. The tab strip gets a first tab, **Main**, that
  is not a room (`id: "all"`): it renders `AllRoomsHistory` and nothing else.
  The room tabs follow, #09439DC2 first, each with today's full `RoomBody`.
* `AllRoomsHistory` reuses Trade history's table, pager, LIVE/DEMO switch,
  search box and the stale-answer rule (an answer is shown only for the book,
  page and search it was asked for, RCA-2026-10-07-J), plus the Room column.
* It refreshes every 5 s while its tab is on screen and every 15 s behind it,
  like every room panel (`useLiveRefresh`), and reports `markReady("past
  trades")`; the loading card's list gains that name.
* A browser that had saved the old "main" tab opens on #09439DC2 (the same
  room); a browser with nothing saved opens on Main.

## If something fails

* A room whose record or settings raise is named at the top ("#X could not be
  read") and the other rooms still show.
* An empty answer names what it checked: "no closed trades on the demo book
  in the 10 rooms examined".
* A slow answer shows the same "loading" line as Trade history; an answer for
  a book, page or search no longer on screen is dropped.

## Testing

* Server, on ONE timeline: two rooms' trade records written through the
  `write_ledger` fixture under `profiles.using(...)` — merged newest first,
  the Room column, one running total across both, the months, a search by
  room id (`#55D32617`, `55d32617`), by trade id and by strategy id, paging,
  a room that raises named in `unreadable`, and `/api/trade/history`
  unchanged for one room.
* Names: `profiles.name_of("main") == "#09439DC2"`, and no module prints the
  word "Main" for a room any more (a guard over the ten places above).
* Page: the Main tab renders `AllRoomsHistory` and nothing else; the
  #09439DC2 tab renders the full room; `PROFILES`' main entry reads
  `#09439DC2`.
* The real site in Safari's engine (WebKit): Main shows only the list, with
  room ids; #09439DC2 shows the tiles, buttons and calendar.

## Not changing

* No file moves, no runner restart of its rules, no change to how any room
  trades, to PANIC, to the orphan sweep or to real money.
* The other room tabs.
* `/api/trade/history` (it gains only the extracted row builder).

## Documentation

* CLAUDE.md, "Every trading profile is its own room" and its STANDING SETUP
  table: the Main tab is the all-rooms past trades; the room that was Main is
  `#09439DC2` (internal id `main`, folder `~/.tradingagents`).
* `docs/TRADING-ROOMS.md` where it names Main.
