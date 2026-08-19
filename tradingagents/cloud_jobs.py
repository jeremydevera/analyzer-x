"""Dispatch any repo workflow on GitHub and hand back the run's URL.

`cloud_sweep` is welded to the market-sweep workflow; this is the generic
door the Download and Backtest buttons use. Results do not come back through
here — candles land in the market database, backtest rows in
backtest_results, and the report page hangs off the run as an artifact.
"""

from __future__ import annotations

import json
import time

from tradingagents.cloud_sweep import CloudError, _gh, repo_slug


def available() -> tuple[bool, str]:
    try:
        slug = repo_slug()
        _gh("auth", "status", timeout=20)
        return True, slug
    except CloudError as exc:
        return False, str(exc)
    except Exception as exc:            # gh missing, not a repo, offline
        return False, str(exc)[:120]


def dispatch(workflow_file: str, inputs: dict[str, str]) -> dict:
    """Start `workflow_file` (e.g. "download.yml") with `inputs`.

    Returns {"id": run_id, "url": html_url}. The workflow must exist on the
    default branch at GitHub — push first, or the dispatch 404s.
    """
    slug = repo_slug()
    before = {r["databaseId"] for r in _runs(slug, workflow_file)}
    args = ["workflow", "run", workflow_file, "--repo", slug]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    _gh(*args)
    # `gh workflow run` prints no id; wait for a run that wasn't there before.
    for _ in range(30):
        time.sleep(2)
        for r in _runs(slug, workflow_file):
            if r["databaseId"] not in before:
                return {"id": r["databaseId"],
                        "url": f"https://github.com/{slug}/actions/runs/"
                               f"{r['databaseId']}"}
    return {"id": 0, "url": f"https://github.com/{slug}/actions"}


def _runs(slug: str, workflow_file: str, limit: int = 5) -> list:
    try:
        return json.loads(_gh(
            "run", "list", "--repo", slug, "--workflow", workflow_file,
            "--limit", str(limit), "--json", "databaseId,status"))
    except Exception:
        return []
