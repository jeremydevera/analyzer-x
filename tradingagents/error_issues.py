"""Every error becomes a GitHub issue (Oct 07, 2026).

The operator: *"here's what i want, everytime the system gets an error, file
an issue to github, then i want you to investigate if its a valid error or
not, if its valid then fix it"*. Their answers: issues on the public project
`jeremydevera/analyzer-x` as-is, checking and fixing on this PC, push and
restart by itself, and ALL errors — the rooms' (the Errors tab), failed jobs,
and crashes inside the site itself.

This module is the FILER. It gathers every error from the three sources,
groups them by a fingerprint (one issue per fault — never per room, never per
occurrence), removes every secret, and files or updates the issue through
`gh`. `error_fixer` then investigates each queued fault on this PC.

Spec: docs/superpowers/specs/2026-10-07-errors-become-issues-design.md
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

HOME = Path(os.path.expanduser("~/.tradingagents"))
REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_LOG = REPO_ROOT / ".run" / "api.log"

# room_errors pages its answer; the filer reads every page
_ROOM_PAGE = 200


def _norm(msg: str) -> str:
    from tradingagents import room_errors

    return room_errors._norm(msg)


def fingerprint(ev: dict) -> str:
    """One fault = one id: the source, the kind and the message with its
    numbers and times taken out. The ROOM is not part of it — SUPRA's
    candles failed in #4FC03172 and #55D32617 on Oct 06, 2026, one fault."""
    key = ev.get("key") or _norm(str(ev.get("message") or ""))
    raw = f"{ev.get('source')}|{ev.get('kind')}|{key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------- sources

def from_rooms() -> list[dict]:
    """Every group on the Errors tab, every page, merged across rooms."""
    from tradingagents import room_errors

    merged: dict = {}
    page, pages = 1, 1
    while page <= pages:
        got = room_errors.report(hours=0, page=page, per=_ROOM_PAGE)
        pages = int(got.get("pages") or 1)
        for g in got.get("rows") or []:
            ev = {"source": "room", "kind": g["kind"],
                  "label": g.get("label") or g["kind"],
                  "message": str(g.get("message") or ""),
                  "key": _norm(str(g.get("message") or ""))}
            fp = fingerprint(ev)
            cur = merged.get(fp)
            if cur is None:
                merged[fp] = {**ev, "rooms": [g["room"]], "count": int(g["count"]),
                              "first": float(g["first"]), "last": float(g["last"])}
                continue
            if g["room"] not in cur["rooms"]:
                cur["rooms"].append(g["room"])
            cur["count"] += int(g["count"])
            cur["first"] = min(cur["first"], float(g["first"]))
            if float(g["last"]) >= cur["last"]:
                cur["last"], cur["message"] = float(g["last"]), ev["message"]
        page += 1
    return list(merged.values())


def from_jobs() -> list[dict]:
    """A job that ended with a failure: `errors` with `first_error`, a
    `failed` list, or the died-before-finishing note `db_jobs.status` adds."""
    from tradingagents import db_jobs as dj

    out = []
    for kind in list(dj.FILES):
        try:
            st = dj.status(kind)
        except Exception:                                      # noqa: BLE001
            continue
        if st.get("running"):
            continue
        why = ""
        if int(st.get("errors") or 0) > 0:
            why = str(st.get("first_error") or "") or f"{st['errors']} error(s)"
        elif st.get("failed"):
            why = "failed: " + ", ".join(str(x) for x in list(st["failed"])[:5])
        elif "died" in str(st.get("note") or ""):
            why = str(st["note"])
        if not why:
            continue
        when = float(st.get("finished") or st.get("updated") or st.get("started") or 0)
        msg = f"{kind}: {why}"[:400]
        out.append({"source": "job", "kind": kind, "label": f"Job failed: {kind}",
                    "message": msg, "key": _norm(f"{kind}: {why}"), "rooms": [],
                    "count": 1, "first": when, "last": when})
    return out


# the site's own log has no timestamps (uvicorn); it is read as a tail, once
# per process, and an event takes the time it was read
_SITE_TAIL: dict = {}
_FRAME = re.compile(r'^\s*File "([^"]+)", line \d+, in (\S+)')
_LAST = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)\b.*)$")


