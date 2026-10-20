"""GITHUB MACHINES — every failed job on both GitHub accounts, its log saved
on this PC and shown in Auto Trade -> Errors.

The operator, Oct 19, 2026: *"can you do a logging option where if there is
error in github machines it will save the log in error tab"*.

Every `POLL_S` the site's own thread asks each account
(`cloud_sweep.fleets()`: jeremydevera and jeremydvera) for the runs that
ENDED red — `failure`, `timed_out`, `startup_failure`; a `cancelled` run was
stopped on purpose and is not an error. For each red machine (job) of such a
run it saves, under `~/.tradingagents/github_errors/` (the store's drive):

* the WHOLE job log, colour codes removed and every secret scrubbed
  (`error_issues.scrub`), capped at `LOG_CAP` bytes from the END, where the
  error is — a cut is said at the top of the file;
* GitHub's own notes on the job (annotations): a machine GitHub lost
  ("The hosted runner lost communication with the server") has NO log at
  all, and the note is then the only record of why;
* the failed step's name and the lines just before the first `##[error]`.

A run is recorded once and never fetched again; a run whose jobs could not
be read is NOT recorded, so the next pass tries again. A pass that could not
ask GitHub says why on the page (`last_error`) — never an empty list that
looks like "nothing failed". Records older than `KEEP_DAYS` are removed with
their logs, from this folder only.

Read only on GitHub: nothing here re-runs, cancels or files anything.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

POLL_S = 600                       # one look at both accounts every 10 minutes
FIRST_DAYS = 7                     # the first pass reaches this far back
KEEP_DAYS = 30
LOG_CAP = 2_000_000                # bytes of one job's log kept, from the end
CONTEXT_LINES = 40                 # lines shown before the first ##[error]
PER_PAGE = 10                      # the Errors page's own page size
RED = ("failure", "timed_out", "startup_failure")
_ESC = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z ")


def home() -> Path:
    return Path(os.path.expanduser("~/.tradingagents")) / "github_errors"


def _state_path() -> Path:
    return home() / "index.json"


def _read() -> dict:
    try:
        st = json.loads(_state_path().read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(st: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")
    for _ in range(30):
        try:
            tmp.replace(p)
            return
        except PermissionError:          # Windows: a reader holds it open
            time.sleep(0.1)
    tmp.replace(p)


def _iso(s: str | None) -> float:
    if not s:
        return 0.0
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _gh_json(gh, *args) -> object:
    raw = gh("api", *args)
    return json.loads(raw) if raw.strip() else None


def _clean(text: str) -> str:
    from tradingagents import error_issues as ei

    return ei.scrub(_ESC.sub("", text))


def excerpt(log: str) -> tuple[str, str]:
    """(the first ##[error] line, the CONTEXT_LINES before it), with GitHub's
    time stamps taken off so the lines read as the program wrote them."""
    lines = log.splitlines()
    at = next((i for i, ln in enumerate(lines) if "##[error]" in ln), None)
    if at is None:
        tail = lines[-CONTEXT_LINES:]
        return "", "\n".join(_STAMP.sub("", ln) for ln in tail)
    first = _STAMP.sub("", lines[at]).replace("##[error]", "").strip()
    ctx = lines[max(0, at - CONTEXT_LINES):at + 1]
    return first, "\n".join(_STAMP.sub("", ln) for ln in ctx)


def _log_name(slug: str, job_id) -> str:
    return f"{slug.split('/')[0]}-{job_id}.log"


def _job_record(gh, slug: str, job: dict) -> dict:
    jid = job["id"]
    notes = []
    try:
        for a in _gh_json(gh, f"repos/{slug}/check-runs/{jid}/annotations") or []:
            if a.get("annotation_level") in ("failure", "warning") and a.get("message"):
                notes.append(_clean(str(a["message"]))[:500])
    except Exception as exc:                                   # noqa: BLE001
        notes.append(f"(GitHub's notes for this machine could not be read: "
                     f"{type(exc).__name__})")
    rec = {"id": jid, "name": job.get("name"), "conclusion": job.get("conclusion"),
           "started": _iso(job.get("started_at")), "ended": _iso(job.get("completed_at")),
           "step": next((s.get("name") for s in job.get("steps") or []
                         if s.get("conclusion") in RED), None),
           "notes": notes, "log": None, "log_bytes": 0, "log_cut": False,
           "error": "", "context": "", "log_why": ""}
    try:
        raw = gh("api", "--allow-escape-sequences", f"repos/{slug}/actions/jobs/{jid}/logs")
    except Exception as exc:                                   # noqa: BLE001
        msg = str(exc)
        rec["log_why"] = ("GitHub kept no log for this machine (it was lost before "
                          "it could hand one over)" if "404" in msg or "BlobNotFound" in msg
                          else f"the log could not be read: {msg[:160]}")
        return rec
    log = _clean(raw)
    cut = len(log.encode("utf-8")) > LOG_CAP
    if cut:
        log = log.encode("utf-8")[-LOG_CAP:].decode("utf-8", "ignore")
    name = _log_name(slug, jid)
    path = home() / "logs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# {slug} · job {jid} · {job.get('name')}\n"
            + (f"# only the last {LOG_CAP:,} bytes are kept\n" if cut else ""))
    path.write_text(head + log, encoding="utf-8")
    rec.update(log=name, log_bytes=path.stat().st_size, log_cut=cut)
    rec["error"], rec["context"] = excerpt(log)
    return rec


def _run_record(gh, slug: str, run: dict, names: dict | None = None) -> dict:
    jobs, page = [], 1
    while True:
        got = _gh_json(gh, f"repos/{slug}/actions/runs/{run['id']}/jobs?per_page=100&page={page}")
        part = (got or {}).get("jobs") or []
        jobs += part
        if len(part) < 100:
            break
        page += 1
    red = [j for j in jobs if j.get("conclusion") in RED]
    return {"key": f"{slug}#{run['id']}", "account": slug.split("/")[0], "repo": slug,
            # the WORKFLOW's name for the filter: a run's own "name" is its
            # run-name ("Costs per minute · 2026-09-18,... · 520 coins"), one
            # per run, so filtering by it would list every run once
            "run": run["id"], "workflow_id": run.get("workflow_id"),
            "workflow": (names or {}).get(run.get("workflow_id")) or run.get("name"),
            "title": run.get("display_title") or run.get("name"),
            "conclusion": run.get("conclusion"), "url": run.get("html_url"),
            "created": _iso(run.get("created_at")), "ended": _iso(run.get("updated_at")),
            "machines": len(jobs), "red": len(red),
            "jobs": [_job_record(gh, slug, j) for j in red]}


def tick(now: float | None = None, gh=None, slugs=None) -> dict:
    """One look at every account, at most every POLL_S. Returns what it did."""
    from tradingagents import cloud_sweep as cs

    now = time.time() if now is None else now
    st = _read()
    if now - float(st.get("last_try") or 0) < POLL_S:
        return {"skipped": "not due"}
    gh = gh or cs._gh
    runs = st.setdefault("runs", {})
    st["last_try"] = now
    problems, saved = [], 0
    try:
        slugs = list(slugs if slugs is not None else cs.fleets())
    except Exception as exc:                                   # noqa: BLE001
        slugs, problems = [], [f"the accounts could not be listed: {exc}"]
    since = float(st.get("since") or now - FIRST_DAYS * 86_400)
    day = datetime.fromtimestamp(since - 86_400, timezone.utc).strftime("%Y-%m-%d")
    for slug in slugs:
        try:
            names = {w.get("id"): w.get("name") for w in
                     (_gh_json(gh, f"repos/{slug}/actions/workflows?per_page=100") or {})
                     .get("workflows") or []}
            page = 1
            while True:
                got = _gh_json(gh, f"repos/{slug}/actions/runs?status=completed"
                                   f"&created=>={day}&per_page=100&page={page}") or {}
                part = got.get("workflow_runs") or []
                for run in part:
                    key = f"{slug}#{run['id']}"
                    if run.get("conclusion") not in RED or key in runs:
                        continue
                    runs[key] = _run_record(gh, slug, run, names)
                    saved += 1
                    _write(st)            # one run at a time: a stop keeps what it saved
                if len(part) < 100 or page >= 10:
                    break
                page += 1
        except Exception as exc:                               # noqa: BLE001
            problems.append(f"{slug}: {str(exc)[:200]}")
    if not problems:
        st["since"] = now - 2 * POLL_S      # the next pass overlaps this one
        st["last_ok"] = now
    st["last_error"] = "; ".join(problems)
    # the old ones go, with their logs (this folder only)
    old = [k for k, r in runs.items() if float(r.get("ended") or 0) < now - KEEP_DAYS * 86_400]
    for k in old:
        for j in runs[k].get("jobs") or []:
            if j.get("log"):
                with contextlib.suppress(OSError):
                    (home() / "logs" / j["log"]).unlink()
        del runs[k]
    st["accounts"] = [s.split("/")[0] for s in slugs]
    _write(st)
    return {"saved": saved, "removed": len(old), "problems": problems}


def listing(account: str = "", workflow: str = "", page: int = 1,
            per_page: int = PER_PAGE) -> dict:
    """The Errors page's GitHub machines section: newest first, filtered and
    paged here, never in the browser."""
    st = _read()
    rows = sorted((st.get("runs") or {}).values(), key=lambda r: -float(r.get("ended") or 0))
    workflows = sorted({r.get("workflow") or "" for r in rows})
    accounts = sorted({r.get("account") or "" for r in rows} | set(st.get("accounts") or []))
    if account:
        rows = [r for r in rows if r.get("account") == account]
    if workflow:
        rows = [r for r in rows if r.get("workflow") == workflow]
    matched = len(rows)
    pages = max(1, -(-matched // max(1, per_page)))
    page = min(max(1, int(page)), pages)
    return {"rows": rows[(page - 1) * per_page:page * per_page],
            "matched": matched, "total": len(st.get("runs") or {}),
            "page": page, "pages": pages, "workflows": workflows, "accounts": accounts,
            "last_try": st.get("last_try"), "last_ok": st.get("last_ok"),
            "last_error": st.get("last_error") or "", "since_days": KEEP_DAYS,
            "every_s": POLL_S}


def log_text(name: str) -> str | None:
    """A saved log by its file name, from this folder only."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+-\d+\.log", name or ""):
        return None
    p = home() / "logs" / name
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
