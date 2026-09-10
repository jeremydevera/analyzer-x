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


# How long the named-coin list may be on one `gh` command line. Windows caps a
# command line at 32,767 characters and `gh` has its own ideas; 8,000 is ~600
# coins, far from both. A longer ask means "most of the market" and falls back
# to the whole board, out loud (rule 20).
MAX_COIN_LIST_CHARS = 8000


def symbols_of(coin_list) -> list:
    """The venue's own names for what the operator picked: BTC -> BTC_USDT.

    The Backtest screen holds bare coin names, the store keys on them, and the
    shard's board holds SYMBOLS. One conversion, here, so a picked coin cannot
    miss its contract by a suffix."""
    out = set()
    for c in coin_list or ():
        c = str(c).strip().upper()
        if not c:
            continue
        out.add(c if c.endswith("_USDT") else f"{c}_USDT")
    return sorted(out)


# THE WINDOW A SWEEP MEASURES WHEN NOBODY SAYS. Operator, Sep 10, 2026:
# *"i only need past 30 days not 1 year because thats too much"* — a full-year
# sweep of the whole market on 15m/30m sat at 0.9% across 20 machines after an
# hour (an implied 4.7 days) against the 2.0 h and 4.3 h their earlier runs
# took. Every caller may still pass any window; this is what a caller that
# says nothing gets, and it is the operator's explicit choice, not a silent cap
# (see "Never cap the grid with a default nobody chose" in CLAUDE.md).
SWEEP_DAYS = 30