def from_site_log(now: float) -> list[dict]:
    """Tracebacks and supervisor failures in `.run/api.log` since the last
    read. A traceback becomes its last line plus its deepest frame inside
    `tradingagents` — what a reader needs to find the code."""
    try:
        size = SITE_LOG.stat().st_size
    except OSError:
        return []
    off = int(_SITE_TAIL.get("offset") or 0)
    if size < off:                       # a restart started a fresh log
        off = 0
    if size == off:
        return []
    with SITE_LOG.open("rb") as fh:
        fh.seek(off)
        data = fh.read(size - off)
    _SITE_TAIL["offset"] = size
    lines = data.decode("utf-8", "replace").splitlines()
    out: list[dict] = []
    frame = ""
    in_tb = False
    for ln in lines:
        if ln.startswith("Traceback (most recent call last):"):
            in_tb, frame = True, ""
            continue
        if in_tb:
            m = _FRAME.match(ln)
            if m:
                path, func = m.group(1), m.group(2)
                if "tradingagents" in path.replace("\\", "/").split("/"):
                    frame = f"{Path(path).name}:{func}"
                continue
            last = _LAST.match(ln.strip())
            if last and not ln.startswith(" "):
                msg = last.group(1) + (f" (in {frame})" if frame else "")
                out.append({"source": "site", "kind": "site_crash",
                            "label": "The site itself failed", "message": msg[:400],
                            "key": _norm(msg), "rooms": [], "count": 1,
                            "first": now, "last": now})
                in_tb = False
            continue
        if ln.startswith("[supervisor]") and ("failed" in ln or "could not" in ln):
            out.append({"source": "site", "kind": "supervisor",
                        "label": "The site's supervisor failed", "message": ln[:400],
                        "key": _norm(ln), "rooms": [], "count": 1,
                        "first": now, "last": now})
    merged: dict = {}
    for ev in out:
        fp = fingerprint(ev)
        if fp in merged:
            merged[fp]["count"] += 1
        else:
            merged[fp] = ev
    return list(merged.values())


def collect(now: float) -> list[dict]:
    """Every error the system has now, one event per fault."""
    out: list[dict] = []
    for source in (from_rooms, from_jobs):
        try:
            out += source()
        except Exception as exc:                               # noqa: BLE001
            print(f"[error-issues] could not read {source.__name__}: "
                  f"{type(exc).__name__}: {exc}", flush=True)
    try:
        out += from_site_log(now)
    except Exception as exc:                                   # noqa: BLE001
        print(f"[error-issues] could not read the site log: "
              f"{type(exc).__name__}: {exc}", flush=True)
    return out


# ------------------------------------------------------------ the scrubber
# "As-is" was the operator's choice for DETAILS; a credential is not a detail.
# Nothing that can sign an order or open the live door leaves this PC.
_SECRET_WORDS = (r"signature|apikey|api_key|api-key|access[_-]?key|secret|"
                 r"token|password|passwd|authorization")
_SECRET_RX = re.compile(
    r"(?i)(\b(?:" + _SECRET_WORDS + r")\b[\"']?\s*[:=]\s*[\"']?)"
    r"((?:bearer\s+)?)([^\s\"'&,;}]+)")


