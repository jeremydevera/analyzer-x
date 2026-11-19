"""THE REVIEWED GITHUB REPOS' OWN STRATEGIES, RUN ON OUR MARKET (Nov 18, 2026).

The operator: *"review all the github and make sure to document what's their strategies"*, then
*"also run multiple agents to scrape them, do backtest, and send me results for all repository so we
can get idea from them"*. The 36 repos are documented in `knowledge/github-repos/` (one note each);
this package ports every strategy that can run on one coin's candles into the Backtest v4 skill
engine (`skill_bt`): the same walk as the skill rooms - entry at the signal candle's close, every
fill at the recorded order book of its own minute where one exists (else the coin's usual gap),
Gate's fee both ways, funding over the hold, stops and targets settled by the minute - on every
coin x 15m, 30m, 1h, 4h, 1d, judged on the newest 30% of the candles (`skill_bt.SPLIT`).

Each batch module exports the same seven names, merged here:

* `STRATEGIES` {name: object with `.name` and `.signals_all(df, params) -> list[TaSignal | None]`}
  - one entry per candle, worked out from candles 0..i only (tests cut the frame and compare);
* `GRID` {name: [params, ...]} - the repo's own settings first, at most 2;
* `STOPS` {name: (stop, ...)} - a fraction of the entry; the repo's own stop where it has one,
  otherwise `DEFAULT_STOPS` (the engine needs a stop on every trade);
* `TARGETS` {name: multiple of the stop or None} - None = out only by the stop or the exit signal;
* `REPO_OF` {name: "owner/repo"};
* `RULE_OF` {name: one plain sentence - entry, exit, and the repo file it came from};
* `NOT_PORTED` {"owner/repo": why its strategy cannot run in this engine}.

Every name starts with `gh_`; a name in two batches is an error, never a silent overwrite.
"""
from __future__ import annotations

import importlib

# ONE stop for a strategy whose repo has none: 2% - the widest the rooms allow (watcher_policy max_sl).
# Two stops doubled every trade list: BTC's 15m, 1h and 1d alone came to 2.6 MB a coin, ~5 GB for the
# market, more than the collect or a page can hold (smoke run, Nov 18, 2026).
DEFAULT_STOPS = (0.02,)
BATCHES = ("classic_a", "classic_b", "ml", "rest", "baseline")

STRATEGIES: dict = {}
GRID: dict = {}
STOPS: dict = {}
TARGETS: dict = {}
REPO_OF: dict = {}
RULE_OF: dict = {}
NOT_PORTED: dict = {}
LOADED: list = []


def _merge():
    for b in BATCHES:
        try:
            m = importlib.import_module(f"{__name__}.{b}")
        except ModuleNotFoundError as exc:
            if exc.name == f"{__name__}.{b}":
                continue                    # a batch not written yet
            raise
        LOADED.append(b)
        for name in m.STRATEGIES:
            if not name.startswith("gh_"):
                raise ValueError(f"{b}: strategy {name!r} must start with gh_")
            if name in STRATEGIES:
                raise ValueError(f"{b}: strategy {name!r} is already defined by another batch")
            for table in ("GRID", "TARGETS", "REPO_OF", "RULE_OF"):
                if name not in getattr(m, table):
                    raise ValueError(f"{b}: strategy {name!r} has no {table} entry")
        STRATEGIES.update(m.STRATEGIES)
        GRID.update(m.GRID)
        TARGETS.update(m.TARGETS)
        REPO_OF.update(m.REPO_OF)
        RULE_OF.update(m.RULE_OF)
        STOPS.update({n: tuple(getattr(m, "STOPS", {}).get(n, DEFAULT_STOPS)) for n in m.STRATEGIES})
        for repo, why in getattr(m, "NOT_PORTED", {}).items():
            NOT_PORTED.setdefault(repo, why)


_merge()


def combos() -> list[dict]:
    """Every strategy x setting x stop of one coin-timeframe, in skill_bt.measure's shape."""
    out = []
    for name, settings in GRID.items():
        r = TARGETS.get(name)
        for params in settings:
            for stop in STOPS[name]:
                out.append({"strategy": name, "params": params, "stop": stop,
                            "target": round(stop * r, 6) if r else None})
    return out
