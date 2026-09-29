# Trading profiles — one room per watcher rule set

Operator, Sep 29, 2026:

> *"can you activate those 3 / what i want is in auto trade tab create 3
> subtabs under auto trade DC57174E, CC8DC54C, and B52662ED / then each has
> their own environment for live trade demo trade calendar so that i can
> compare each"*

> *"when i click auto trade tab, it should have folder like tab / meaning when
> i switch to B52662ED i should see its own tiles, own live trade, own demo
> trade, own calendar pnl, in short it has its own room/ profile"*

Asked: real money too? *"Real money too"*. Watcher switches real rows by
itself? *"i want both, if i enable live trade, then it should be included"*.
Keep the current setup as Main? *"Yes, keep 'Main'"*.

## What a profile is

A folder. `main` is `~/.tradingagents` exactly as today (byte for byte — no
file moves). Every other profile is `~/.tradingagents/profiles/<ID>/`, holding
its own `auto_trade.json` (settings), `auto_trade_state.json` (open
positions), `auto_trade_ledger.jsonl` (trade record), runner pid/lock/log/
WANT/KILL files, and its own `strategy_watcher.json` / `.jsonl`.

Shared by every profile, on purpose: candles, backtest stores, MEXC keys,
funding and book caches, `runtime_specs.json` (a recipe is a recipe), and the
wallet itself.

| profile | switch on / off | trades | TP rule | stop cap |
|---|---|---|---|---|
| Main | the operator's own (90 / 90) | 20+ | wider | 2% |
| DC57174E | 80 / 80 | 50+ | wider | 2% |
| CC8DC54C | 80 / 80 | 40+ | wider | 2% |
| B52662ED | 70 / 70 | 50+ | wider | 2% |

## How the code finds the folder

* `tradingagents/profiles.py` — the registry, `current()` (a ContextVar,
  defaulting to env `TA_PROFILE`, else `main`), `using(pid)`, `dir_for(pid)`.
* `auto_trader._pp(PATH)` — `PATH` itself for `main` (so every existing test
  that monkeypatches `at.LEDGER_PATH` still works), else the same file name in
  the profile's folder. Every read and write of a runner file goes through it.
* **The runner** is one process per profile: `start_runner()` passes
  `TA_PROFILE`; the API supervisor keeps every wanted profile's runner up.
* **The API** is one process for all: a middleware reads `?profile=` (or the
  `X-TA-Profile` header) and sets the ContextVar for the request. FastAPI runs
  sync routes in a thread that copies the context, so every trade route is
  profile-aware without being edited.
* **The screen** sends the chosen profile on every `/api/trade/*` call.

## Real money across profiles (the hard part)

One MEXC account nets every order on a contract into one position. So:

1. **One real position per coin across ALL profiles.** Before a real entry the
   runner takes a machine-wide lock and reads every other profile's state; a
   coin another profile holds with real money is refused and recorded
   (`coin_busy`, naming the profile). Each profile's real results therefore
   stay its own.
2. **Orphan sweep never adopts another profile's position.** A position some
   other profile tracks is not an orphan.
3. **PANIC closes only the profile's own positions** (plus true orphans on
   Main).
4. The capital gate reads the real wallet, which every profile shares.

## The watcher per profile

Each profile's watcher has its own rules (above), its own slots, its own
log. A per-profile **live switch** (off by default): when on, the watcher
arms `["paper", "real"]` and switches its own real rows off by the same rule.
Every real-money guard in the runner still applies to every entry.

## Out of this cut

* A profile cannot be created from the screen yet (the four are built in).
* Per-profile Telegram/bell routing.
