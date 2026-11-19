"""THE LUCK BAR FOR THE REVIEWED REPOS' STRATEGIES: random entries through the same engine (Nov 18, 2026).

BEST-PRACTICES.md 3.2 (knowledge/github-repos/): a result means something only if it beats random
entries run through the SAME rules and costs (Thomas-lcb's random agent, tmr-crypto's 1,000 random
runs). These enter on a coin flip: a candle is an entry when a hash of its open time and the seed
falls under `rate`, long or short by another bit of that hash, and the trade is closed after `hold`
candles (or earlier by its stop, like every other strategy). The hash makes it the same signal
whatever the frame's length (cut-invariant) and the same on every machine.
"""
from __future__ import annotations

import hashlib

import numpy as np

from tradingagents.skill_ta import _to_signals


def _u(ts_ns: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Two uniform numbers in [0, 1) per candle, from a hash of (seed, the candle's open time)."""
    a, b = np.empty(len(ts_ns)), np.empty(len(ts_ns))
    for i, t in enumerate(ts_ns.tolist()):
        h = hashlib.blake2b(f"{seed}:{t}".encode(), digest_size=16).digest()
        a[i] = int.from_bytes(h[:8], "big") / 2 ** 64
        b[i] = int.from_bytes(h[8:], "big") / 2 ** 64
    return a, b


class RandomEntries:
    name = "gh_random"

    def signals_all(self, df, params):
        rate, hold, seed = float(params["rate"]), int(params["hold"]), int(params["seed"])
        n = len(df)
        u, side = _u(df.index.asi8, seed)
        go = u < rate
        long_in, short_in = go & (side < 0.5), go & (side >= 0.5)
        long_in[0] = short_in[0] = False
        # a long entered at candle j is closed at j + hold (a short likewise), unless its stop came
        # first: the exit is tied to the entry candle, never to a guess of what the engine holds
        long_out, short_out = np.zeros(n, bool), np.zeros(n, bool)
        long_out[hold:], short_out[hold:] = long_in[:-hold], short_in[:-hold]
        return _to_signals(n, 1, long_in, short_in, long_out, short_out)


STRATEGIES = {"gh_random": RandomEntries()}
GRID = {"gh_random": [{"rate": 0.02, "hold": 10, "seed": 1}, {"rate": 0.02, "hold": 10, "seed": 2}]}
TARGETS = {"gh_random": None}
REPO_OF = {"gh_random": "luck-bar/random-entries"}
RULE_OF = {"gh_random": "Random entries (our luck bar, not a repo): about 2 candles in 100 enter, long "
                        "or short on a coin flip, out after 10 candles or at the stop - two seeds."}
NOT_PORTED: dict = {}
