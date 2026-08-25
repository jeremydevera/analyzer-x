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

import contextlib
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

WORKFLOW = "Market sweep (15m / 30m)"
ARTIFACT = "sweep-results"


logger = logging.getLogger(__name__)


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
    """Can we dispatch right now? Returns (ok, why-not).

    Judged by whether the thing we NEED works, not by how `gh auth status`
    feels about it. That command exits non-zero when ANY configured account is
    unhealthy — the operator's keyring token was invalid all day on
    2026-08-25 — while `gh workflow list` answered fine through another
    credential. The strict check made the hand-off button vanish and reported
    "gh is not logged in" about a CLI that was, demonstrably, logged in.

    So: no auth pre-flight. Ask for the workflow list; if that answers, we can
    dispatch, and if it does not, its own error is the honest reason.
    """
    try:
        slug = repo_slug()
    except CloudError as exc:
        return False, str(exc)
    try:
        wf = json.loads(_gh("workflow", "list", "--repo", slug, "--json",
                            "name,state"))
    except CloudError as exc:
        msg = str(exc)
        if "auth" in msg.lower() or "login" in msg.lower():
            msg += " — run `gh auth refresh -h github.com`"
        return False, msg
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
    plan = [j for j in d.get("jobs", []) if j["name"] == "plan"]
    done = sum(1 for j in jobs if j["status"] == "completed")
    running = sum(1 for j in jobs if j["status"] == "in_progress")
    queued = sum(1 for j in jobs if j["status"] in ("queued", "waiting",
                                                    "pending"))
    # GitHub gives a free repo about 20 concurrent jobs. Two 20-shard runs at
    # once means the second one waits, which looks like "nothing is happening"
    # unless the panel says so.
    waiting = (not jobs and plan
               and plan[0].get("status") in ("queued", "waiting", "pending"))
    return {"status": d.get("status"), "conclusion": d.get("conclusion"),
            "url": d.get("url"), "shards": len(jobs), "shards_done": done,
            "running": running, "queued": queued,
            "waiting_for_runners": bool(waiting),
            "started": (plan[0].get("startedAt") if plan else None),
            "jobs": [{"name": j["name"], "status": j["status"],
                       "conclusion": j.get("conclusion"),
                       "startedAt": j.get("startedAt"),
                       "completedAt": j.get("completedAt"),
                       # the step a machine is on right now — the only live
                       # detail GitHub exposes before a job's log is released
                       "step": next((st_["name"] for st_ in (j.get("steps") or [])
                                     if st_.get("status") == "in_progress"),
                                    None)}
                     for j in jobs],
            "failed": sum(1 for j in jobs if j.get("conclusion") == "failure")}


PROGRESS_BRANCH = "sweep-progress"


def live_progress(run_id: int, slug: str | None = None) -> list:
    """What each machine says it is doing, right now.

    GitHub serves no log for a running job, so the shards publish a small file
    each — ``progress/run-<id>/shard-<n>.json`` on an orphan branch. This reads
    them back. Empty list simply means nothing has reported yet.
    """
    slug = slug or repo_slug()
    path = f"progress/run-{run_id}"
    try:
        listing = json.loads(_gh(
            "api", f"repos/{slug}/contents/{path}?ref={PROGRESS_BRANCH}",
            timeout=45))
    except CloudError:
        return []
    out = []
    for f in listing if isinstance(listing, list) else []:
        try:
            # --jq .content prints the raw base64 string, not JSON, so it must
            # not be passed through json.loads first.
            blob = _gh("api", f["url"], "--jq", ".content", timeout=45)
        except CloudError:
            continue
        try:
            import base64

            out.append(json.loads(base64.b64decode(blob.strip())))
        except Exception:
            continue
    return sorted(out, key=lambda d: d.get("shard", 0))


