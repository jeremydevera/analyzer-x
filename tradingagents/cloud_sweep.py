"""Run the market sweep on GitHub's machines instead of this one.

The Back Test tab's RUN ALL COINS can send the work to GitHub Actions: 20
runners in parallel, free on a public repo, laptop untouched. This module is the
bridge — dispatch, watch, fetch, merge.

It shells out to the `gh` CLI rather than handling a token itself. `gh` is
already logged in on this machine, its credentials live in the system keyring,
and nothing secret is written into the repo or passed on a command line.

The sweep needs NO exchange credentials: candles, funding, order books, fees and
liquidation are all MEXC public data, which is the only reason it can run on
someone else's hardware at all.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

WORKFLOW = "Market sweep (15m / 30m)"
ARTIFACT = "sweep-results"


class CloudError(RuntimeError):
    """gh is missing, not logged in, or the repo has no workflow."""


def _gh(*args: str, timeout: int = 120) -> str:
    try:
        out = subprocess.run(("gh",) + args, capture_output=True, text=True,
                             timeout=timeout)
    except FileNotFoundError as exc:
        raise CloudError("the GitHub CLI (gh) is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise CloudError(f"gh timed out: {' '.join(args)}") from exc
    if out.returncode != 0:
        raise CloudError((out.stderr or out.stdout or "gh failed").strip()[:300])
    return out.stdout


def repo_slug(cwd: str | None = None) -> str:
    """The GitHub repo this checkout pushes to, e.g. ``owner/name``."""
    try:
        out = subprocess.run(["git", "remote", "-v"], capture_output=True,
                             text=True, cwd=cwd, timeout=20).stdout
    except Exception as exc:
        raise CloudError(f"cannot read git remotes: {exc}") from exc
    best = None
    for line in out.splitlines():
        if "github.com" not in line or "(push)" not in line:
            continue
        name, url = line.split()[0], line.split()[1]
        slug = url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
        # a remote the operator added for their own copy wins over `origin`,
        # which on this checkout still points at the upstream project
        if name != "origin":
            return slug
        best = best or slug
    if not best:
        raise CloudError("no GitHub remote found")
    return best


def available() -> tuple[bool, str]:
    """Can we dispatch right now? Returns (ok, why-not)."""
    try:
        _gh("auth", "status", timeout=30)
    except CloudError as exc:
        return False, f"gh is not logged in ({exc})"
    try:
        slug = repo_slug()
    except CloudError as exc:
        return False, str(exc)
    try:
        wf = json.loads(_gh("workflow", "list", "--repo", slug, "--json",
                            "name,state"))
    except CloudError as exc:
        return False, str(exc)
    if not any(w["name"] == WORKFLOW for w in wf):
        return False, f"{slug} has no '{WORKFLOW}' workflow"
    return True, slug


def dispatch(*, shards: int = 20, coins: int = 0, timeframes: str = "15m,30m",
             min_days: int = 365) -> dict:
    """Start a run and return its id and url."""
    ok, slug = available()
    if not ok:
        raise CloudError(slug)
    before = _runs(slug, limit=1)
    _gh("workflow", "run", WORKFLOW, "--repo", slug,
        "-f", f"shards={shards}", "-f", f"coins={coins}",
        "-f", f"timeframes={timeframes}", "-f", f"min_days={min_days}")
    # `gh workflow run` prints no id, so wait for a run newer than the last one
    old = before[0]["databaseId"] if before else 0
    for _ in range(30):
        time.sleep(2)
        runs = _runs(slug, limit=1)
        if runs and runs[0]["databaseId"] != old:
            r = runs[0]
            return {"id": r["databaseId"], "url": r["url"], "repo": slug,
                    "started": time.strftime("%Y-%m-%d %H:%M")}
    raise CloudError("the run did not appear within a minute")


def _runs(slug: str, limit: int = 5) -> list:
    return json.loads(_gh("run", "list", "--repo", slug, "--workflow", WORKFLOW,
                          "--limit", str(limit), "--json",
                          "databaseId,status,conclusion,url,createdAt"))


def status(run_id: int, slug: str | None = None) -> dict:
    """Where a run is, shard by shard."""
    slug = slug or repo_slug()
    d = json.loads(_gh("run", "view", str(run_id), "--repo", slug, "--json",
                       "status,conclusion,url,jobs"))
    jobs = [j for j in d.get("jobs", []) if j["name"].startswith("sweep")]
    done = sum(1 for j in jobs if j["status"] == "completed")
    return {"status": d.get("status"), "conclusion": d.get("conclusion"),
            "url": d.get("url"), "shards": len(jobs), "shards_done": done,
            "failed": sum(1 for j in jobs if j.get("conclusion") == "failure")}


def fetch(run_id: int, slug: str | None = None) -> list:
    """Download the finished artifact and return its rows."""
    slug = slug or repo_slug()
    with tempfile.TemporaryDirectory() as tmp:
        _gh("run", "download", str(run_id), "--repo", slug, "-n", ARTIFACT,
            "-D", tmp, timeout=900)
        rows = []
        for f in Path(tmp).rglob("*.jsonl"):
            for line in f.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def merge_into_store(rows: list) -> dict:
    """Fold cloud rows into the local Back Test store, per coin/timeframe.

    Cloud rows are a fresh full-history measurement, so they REPLACE the stored
    rows for the pairs they cover and leave every other pair alone.
    """
    from tradingagents import market_sweep as msw

    by: dict[tuple[str, str], list] = {}
    for r in rows:
        by.setdefault((r["coin"], r["tf"]), []).append(r)
    for (coin, tf), rs in by.items():
        msw.save_pair_rows(coin, tf, rs)
    return {"pairs": len(by), "rows": len(rows),
            "coins": len({c for c, _ in by})}