def _secret_values() -> list[str]:
    vals = [os.getenv("MEXC_API_KEY", ""), os.getenv("MEXC_API_SECRET", "")]
    try:
        vals.append((HOME / "ingest_token").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    try:
        for ln in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            if re.search(r"(?i)key|secret|token|pass", k):
                vals.append(v.strip().strip("\"'"))
    except OSError:
        pass
    return sorted({v for v in vals if len(v) >= 8}, key=len, reverse=True)


def scrub(text: str) -> str:
    """The text with every credential replaced by `[removed]`."""
    s = str(text)
    for v in _secret_values():
        s = s.replace(v, "[removed]")
    return _SECRET_RX.sub(lambda m: m.group(1) + m.group(2) + "[removed]", s)


# ---------------------------------------------------------- the GitHub side
STATE = HOME / "error_issues.json"
FIXER_DIR = HOME / "fixer"
GH_REPO = "jeremydevera/analyzer-x"
FLOOD_PER_HOUR = 10                  # new issues an hour before the flood summary
COMMENT_EVERY_S = 3600               # an open fault's repeats: one comment an hour
NOT_A_FAULT_COMMENT_EVERY_S = 86400  # a closed not-a-fault one: one a day
LABELS = {
    "auto-error": ("B60205", "Filed by the system from an error it met"),
    "checking": ("FBCA04", "The fixer on the PC is checking it"),
    "real-fault": ("D93F0B", "The fixer found a real fault"),
    "not-a-fault": ("C5DEF5", "Not a fault: an outside event or a deliberate action"),
    "fixed": ("0E8A16", "Fixed, tested, pushed and restarted"),
    "needs-you": ("5319E7", "The fixer could not decide or fix it safely"),
    "came-back": ("E99695", "It happened again after a fix"),
}
_LABELS_MADE: set = set()


class GhFailed(RuntimeError):
    """gh is missing, signed out, offline or refused — the tick tries again."""


GH_OWNER = GH_REPO.split("/")[0]
_OWNER_TOKEN: dict = {}


def _gh_env() -> dict:
    """Act as the project's OWNER whatever account gh has active: on this PC
    the active one is the fork's (jeremydvera, checked Oct 07, 2026), and the
    issues belong to jeremydevera/analyzer-x. Read once per process; when it
    cannot be read, the active account files (it has write access there)."""
    import shutil
    import subprocess

    tok = _OWNER_TOKEN.get("t")
    if tok is None:
        tok = ""
        try:
            out = subprocess.run([shutil.which("gh") or "gh", "auth", "token", "-u", GH_OWNER],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode == 0:
                tok = (out.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            tok = ""
        _OWNER_TOKEN["t"] = tok
    env = dict(os.environ)
    if tok:
        env["GH_TOKEN"] = tok
    return env


def _gh(args: list, input_text: str | None = None) -> str:
    """One `gh` call. UTF-8 always (RCA-2026-10-02-G); no console window — it
    runs from the site's background thread."""
    import shutil
    import subprocess

    # a public project's issues are not a scratchpad: no test ever reaches
    # the real GitHub (the live door's rule, live_ingest.ensure)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise GhFailed("refused: no real GitHub call from a test")
    exe = shutil.which("gh") or "gh"
    try:
        out = subprocess.run([exe, *args], input=input_text, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=90,
                             env=_gh_env(),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GhFailed(f"{type(exc).__name__}: {exc}") from exc
    if out.returncode != 0:
        raise GhFailed((out.stderr or out.stdout or f"gh exited {out.returncode}")
                       .strip()[:300])
    return out.stdout


def _ensure_labels(gh) -> None:
    for name, (color, desc) in LABELS.items():
        if name in _LABELS_MADE:
            continue
        gh(["label", "create", name, "--color", color, "--description", desc,
            "--force", "-R", GH_REPO])
        _LABELS_MADE.add(name)


def _read() -> dict:
    import json

    try:
        got = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(got, dict):
            got.setdefault("faults", {})
            return got
    except (OSError, ValueError):
        pass
    return {"faults": {}}


def _write(st: dict) -> None:
    from tradingagents import db_jobs

    STATE.parent.mkdir(parents=True, exist_ok=True)
    db_jobs._write(STATE, st)


def _when(ts) -> str:
    from tradingagents.positions_view import fmt_when

    try:
        return fmt_when(float(ts)) if ts else "?"
    except (TypeError, ValueError):
        return "?"


def _rooms(rooms) -> str:
    return ", ".join("Main" if r == "main" else f"#{r}" for r in rooms) or "none"


def _rec_of(ev: dict) -> dict:
    return {k: ev.get(k) for k in ("source", "kind", "label", "message", "rooms",
                                   "count", "first", "last")}


def _title(ev: dict) -> str:
    return scrub(f"[{ev.get('label') or ev.get('kind')}] {ev.get('message')}")[:120]


def _body(ev: dict, fp: str) -> str:
    return scrub(
        "**Filed by the system on the operator's PC.** The fixer on that PC "
        "checks it and posts its verdict here.\n\n"
        f"- error: `{ev.get('message')}`\n"
        f"- kind: {ev.get('label')} ({ev.get('source')}/{ev.get('kind')})\n"
        f"- rooms: {_rooms(ev.get('rooms') or [])}\n"
        f"- seen: {int(ev.get('count') or 0):,} time(s), first {_when(ev.get('first'))}, "
        f"last {_when(ev.get('last'))}\n"
        f"- fault id: `{fp}`\n")


def evidence_path(fp: str) -> Path:
    return FIXER_DIR / f"{fp}.json"


def _write_evidence(fp: str, rec: dict, why: str) -> None:
    """What the fixer reads — on this PC, never the public issue's text."""
    import json

    from tradingagents import room_errors

    logs = {}
    for r in rec.get("rooms") or []:
        try:
            logs[r] = str(room_errors._log_path(r))
        except Exception:                                      # noqa: BLE001
            pass
    FIXER_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path(fp).write_text(json.dumps({
        "fingerprint": fp, "issue": rec.get("issue"), "url": rec.get("url"),
        "why": why, **_rec_of(rec), "first_when": _when(rec.get("first")),
        "last_when": _when(rec.get("last")), "room_logs": logs,
        "site_log": str(SITE_LOG)}, indent=1), encoding="utf-8")


def _bell(title: str, detail: str, url: str = "") -> None:
    from tradingagents import notifications

    notifications.record("error_issue", title, detail=scrub(detail)[:300], ok=False,
                         meta={"url": url} if url else None)


def _file(ev: dict, fp: str, gh) -> tuple[int, str]:
    _ensure_labels(gh)
    out = gh(["issue", "create", "-R", GH_REPO, "--title", _title(ev),
              "--label", "auto-error", "--body-file", "-"], input_text=_body(ev, fp))
    url = out.strip().splitlines()[-1].strip() if out.strip() else ""
    m = re.search(r"/issues/(\d+)", url)
    if not m:
        raise GhFailed(f"gh issue create answered without an issue link: {out[:200]!r}")
    return int(m.group(1)), url


def _comment(rec: dict, text: str, gh) -> None:
    gh(["issue", "comment", str(rec["issue"]), "-R", GH_REPO, "--body-file", "-"],
       input_text=scrub(text))


def _label(rec: dict, name: str, gh) -> None:
    _ensure_labels(gh)
    gh(["issue", "edit", str(rec["issue"]), "-R", GH_REPO, "--add-label", name])


def _state_change(gh, args: list, done_phrase: str) -> None:
    """A reopen or close that GitHub answers "already open/closed" has
    happened — a half-finished earlier tick must not turn into a failure that
    repeats for ever."""
    try:
        gh(args)
    except GhFailed as exc:
        if done_phrase not in str(exc).lower():
            raise


def _seen_again(rec: dict, ev: dict) -> str:
    return (f"Seen again: {int(ev.get('count') or 0):,} time(s) in total "
            f"(was {int(rec.get('posted_count') or 0):,}), rooms {_rooms(ev.get('rooms') or [])}, "
            f"last {_when(ev.get('last'))}.")


def tick(now: float | None = None, gh=None) -> dict:
    """File or update the issue of every fault the system has now. Never
    raises a GitHub failure: what could not be posted is tried next tick."""
    import time

    now = time.time() if now is None else float(now)
    gh = gh or _gh
    st = _read()
    faults = st["faults"]
    out = {"filed": 0, "commented": 0, "reopened": 0, "waiting": 0, "failed": 0}
    events = collect(now)
    if not st.get("baseline"):
        # THE BASELINE: what was already there when the filer first ran was
        # checked by hand on Oct 07, 2026 (34 groups) — not filed again
        for ev in events:
            faults[fingerprint(ev)] = {**_rec_of(ev), "state": "baseline"}
        st["baseline"] = now
        _write(st)
        return out
    filed = [t for t in st.get("filed_times", []) if now - t < 3600]
    waiting: list = []
    for ev in events:
        fp = fingerprint(ev)
        rec = faults.get(fp)
        try:
            fresh = (rec is None or rec.get("state") == "waiting"
                     or (rec.get("state") == "baseline"
                         and float(ev["last"]) > float(rec.get("last") or 0)))
            if fresh:
                if len(filed) >= FLOOD_PER_HOUR:
                    faults[fp] = {**(rec or {}), **_rec_of(ev), "state": "waiting"}
                    waiting.append(ev)
                    continue
                n, url = _file(ev, fp, gh)
                filed.append(now)
                faults[fp] = {**_rec_of(ev), "state": "queued", "issue": n, "url": url,
                              "filed_at": now, "commented_at": now,
                              "posted_count": int(ev.get("count") or 0), "came_back": 0}
                _write_evidence(fp, faults[fp], "new")
                _bell(f"Issue #{n} filed: {ev.get('label')}", str(ev.get("message")), url)
                out["filed"] += 1
                continue
            if not rec or not rec.get("issue"):
                if rec is not None:
                    rec.update(_rec_of(ev) | {"state": rec.get("state")})
                continue
            if float(ev["last"]) <= float(rec.get("last") or 0):
                continue
            state = rec.get("state")
            posted = False
            if state == "fixed" and float(ev["last"]) > float(rec.get("fixed_at") or 0):
                came = int(rec.get("came_back") or 0) + 1
                _state_change(gh, ["issue", "reopen", str(rec["issue"]), "-R", GH_REPO],
                              "already open")
                out["reopened"] += 1
                posted = True
                if came == 1:
                    _label(rec, "came-back", gh)
                    _comment(rec, f"It happened again after the fix ({rec.get('commit')}). "
                             + _seen_again(rec, ev) + " Queued for another check.", gh)
                    rec["state"] = "queued"
                    _write_evidence(fp, {**rec, **_rec_of(ev)}, "came_back")
                else:
                    _label(rec, "needs-you", gh)
                    _comment(rec, "It came back after two fixes, so it waits for the "
                             "operator. " + _seen_again(rec, ev), gh)
                    rec["state"] = "needs_you"
                    _bell(f"Issue #{rec['issue']} came back twice: {ev.get('label')}",
                          str(ev.get("message")), rec.get("url", ""))
                rec["came_back"] = came
                rec["commented_at"] = now
            elif state == "not_a_fault":
                if now - float(rec.get("commented_at") or 0) >= NOT_A_FAULT_COMMENT_EVERY_S:
                    _comment(rec, _seen_again(rec, ev), gh)
                    rec["commented_at"] = now
                    out["commented"] += 1
                    posted = True
            elif now - float(rec.get("commented_at") or 0) >= COMMENT_EVERY_S:
                _comment(rec, _seen_again(rec, ev), gh)
                rec["commented_at"] = now
                out["commented"] += 1
                posted = True
            if posted:
                # "was N" in the next comment is what the issue last SAID
                rec["posted_count"] = int(ev.get("count") or 0)
            for k in ("rooms", "count", "last", "message"):
                rec[k] = ev.get(k)
        except GhFailed as exc:
            out["failed"] += 1
            out["why"] = str(exc)
    if waiting:
        out["waiting"] = len(waiting)
        if now - float(st.get("flood_at") or 0) >= 3600:
            try:
                lines = "\n".join(f"- {_title(e)}" for e in waiting[:30])
                n, url = _file({"source": "filer", "kind": "flood",
                                "label": "error flood",
                                "message": f"{len(waiting)} more new errors this hour",
                                "rooms": [], "count": len(waiting),
                                "first": now, "last": now}, "flood", gh)
                _comment({"issue": n}, "Waiting to be filed next hour:\n" + lines, gh)
                st["flood_at"] = now
                _bell(f"Issue #{n}: error flood", f"{len(waiting)} new errors wait", url)
            except GhFailed as exc:
                out["failed"] += 1
                out["why"] = str(exc)
    st["filed_times"] = filed
    _write(st)
    return out


def mark_checking(fp: str, gh=None) -> None:
    gh = gh or _gh
    st = _read()
    rec = st["faults"].get(fp)
    if not rec:
        return
    rec["state"] = "checking"
    _write(st)
    try:
        _label(rec, "checking", gh)
    except GhFailed:
        pass


def set_verdict(fp: str, verdict: str, *, commit: str = "", summary: str = "",
                now: float | None = None, gh=None) -> None:
    """Move a fault's issue to the fixer's verdict: `fixed`, `not_a_fault`
    or `needs_you`. Raises GhFailed so the caller can try again later."""
    import time

    now = time.time() if now is None else float(now)
    gh = gh or _gh
    st = _read()
    rec = st["faults"].get(fp)
    if not rec or not rec.get("issue"):
        return
    n = str(rec["issue"])
    if verdict == "fixed":
        _comment(rec, f"Real fault, fixed in {commit}. {summary}", gh)
        _label(rec, "real-fault", gh)
        _label(rec, "fixed", gh)
        _state_change(gh, ["issue", "close", n, "-R", GH_REPO, "--reason", "completed"],
                      "already closed")
        rec.update(state="fixed", fixed_at=now, commit=commit)
    elif verdict == "not_a_fault":
        _comment(rec, f"Not a fault. {summary}", gh)
        _label(rec, "not-a-fault", gh)
        _state_change(gh, ["issue", "close", n, "-R", GH_REPO, "--reason", "not planned"],
                      "already closed")
        rec.update(state="not_a_fault")
    else:
        _comment(rec, f"Needs the operator. {summary}", gh)
        _label(rec, "needs-you", gh)
        rec.update(state="needs_you")
        _bell(f"Issue #{n} needs you: {rec.get('label')}", summary, rec.get("url", ""))
    rec["verdict"] = summary
    rec["commented_at"] = now
    _write(st)


def issue_for(fp: str, st: dict | None = None) -> dict | None:
    """{number, url, state} of a fault's issue, for the Errors tab."""
    rec = (st or _read())["faults"].get(fp)
    if not rec or not rec.get("issue"):
        return None
    return {"number": rec["issue"], "url": rec.get("url", ""),
            "state": rec.get("state", ""), "commit": rec.get("commit", "")}
