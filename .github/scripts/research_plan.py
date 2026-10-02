"""The research run's matrix: the replay shards that hold coins x the slices
(Oct 02, 2026).

The replay hands its coins out first come, first served, so run 37007971331
put all 1,098 coins on 19 of its 40 machines; the other 21 uploaded a
replay-<N> of ~600 bytes holding nothing. A research job on one of those
measures nothing, and GitHub refuses a matrix of more than 256 jobs — so the
slices a big round needs (19 x 13 = 247) fit only without them.

Prints `shards=[...]` and `chunks=[...]` for $GITHUB_OUTPUT; every shard it
leaves out is named on stderr. A shard whose artifact cannot be seen at all is
KEPT (its download then fails by name) — never silently dropped, and a listing
that cannot be read keeps every shard.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

EMPTY_BYTES = 4096       # a shard with coins is megabytes; an empty one ~600 B
MATRIX_MAX = 256         # GitHub's own ceiling for one matrix


def pick(n: int, sizes: dict | None) -> tuple[list[int], list[int]]:
    """(shards to research, shards left out as empty) of `n`, from the
    source run's artifact sizes ({name: bytes}, None = unreadable)."""
    if sizes is None:
        return list(range(n)), []
    keep, empty = [], []
    for i in range(n):
        got = sizes.get(f"replay-{i}")
        (empty if got is not None and got <= EMPTY_BYTES else keep).append(i)
    return keep, empty


def artifact_sizes(repo: str, run: str, token: str) -> dict | None:
    out: dict = {}
    page = 1
    try:
        while True:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/runs/{run}/artifacts?per_page=100&page={page}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                got = json.load(r)
            arts = got.get("artifacts") or []
            for a in arts:
                if not a.get("expired"):
                    out[a["name"]] = int(a["size_in_bytes"])
            if len(arts) < 100:
                return out
            page += 1
    except Exception as e:  # noqa: BLE001 — a listing we cannot read keeps every shard
        print(f"could not list run {run}'s artifacts ({type(e).__name__}: {e}); "
              "researching every shard", file=sys.stderr)
        return None


def main() -> int:
    n = int(os.environ["N"])
    chunks = max(1, int(os.environ.get("C") or 1))
    sizes = artifact_sizes(os.environ["REPO"], os.environ["SRC_RUN"], os.environ.get("GH_TOKEN", ""))
    keep, empty = pick(n, sizes)
    if empty:
        print(f"left out {len(empty)} empty shard(s) of {n} (no coins): {empty}", file=sys.stderr)
    print(f"researching {len(keep)} shard(s) x {chunks} slice(s) = {len(keep) * chunks} jobs",
          file=sys.stderr)
    if len(keep) * chunks > MATRIX_MAX:
        print(f"{len(keep)} x {chunks} = {len(keep) * chunks} jobs is past GitHub's {MATRIX_MAX}; "
              f"ask for at most {MATRIX_MAX // max(1, len(keep))} slices", file=sys.stderr)
        return 1
    print("shards=" + json.dumps(keep))
    print("chunks=" + json.dumps(list(range(chunks))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
