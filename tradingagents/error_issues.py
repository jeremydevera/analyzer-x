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
