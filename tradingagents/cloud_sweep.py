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
import pathlib
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
             min_days: int = 0, days: int = 365) -> dict:
    """Start a run and return its id and url. `days` is the history window the
    shards measure -- the same number the Backtest screen sends the local job."""
    ok, slug = available()
    if not ok:
        raise CloudError(slug)
    before = _runs(slug, limit=1)
    _gh("workflow", "run", WORKFLOW, "--repo", slug,
        "-f", f"shards={shards}", "-f", f"coins={coins}",
        "-f", f"timeframes={timeframes}", "-f", f"min_days={min_days}",
        "-f", f"days={days}")
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


_STATUS_CACHE: dict = {"at": 0.0, "run": None, "payload": None,
                       "failed_at": 0.0, "why": ""}
# The one remaining API call per poll. Cached, because the panel polls every
# 4 s and GitHub's SECONDARY limit for Actions endpoints does not care that the
# primary budget is untouched: it 403'd this user for hours on 2026-09-02.
STATUS_CACHE_S = 30.0
STATUS_FAIL_S = 120.0


def status(run_id: int, slug: str | None = None) -> dict:
    """Where a run is, shard by shard. Cached, and a rate-limited answer serves
    the last good one rather than blanking the panel."""
    import time as _t

    now = _t.time()
    c = _STATUS_CACHE
    fresh = c["run"] == run_id and c["payload"] is not None
    if fresh and now - c["at"] < STATUS_CACHE_S:
        return c["payload"]
    if fresh and now - c["failed_at"] < STATUS_FAIL_S:
        # still inside a failure window: the run's own state is unknown, so say
        # so on the payload instead of pretending it changed
        out = dict(c["payload"])
        out["stale"] = True
        out["stale_why"] = c["why"]
        return out
    slug = slug or repo_slug()
    try:
        d = json.loads(_gh("run", "view", str(run_id), "--repo", slug, "--json",
                           "status,conclusion,url,jobs"))
    except CloudError as exc:
        c.update(failed_at=now, why=str(exc)[:200])
        if fresh:
            out = dict(c["payload"])
            out["stale"] = True
            out["stale_why"] = str(exc)[:200]
            return out
        raise
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
    payload = {"status": d.get("status"), "conclusion": d.get("conclusion"),
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
    _STATUS_CACHE.update(at=_t.time(), run=run_id, payload=payload,
                         failed_at=0.0, why="")
    return payload


PROGRESS_BRANCH = "sweep-progress"


_PROGRESS_CACHE: dict = {"at": 0.0, "run": None, "rows": []}
# how long a read of the progress branch is reused. The panel polls every 4 s;
# the shards write every few seconds at most.
PROGRESS_CACHE_S = 15.0
# how long a fetch failure is remembered, so a network blip does not turn into
# a fetch per poll
FETCH_FAIL_S = 60.0
_FETCH_FAILED_AT = [0.0]


def _git(*args, timeout: int = 120) -> str:
    """Run git in the repository, quietly. Raises CloudError on failure."""
    root = pathlib.Path(__file__).resolve().parent.parent
    try:
        p = subprocess.run(("git", *args), cwd=str(root), capture_output=True,
                           text=True, timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001
        raise CloudError(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
    if p.returncode:
        raise CloudError(f"git {args[0]}: {(p.stderr or '').strip()[:160]}")
    return p.stdout


def live_progress(run_id: int, slug: str | None = None) -> list:
    """What each machine says it is doing, right now — read over GIT.

    GitHub serves no log for a running job, so the shards publish a small file
    each: ``progress/run-<id>/shard-<n>.json`` on the ``sweep-progress``
    branch. Reading those through the CONTENTS API cost 21 calls a poll and
    tripped GitHub's secondary rate limit for hours (see the note above), which
    blinded this panel while the run was healthy. `git fetch` + `git show`
    reads the same bytes with no API and no budget.

    Empty list means nothing has reported yet. A fetch that fails is remembered
    for a minute and the last good rows are served meanwhile — a stale row is
    labelled by its own `note`, an empty panel is not.
    """
    import time as _t

    now = _t.time()
    c = _PROGRESS_CACHE
    if c["run"] == run_id and now - c["at"] < PROGRESS_CACHE_S:
        return c["rows"]

    if now - _FETCH_FAILED_AT[0] > FETCH_FAIL_S:
        try:
            _git("fetch", "--quiet", "origin",
                 f"{PROGRESS_BRANCH}:refs/remotes/origin/{PROGRESS_BRANCH}",
                 "--force", timeout=180)
        except CloudError as exc:
            _FETCH_FAILED_AT[0] = now
            print(f"[cloud] could not fetch {PROGRESS_BRANCH}: {exc}",
                  flush=True)

    path = f"progress/run-{run_id}/"
    try:
        names = [n for n in _git("ls-tree", "--name-only",
                                 f"origin/{PROGRESS_BRANCH}", path,
                                 timeout=60).split() if n.endswith(".json")]
    except CloudError:
        return c["rows"] if c["run"] == run_id else []
    out = []
    for n in names:
        try:
            out.append(json.loads(_git("show", f"origin/{PROGRESS_BRANCH}:{n}",
                                       timeout=60)))
        except Exception:                                      # noqa: BLE001
            continue
    out.sort(key=lambda d: d.get("shard", 0))
    c.update(at=now, run=run_id, rows=out)
    return out


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


def artifact_names(run_id: int, slug: str | None = None) -> list[str]:
    """The artifacts a run really produced, newest measurement first.

    `ARTIFACT` ("sweep-results") is written by the workflow's `merge` job, and
    on 2026-08-25 that job was OOM-killed: it loads every row into one Python
    list, and 29.7 million of them is about 12 GB on a 7 GB runner. So the only
    artifact that existed was the twenty per-shard `rows-N` uploads -- 3.3 GB of
    measured rows -- and the collector, which asked for `sweep-results` and
    nothing else, reported "no usable artifact" and released the run.

    The per-shard artifacts ARE the measurement. The merge job only concatenates
    them. So they are what this prefers, and the merged file is the fallback.
    """
    slug = slug or repo_slug()
    try:
        raw = json.loads(_gh("api", f"repos/{slug}/actions/runs/{run_id}"
                                    "/artifacts?per_page=100"))
    except Exception as exc:                       # noqa: BLE001
        logger.warning("cloud sweep: cannot list artifacts for %s: %s",
                       run_id, str(exc)[:80])
        return []
    live = [a["name"] for a in (raw.get("artifacts") or [])
            if not a.get("expired")]
    shards = sorted((n for n in live if n.startswith("rows-")),
                    key=lambda n: int(n.split("-", 1)[1])
                    if n.split("-", 1)[1].isdigit() else 0)
    return shards or [n for n in live if n == ARTIFACT]


def collect_into_store(run_id: int, slug: str | None = None, *,
                       on_progress=None) -> dict:
    """Stream a finished run's artifacts straight into the pair store.

    `fetch()` builds one list of every row. At 29.7 million rows that is more
    memory than this Mac should be asked for while it is also measuring, and it
    is exactly how the cloud's own merge job died. So nothing is accumulated:
    each shard file is read a line at a time and each (coin, timeframe) is
    written the moment the pair changes.

    Shards write `for coin: for tf:`, so a pair's rows are contiguous in the
    file. That is not RELIED on -- a pair seen again after being written is
    appended to rather than replacing what is already there -- but it is why
    peak memory is one pair rather than one shard.
    """
    from tradingagents import market_sweep as msw

    slug = slug or repo_slug()
    names = artifact_names(run_id, slug)
    if not names:
        return {"pairs": 0, "rows": 0, "coins": 0, "skipped": 0,
                "artifacts": 0, "why": "the run produced no live artifact"}

    written: set = set()
    skipped: list = []
    kept = rows_seen = bad = 0
    coins: set = set()

    def flush(key, buf):
        nonlocal kept
        if not key or not buf:
            return
        coin, tf = key
        # A pair refused once stays refused. It has to be its OWN set: marking
        # it in `written` would make the second sighting of the same pair take
        # the append branch below and overwrite the very rows being protected.
        if key in refused:
            return
        # NEVER overwrite a pair the Mac finished: its watermark promises every
        # bar up to X was tested for every combination, and replacing the rows
        # under that promise makes the next local update extend a measurement
        # it did not make.
        if key not in written and msw.pair_watermark(coin, tf) > 0:
            refused.add(key)                   # do not re-check it per line
            skipped.append(f"{coin} {tf}")
            return
        if key in written:                     # a pair split across the file
            buf = msw.pair_rows(coin, tf) + buf
        else:
            kept += 1
        msw.save_pair_rows(coin, tf, buf)
        last_ms = max(int(r.get("last_ms") or 0) for r in buf)
        if last_ms:
            # __last_ms__ LAST. `pair_watermark` reads the final 256 bytes and
            # its regex anchors the key to the closing brace, so writing it
            # first made every cloud-merged pair read as watermark 0 -- that is
            # "never measured", which undercounts the progress bar and invites
            # a re-sweep of work already done.
            msw.save_states(coin, tf, {"__cloud__": True,
                                       "__last_ms__": last_ms})
        written.add(key)
        coins.add(coin)

    refused: set = set()
    for n, name in enumerate(names, 1):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                _gh("run", "download", str(run_id), "--repo", slug,
                    "-n", name, "-D", tmp, timeout=1800)
            except Exception as exc:           # noqa: BLE001
                logger.warning("cloud sweep: %s did not download: %s",
                               name, str(exc)[:80])
                continue
            for f in sorted(Path(tmp).rglob("*.jsonl")):
                key, buf = None, []
                with f.open(encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        try:
                            r = json.loads(line)
                        except ValueError:
                            # a runner killed at the 6h ceiling truncates its
                            # last line; skipping it must not lose the file
                            bad += 1
                            continue
                        rows_seen += 1
                        k = (r["coin"], r["tf"])
                        if k != key:
                            flush(key, buf)
                            key, buf = k, []
                        buf.append(r)
                flush(key, buf)
        if on_progress:
            on_progress(name, n, len(names), kept, rows_seen)
    if bad:
        logger.warning("cloud sweep: skipped %d unparseable line(s); "
                       "%d rows kept", bad, rows_seen)
    return {"pairs": kept, "rows": rows_seen, "coins": len(coins),
            "artifacts": len(names), "skipped": len(skipped),
            "skipped_pairs": skipped[:20], "unparseable": bad,
            "why_skipped": ("already measured locally — a cloud row would land "
                            "behind the Mac's own watermark" if skipped else "")}


RUNFILE = Path(os.path.expanduser("~/.tradingagents/backtest/cloud_run.json"))


def working_run(slug: str | None = None) -> dict | None:
    """The sweep run that is actually MEASURING right now, if any.

    `remembered()` holds the LAST DISPATCHED run, which is not the same thing:
    on 2026-08-25 three runs existed at once and the orchestrator adopted a
    QUEUED one while a different run had 20 shards live and half a million rows
    per shard. It then reported "0/0 shards" for twenty minutes while the cloud
    was, in fact, most of the way through the grid.

    Prefers a run with shards genuinely running over one merely not-completed.
    """
    slug = slug or repo_slug()
    try:
        rows = json.loads(_gh(
            "run", "list", "--repo", slug, "--workflow", WORKFLOW,
            "--limit", "8", "--json", "databaseId,status,conclusion"))
    except CloudError:
        return None
    live = [r for r in rows if r.get("status") == "in_progress"]
    for r in live:                       # a run whose shards have started wins
        try:
            st = status(int(r["databaseId"]), slug)
        except CloudError:
            continue
        if int(st.get("running") or 0) > 0:
            return {"id": int(r["databaseId"]), "repo": slug}
    if live:
        return {"id": int(live[0]["databaseId"]), "repo": slug}
    return None


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
            # __last_ms__ LAST. `pair_watermark` reads the final 256 bytes and
            # its regex anchors the key to the closing brace, so writing it
            # first made every cloud-merged pair read as watermark 0 -- that is
            # "never measured", which undercounts the progress bar and invites
            # a re-sweep of work already done.
            msw.save_states(coin, tf, {"__cloud__": True,
                                       "__last_ms__": last_ms})
        kept += 1
    return {"pairs": kept, "rows": len(rows),
            "coins": len({c for c, _ in by}),
            "skipped": len(skipped), "skipped_pairs": skipped[:20],
            "why_skipped": ("already measured locally — a cloud row would "
                            "land behind the Mac's own watermark"
                            if skipped else "")}