def fetch(run_id: int, slug: str | None = None) -> list:
    """Download the finished artifact and return its rows."""
    slug = slug or repo_slug()
    with tempfile.TemporaryDirectory() as tmp:
        _gh("run", "download", str(run_id), "--repo", slug, "-n", ARTIFACT,
            "-D", tmp, timeout=900)
        rows, bad = [], 0
        for f in Path(tmp).rglob("*.jsonl"):
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    # One truncated line (a runner killed at the 6h ceiling)
                    # used to raise here and return NOTHING, throwing away a
                    # whole sweep's measured rows. Skip it and count it.
                    bad += 1
    if bad:
        logger.warning("cloud sweep: skipped %d unparseable row line(s) — "
                       "a shard was truncated; %d rows kept", bad, len(rows))
    return rows


RUNFILE = Path(os.path.expanduser("~/.tradingagents/backtest/cloud_run.json"))


def remember(run: dict) -> None:
    """Persist the run being watched, so it survives a browser reload, a tab
    switch, or the app restarting. Session state does not."""
    RUNFILE.parent.mkdir(parents=True, exist_ok=True)
    RUNFILE.write_text(json.dumps(run))


def remembered() -> dict:
    try:
        return json.loads(RUNFILE.read_text())
    except (OSError, ValueError):
        return {}


def forget() -> None:
    with contextlib.suppress(OSError):
        RUNFILE.unlink()


def cancel(run_id: int, slug: str | None = None) -> None:
    """Cancel a run on GitHub. The machines stop; nothing is charged."""
    _gh("run", "cancel", str(run_id), "--repo", slug or repo_slug())


def unmeasured(coins, tfs) -> list:
    """The coins the local sweep has NOT finished, for a hand-off.

    Pointing the cloud at everything would have it re-measure pairs the Mac
    already holds, and `merge_into_store` REPLACES what it covers — cloud rows
    would land behind the Mac's own watermark, so the next local update would
    add new bars on top of someone else's measurement.
    """
    from tradingagents import market_sweep as msw

    left = []
    for c in coins:
        if any(msw.pair_watermark(c.replace("_USDT", ""), tf) == 0 for tf in tfs):
            left.append(c)
    return left


def merge_into_store(rows: list) -> dict:
    """Fold cloud rows into the local Back Test store, per coin/timeframe.

    Cloud rows are a fresh full-history measurement, so they REPLACE the stored
    rows for the pairs they cover and leave every other pair alone.
    """
    from tradingagents import market_sweep as msw

    by: dict[tuple[str, str], list] = {}
    for r in rows:
        by.setdefault((r["coin"], r["tf"]), []).append(r)
    kept, skipped = 0, []
    for (coin, tf), rs in by.items():
        # NEVER overwrite a pair the Mac finished. Its rows sit behind a
        # watermark that says every bar up to X was tested for every
        # combination; replacing the rows while leaving that watermark makes
        # the next local update extend a measurement it did not make.
        if msw.pair_watermark(coin, tf) > 0:
            skipped.append(f"{coin} {tf}")
            continue
        msw.save_pair_rows(coin, tf, rs)
        # Record HOW CURRENT the measurement is, and that a machine other than
        # this one made it.
        #
        # Without a watermark the pair reads as unmeasured: the progress
        # counter undercounts it and the storage screen calls it interrupted.
        # With a watermark but no per-combination state, a later UPDATE would
        # resume every combination from that bar with no ladder or running
        # totals behind it — extending a measurement it never made. The
        # `__cloud__` mark is what stops that: run_pair treats it as a full
        # recompute, so the rows are trusted and the resume point is not.
        last_ms = max(int(r.get("last_ms") or 0) for r in rs)
        if last_ms:
            msw.save_states(coin, tf, {"__last_ms__": last_ms,
                                       "__cloud__": True})
        kept += 1
    return {"pairs": kept, "rows": len(rows),
            "coins": len({c for c, _ in by}),
            "skipped": len(skipped), "skipped_pairs": skipped[:20],
            "why_skipped": ("already measured locally — a cloud row would "
                            "land behind the Mac's own watermark"
                            if skipped else "")}