def dispatch(*, shards: int = 20, coins: int = 0, timeframes: str = "15m,30m",
             min_days: int = 0, days: int = SWEEP_DAYS, base: float = 5.0,
             mode: str = "full", state_runs=(), live: bool = True,
             coin_list=()) -> dict:
    """Start a run and return its id and url. `days` is the history window the
    shards measure -- the same number the Backtest screen sends the local job.

    `mode` is "full" (BACKTEST: every pair from scratch) or "update" (UPDATE:
    every pair with a saved position continues over its new bars only — see
    sweep_shard.continue_pair). `state_runs` names the earlier runs whose
    `state-*` artifacts hold the latest saved positions (state_runs_for).

    `coin_list` is WHICH COINS to measure, by name. Empty means the whole
    market, which is what every caller used to mean by accident: before
    Sep 10, 2026 only the COUNT travelled (`coins`), so picking BTC and
    pressing BACKTEST measured the first coins on the shard's own alphabetical
    board — 0G, ALPINE, AVAAI… — and never BTC, which sits at position 190 of
    1,065. `coins` keeps its real meaning: the most coins ONE machine may
    claim, a cap for small runs. A named list is its own limit, so the cap
    goes to 0 and the fleet is trimmed to the list.
    """
    ok, slug = available()
    if not ok:
        raise CloudError(slug)
    mode = "update" if str(mode).lower() == "update" else "full"
    named = symbols_of(coin_list)
    coin_arg, coin_why = "", ""
    if named:
        joined = ",".join(named)
        if len(joined) > MAX_COIN_LIST_CHARS:
            coin_why = (f"{len(named)} coins is too many to name on one "
                        f"command line — measuring the whole board instead")
            logger.warning("cloud sweep: %s", coin_why)
        else:
            coin_arg = joined
            # no machine sits on an empty board, and none races another for
            # the only coin: twenty machines for a one-coin list is nineteen
            # runners starting up to find nothing to claim
            shards = max(1, min(int(shards), len(named)))
            coins = 0          # the list is the limit; the per-machine cap is not
    # THE LIVE DOOR (operator, Sep 09, 2026: "i want you to post the result
    # immediately to my pc"). Opened here, before the machines start, and its
    # public url handed to them — a machine posts each pair the moment it
    # finishes instead of leaving everything in an artifact for an hour. Never
    # fatal: without it the run is exactly what it was, artifacts and all.
    ingest_url, ingest_why = "", ""
    if live:
        try:
            from tradingagents import live_ingest as li

            got = li.ensure()
            ingest_url, ingest_why = got.get("url") or "", got.get("why") or ""
            if ingest_url:
                # the machines read the secret from the repository; a token
                # this PC rotated and never pushed is 401 on every post
                ingest_why = li.sync_secret(slug)
                if ingest_why:
                    ingest_url = ""
        except Exception as exc:                                # noqa: BLE001
            ingest_why = f"{type(exc).__name__}: {str(exc)[:120]}"
        if ingest_why:
            logger.warning("cloud sweep: no live posting this run (%s) — the "
                           "rows still ride the artifacts", ingest_why)
    before = _runs(slug, limit=1)
    _gh("workflow", "run", WORKFLOW, "--repo", slug,
        "-f", f"ingest_url={ingest_url}",
        "-f", f"shards={shards}", "-f", f"coins={coins}",
        "-f", f"timeframes={timeframes}", "-f", f"min_days={min_days}",
        # the operator's STAKE. The shard hardcoded 5.0 while the local job
        # took it from the Backtest screen, so after the move to GitHub every
        # dollar figure would have been measured at a stake nobody chose.
        "-f", f"days={days}", "-f", f"base={base}",
        "-f", f"mode={mode}",
        "-f", f"coin_list={coin_arg}",
        "-f", f"state_runs={','.join(str(x) for x in (state_runs or ()))}")
    # `gh workflow run` prints no id, so wait for a run newer than the last one
    old = before[0]["databaseId"] if before else 0
    for _ in range(30):
        time.sleep(2)
        runs = _runs(slug, limit=1)
        if runs and runs[0]["databaseId"] != old:
            r = runs[0]
            return {"id": r["databaseId"], "url": r["url"], "repo": slug,
                    "mode": mode,
                    # whether the machines are posting straight here, and why
                    # not when they are not — never a silent downgrade
                    "live": bool(ingest_url), "live_why": ingest_why,
                    # WHICH COINS were asked for by name (empty = the whole
                    # market), and why a named list could not be sent. A run
                    # that quietly measured something else is the bug this
                    # field exists to make impossible to miss.
                    "coins_named": named if coin_arg else [],
                    "coin_list_why": coin_why,
                    # what this run MEASURES, kept with the run: since the
                    # autopilot stopped dispatching (2026-09-09, "no no no, i
                    # want option to start the backtest"), button dispatches
                    # are the only kind, and the pending panel's "the busy run
                    # covers X" note needs the frames from the run's own record
                    "timeframes": [t.strip() for t in str(timeframes).split(",")
                                   if t.strip()],
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


def _fetch_progress() -> None:
    """Fetch the progress branch, surviving a LOCK RACE on its tracking ref.

    `--force` overrides a non-fast-forward; it does NOT help when another git
    process is writing the same ref at that instant, which is what happens
    when the API polls this branch while a sweep, an orchestrator or a person
    runs `git fetch origin` (that fetches every ref, this one included). Git
    then refuses with:

        cannot lock ref 'refs/remotes/origin/sweep-progress':
        is at 1c14b6d8... but expected 418409e6...

    Seen on Sep 06, 2026 while watching run 34011544601: the panel showed no
    machines at all for minutes on a healthy run, because the only symptom was
    one line in the API log. A stale tracking ref is worth nothing on its own —
    the branch is re-fetched whole — so on that error the ref is dropped and
    the fetch retried once. Any other failure is raised as before.
    """
    ref = f"refs/remotes/origin/{PROGRESS_BRANCH}"
    try:
        _git("fetch", "--quiet", "origin", f"{PROGRESS_BRANCH}:{ref}",
             "--force", timeout=180)
        return
    except CloudError as exc:
        if "cannot lock ref" not in str(exc):
            raise
    # drop the wedged tracking ref and take the branch again from scratch
    with contextlib.suppress(CloudError):
        _git("update-ref", "-d", ref, timeout=30)
    _git("fetch", "--quiet", "origin", f"{PROGRESS_BRANCH}:{ref}",
         "--force", timeout=180)


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
            _fetch_progress()
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
    with tempfile.TemporaryDirectory(dir=_scratch()) as tmp:
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


SCRATCH_TTL_S = 6 * 3600


def _scratch() -> str | None:
    """Where an artifact download is unpacked — BESIDE THE STORE, not on C:.

    `tempfile.TemporaryDirectory()` unpacks into %TEMP%, which on Windows is
    the operator's own AppData temp folder — the SYSTEM drive. The store lives
    on G: through a junction, so the operator reasonably believed the fleet's
    rows never touched C:. They did: a collect downloads and unzips EVERY
    shard's artifact before streaming it into the store, and on 2026-09-10
    three of those folders held 9.4 GB between them while C: sat at 6 GB free
    of 118 GB. The operator asked "why are you using my c drive?". Twenty
    shards of a big run would have filled it and taken Windows down with it.

    Leftovers are swept here too. `TemporaryDirectory` cleans up on exit, but
    a collect that is KILLED never gets there — and `start.py` kills the job
    tree on every restart, so each hard stop leaks a whole shard's unpack.
    That is how three of them piled up. Only our own `tmp*` folders, only ones
    older than `SCRATCH_TTL_S` (a download times out at 30 minutes, so six
    hours cannot be live work).

    Falls back to the system default when the store's drive cannot be used, so
    a machine with a different layout still works.
    """
    from tradingagents import market_sweep as msw

    try:
        d = pathlib.Path(msw.HOME) / "tmp"
        d.mkdir(parents=True, exist_ok=True)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("scratch beside the store unusable (%s) — "
                       "artifact downloads fall back to the system temp", exc)
        return None

    cutoff = time.time() - SCRATCH_TTL_S
    for old in d.glob("tmp*"):
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                import shutil

                shutil.rmtree(old, ignore_errors=True)
                logger.info("swept leaked artifact scratch %s", old.name)
        except Exception:                                      # noqa: BLE001
            pass
    return str(d)


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
        # PAIR-DONE MARKERS (Sep 06, 2026): the shard writes one line per
        # measured pair even when every combination fell under the trade
        # floor. Without it a zero-row pair left no trace, no state file was
        # written, and the pair stayed "pending" through every sweep — ROAM,
        # QUID, SHARE, STAR, TOAD and IGV were measured twice in one day and
        # counted as never measured both times.
        marks = [r for r in buf if r.get("pair_done")]
        buf = [r for r in buf if not r.get("pair_done")]
        # A pair refused once stays refused. It has to be its OWN set: marking
        # it in `written` would make the second sighting of the same pair take
        # the append branch below and overwrite the very rows being protected.
        if key in refused:
            return
        if not buf and marks:
            if key in written:
                return
            if land_rows(coin, tf, [], marks=marks) == "stale":
                refused.add(key)
                skipped.append(f"{coin} {tf}")
                return
            kept += 1
            written.add(key)
            coins.add(coin)
            return
        if not buf:
            return
        # THE NEWER MEASUREMENT WINS. This used to refuse any pair with a
        # watermark ("never overwrite a pair the Mac finished") — right while
        # this PC measured and the cloud filled gaps, and a store-freezer once
        # the cloud became the only measurer (Sep 05, 2026): the collect log
        # for the eight runs up to Sep 09 reads 0, 1, 17, 4, 0, 0, 0 and 9
        # pairs kept against 1,550–4,549 "skipped, already measured here"
        # per run — 40,148,482 rows measured by twenty machines and thrown
        # away, the Stored strategies still August's. Only a measurement no
        # newer than the stored one is refused now (a stale run landing after
        # a fresher one). The continued run's rows carry their real end bar.
        # (its history is in `land_rows`, which now holds the rule for both the
        # collector and the live door)
        if land_rows(coin, tf, buf, marks=marks,
                     append=key in written) == "stale":
            refused.add(key)                   # do not re-check it per line
            skipped.append(f"{coin} {tf}")
            return
        if key not in written:
            kept += 1
        written.add(key)
        coins.add(coin)

    refused: set = set()
    tfs_seen: set = set()

    for n, name in enumerate(names, 1):
        with tempfile.TemporaryDirectory(dir=_scratch()) as tmp:
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
                        # a pair-done marker is bookkeeping, not a row —
                        # counting it would inflate the "N row(s)" note
                        if not r.get("pair_done"):
                            rows_seen += 1
                        k = (r["coin"], r["tf"])
                        tfs_seen.add(str(r["tf"]))
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
    # WHERE THE SAVED POSITIONS NOW LIVE. A run that shipped `state-*`
    # artifacts is the one the next UPDATE continues from, per timeframe.
    # Never allowed to raise: the rows are already written.
    try:
        if has_state_artifacts(run_id, slug):
            record_state_run(run_id, sorted(tfs_seen))
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("cloud sweep: state-run record failed: %r", exc)
    # OFF THE PENDING BOOKS. Operator, 2026-09-09: pending is what BROKE, so a
    # pair the fleet measured and this just landed is no longer a problem —
    # whichever run originally failed it. Never allowed to raise: the rows are
    # already written and a bookkeeping slip must not look like a failed merge.
    try:
        from tradingagents import pending_ledger as _pl

        _pl.clear("backtest", sorted(written))
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("cloud sweep: pending ledger clear failed: %r", exc)
    return {"pairs": kept, "rows": rows_seen, "coins": len(coins),
            "artifacts": len(names), "skipped": len(skipped),
            "skipped_pairs": skipped[:20], "unparseable": bad,
            "why_skipped": ("no newer than the measurement already stored "
                            "(a stale run landing after a fresher one)"
                            if skipped else "")}


def land_rows(coin: str, tf: str, rows: list, *, marks=(), append: bool = False) -> str:
    """Write ONE pair's measurement into the store. Returns "kept", "empty"
    (a measured pair whose every combination fell under the trade floor) or
    "stale" (no newer than what is already stored).

    THE ONE PLACE that rule lives. Two paths write cloud measurements now — the
    collector reading a finished run's artifacts, and the live door taking a
    pair the moment a machine finishes it (`live_ingest`) — and a store rule
    with two implementations is how this repo lost a week of measurements
    (RCA-2026-09-09-P: the collector kept a rule the shard had outgrown).
    """
    from tradingagents import market_sweep as msw

    marks = list(marks or [])
    rows = list(rows or [])
    if not rows and not marks:
        return "stale"
    last_ms = max([int(r.get("last_ms") or 0) for r in rows + marks] or [0])
    # A pair already written by THIS pass is appended to, not re-judged: the
    # rows of one pair can be split across a shard file.
    if not append and not is_fresher(coin, tf, last_ms):
        return "stale"
    # MERGE, NEVER REPLACE. `save_pair_rows` was here, and it is the reason
    # 1,261,358 measured rows across 267 pairs disappeared on Sep 10, 2026 —
    # 100 of those pairs emptied outright (GPNSTOCK-15m 18,880 -> 0,
    # SUPRA-15m 21,780 -> 0). Nothing was wrong with those measurements: a
    # later shard produced FEWER rows for the pair, because its cost gate
    # skipped almost every barrier while the coin's spread was wide (a stock
    # token outside US market hours, or a thin alt whose book is always wide —
    # UTILITY-1h costs 3.5866% round-trip, so only its 8% target cleared), and
    # this line then wrote that smaller set OVER the full one.
    #
    # `is_fresher` compares WATERMARKS, which say when a run ended and nothing
    # about what it holds. So freshness alone must never authorise a shrink.
    # `merge_pair_rows` — the writer the LOCAL sweep has always used, whose own
    # docstring warns that save_pair_rows "would delete every combination not
    # yet reached" — keys on the combination: what this run measured wins,
    # what it did not measure is kept.
    #
    # `append` is now redundant (the merge dedupes by combination) and is kept
    # only so callers do not have to change; an empty `rows` on a pair that has
    # none still leaves the empty file a first measurement is entitled to
    # write, with the state file beside it saying "measured" (the 1d incident,
    # 2026-08-26).
    if rows or not msw.pair_rows(coin, tf):
        msw.merge_pair_rows(coin, tf, rows)
    if last_ms:
        # __last_ms__ LAST. `pair_watermark` reads the final 256 bytes and its
        # regex anchors the key to the closing brace, so writing it first made
        # every cloud-merged pair read as watermark 0 — "never measured", which
        # undercounts the progress bar and invites a re-sweep of done work.
        msw.save_states(coin, tf, {"__cloud__": True, "__last_ms__": last_ms})
    return "kept" if rows else "empty"


def is_fresher(coin: str, tf: str, last_ms: int) -> bool:
    """Is a measurement ending at `last_ms` newer than what the store holds
    for this pair? The one rule the collector applies (see collect_into_store).
    A pair the store has never measured (watermark 0) is always fresher."""
    from tradingagents import market_sweep as msw

    return int(last_ms or 0) > int(msw.pair_watermark(coin, tf) or 0)


# Which run holds the latest SAVED POSITIONS per timeframe — what an UPDATE
# hands the machines so they continue from it (sweep_shard.fetch_prior_states).
STATE_RUNS_FILE = Path(os.path.expanduser(
    "~/.tradingagents/backtest/cloud_state_runs.json"))
# artifacts are kept 90 days (sweep.yml); a record older than this is not
# offered, and the header then says the run measured in full
STATE_RUN_MAX_AGE_S = 85 * 86400


def has_state_artifacts(run_id: int, slug: str | None = None) -> bool:
    slug = slug or repo_slug()
    raw = json.loads(_gh("api", f"repos/{slug}/actions/runs/{run_id}"
                                "/artifacts?per_page=100"))
    return any(str(a.get("name", "")).startswith("state-")
               and not a.get("expired") for a in (raw.get("artifacts") or []))


# How many runs' saved positions may be handed to one UPDATE, per timeframe.
# It used to be ONE — the newest — which was right while every run measured the
# whole market. From Sep 10, 2026 a run can be asked for two coins by name, and
# one of those would have become the only source of positions for its
# timeframe: the next UPDATE would find a position for BTC and measure the
# other 1,063 coins from scratch, the RCA-2026-09-09-P shape all over again.
# A few are kept, newest first, and the shard lets the newest win a pair.
STATE_RUNS_PER_TF = 3


def record_state_run(run_id: int, tfs, now: float | None = None) -> dict:
    """`run_id` now holds the newest saved positions for `tfs` — in FRONT of
    the runs already recorded, which still hold the coins it did not touch."""
    rec = state_runs()
    at = float(now if now is not None else time.time())
    for tf in tfs:
        kept = [e for e in _entries(rec.get(str(tf)))
                if int(e.get("run") or 0) != int(run_id)]
        rec[str(tf)] = ([{"run": int(run_id), "at": at}]
                        + kept)[:STATE_RUNS_PER_TF]
    STATE_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_RUNS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(STATE_RUNS_FILE)
    return rec


def state_runs() -> dict:
    try:
        return json.loads(STATE_RUNS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _entries(val) -> list:
    """A timeframe's recorded runs, newest first. Records written before
    Sep 10, 2026 hold ONE dict instead of a list — read both, or the first
    UPDATE after this change would find no saved positions at all and measure
    the whole market from scratch."""
    if isinstance(val, dict):
        return [val]
    return [e for e in (val or []) if isinstance(e, dict)]


def state_runs_for(tfs, now: float | None = None) -> list:
    """The run ids whose saved positions cover `tfs`, NEWEST FIRST — the order
    IS the priority: the shard takes each pair from the first run that has it,
    and stops downloading when the runner's disk is full. Newest-last would
    have spent that disk on stale positions and skipped the fresh ones.

    Records older than the artifact retention are left out: those artifacts are
    gone, and a full measure with an honest header beats a download that fails
    on twenty machines."""
    at = float(now if now is not None else time.time())
    rec = state_runs()
    picked: dict = {}
    for tf in tfs:
        for e in _entries(rec.get(str(tf))):
            when = float(e.get("at") or 0)
            if at - when > STATE_RUN_MAX_AGE_S:
                continue
            picked[int(e["run"])] = max(when, picked.get(int(e["run"]), 0.0))
    return [str(r) for r, _ in sorted(picked.items(), key=lambda kv: kv[1],
                                      reverse=True)]


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
