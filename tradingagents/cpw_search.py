"""THE CRYPTO-PREDICTOR SWITCH SEARCH, started from this PC (Oct 19, 2026).

The operator: "use the strategy and switches and come up with best combination
for all coins", then "use the best combination and see what's setting will
win" and "One run first". The machines run .github/workflows/cpw.yml
(.github/scripts/cpw_shard.py); this module deals the market between BOTH
GitHub accounts and starts one run on each — the 40-machine rule (CLAUDE.md):
each account's claim board lives in its own repository, so two runs left to
find the coins themselves would each measure the whole market.

    python -m tradingagents.cpw_search dispatch [label]

The run ids are kept in <store>/cpw/state.json for the collect.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKFLOW = "cpw.yml"
SHARDS = 20                       # machines per account (MACHINES_PER_ACCOUNT)
TIMEFRAMES = "15m,30m,1h,4h,1d"


def home() -> Path:
    from tradingagents import market_sweep as msw

    p = Path(msw.HOME) / "cpw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def title_of(label: str) -> str:
    """The run-name cpw.yml gives a dispatch — how its run is found."""
    return f"Crypto-Predictor search · {label}"


def _gh(*args: str, timeout: int = 120) -> str:
    from tradingagents import cloud_sweep as cs

    return cs._gh(*args, timeout=timeout)


def _runs(repo: str, limit: int = 10) -> list:
    return json.loads(_gh("run", "list", "--repo", repo, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json", "databaseId,displayTitle,createdAt"))


def _start(repo: str, inputs: dict) -> int:
    """Start cpw.yml on `repo` and return ITS run id, found by its title."""
    want = title_of(inputs["label"])
    before = {int(r["databaseId"]) for r in _runs(repo)}
    args = ["workflow", "run", WORKFLOW, "--repo", repo]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    for _ in range(45):
        time.sleep(2)
        for r in _runs(repo):
            if int(r["databaseId"]) not in before and str(r["displayTitle"]).strip() == want:
                return int(r["databaseId"])
    raise RuntimeError(f"the {WORKFLOW} run on {repo} ({want}) did not appear within 90 seconds")


def dispatch(label: str | None = None, *, days: int = 30, base: float = 5.0) -> dict:
    """Deal the exchange's whole market between every account that can run
    now (round robin, cloud_sweep.split_coins) and start one run on each. An
    account that refuses, or cannot be brought up to this code, is NAMED and
    the others still run."""
    from tradingagents import cloud_sweep as cs
    from tradingagents import forecast_v2_daily as fd
    from tradingagents.positions_view import fmt_when

    ready, refused = fd.fleets_now()
    if not ready:
        raise RuntimeError("no GitHub account can run the search: " + "; ".join(refused))
    coins = fd.market()
    piles = cs.split_coins(coins, len(ready))
    label = label or fmt_when(time.time())
    origin = cs.origin_fleet()
    runs, named = {}, list(refused)
    for k, (repo, pile) in enumerate(zip(ready, piles, strict=False)):
        if repo != origin:
            drift = cs.sync_fleet(repo)
            if drift:
                named.append(f"{repo}: not brought up to this code ({drift})")
                continue
        inputs = {"shards": str(SHARDS), "timeframes": TIMEFRAMES,
                  "coin_list": ",".join(pile), "days": str(days), "base": f"{base:g}",
                  "label": f"{label} · {k + 1} of {len(ready)}"}
        try:
            runs[repo] = {"run": _start(repo, inputs), "coins": len(pile),
                          "label": inputs["label"]}
        except Exception as exc:                               # noqa: BLE001
            named.append(f"{repo}: {str(exc)[:160]}")
    state = {"label": label, "started": time.time(), "started_at": fmt_when(time.time()),
             "coins": len(coins), "runs": runs, "refused": named}
    tmp = home() / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(home() / "state.json")
    return state


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "dispatch":
        print(json.dumps(dispatch(sys.argv[2] if len(sys.argv) > 2 else None), indent=2))
    else:
        print("usage: python -m tradingagents.cpw_search dispatch [label]")
