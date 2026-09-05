"""Which long-running process is still holding OLD CODE.

Operator, Sep 04, 2026: *"SO WHAT'S NOT UPDATED?"* and then *"I DONT WANT THIS
BUG FIX THIS"*.

A process keeps the code it started with. Nothing on any screen said so, so:

* the backtest job (pid 22032, Sep 03 3:30pm) ran 32 hours on 3 of 11 cores
  after the commit that lets the window grow — a ProcessPoolExecutor cannot be
  resized, so it could never pick it up;
* the runner (pid 9392, Sep 04 11:04am) went on holding the loss-cap version
  that writes the KILL file and EXITS, taking the paper book down with it, two
  minutes after the fix landed.

The only way anyone found out was comparing process start times to `git log` by
hand. This module does that, and the panel prints it.

It answers with THREE states, never two: stale, current, or unknown. A silent
"current" when git cannot be read is exactly how a 32-hour stale job looked
healthy.
"""
from __future__ import annotations

import pathlib
import subprocess
import time

# How long a git answer is reused. Cheap, but this is polled.
CACHE_S = 30.0
_CACHE: dict = {"at": 0.0, "payload": None}

ROOT = pathlib.Path(__file__).resolve().parent.parent

# What a process is called on screen, and how to recognise its command line.
# `api` is here because a route added to a running server is not served until
# it restarts — which is its own quiet way of looking broken.
KINDS = {
    "backtest": "db_jobs backtest",
    "download": "db_jobs download",
    "btupdate": "db_jobs btupdate",
    "runner": "auto_trader run",
    "api": "uvicorn tradingagents.api",
}


def _git(*args, timeout: int = 20) -> str:
    p = subprocess.run(("git", *args), cwd=str(ROOT), capture_output=True,
                       text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or "").strip()[:120])
    return p.stdout.strip()


def head_commit() -> dict | None:
    """The newest commit on this checkout, or None when git will not say."""
    from tradingagents.positions_view import fmt_when

    try:
        sha, ts = _git("log", "-1", "--format=%h %ct").split()
        return {"sha": sha, "committed": int(ts), "when": fmt_when(int(ts))}
    except Exception:                                          # noqa: BLE001
        return None


def commits_after(ts: float) -> int | None:
    """How many commits landed after `ts`, or None when git will not say."""
    try:
        out = _git("log", "--oneline", f"--since=@{int(ts)}")
        return len([ln for ln in out.splitlines() if ln.strip()])
    except Exception:                                          # noqa: BLE001
        return None


def process_code_age(*, started, head_committed, commits_since) -> dict:
    """Is a process started at `started` holding code older than HEAD?

    Pure, so the three states can be tested without a machine or a repo.
    `started` None means nothing is running — which is not stale.
    `head_committed` None means git would not answer — which is not "current".
    """
    if started is None:
        return {"running": False, "stale": False, "commits_behind": 0,
                "why": ""}
    if head_committed is None:
        return {"running": True, "stale": None, "commits_behind": None,
                "why": "could not read the repository, so its code age is "
                       "unknown"}
    if float(started) >= float(head_committed):
        return {"running": True, "stale": False, "commits_behind": 0,
                "why": ""}
    n = commits_since if commits_since is not None else 0
    return {"running": True, "stale": True, "commits_behind": int(n),
            "why": (f"started before the newest commit — {int(n)} commit(s) "
                    f"behind; restart it to pick them up")}


def _process_starts() -> dict:
    """When each kind started, by wall-clock seconds, or None if not running.

    Read from the OS process table, not from a pid file: a pid file survives
    the process and would report a dead job as a running one.
    """
    out = dict.fromkeys(KINDS)
    try:
        import sys

        if sys.platform == "win32":
            # [DateTimeOffset], NOT `Get-Date -UFormat %s`: CreationDate is
            # a LOCAL DateTime and -UFormat treats it as UTC, so every stamp
            # came back 8 hours in the future here (1788563699 against a
            # clock reading 1788534988). A process that starts in the future
            # is never behind a commit, so the check would have reported a
            # stale runner as current — the exact failure it exists to catch.
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' "
                  "or Name='node.exe'\" | ForEach-Object { "
                  "\"$($_.ProcessId)`t"
                  "$([DateTimeOffset]::new($_.CreationDate).ToUnixTimeSeconds())`t"
                  "$($_.CommandLine)\" }")
            raw = subprocess.run(["powershell", "-NoProfile",
                                  "-NonInteractive", "-Command", ps],
                                 capture_output=True, text=True,
                                 timeout=60).stdout
            rows = []
            for line in raw.splitlines():
                bits = line.split("\t", 2)
                if len(bits) == 3:
                    rows.append((int(bits[1]), bits[2]))
        else:
            raw = subprocess.run(["ps", "-eo", "lstart=,command="],
                                 capture_output=True, text=True,
                                 timeout=60).stdout
            rows = []
            for line in raw.splitlines():
                try:
                    when = time.mktime(time.strptime(line[:24]))
                except (ValueError, TypeError):
                    continue
                rows.append((int(when), line[24:]))
    except Exception:                                          # noqa: BLE001
        return out
    for kind, needle in KINDS.items():
        best = None
        for started, cmd in rows:
            if needle in cmd and (best is None or started < best):
                # the OLDEST match: a job's launcher and its worker share the
                # command line, and the launcher is the one that fixed the code
                best = started
        out[kind] = best
    return out


def report(force: bool = False) -> dict:
    """Every long-running process, and which of them is on old code."""
    now = time.time()
    if not force and _CACHE["payload"] and now - _CACHE["at"] < CACHE_S:
        return _CACHE["payload"]

    head = head_commit()
    starts = _process_starts()
    rows = []
    for kind in ("backtest", "download", "btupdate", "runner", "api"):
        started = starts.get(kind)
        since = (commits_after(started)
                 if started is not None and head else None)
        age = process_code_age(started=started,
                              head_committed=head["committed"] if head else None,
                              commits_since=since)
        from tradingagents.positions_view import fmt_when

        rows.append({"kind": kind, "started": fmt_when(started) if started else "",
                     **age})
    stale = [r for r in rows if r["stale"]]
    unknown = [r for r in rows if r["stale"] is None]
    if stale:
        summary = " · ".join(
            f"{r['kind']} is {r['commits_behind']} commit(s) behind "
            f"(started {r['started']})" for r in stale)
        summary += " — restart it to pick them up"
    elif unknown:
        summary = (f"{len(unknown)} process(es) of unknown code age: "
                   f"{', '.join(r['kind'] for r in unknown)}")
    else:
        summary = ("every running process is up to date with "
                   + (f"{head['sha']} ({head['when']})" if head else "HEAD"))
    payload = {"processes": rows, "stale_count": len(stale),
               "unknown_count": len(unknown), "head": head,
               "summary": summary}
    _CACHE.update(at=now, payload=payload)
    return payload
